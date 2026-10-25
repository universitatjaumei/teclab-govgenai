"""LANG.1 — `language_mode` deja de estar desconectado.

**El hueco, medido el 2026-09-01**: `language_mode` viaja por **toda** la cascada —plataforma
(`prefer`) → `HubOrganizacion.default_language_mode` → `HubChatbot.language_mode` →
`PublicGraphConfig.language_mode`— y **nadie lo consume**. `_make_public_kb_rich` monta siempre
`DefaultLanguagePolicy`, y el valor `"none"` que documenta `metadata_filter.py` no tiene ni un
`if` que lo lea. Encima la columna es `String(20)` libre, así que un `language_mode="castellano"`
caía a `prefer` sin avisar a nadie.

Y falta el modo que pediría una organización monolingüe: **«responde siempre en X, pregunten como
pregunten»**. Hoy el grafo detecta la lengua de la pregunta e instruye «Responde en {esa}», así
que a quien escriba en catalán a un ayuntamiento castellanohablante se le contesta en catalán, sin
que el organismo tenga dónde decidir lo contrario.

**Todo cuelga de `detect()`, y por eso el CoreGraph no se toca.** Su `detect_language_node` pone
el resultado en `state["language"]`, y de ahí salen las tres consecuencias: `"Responde en {lang}"`
en el prompt (`public_kb_rich.py:143`), `language=` en la recuperación (`core_graph.py:202`) y la
lógica de segunda búsqueda y aviso de traducción. Una política que devuelve `None` degrada sola;
una que devuelve siempre `es` fija la lengua sola. Lo único que cambia es **qué política compone
la factoría**.

**Desviación documentada**: el plan pedía crear `NoneLanguagePolicy`, y ya existe
`NeutralLanguagePolicy` en `strategies/protocols.py` con exactamente ese comportamiento —`detect`
a `None`, sin segunda búsqueda, `filter_items` passthrough, sin aviso—. Se reutiliza en vez de
duplicarla: una segunda clase con el mismo cuerpo son dos sitios que pueden divergir, y AGENTS.md
prohíbe el código muerto especulativo.
"""
from __future__ import annotations

from types import SimpleNamespace

from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
)

CONSULTA_EN_CATALAN = "Quin és el límit dels contractes menors de serveis?"


def _cfg(language_mode: str) -> SimpleNamespace:
    """La configuración efectiva que llega a la factoría, con lo justo que lee el perfil."""
    return SimpleNamespace(
        language_mode=language_mode,
        retrieval_mode="RAG",
        system_prompt="Ets l'assistent normatiu.",
        router_index=None,
        query_rewriting_enabled=False,
        public_graph_profile="PUBLIC_KB_RICH",
    )


class TestLaFactoriaCompolePorElModo:
    """El branch que faltaba: `cfg.language_mode` decide la política."""

    def _politica(self, language_mode: str):
        from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
            _make_public_kb_rich,
        )

        grafo = _make_public_kb_rich(_cfg(language_mode), deps=SimpleNamespace(), llm=None)
        return grafo.language_policy

    def test_should_use_the_neutral_policy_for_none(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
            NeutralLanguagePolicy,
        )

        assert isinstance(self._politica("none"), NeutralLanguagePolicy)

    def test_should_use_the_fixed_policy_for_a_fixed_mode(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
            FixedLanguagePolicy,
        )

        politica = self._politica("fixed:es")

        assert isinstance(politica, FixedLanguagePolicy)
        assert politica.detect(CONSULTA_EN_CATALAN) == "es"

    def test_should_keep_the_current_policy_for_prefer(self):
        """Test de regresión: `prefer` sigue siendo el defecto y no cambia de comportamiento."""
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            DefaultLanguagePolicy,
        )

        assert isinstance(self._politica("prefer"), DefaultLanguagePolicy)

    def test_should_fall_back_to_the_current_policy_for_an_unknown_mode(self):
        """La factoría no es el sitio donde se valida: eso es 422 en el router.

        Aquí lo que importa es que un valor raro no reviente el grafo de un chatbot ya
        existente: se comporta como hoy. La validación impide que llegue.
        """
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            DefaultLanguagePolicy,
        )

        assert isinstance(self._politica("castellano"), DefaultLanguagePolicy)


class TestFixedLanguagePolicy:
    """«Responde siempre en X, pregunten como pregunten»."""

    def test_should_not_look_at_the_query_at_all(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
            FixedLanguagePolicy,
        )

        politica = FixedLanguagePolicy("es")

        assert politica.detect(CONSULTA_EN_CATALAN) == "es"
        assert politica.detect("Whatever the question is") == "es"
        assert politica.detect("") == "es"

    def test_should_prefer_that_version_of_a_bilingual_norm(self):
        """Hereda la ordenación de `prefer`: la lengua fijada gana **dentro** de la vigencia."""
        from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
            FixedLanguagePolicy,
        )

        ca = EvidenceItem(source_id="norma-ca", content="Contingut", language="ca")
        es = EvidenceItem(source_id="norma-es", content="Contenido", language="es")

        ordenados = FixedLanguagePolicy("es").filter_items("es", [ca, es])

        assert [i.source_id for i in ordenados] == ["norma-es", "norma-ca"]


class TestElEfectoAguasAbajo:
    """Que la política decida la lengua no sirve de nada si no llega al prompt y a la búsqueda."""

    def test_should_instruct_the_fixed_language_in_the_prompt(self):
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            GenericAnswerTemplateStrategy,
        )
        from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
            FixedLanguagePolicy,
        )

        lang = FixedLanguagePolicy("es").detect(CONSULTA_EN_CATALAN)
        prompt = GenericAnswerTemplateStrategy(base_system_prompt="Assistent").build_prompt_context(
            items=[EvidenceItem(source_id="d", content="text", language="ca")],
            language=lang,
            query=CONSULTA_EN_CATALAN,
        )

        assert "Responde en es." in prompt

    def test_should_not_instruct_any_language_with_the_neutral_policy(self):
        """`none` es «sin política»: ni detección, ni orden por lengua, ni instrucción."""
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            GenericAnswerTemplateStrategy,
        )
        from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
            NeutralLanguagePolicy,
        )

        politica = NeutralLanguagePolicy()
        lang = politica.detect(CONSULTA_EN_CATALAN)
        prompt = GenericAnswerTemplateStrategy(base_system_prompt="Assistent").build_prompt_context(
            items=[EvidenceItem(source_id="d", content="text", language="ca")],
            language=lang,
            query=CONSULTA_EN_CATALAN,
        )

        assert lang is None
        assert "Responde en" not in prompt

    def test_should_not_launch_a_secondary_search_with_the_neutral_policy(self):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
            NeutralLanguagePolicy,
        )

        politica = NeutralLanguagePolicy()
        items = [EvidenceItem(source_id="d", content="text", language="ca")]

        assert politica.needs_secondary_search(politica.detect(CONSULTA_EN_CATALAN), items) is False


class TestElValorSeValidaAlEscribirse:
    """`String(20)` libre: hoy `language_mode="castellano"` cae a `prefer` sin avisar."""

    def test_should_accept_the_three_modes(self):
        from server.app.core.language_mode import valida_language_mode

        for valor in ("prefer", "none", "fixed:es", "fixed:ca", "fixed:eng"):
            assert valida_language_mode(valor) == valor

    def test_should_refuse_a_language_name_instead_of_a_mode(self):
        import pytest

        from server.app.core.language_mode import valida_language_mode

        with pytest.raises(ValueError, match="Modo de lengua no válido") as exc:
            valida_language_mode("castellano")

        # El mensaje enumera los modos: un 422 que solo dice «inválido» obliga a leer el código.
        assert "prefer" in str(exc.value)
        assert "fixed:" in str(exc.value)

    def test_should_refuse_a_fixed_mode_without_a_language(self):
        import pytest

        from server.app.core.language_mode import valida_language_mode

        with pytest.raises(ValueError, match="Modo de lengua no válido"):
            valida_language_mode("fixed:")

    def test_should_refuse_a_fixed_mode_with_a_bogus_code(self):
        import pytest

        from server.app.core.language_mode import valida_language_mode

        for valor in ("fixed:ESP", "fixed:e", "fixed:espanyol", "fixed:es-ES"):
            with pytest.raises(ValueError, match="Modo de lengua no válido"):
                valida_language_mode(valor)


class TestElRouterDevuelve422:
    """El valor se rechaza **al escribirse**, que es donde se puede corregir.

    Se prueba contra los modelos del contrato y no montando la aplicación: lo que se quiere fijar
    es que el campo lleva el validador, y un Pydantic que levanta `ValidationError` es
    exactamente el 422 que FastAPI devuelve. Montar el router entero para esto pediría base de
    datos y autenticación, y no mediría nada más.
    """

    def test_should_refuse_creating_a_chatbot_with_a_bogus_mode(self):
        import uuid

        import pytest
        from pydantic import ValidationError

        from server.app.routers.hub_chatbots_router import ChatbotCreate

        comunes = {
            "name": "Assistent",
            "organizacion_id": uuid.uuid4(),
            "llm_config_id": uuid.uuid4(),
            "system_prompt": "Ets l'assistent.",
        }

        with pytest.raises(ValidationError) as exc:
            ChatbotCreate(**comunes, language_mode="castellano")
        assert "prefer" in str(exc.value)

        # Y los tres modos buenos entran.
        for modo in ("prefer", "none", "fixed:es"):
            assert ChatbotCreate(**comunes, language_mode=modo).language_mode == modo

    def test_should_refuse_updating_a_chatbot_with_a_bogus_mode(self):
        import pytest
        from pydantic import ValidationError

        from server.app.routers.hub_chatbots_router import ChatbotUpdate

        with pytest.raises(ValidationError):
            ChatbotUpdate(language_mode="fixed:")

        assert ChatbotUpdate(language_mode="fixed:ca").language_mode == "fixed:ca"
        # `None` sigue significando «no lo mandé»: la validación no puede romper el parcheo.
        assert ChatbotUpdate().language_mode is None

    def test_should_refuse_a_bogus_default_for_an_organization(self):
        import pytest
        from pydantic import ValidationError

        from server.app.routers.hub_organizaciones_router import ValoresPorDefectoUpdate

        with pytest.raises(ValidationError) as exc:
            ValoresPorDefectoUpdate(default_language_mode="valencià")
        assert "fixed:" in str(exc.value)

        assert (
            ValoresPorDefectoUpdate(default_language_mode="none").default_language_mode == "none"
        )
