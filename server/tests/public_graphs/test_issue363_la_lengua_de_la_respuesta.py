"""#363 — la lengua de la respuesta la decide el modelo, no `langdetect`.

**El defecto, medido el 2026-11-02** con 43 preguntas reales de los técnicos de la OPAQ sobre el
DOCENTIA: `detect_language` devuelve lo que diga `langdetect`, que conoce más de 50 lenguas.
«¿Cuál es mi nota de DOCENTIA?» salía `pt` y «Quan estan obertes les enquestes del primer
semestre?» `fr`. El prompt decía «Responde en pt», `gemini-4-argon` lo obedecía —una respuesta
entera en francés en producción— y, como ninguna versión del corpus es portuguesa, el contexto
largo cargaba las dos lenguas: 429.000 caracteres en vez de 229.000.

**Restringir el detector no basta**, y por eso la decisión del usuario fue otra. Limitado a
castellano, valenciano e inglés, `langdetect` sigue fallando 4 de las 43: «¿Cómo funciona DOCENTIA
en la Universitat de València?» sale valenciano **con un 100 %** de confianza. Un modelo de lenguaje
distingue esas lenguas sin esfuerzo. Así que:

- el prompt dice «responde en la lengua de la pregunta: castellano, valenciano o inglés; si no está
  clara, en X», y X es la lengua de la página donde está el widget (`lang`), que el widget ya
  mandaba y la API tiraba porque `ChatRequest` no la declaraba;
- `langdetect` sólo decide **qué versión del corpus** se prefiere, limitado a esas tres lenguas y,
  si no está seguro, con la de la página como reserva;
- `fixed:<código>` sigue obligando y `none` sigue sin decir nada: son decisiones del organismo.
"""
from __future__ import annotations

import uuid

import pytest

from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
)

NOTA = "¿Cuál es mi nota de DOCENTIA?"  # langdetect: pt 1.00
ENQUESTES = "Quan estan obertes les enquestes del primer semestre?"  # fr 0.57, es 0.29, ca 0.14
VALENCIA = "¿Cómo funciona DOCENTIA en la Universitat de València?"  # ca 1.00
CASTELLANO_CLARO = (
    "Durante el curso pasado dirigí un proyecto de innovación educativa y no me aparece en los "
    "resultados del programa. ¿A quién tengo que dirigirme para que lo revisen?"
)
VALENCIANO_CLAR = (
    "Durant el curs passat vaig dirigir un projecte d'innovació educativa i no m'apareix en els "
    "resultats del programa. A qui m'he d'adreçar perquè el revisen?"
)


class TestElDetectorSoloConoceLasLenguasDeRespuesta:

    def test_should_never_return_a_language_outside_spanish_valencian_or_english(self):
        from server.app.modules.agents_hub.services.language_detector import (
            lengua_de_la_pregunta,
        )

        for texto in (NOTA, ENQUESTES, VALENCIA, CASTELLANO_CLARO, VALENCIANO_CLAR):
            assert lengua_de_la_pregunta(texto, reserva=None) in {"es", "val", "en", None}

    def test_should_use_the_page_language_when_no_admitted_language_is_a_candidate(self):
        from server.app.modules.agents_hub.services.language_detector import (
            lengua_de_la_pregunta,
        )

        assert lengua_de_la_pregunta(NOTA, reserva="es") == "es"
        assert lengua_de_la_pregunta(NOTA, reserva="val") == "val"

    def test_should_use_the_page_language_when_the_detector_is_not_sure(self):
        from server.app.modules.agents_hub.services.language_detector import (
            lengua_de_la_pregunta,
        )

        assert lengua_de_la_pregunta(ENQUESTES, reserva="val") == "val"

    def test_should_trust_a_clear_question_over_the_page_language(self):
        from server.app.modules.agents_hub.services.language_detector import (
            lengua_de_la_pregunta,
        )

        assert lengua_de_la_pregunta(CASTELLANO_CLARO, reserva="val") == "es"
        assert lengua_de_la_pregunta(VALENCIANO_CLAR, reserva="es") == "val"

    def test_should_give_the_same_answer_every_time(self):
        """`langdetect` es aleatorio si no se le fija la semilla, y no la tenía fijada: con un
        texto ambiguo, dos llamadas podían dar lenguas distintas."""
        from server.app.modules.agents_hub.services.language_detector import (
            lengua_de_la_pregunta,
        )

        resultados = {lengua_de_la_pregunta(ENQUESTES, reserva=None) for _ in range(30)}

        assert len(resultados) == 1


class TestLaPoliticaPorDefectoUsaLaReserva:

    def test_should_fall_back_to_the_page_language(self):
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            DefaultLanguagePolicy,
        )

        politica = DefaultLanguagePolicy()

        assert politica.detect_con_reserva(NOTA, "val") == "val"
        assert politica.detect(NOTA) != "pt"


class TestElGrafoRecibeLaLenguaDeLaPagina:

    @pytest.mark.asyncio
    async def test_should_pass_the_page_language_as_the_reserve(self):
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            DefaultLanguagePolicy,
        )

        grafo = _grafo(DefaultLanguagePolicy())

        estado = await grafo.run(
            NOTA, str(uuid.uuid4()), debug_bypass=True, lengua_de_la_pagina="val"
        )

        assert estado["language"] == "val"

    @pytest.mark.asyncio
    async def test_should_keep_working_with_policies_that_only_know_detect(self):
        """Las políticas de terceros (PLG) sólo implementan `detect`: la reserva es opcional."""

        class _SoloDetect:
            def detect(self, query):
                return "es"

            def filter_items(self, language, items):
                return items

            def should_warn_translation(self, a, b):
                return False

        estado = await _grafo(_SoloDetect()).run(
            NOTA, str(uuid.uuid4()), debug_bypass=True, lengua_de_la_pagina="val"
        )

        assert estado["language"] == "es"


class TestElPromptDejaLaLenguaAlModelo:

    def _prompt(self, language, language_mode="prefer"):
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            GenericAnswerTemplateStrategy,
        )

        return GenericAnswerTemplateStrategy(
            base_system_prompt="Assistent", language_mode=language_mode
        ).build_prompt_context(
            items=[EvidenceItem(source_id="d", content="text", language="val")],
            language=language,
            query=ENQUESTES,
        )

    def test_should_ask_for_the_language_of_the_question_with_the_reserve(self):
        prompt = self._prompt("val")

        assert "lengua en que está escrita la pregunta" in prompt
        assert "castellano, valenciano o inglés" in prompt
        assert "Si no está clara, responde en valenciano." in prompt
        assert "Responde en val." not in prompt

    def test_should_still_ask_for_the_language_of_the_question_without_a_reserve(self):
        prompt = self._prompt(None)

        assert "castellano, valenciano o inglés" in prompt
        assert "Si no está clara" not in prompt

    def test_should_keep_forcing_the_language_in_fixed_mode(self):
        prompt = self._prompt("es", language_mode="fixed:es")

        assert "Responde en castellano" in prompt
        assert "lengua en que está escrita la pregunta" not in prompt

    def test_should_say_nothing_about_language_without_a_policy(self):
        prompt = self._prompt(None, language_mode="none")

        assert "Responde en" not in prompt
        assert "lengua en que está escrita la pregunta" not in prompt

    def test_should_build_the_template_with_the_language_mode_of_the_chatbot(self):
        from types import SimpleNamespace

        from server.app.modules.agents_hub.agent.public_graphs.strategies.nucleo import (
            generic_template,
        )

        plantilla = generic_template(
            SimpleNamespace(
                system_prompt="x", retrieval_mode="RAG", router_index=None,
                language_mode="fixed:val",
            ),
            deps=None,
        )

        prompt = plantilla.build_prompt_context([], "val", "pregunta")

        assert "Responde en valenciano" in prompt


class TestLaApiAceptaLaLenguaDeLaPagina:

    @pytest.mark.parametrize(
        ("enviada", "esperada"),
        [("es", "es"), ("ca", "val"), ("val", "val"), ("en", "en"), ("es-ES", "es"),
         ("CA", "val"), ("pt", None), ("", None), (None, None)],
    )
    def test_should_normalise_the_page_language(self, enviada, esperada):
        """Un `data-lang` raro en una página que embebe el widget no puede tumbar el chat: lo que
        no es una lengua de respuesta se ignora, y el modelo sigue contestando en la de la
        pregunta."""
        from server.app.api.v1.hub_chat import ChatRequest

        cuerpo = {"message": "hola"}
        if enviada is not None:
            cuerpo["lang"] = enviada

        assert ChatRequest(**cuerpo).lengua_de_la_pagina == esperada


class TestPorHttp:
    """Que la API la declare no sirve si no llega al grafo: la petición real, hasta el estado
    inicial que recibe LangGraph."""

    def test_should_carry_the_page_language_from_the_request_to_the_graph(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from server.app.modules.agents_hub.database.config_models import HubChatbot
        from server.tests.modules.agents_hub.integration.test_debug_bypass import (
            ORG_PRUEBA,
            TestEndpointDeBypass,
        )

        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        cliente, _ = TestEndpointDeBypass()._cliente(chatbot)

        compilado = MagicMock()
        compilado.ainvoke = AsyncMock(return_value={"bypass": {"system_prompt": "S"}})
        grafo = MagicMock(cfg=MagicMock(), compile=MagicMock(return_value=compilado))
        modulo = "server.app.modules.agents_hub.services.turno_de_chat"

        with patch(
            f"{modulo}.GraphFactory", return_value=MagicMock(build=AsyncMock(return_value=grafo))
        ), patch(f"{modulo}.resolve_embedding_service", new_callable=AsyncMock), patch(
            f"{modulo}.assert_embedding_space_matches", new_callable=AsyncMock
        ), patch(f"{modulo}.get_model", new_callable=AsyncMock):
            resp = cliente.post(
                f"/api/v1/hub/chat/{chatbot.id}",
                json={"message": NOTA, "lang": "ca", "debug_bypass": True},
            )

        assert resp.status_code == 200
        estado_inicial = compilado.ainvoke.call_args.args[0]
        assert estado_inicial["lengua_de_la_pagina"] == "val"


def _grafo(politica):
    from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
        PublicGraphConfig,
    )
    from server.app.modules.agents_hub.agent.public_graphs.core.core_graph import CoreGraph
    from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
        RetrievalOutput,
        RetrievalResult,
    )

    class _Retrieval:
        async def retrieve(self, query, chatbot_id, cfg, deps, language=None):
            return RetrievalOutput(
                buckets=[
                    RetrievalResult(items=[EvidenceItem(source_id="d", content="t")], debug={})
                ]
            )

    class _Merge:
        def merge(self, output):
            return [i for b in output.buckets for i in b.items]

    class _Template:
        def build_prompt_context(self, items, language, query):
            return "SYSTEM"

    cfg = PublicGraphConfig(
        profile="PUBLIC_KB_RICH", retrieval_mode="RAG", language_mode="prefer",
        quality_threshold=0.0, min_retrieval_results=1, min_retrieval_score=0.0,
        reranker_enabled=False, answer_template="generic",
    )
    return CoreGraph(
        retrieval_strategy=_Retrieval(), merge_strategy=_Merge(), template_strategy=_Template(),
        language_policy=politica, cfg=cfg, deps=object(), llm=None,
    )
