"""APER.26 — la exención del DCO deja de ser un comodín sobre un dato que elige quien commitea.

APER.13 eximió a Dependabot del DCO por una razón buena —«I have the right to submit it under
the open source license», dice el DCO, y eso lo certifica una persona sobre código que aporta; un
robot que sube un número de versión en un `uv.lock` no aporta código de nadie— pero lo escribió
como un **comodín**:

    if [[ "$correo" == *"[bot]@users.noreply.github.com" ]]

El comentario que lo acompañaba decía que la exención va «por correo del autor, no por nombre: el
nombre lo puede poner cualquiera en un commit». Es verdad a medias, y la mitad que falta es la
que importa: **el correo del autor también lo pone cualquiera**, con un `git config user.email`.
Cualquiera podía firmar como `loquesea[bot]@users.noreply.github.com` y saltarse el DCO entero.

Lo encontró la revisión automática de la PR #50, que además señaló la incoherencia con el propio
texto de al lado.

**Lo que se cambia, y lo que no.** La exención sigue existiendo, porque la razón sigue siendo
buena. Lo que se estrecha es a **quién**: de un comodín que acepta cualquier cosa acabada en
`[bot]@…` a una lista exacta y corta con el único robot que de verdad abre PR aquí. Un correo
seguía siendo un dato que se puede escribir a mano, así que esto no lo vuelve infalsificable;
lo vuelve **estrecho y visible**, que es lo que se puede conseguir dentro de un `git log`.

**Este fichero ejecuta el guion del workflow contra un repositorio de mentira**, con cuatro
commits: uno firmado, uno sin firmar, uno del robot de verdad y uno de un impostor. Mirar el YAML
no habría servido de nada: el comodín estaba a la vista y llevaba su propio comentario
explicando por qué era seguro.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[3]
DCO = RAIZ / ".github" / "workflows" / "dco.yml"

CORREO_HUMANO = "fulana@example.org"
CORREO_ROBOT = "49699333+dependabot[bot]@users.noreply.github.com"
CORREO_IMPOSTOR = "cualquiera[bot]@users.noreply.github.com"


def _guion_del_dco() -> str:
    datos = yaml.safe_load(DCO.read_text(encoding="utf-8"))
    for cuerpo in datos["jobs"].values():
        for paso in cuerpo.get("steps", []):
            texto = paso.get("run") or ""
            if "Signed-off-by" in texto and "rev-list" in texto:
                return re.sub(r"\$\{\{[^}]*\}\}", "", texto)
    raise AssertionError("no encuentro el paso del DCO que recorre los commits")


def _git(*args: str, cwd: Path, correo: str | None = None) -> None:
    entorno = dict(os.environ)
    if correo is not None:
        entorno.update(
            GIT_AUTHOR_NAME="Quien Sea", GIT_AUTHOR_EMAIL=correo,
            GIT_COMMITTER_NAME="Quien Sea", GIT_COMMITTER_EMAIL=correo,
        )
    subprocess.run(
        ["git", *args], cwd=cwd, env=entorno, check=True,
        capture_output=True, text=True,
    )


def _commit(repo: Path, fichero: str, correo: str, mensaje: str) -> None:
    (repo / fichero).write_text(fichero, encoding="utf-8")
    _git("add", fichero, cwd=repo)
    _git("commit", "-m", mensaje, cwd=repo, correo=correo)


@pytest.fixture(scope="module")
def veredictos(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[int, str]]:
    """Ejecuta el guion real una vez por caso y devuelve (código de salida, salida)."""
    if shutil.which("git") is None or shutil.which("bash") is None:  # pragma: no cover
        pytest.skip("hacen falta git y bash")

    repo = tmp_path_factory.mktemp("repo")
    _git("init", "-q", "-b", "principal", cwd=repo)
    _commit(repo, "base.txt", CORREO_HUMANO, "raíz\n\nSigned-off-by: Quien Sea <fulana@example.org>")
    base = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()

    casos = {
        "humano firmado": (
            CORREO_HUMANO,
            "un cambio\n\nSigned-off-by: Quien Sea <fulana@example.org>",
        ),
        "humano sin firmar": (CORREO_HUMANO, "un cambio sin firma"),
        "robot de verdad": (CORREO_ROBOT, "chore(deps): sube una version"),
        "impostor": (CORREO_IMPOSTOR, "un cambio sin firma con correo de robot"),
    }

    guion = repo / "dco.sh"
    guion.write_text(_guion_del_dco(), encoding="utf-8", newline="\n")

    salidas: dict[str, tuple[int, str]] = {}
    for rotulo, (correo, mensaje) in casos.items():
        _git("checkout", "-q", "-B", "prueba", base, cwd=repo)
        _commit(repo, f"{rotulo.replace(' ', '_')}.txt", correo, mensaje)
        entorno = dict(os.environ, BASE=base, HEAD="HEAD")
        hecho = subprocess.run(
            ["bash", guion.as_posix()], cwd=repo, env=entorno,
            capture_output=True, text=True, timeout=120,
            check=False,
        )
        salidas[rotulo] = (hecho.returncode, hecho.stdout + hecho.stderr)
    return salidas


def test_un_commit_firmado_pasa(veredictos: dict[str, tuple[int, str]]) -> None:
    codigo, salida = veredictos["humano firmado"]
    assert codigo == 0, f"un commit bien firmado no debería fallar:\n{salida}"


def test_un_commit_sin_firmar_falla(veredictos: dict[str, tuple[int, str]]) -> None:
    """El camino que justifica que exista el workflow."""
    codigo, salida = veredictos["humano sin firmar"]
    assert codigo != 0, f"un commit sin `Signed-off-by` ha pasado:\n{salida}"


def test_el_robot_de_verdad_sigue_exento(veredictos: dict[str, tuple[int, str]]) -> None:
    """Lo que APER.13 arregló no se rompe: las trece PR de Dependabot tienen que poder mezclarse."""
    codigo, salida = veredictos["robot de verdad"]
    assert codigo == 0, (
        f"Dependabot ha dejado de estar exento, así que ninguna de sus PR se podrá mezclar:\n"
        f"{salida}"
    )
    assert "exento" in salida.lower(), (
        f"pasó, pero sin decir que era por la exención. Una exención que no se ve en el registro "
        f"es una exención que nadie vuelve a revisar:\n{salida}"
    )


def test_un_correo_que_imita_a_un_robot_no_cuela(
    veredictos: dict[str, tuple[int, str]]
) -> None:
    """El defecto. Cualquiera puede escribir este correo con un `git config`."""
    codigo, salida = veredictos["impostor"]
    assert codigo != 0, (
        f"un commit sin firmar con el correo «{CORREO_IMPOSTOR}» se ha saltado el DCO. El correo "
        f"del autor lo elige quien commitea, igual que el nombre, así que un comodín sobre él no "
        f"exime a un robot: exime a cualquiera que lo escriba.\n{salida}"
    )
