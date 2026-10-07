"""#230 — Claude Code registra su actividad solo, con un hook al cerrar la sesión.

El registro por MCP es declarativo: Claude sólo registra si alguien se lo pide, y un registro de
cumplimiento que depende de la memoria de cada uno se queda vacío. El hook lo hace automático.

Decisiones del usuario (2026-10-06):
1. **Un evento por sesión** (`SessionEnd`).
2. **La finalidad la declara el proyecto**, en `.claude/govgenai.json`; sin ese fichero no se
   registra, y se dice.
3. **Las categorías de datos, en ese mismo fichero**, con los códigos de la organización.
4. **Guion en el repositorio + instrucciones**; lo instala cada persona.

Lo que fija este fichero:
- el evento lleva **sólo metadatos**: nunca nada de la conversación, aunque el guion lea la
  transcripción para saber el modelo;
- el token y la dirección vienen del entorno, nunca del repositorio;
- **si algo falla, la sesión no se rompe** (sale con 0) **pero queda escrito**, en el registro
  local y en la salida de error.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[3]
GUION = RAIZ / "scripts" / "hooks" / "registrar_actividad_claude.py"

CAMPOS_DEL_CONTRATO = {
    "ocurrido_en", "actor", "herramienta", "agente", "finalidad", "modelo_usado",
    "categorias_datos", "payload_hash", "funcion_sha256",
}
SECRETO_DE_LA_CONVERSACION = "TEXTO_PRIVADO_DE_LA_CONVERSACION"


def _guion():
    spec = importlib.util.spec_from_file_location("registrar_actividad_claude", GUION)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def proyecto(tmp_path, monkeypatch):
    """Un proyecto con su `.claude/govgenai.json`, una transcripción y un HOME aparte."""
    raiz = tmp_path / "proyecto"
    (raiz / ".claude").mkdir(parents=True)
    (raiz / ".claude" / "govgenai.json").write_text(
        json.dumps({"finalidad": "Desarrollo de la plataforma", "categorias_datos": ["sin_datos_personales"]}),
        encoding="utf-8",
    )
    transcripcion = tmp_path / "sesion.jsonl"
    transcripcion.write_text(
        "\n".join(
            json.dumps(linea)
            for linea in [
                {"type": "user", "message": {"role": "user", "content": SECRETO_DE_LA_CONVERSACION}},
                {"type": "assistant", "message": {"role": "assistant", "model": "claude-opus-5-5", "content": "vale"}},
            ]
        ),
        encoding="utf-8",
    )
    casa = tmp_path / "casa"
    casa.mkdir()
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("USERPROFILE", str(casa))
    monkeypatch.setenv("GOVGENAI_URL", "https://normativa.example")
    monkeypatch.setenv("GOVGENAI_PAT_ACTIVIDAD", "pat_abc_secreto")
    monkeypatch.setenv("GOVGENAI_ACTOR", "u-opaco")
    entrada = {
        "session_id": "s1",
        "transcript_path": str(transcripcion),
        "cwd": str(raiz / "subcarpeta"),
        "hook_event_name": "SessionEnd",
        "reason": "exit",
    }
    (raiz / "subcarpeta").mkdir()
    return {"entrada": entrada, "casa": casa, "raiz": raiz}


class Envios:
    def __init__(self, estado=201):
        self.peticiones = []
        self.estado = estado

    def __call__(self, peticion, timeout=None):
        self.peticiones.append(peticion)
        if self.estado >= 400:
            import urllib.error

            raise urllib.error.HTTPError(peticion.full_url, self.estado, "x", {}, io.BytesIO(b'{"detail": "falta"}'))

        class _Resp(io.BytesIO):
            status = 201

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Resp(b'{"id": "e1"}')


def _ejecutar(modulo, entrada, monkeypatch, envios):
    monkeypatch.setattr(modulo.urllib.request, "urlopen", envios)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(entrada)))
    return modulo.main()


class TestElEvento:

    def test_manda_un_evento_con_solo_metadatos(self, proyecto, monkeypatch):
        modulo = _guion()
        envios = Envios()
        assert _ejecutar(modulo, proyecto["entrada"], monkeypatch, envios) == 0

        assert len(envios.peticiones) == 1
        peticion = envios.peticiones[0]
        assert peticion.full_url == "https://normativa.example/api/v1/actividad"
        assert peticion.get_header("Authorization") == "Bearer pat_abc_secreto"
        evento = json.loads(peticion.data)
        assert set(evento) <= CAMPOS_DEL_CONTRATO
        assert evento["herramienta"] == "claude-code"
        assert evento["finalidad"] == "Desarrollo de la plataforma"
        assert evento["categorias_datos"] == ["sin_datos_personales"]
        assert evento["modelo_usado"] == "claude-opus-5-5"
        assert evento["actor"] == "u-opaco"
        assert evento["ocurrido_en"].endswith("+00:00")

    def test_nada_de_la_conversacion_sale(self, proyecto, monkeypatch):
        modulo = _guion()
        envios = Envios()
        _ejecutar(modulo, proyecto["entrada"], monkeypatch, envios)
        assert SECRETO_DE_LA_CONVERSACION.encode() not in envios.peticiones[0].data

    def test_sin_actor_declarado_usa_uno_opaco_y_estable(self, proyecto, monkeypatch):
        monkeypatch.delenv("GOVGENAI_ACTOR")
        modulo = _guion()
        primero, segundo = Envios(), Envios()
        _ejecutar(modulo, proyecto["entrada"], monkeypatch, primero)
        _ejecutar(modulo, proyecto["entrada"], monkeypatch, segundo)
        actor = json.loads(primero.peticiones[0].data)["actor"]
        assert actor == json.loads(segundo.peticiones[0].data)["actor"]
        assert "@" not in actor


class TestLoQueNoRegistra:

    def test_sin_fichero_del_proyecto_no_registra_y_lo_dice(self, proyecto, monkeypatch):
        (proyecto["raiz"] / ".claude" / "govgenai.json").unlink()
        modulo = _guion()
        envios = Envios()
        assert _ejecutar(modulo, proyecto["entrada"], monkeypatch, envios) == 0
        assert envios.peticiones == []
        registro = (proyecto["casa"] / ".claude" / "govgenai-actividad.log").read_text(encoding="utf-8")
        assert "govgenai.json" in registro

    def test_sin_token_no_registra_y_lo_dice(self, proyecto, monkeypatch):
        monkeypatch.delenv("GOVGENAI_PAT_ACTIVIDAD")
        modulo = _guion()
        envios = Envios()
        assert _ejecutar(modulo, proyecto["entrada"], monkeypatch, envios) == 0
        assert envios.peticiones == []
        assert "GOVGENAI_PAT_ACTIVIDAD" in (proyecto["casa"] / ".claude" / "govgenai-actividad.log").read_text(encoding="utf-8")


class TestSiFalla:

    def test_la_sesion_no_se_rompe_pero_queda_escrito(self, proyecto, monkeypatch, capsys):
        modulo = _guion()
        assert _ejecutar(modulo, proyecto["entrada"], monkeypatch, Envios(estado=403)) == 0
        registro = (proyecto["casa"] / ".claude" / "govgenai-actividad.log").read_text(encoding="utf-8")
        assert "403" in registro
        assert "403" in capsys.readouterr().err
        assert "pat_abc_secreto" not in registro


def test_el_token_no_vive_en_el_repositorio():
    """El guion lo lee del entorno; ni el guion ni la documentación llevan uno."""
    texto = GUION.read_text(encoding="utf-8")
    assert "GOVGENAI_PAT_ACTIVIDAD" in texto
    import re

    assert not re.search(r"pat_[A-Za-z0-9]{4,}_[A-Za-z0-9]{8,}", texto)


class TestEntradasRaras:
    """Revisión de la PR #237: había entradas que salían con traza y código 1 sin dejar nada escrito."""

    def _registro(self, proyecto):
        return (proyecto["casa"] / ".claude" / "govgenai-actividad.log").read_text(encoding="utf-8")

    def test_una_entrada_que_no_es_un_objeto(self, proyecto, monkeypatch):
        modulo = _guion()
        envios = Envios()
        monkeypatch.setattr(modulo.urllib.request, "urlopen", envios)
        monkeypatch.setattr("sys.stdin", io.StringIO("[]"))
        assert modulo.main() == 0
        assert envios.peticiones == []
        assert "entrada" in self._registro(proyecto)

    def test_una_declaracion_que_no_es_un_objeto(self, proyecto, monkeypatch):
        (proyecto["raiz"] / ".claude" / "govgenai.json").write_text('["x"]', encoding="utf-8")
        modulo = _guion()
        envios = Envios()
        assert _ejecutar(modulo, proyecto["entrada"], monkeypatch, envios) == 0
        assert envios.peticiones == []
        assert "govgenai.json" in self._registro(proyecto)

    def test_categorias_que_no_son_una_lista_no_se_inventan(self, proyecto, monkeypatch):
        (proyecto["raiz"] / ".claude" / "govgenai.json").write_text(
            json.dumps({"finalidad": "x", "categorias_datos": "sin_datos_personales"}), encoding="utf-8"
        )
        modulo = _guion()
        envios = Envios()
        assert _ejecutar(modulo, proyecto["entrada"], monkeypatch, envios) == 0
        assert envios.peticiones == []
        assert "categorias_datos" in self._registro(proyecto)

    def test_una_transcripcion_con_bytes_invalidos_no_impide_registrar(self, proyecto, monkeypatch):
        Path(proyecto["entrada"]["transcript_path"]).write_bytes(b'\xff\xfe{"message": 1}\n')
        modulo = _guion()
        envios = Envios()
        assert _ejecutar(modulo, proyecto["entrada"], monkeypatch, envios) == 0
        assert len(envios.peticiones) == 1
        assert "modelo_usado" not in json.loads(envios.peticiones[0].data)

    def test_cualquier_otro_fallo_sale_con_cero_y_queda_escrito(self, proyecto, monkeypatch):
        modulo = _guion()

        def _revienta(_desde):
            raise PermissionError("sin permiso")

        monkeypatch.setattr(modulo, "_declaracion_del_proyecto", _revienta)
        assert _ejecutar(modulo, proyecto["entrada"], monkeypatch, Envios()) == 0
        assert "sin permiso" in self._registro(proyecto)


class TestLaEntradaEnWindows:
    """La entrada llega en UTF-8, pero Python en Windows lee la tubería con la página de códigos.

    Salió probándolo a mano el 2026-10-07: con una ruta con acentos, el `cwd` llegaba desfigurado,
    el guion no encontraba la declaración del proyecto y no registraba. Y una entrada con BOM, como
    la que manda PowerShell 5.1, no se leía.
    """

    def _stdin(self, crudo: bytes):
        return io.TextIOWrapper(io.BytesIO(crudo), encoding="cp1252")

    def test_una_ruta_con_acentos_encuentra_la_declaracion(self, proyecto, monkeypatch, tmp_path):
        raiz = tmp_path / "Proyección"
        (raiz / ".claude").mkdir(parents=True)
        (raiz / ".claude" / "govgenai.json").write_text(
            json.dumps({"finalidad": "Con acentos", "categorias_datos": []}), encoding="utf-8"
        )
        entrada = dict(proyecto["entrada"], cwd=str(raiz))
        modulo = _guion()
        envios = Envios()
        monkeypatch.setattr(modulo.urllib.request, "urlopen", envios)
        monkeypatch.setattr("sys.stdin", self._stdin(json.dumps(entrada, ensure_ascii=False).encode("utf-8")))
        assert modulo.main() == 0
        assert json.loads(envios.peticiones[0].data)["finalidad"] == "Con acentos"

    def test_una_entrada_con_bom_se_lee(self, proyecto, monkeypatch):
        modulo = _guion()
        envios = Envios()
        monkeypatch.setattr(modulo.urllib.request, "urlopen", envios)
        monkeypatch.setattr("sys.stdin", self._stdin(b"\xef\xbb\xbf" + json.dumps(proyecto["entrada"]).encode("utf-8")))
        assert modulo.main() == 0
        assert len(envios.peticiones) == 1


def test_una_declaracion_con_bom_se_lee(proyecto, monkeypatch):
    """El `.claude/govgenai.json` que escribe PowerShell 5.1 lleva BOM (revisión de la PR #240)."""
    (proyecto["raiz"] / ".claude" / "govgenai.json").write_bytes(
        b"\xef\xbb\xbf" + json.dumps({"finalidad": "Con BOM", "categorias_datos": []}).encode("utf-8")
    )
    modulo = _guion()
    envios = Envios()
    assert _ejecutar(modulo, proyecto["entrada"], monkeypatch, envios) == 0
    assert json.loads(envios.peticiones[0].data)["finalidad"] == "Con BOM"
