"""AUT.4 (issue #115) — el paquete de gobernanza dice la verdad sobre las herramientas.

Las herramientas existían; lo que faltaba era el **empaquetado** que hace que un agente de código
las use por defecto. Hoy quien quiere que Claude Code o un asistente de escritorio las llame tiene
que saber que existen, emitir el PAT con los scopes correctos y explicárselo al agente cada vez.

**Lo que este test vigila no es que el paquete exista, sino que no mienta.** Un ejemplo de
configuración y una skill son documentación ejecutable: envejecen igual que un docstring, y peor,
porque quien los copia no tiene forma de saber que ya no valen. Los tres modos de mentir que se
pueden comprobar desde aquí:

1. **Nombrar una herramienta que no existe** — el agente la llama y recibe un error que no sabe
   interpretar.
2. **Pedir un scope que no está en el catálogo** — el PAT no se puede emitir, y quien lo intenta
   descubre el error en el panel sin saber de dónde salió el nombre.
3. **Quedarse corto de scopes** — el agente llama a una herramienta y recibe un 403 en mitad de un
   trabajo, que es el peor momento para enterarse.

Lo que **no** se comprueba aquí, porque no se puede: que el agente llame a las herramientas. El
cumplimiento por MCP es voluntario y el paquete existe para hacerlo fácil, no para imponerlo. La
imposición sólo existe donde la ejecución ocurre dentro, que es el catálogo de funciones.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

_PAQUETE = (
    pathlib.Path(__file__).resolve().parents[3] / "docs" / "ejemplos" / "gobernanza"
)

#: Los scopes que el ciclo de la skill necesita, uno por paso.
_SCOPES_DEL_CICLO = {
    "verificaciones:use",  # reglas_de_auditoria, auditar_codigo
    "anonimizacion:use",  # detectar_pii, anonimizar_texto
    "actividad:write",  # registrar_actividad
}


def _skill() -> str:
    return (_PAQUETE / "SKILL.md").read_text(encoding="utf-8")


def _configuracion() -> dict:
    return json.loads((_PAQUETE / ".mcp.json").read_text(encoding="utf-8"))


class TestElPaqueteEstaCompleto:

    def test_trae_la_configuracion_y_la_skill(self):
        assert (_PAQUETE / ".mcp.json").is_file()
        assert (_PAQUETE / "SKILL.md").is_file()

    def test_la_skill_declara_cuando_usarse(self):
        """Sin `description`, el agente no sabe cuándo cargarla y la skill no se usa nunca."""
        cabecera = _skill().split("---")[1]

        assert "name:" in cabecera
        assert "description:" in cabecera

    def test_la_configuracion_apunta_al_transporte_http(self):
        """El otro transporte es stdio y corre el servidor en la máquina de quien lo usa; el
        paquete es para agentes que hablan con la plataforma desplegada."""
        servidor = _configuracion()["mcpServers"]["govgenai"]

        assert servidor["type"] == "http"
        assert servidor["url"].startswith("https://")

    def test_el_token_no_va_escrito_en_el_fichero(self):
        """Un ejemplo con un token dentro es un ejemplo que alguien copia con el token dentro."""
        crudo = (_PAQUETE / ".mcp.json").read_text(encoding="utf-8")

        assert "${GOVGENAI_PAT}" in crudo
        assert not re.search(r"pat_[A-Za-z0-9]{8,}", crudo)


class TestLasHerramientasQueNombraExisten:

    @pytest.mark.parametrize(
        "herramienta",
        [
            "reglas_de_auditoria",
            "auditar_codigo",
            "detectar_pii",
            "anonimizar_texto",
            "registrar_actividad",
        ],
    )
    def test_la_skill_solo_nombra_herramientas_del_servidor(self, herramienta):
        """Las cinco del ciclo, comprobadas contra el servidor MCP de verdad.

        Se listan a mano y se comprueban contra el servidor, en vez de leerlas del servidor y
        compararlas consigo mismas: un test que se lee a sí mismo pasa siempre.
        """
        assert herramienta in _skill()
        assert herramienta in _las_del_servidor()


def _las_del_servidor() -> set[str]:
    """Los nombres de tool que el módulo del servidor registra, leídos de su código.

    Se leen del árbol y no levantando el servidor: este test vive en `tests/infra`, corre en CI
    sin red y no tiene por qué arrastrar el arranque de un servidor MCP para comprobar nombres.
    """
    raiz = pathlib.Path(__file__).resolve().parents[3] / "mcp_server" / "tools"
    nombres: set[str] = set()
    for fichero in raiz.glob("*.py"):
        texto = fichero.read_text(encoding="utf-8")
        nombres.update(re.findall(r"@mcp\.tool\(\)\s*\n\s*async def (\w+)", texto))
    return nombres


class TestLosScopesQueDice:

    def test_los_tres_del_ciclo_estan_en_el_catalogo(self):
        """Un scope que no existe deja un PAT que no se puede emitir."""
        from server.app.core.auth.pat.scopes import ALL_SCOPES

        assert _SCOPES_DEL_CICLO <= set(ALL_SCOPES)

    def test_la_skill_los_nombra_todos(self):
        """Quedarse corto es un 403 en mitad de un trabajo, que es el peor momento."""
        texto = _skill()

        faltan = [s for s in _SCOPES_DEL_CICLO if s not in texto]
        assert not faltan, f"la skill no dice qué scopes hacen falta: {faltan}"

    def test_los_puede_emitir_un_admin_de_organizacion(self):
        """Si hiciera falta un superadministrador, el paquete no sería instalable por quien lo
        va a usar, y el camino fácil dejaría de serlo."""
        from server.app.core.auth.pat.scopes import allowed_scopes_for_role

        assert _SCOPES_DEL_CICLO <= set(allowed_scopes_for_role("admin"))


class TestLoQueLaSkillDiceSinRodeos:

    def test_avisa_de_que_el_cumplimiento_es_voluntario(self):
        """Es lo que hace honesto el paquete: por MCP un agente puede no llamar a nada."""
        assert "voluntario" in _skill()

    def test_dice_que_anonimizar_no_lo_decide_ella(self):
        """Depende del contrato con el proveedor y de la sensibilidad del dato, y ninguna de las
        dos cosas la sabe una skill."""
        texto = _skill()

        assert "contrato" in texto
        assert "no lo decide la skill" in texto.lower()

    def test_dice_que_no_se_manda_el_contenido(self):
        assert "Nunca el contenido" in _skill()
