"""`docs/ESPECIFICACIONES.md` no puede envejecer en silencio.

Un documento de especificaciones viejo es peor que no tenerlo, porque **miente con autoridad**:
alguien de fuera lo lee, construye encima de una garantía que ya no se cumple, y el fallo aparece
lejos. Este test es lo que convierte ese documento en verdad comprobable.

Es el patrón de `test_mt7_el_inventario_esta_escrito.py`, y por el mismo motivo: la auditoría de
multitenencia costó leer 31 tablas y 32 routers, y su resultado sólo sigue valiendo mientras algo
lo obligue.

**Qué comprueba.**

1. Que el documento existe donde alguien lo buscaría, y que está enlazado desde los tres sitios
   por los que se llega a él.
2. Que **todos los ficheros y tests que nombra existen**. Una ruta muerta en un documento de
   especificaciones manda a quien llega a buscar código que no está.
3. Que **los vocabularios que enumera son exactamente los que el código declara**: los cuatro
   ámbitos, los cuatro roles, los tres modos de política de lengua, los módulos del catálogo, los
   modos de recuperación y los módulos de negocio. Un valor nuevo o renombrado pone esto rojo, y
   entonces alguien actualiza la única página donde se puede consultar.

**Qué NO comprueba, y hay que decirlo**: la prosa. Puede garantizar que
`enforce_citation_contract` existe; no que siga rindiéndose sin cita. Eso lo prueban los tests de
cada capacidad, que la §9 del documento enumera. Un test que intentara validar afirmaciones en
lenguaje natural sería un generador de falsos positivos, y el primer rojo espurio lo dejaría
desactivado para siempre.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

#: La raíz del repositorio: `server/tests/infra/` → tres niveles arriba.
#:
#: Se comprueba con un `assert` a propósito. El guardarraíl de USR.5 recorría
#: `parents[5] / "app"`, que no existe, así que `rglob` no encontraba nada y el test pasaba en
#: verde **sin mirar nada** durante días. Un test que busca algo tiene que demostrar que sabe
#: dónde buscar.
RAIZ = Path(__file__).resolve().parents[3]
assert (RAIZ / "docs").is_dir(), f"la raíz no es la que se cree: {RAIZ}"

DOCUMENTO = RAIZ / "docs" / "ESPECIFICACIONES.md"


@pytest.fixture(scope="module")
def texto() -> str:
    assert DOCUMENTO.is_file(), (
        "`docs/ESPECIFICACIONES.md` es la especificación por capacidad del proyecto y la primera "
        "cosa que lee quien llega de fuera a continuar un desarrollo. Si se ha movido, hay que "
        "mover también este test y los enlaces que lo apuntan."
    )
    return DOCUMENTO.read_text(encoding="utf-8")


# ─────────────────────────── Referencias a código ───────────────────────────

#: Rutas del proyecto citadas en el documento, tal como aparecen entre acentos graves.
#: Se listan a mano y no se extraen con una expresión regular **a propósito**: el documento
#: menciona también rutas ilustrativas que no existen todavía (`planificacion/fase1/BLOQUE_REG.md`
#: si algún día se parte el plan) y nombres de tabla que no son ficheros. Una extracción
#: automática las confundiría, y el primer falso positivo dejaría este test desactivado.
_FICHEROS_CITADOS = (
    "docs/PRESENTACION_PROYECTO.md",
    "docs/Arquitectura.md",
    "docs/MULTITENENCIA.md",
    "docs/CONTRATO_MD_CORPUS.md",
    "docs/REDACCION_CONTRACT_FIRST.md",
    "docs/DECISION_IDENTIDAD_DE_ADMINISTRACION.md",
    "docs/DESPLIEGUE_PROTOTIPO_GCP.md",
    "docs/SANDBOX_SECURITY.md",
    "planificacion/PROJECT_STATE.md",
    "planificacion/HISTORIAL.md",
    "planificacion/Plan_TDD_Fase1.md",
    # `Plan_TDD_Fase2.md` salió de esta lista el 2026-09-23: §6 dejó de citarlo al replantear la
    # fase 2 como «automatización gobernada», y lo que la sustituye es `ROADMAP.md`. El fichero
    # sigue en el árbol como documento de diseño con historia; lo que ya no hace es sostener una
    # afirmación de la especificación.
    "ROADMAP.md",
    "AGENTS.md",
    "CONTRIBUTING.md",
    "deploy/vm/Caddyfile",
    ".github/workflows/ci.yml",
    ".github/workflows/deploy.yml",
    ".github/workflows/dco.yml",
    "server/app/core/language_mode.py",
    "server/app/core/llm_text.py",
    "server/app/core/ambito.py",
    "server/app/core/storage.py",
    "server/app/core/auth/tenancy.py",
    "server/app/core/auth/modulos.py",
    "server/app/modules/agents_hub/agent/citation_validator.py",
    "server/app/modules/curation/site_crawler.py",
    "server/app/modules/redaccion/services/script_auditor.py",
    "server/app/routers/hub_opciones_router.py",
    "server/tests/api/test_router_inventory_is_walked.py",
    "server/tests/api/test_tenant_isolation.py",
    "server/tests/core/test_mt7_el_inventario_esta_escrito.py",
    "server/tests/infra/test_suite_hygiene.py",
    "server/tests/public_graphs/test_profile_contract.py",
    (
        "server/tests/modules/agents_hub/integration/"
        "test_usr8_el_flujo_del_chat_siempre_termina.py"
    ),
    (
        "server/tests/modules/agents_hub/integration/"
        "test_mt16_aislamiento_dos_organizaciones.py"
    ),
)


class TestLoQueNombraExiste:
    """Una ruta muerta manda a quien llega a buscar código que no está."""

    @pytest.mark.parametrize("relativa", _FICHEROS_CITADOS)
    def test_should_point_at_a_file_that_exists(self, relativa: str):
        assert (RAIZ / relativa).exists(), (
            f"`docs/ESPECIFICACIONES.md` nombra `{relativa}` y no existe. Si se movió o se "
            "retiró, hay que actualizar el documento: es lo que lee quien llega de fuera."
        )

    def test_should_actually_mention_every_file_this_test_guards(self, texto: str):
        """La lista de arriba y el documento tienen que hablar de lo mismo.

        Sin esto, el test podría estar vigilando ficheros que el documento ya no menciona —o peor,
        pasar en verde mientras el documento nombra otros—: la mitad de la protección se iría sin
        que nada se pusiera rojo. Es la variante de «un test que busca algo tiene que demostrar
        que sabe encontrarlo».
        """
        # El documento nombra los routers **sin** `.py` (`hub_opciones_router`), que es la
        # convención de todo el proyecto. Se normaliza aquí en vez de obligar al documento a
        # escribir algo que nadie escribe.
        no_mencionados = [
            r
            for r in _FICHEROS_CITADOS
            if Path(r).name not in texto and Path(r).stem not in texto
        ]
        assert not no_mencionados, (
            "estos ficheros están en la lista que vigila el test pero el documento ya no los "
            f"nombra, así que la lista se ha quedado vieja: {no_mencionados}"
        )


# ────────────────────────── Vocabularios enumerados ─────────────────────────


def _valores_citados(texto: str, patron: str) -> set[str]:
    """Los valores que el documento escribe entre acentos graves para un patrón dado."""
    return set(re.findall(patron, texto))


class TestLosVocabulariosSonLosDelCodigo:
    """Lo que el documento enumera tiene que ser lo que el código declara, ni más ni menos."""

    def test_should_list_the_four_scopes(self, texto: str):
        from server.app.core.ambito import Ambito

        citados = _valores_citados(
            texto, r"`(plataforma|organizacion|heredable|derivada)`"
        )
        assert citados == {a.value for a in Ambito}, (
            "los ámbitos del documento no son los de `core/ambito.py`. Son cuatro y no tres "
            "porque tres serían una mentira: varias tablas llegan a la organización por otra "
            "tabla."
        )

    def test_should_list_the_four_roles(self, texto: str):
        from server.app.core.auth.models import UserRole

        citados = _valores_citados(texto, r"`(superadmin|admin|informer|user)`")
        assert citados == {r.value for r in UserRole}, (
            "los roles del documento no son los de `UserRole`. §5.6 los enumera y §4 apoya en "
            "ellos los invariantes de acceso."
        )

    def test_should_list_the_three_language_modes(self, texto: str):
        from server.app.core.language_mode import MODOS_SIMPLES, PREFIJO_FIJO

        esperados = set(MODOS_SIMPLES) | {PREFIJO_FIJO.rstrip(":")}
        # `fixed` aparece como `fixed:<código>`: el modo es paramétrico y el documento lo
        # escribe entero. Sin admitir el parámetro, el test diría que falta un modo que está.
        citados = _valores_citados(texto, r"`(prefer|none|fixed)(?::[^`]*)?`")
        assert citados == esperados, (
            "los modos de política de lengua del documento no son los que acepta "
            "`core/language_mode.py`. Si se añade un cuarto modo, la tabla de §5.2 deja de "
            "estar completa y quien la lea creerá que no existe."
        )

    def test_should_list_the_module_catalogue_seeds(self, texto: str):
        from server.app.core.auth.modulos import MODULOS_INICIALES

        codigos = {codigo for codigo, _etiqueta in MODULOS_INICIALES}
        # El documento los escribe en una sola línea separados por comas, entre acentos graves.
        citados = _valores_citados(
            texto, r"`(chatbots|curacion|informes|personas|registro|utilidades|agentes|consulta_agentes|plataforma)`"
        )
        assert codigos <= citados, (
            f"el documento no nombra todos los módulos del catálogo. Falta(n): "
            f"{sorted(codigos - citados)}. §5.6 dice qué abre cada uno y sin el nuevo, quien "
            "administre no sabrá que existe."
        )

    def test_should_list_the_retrieval_modes(self, texto: str):
        """Los tres modos que el router de chatbots acepta hoy.

        Se leen del contrato del router y no de una lista propia: el `Literal[...]` de
        `ChatbotCreate.retrieval_mode` es lo que de verdad se puede guardar.
        """
        from server.app.routers.hub_chatbots_router import ChatbotCreate

        from typing import get_args

        modos = set(get_args(ChatbotCreate.model_fields["retrieval_mode"].annotation))
        citados = _valores_citados(
            texto, r"`(RAG|MD_LONG_CONTEXT|MD_AGENT_SELECTOR)`"
        )
        assert modos <= citados, (
            f"el documento no nombra todos los modos de recuperación que el contrato acepta. "
            f"Falta(n): {sorted(modos - citados)}"
        )

    def test_should_list_the_business_modules(self, texto: str):
        modulos = {
            d.name
            for d in (RAIZ / "server" / "app" / "modules").iterdir()
            if d.is_dir() and not d.name.startswith("_")
        }
        assert modulos, "no se han encontrado módulos: la ruta está mal"
        faltan = [m for m in modulos if m not in texto]
        assert not faltan, (
            f"`server/app/modules/` tiene módulos que el documento no menciona: {faltan}. §3 "
            "dibuja el sistema en una página y un módulo ausente de ese dibujo es un módulo que "
            "nadie de fuera sabe que existe."
        )


# ──────────────────────── Se llega a él desde donde toca ────────────────────


class TestSeLlegaDesdeDondeAlguienMiraria:
    """Un documento al que no se llega es un documento que no existe."""

    @pytest.mark.parametrize(
        "desde",
        ["README.md", "docs/README.md", "planificacion/README.md"],
    )
    def test_should_be_linked_from(self, desde: str):
        contenido = (RAIZ / desde).read_text(encoding="utf-8")
        assert "ESPECIFICACIONES.md" in contenido, (
            f"`{desde}` no enlaza la especificación. Los tres sitios son los tres caminos por "
            "los que se llega: la portada del repositorio, el índice de documentación y la "
            "entrada a la planificación."
        )


class TestLaReglaDeActualizarloExiste:
    """Un documento vigilado por un test estructural pero sin regla de mantenimiento envejece.

    El test de este fichero caza la deriva **estructural** —un ámbito renombrado, una ruta
    muerta— y no puede comprobar la prosa. Lo que se escapa es lo que hace daño: una capacidad
    nueva que no aparece en §5, una garantía que cambia de significado, un «Abierto» ya cerrado.
    Eso lo cubre una regla en `AGENTS.md`, que es lo que un agente lee antes de escribir código.

    Se comprueba que la regla sigue ahí porque una regla borrada es una regla que nadie sigue, y
    su ausencia no produce ningún rojo por sí misma. Es el mismo criterio que
    `test_mt7_el_inventario_esta_escrito.py`, que exige que su inventario esté enlazado desde las
    reglas que leen los agentes.
    """

    def test_should_be_required_when_a_guarantee_changes(self):
        reglas = " ".join((RAIZ / "AGENTS.md").read_text(encoding="utf-8").split())

        assert "ESPECIFICACIONES.md" in reglas, (
            "`AGENTS.md` no menciona la especificación. Sin regla de mantenimiento, el documento "
            "envejece en todo lo que este test no puede comprobar, que es la prosa."
        )
        assert "si cambió una garantía" in reglas, (
            "falta la regla de actualizar la especificación al cerrar un bloque. Es condicional a "
            "propósito —incondicional produce commits de churn vacío— y por eso el enunciado "
            "lleva la condición dentro."
        )

    def test_should_hook_maturity_to_the_deploy_and_not_to_the_block(self):
        """El error que la formulación literal invitaba a cometer.

        USR era `construido` al cerrar el bloque y `producción` tras el push a `main`; LANG cerró
        y sigue `construido`. Si el disparador fuera «cerrar el bloque», la madurez quedaría mal
        en todos los bloques que no se despliegan el mismo día — o sea casi todos.
        """
        reglas = " ".join((RAIZ / "AGENTS.md").read_text(encoding="utf-8").split())

        assert "La madurez la mueve el despliegue" in reglas, (
            "la regla no dice que la madurez la mueve el despliegue y no el cierre del bloque, "
            "que es justo lo que se confunde."
        )

    def test_should_require_saying_it_in_the_closing_report(self):
        """Obligar a decir «no cambió nada, y por esto» convierte la omisión en afirmación.

        Es lo que de verdad sostiene la regla: sin esa línea, saltársela no deja rastro. Mismo
        criterio que se aplica a las cifras de tests — si no se ha medido, no se reporta como
        medida.
        """
        # El texto se normaliza porque un marcador sensible al salto de línea es frágil: este
        # test casaba con la COPIA duplicada de la regla, y al quitar la duplicación se puso
        # rojo aunque la regla seguía escrita —partida por un reajuste de párrafo—. Lo que hay
        # que exigir es que la regla esté, no que quepa en una línea.
        reglas = " ".join((RAIZ / "AGENTS.md").read_text(encoding="utf-8").split())

        assert "o por qué no cambió nada" in reglas, (
            "el informe de cierre no está obligado a decir qué cambió en la especificación. Un "
            "bloque puede no tocarla legítimamente, pero decirlo es lo que impide saltárselo en "
            "silencio."
        )


class TestLaEstructuraDelDocumento:
    """Las secciones a las que el propio documento y este test se refieren por número."""

    @pytest.mark.parametrize(
        "seccion",
        [
            "## 1. Qué es y qué no es este documento",
            "## 2. Cómo leer una capacidad",
            "## 3. El sistema en una página",
            "## 4. Invariantes de plataforma",
            "## 9. Cómo se prueba lo que aquí se afirma",
            "## 10. Qué NO hace la plataforma",
            "## 11. Cómo mantener este documento honesto",
        ],
    )
    def test_should_keep_the_section(self, texto: str, seccion: str):
        assert seccion in texto, (
            f"falta la sección «{seccion}». El documento se refiere a sus secciones por número "
            "en varios sitios, y este test también: renumerarlas sin actualizar las referencias "
            "deja punteros que no llevan a ninguna parte."
        )

    def test_should_number_every_invariant_it_uses(self, texto: str):
        """Cada `I<n>` citado en una capacidad tiene que estar definido en la tabla de §4."""
        tabla = texto.split("## 4. Invariantes de plataforma", 1)[1].split("## 5.", 1)[0]
        definidos = set(re.findall(r"^\| (I\d+) \|", tabla, re.MULTILINE))
        usados = set(re.findall(r"\b(I\d+)\b", texto)) - definidos
        assert not usados, (
            f"estos invariantes se citan en alguna capacidad y no están definidos en la tabla de "
            f"§4: {sorted(usados)}. Un invariante sin fila no dice dónde se hace cumplir, que es "
            "justo lo que lo distingue de una intención."
        )
