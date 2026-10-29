"""#327 — los dos pasos de CI sobre las imágenes de los compose daban verde o rojo por la razón
equivocada.

Los añadieron #312 y #318 como `run:` de shell, y la revisión High del commit que los arreglaba
(`782a3520`) encontró que seguían mintiendo de cinco maneras:

- **El arranque copiado se comparaba a medias**: que el `Cmd` de Langfuse *contuviera* la línea
  que copia la guarda. Una opción nueva en la imagen pasaba en verde y la guarda la perdía.
- **Sólo se vigilaba Langfuse**, pero ClickHouse y SeaweedFS también sustituyen el `entrypoint` de
  su imagen y acaban ejecutando su arranque a mano.
- **`imagetools inspect` no reintentaba**: un 429 de Docker Hub ponía CI en rojo sin defecto.
- **El primer error que no era de credenciales cortaba el bucle**, y una imagen que de verdad
  había dejado de descargarse quedaba escondida detrás.
- **Los guardarraíles leían una ventana de `ci.yml` que incluía comentarios**: si el `grep` dejaba
  de leer un compose, el comentario seguía nombrándolo y el test seguía verde.

Ahora es un guion, `scripts/imagenes_de_los_compose.py`, que se prueba aquí con datos falsos, y el
test sobre `ci.yml` lee el `run:` del paso, no el texto que lo rodea.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
GUIONES = RAIZ / "scripts"
COMPOSES = ("docker-compose.yml", "docker-compose.prod.yml", "deploy/vm/docker-compose.vm.yml")

if str(GUIONES) not in sys.path:  # los guiones no son un paquete instalable
    sys.path.insert(0, str(GUIONES))

import imagenes_de_los_compose as guion  # noqa: E402


def _servicios(compose: str) -> dict:
    return yaml.safe_load((RAIZ / compose).read_text(encoding="utf-8"))["services"]


def _imagen(entrypoint, cmd, workdir="/app", plataformas=True) -> str:
    """Lo que imprime `imagetools inspect --format '{{json .Image}}'`."""
    imagen = {"config": {"Entrypoint": entrypoint, "Cmd": cmd, "WorkingDir": workdir}}
    return json.dumps({"linux/amd64": imagen, "linux/arm64": imagen} if plataformas else imagen)


LANGFUSE = guion.ARRANQUES["langfuse/langfuse"]


class _Registro:
    """Un `docker buildx imagetools inspect` falso: por imagen, la lista de respuestas que da."""

    def __init__(self, respuestas: dict[str, list[tuple[int, str]]]) -> None:
        self.respuestas = respuestas
        self.llamadas: list[str] = []

    def __call__(self, orden, **_):
        imagen = orden[4]
        self.llamadas.append(imagen)
        codigo, salida = self.respuestas[imagen].pop(0)
        return subprocess.CompletedProcess(orden, codigo, salida if codigo == 0 else "", salida)


# --- La configuración de la imagen se lee con y sin índice de plataformas -----------------------


@pytest.mark.parametrize("plataformas", [True, False], ids=["indice", "una-plataforma"])
def test_lee_la_configuracion_con_y_sin_indice_de_plataformas(plataformas) -> None:
    config = guion.configuracion(_imagen(["/entrypoint.sh"], None, "/", plataformas))
    assert config == guion.Arranque(["/entrypoint.sh"], None, "/")


def test_una_imagen_sin_linux_amd64_lo_dice() -> None:
    with pytest.raises(guion.ImagenIlegible, match="linux/amd64"):
        guion.configuracion(json.dumps({"linux/arm64": {"config": {}}}))


# --- El arranque se compara entero ----------------------------------------------------------------


def test_el_mismo_arranque_no_da_diferencias() -> None:
    assert guion.diferencias(LANGFUSE, LANGFUSE) == []


def test_una_opcion_nueva_en_el_cmd_es_una_diferencia() -> None:
    """Lo que la comparación por subcadena dejaba pasar."""
    nuevo = guion.Arranque(LANGFUSE.entrypoint, [*LANGFUSE.cmd[:-1], LANGFUSE.cmd[-1] + " --x"], LANGFUSE.workdir)
    assert [d.split(":")[0] for d in guion.diferencias(LANGFUSE, nuevo)] == ["Cmd"]


def test_un_directorio_de_trabajo_movido_es_una_diferencia() -> None:
    """La guarda de Langfuse ejecuta rutas relativas: `./web/entrypoint.sh`."""
    movido = guion.Arranque(LANGFUSE.entrypoint, LANGFUSE.cmd, "/srv")
    assert [d.split(":")[0] for d in guion.diferencias(LANGFUSE, movido)] == ["WorkingDir"]


# --- Qué servicios sustituyen el arranque de su imagen --------------------------------------------


def test_la_tabla_cubre_cada_servicio_que_sustituye_el_entrypoint() -> None:
    """Langfuse, ClickHouse y SeaweedFS, en los compose de hoy; y uno nuevo pone rojo."""
    vigilados = {
        guion.repositorio(s["image"])
        for compose in COMPOSES
        for s in _servicios(compose).values()
        if "entrypoint" in s
    }
    assert vigilados == {"langfuse/langfuse", "clickhouse/clickhouse-server", "chrislusf/seaweedfs"}
    for compose in COMPOSES:
        assert guion.sin_vigilar(_servicios(compose)) == []


def test_un_entrypoint_de_una_imagen_que_no_esta_en_la_tabla_se_dice() -> None:
    servicios = {"cache": {"image": "valkey/valkey:8.1", "entrypoint": ["/bin/sh", "-c", "exec valkey-server"]}}
    assert guion.sin_vigilar(servicios) == ["cache (valkey/valkey)"]


def test_la_guarda_cede_al_entrypoint_que_dice_la_tabla() -> None:
    """La tabla y el compose describen el mismo arranque: la guarda acaba en `exec <Entrypoint>`."""
    for compose in COMPOSES:
        for nombre, servicio in _servicios(compose).items():
            if "entrypoint" in servicio:
                arranque = guion.ARRANQUES[guion.repositorio(servicio["image"])]
                assert "exec " + shlex.join(arranque.entrypoint) in " ".join(servicio["entrypoint"]), nombre


# --- El registro: niega, se corta o responde ------------------------------------------------------


def test_un_corte_del_registro_se_reintenta(monkeypatch) -> None:
    registro = _Registro({"a:1": [(1, "toomanyrequests: rate limit"), (0, _imagen(["/e"], None))]})
    monkeypatch.setattr(guion.time, "sleep", lambda _: None)
    assert guion.inspecciona("a:1", ejecuta=registro) == guion.Arranque(["/e"], None, "/app")
    assert registro.llamadas == ["a:1", "a:1"]


def test_lo_que_el_registro_niega_no_se_reintenta(monkeypatch) -> None:
    registro = _Registro({"a:1": [(1, "unauthorized: authentication required")]})
    with pytest.raises(guion.Niega):
        guion.inspecciona("a:1", ejecuta=registro)
    assert registro.llamadas == ["a:1"]


def test_un_corte_que_sigue_se_dice_como_corte(monkeypatch) -> None:
    registro = _Registro({"a:1": [(1, "i/o timeout")] * 3})
    monkeypatch.setattr(guion.time, "sleep", lambda _: None)
    with pytest.raises(guion.NoResponde):
        guion.inspecciona("a:1", ejecuta=registro)


def test_un_corte_no_esconde_la_imagen_que_viene_detras(monkeypatch, capsys) -> None:
    """El bucle de shell salía con la primera imagen que no respondía."""
    registro = _Registro({
        "a:1": [(1, "i/o timeout")] * 3,
        "b:1": [(1, "unauthorized: authentication required")],
    })
    monkeypatch.setattr(guion.time, "sleep", lambda _: None)
    assert guion.comprueba({"x": {"image": "a:1"}, "y": {"image": "b:1"}}, ejecuta=registro) == 1
    salida = capsys.readouterr().out
    assert "a:1" in salida
    assert "b:1" in salida


def test_las_imagenes_por_variable_no_se_piden() -> None:
    """Las nuestras van por variable y piden credenciales a propósito."""
    assert guion.imagenes_fijas({"app": {"image": "${GOVGENAI_IMAGE:?falta}"}, "c": {"image": "caddy:2.8"}}) == ["caddy:2.8"]


# --- CI ejecuta el guion sobre los tres compose ---------------------------------------------------


def test_ci_ejecuta_el_guion_sobre_los_tres_compose() -> None:
    """Se lee el `run:` de los pasos, no una ventana de texto con comentarios dentro."""
    ci = yaml.safe_load((RAIZ / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    ordenes = [
        shlex.split(linea)
        for paso in ci["jobs"]["imagen"]["steps"]
        for linea in paso.get("run", "").splitlines()
        if "imagenes_de_los_compose.py" in linea
    ]
    assert len(ordenes) == 1
    assert set(COMPOSES) <= set(ordenes[0])
    pasos = " ".join(paso.get("run", "") for paso in ci["jobs"]["imagen"]["steps"])
    assert "docker manifest inspect" not in pasos, "lo hace el guion, con reintentos"
