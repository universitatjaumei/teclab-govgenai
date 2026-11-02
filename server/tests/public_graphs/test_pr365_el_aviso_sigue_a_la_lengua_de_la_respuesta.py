"""PR #365 — el aviso de traducción sigue a la lengua en que el modelo ha **contestado**.

Lo vio Copilot al revisar #363. Desde #363 la lengua de la respuesta la decide el modelo, pero el
aviso de traducción (VIS.5) se seguía calculando en `merge` con `state["language"]`, que ahora es
sólo **la preferencia de versión del corpus**. Con «¿Cuál es mi nota de DOCENTIA?» en una página
en valenciano, `language` es `val` (la reserva), las fuentes son valencianas, y el aviso se
omitía aunque el modelo contestara —bien— en castellano: quien pregunta leía una traducción sin
saberlo.

Ahora el aviso se decide **después de generar**, con la lengua de la respuesta detectada sobre su
propio texto —largo, así que la detección es fiable— y la misma política de lengua, de modo que
`none` y `strict` siguen sin avisar. Los títulos de los enlaces se quitan antes de detectar: están
en la lengua de la fuente y empujarían la detección justo hacia la que oculta el aviso.
"""
from __future__ import annotations

import uuid

import pytest

from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
)

NOTA = "¿Cuál es mi nota de DOCENTIA?"
URL = "https://normativa.uji.es/html/val_Reglament.html"
TITULO_VAL = "Reglament d'avaluació de l'activitat docent del professorat de la Universitat Jaume I"

RESPUESTA_ES = (
    "No puedo consultar tu nota: el asistente no tiene acceso a los datos personales del "
    "profesorado. Puedes ver tu resultado en la actividad de evaluación docente del IGLU, y si no "
    "estás de acuerdo puedes presentar un recurso de reposición ante el Rectorado en el plazo de "
    f"un mes [{TITULO_VAL}, art. 11]({URL})."
)
RESPUESTA_VAL = (
    "No puc consultar la teua nota: l'assistent no té accés a les dades personals del "
    "professorat. Pots veure el teu resultat en l'activitat d'avaluació docent de l'IGLU, i si no "
    "hi estàs d'acord pots presentar un recurs de reposició davant del Rectorat en el termini "
    f"d'un mes [{TITULO_VAL}, art. 11]({URL})."
)


class TestLaLenguaDeLaRespuesta:

    def test_should_ignore_the_titles_of_the_links(self):
        from server.app.modules.agents_hub.services.language_detector import (
            lengua_de_la_respuesta,
        )

        assert lengua_de_la_respuesta(RESPUESTA_ES, reserva="val") == "es"
        assert lengua_de_la_respuesta(RESPUESTA_VAL, reserva="es") == "val"


class TestElGrafoDecideElAvisoConLaRespuesta:

    @pytest.mark.asyncio
    async def test_should_warn_when_the_model_answers_in_another_language_than_the_sources(self):
        """El caso de Copilot: preferencia `val`, fuentes `val`, respuesta en castellano."""
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            DefaultLanguagePolicy,
        )

        estado = await _ejecutar(DefaultLanguagePolicy(), RESPUESTA_ES)

        assert estado["language"] == "val"
        assert estado["lengua_de_la_respuesta"] == "es"
        assert estado["translation_warning"] is True

    @pytest.mark.asyncio
    async def test_should_not_warn_when_the_answer_is_in_the_language_of_the_sources(self):
        from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
            DefaultLanguagePolicy,
        )

        estado = await _ejecutar(DefaultLanguagePolicy(), RESPUESTA_VAL)

        assert estado["lengua_de_la_respuesta"] == "val"
        assert estado["translation_warning"] is False

    @pytest.mark.asyncio
    async def test_should_keep_the_neutral_policy_silent(self):
        """`none` es «sin política»: ni detección ni aviso, conteste el modelo en lo que conteste."""
        from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
            NeutralLanguagePolicy,
        )

        estado = await _ejecutar(NeutralLanguagePolicy(), RESPUESTA_ES)

        assert estado.get("lengua_de_la_respuesta") is None
        assert estado["translation_warning"] is False


class TestElChatRedactaElAvisoEnLaLenguaDeLaRespuesta:

    def test_should_use_the_flag_and_the_language_of_the_final_node(self):
        """`merge` dijo que no (preferencia `val` = fuente `val`); el nodo final, que sí y que la
        respuesta es castellana. Gana el nodo final, y el aviso se redacta en castellano."""
        from unittest.mock import AsyncMock, MagicMock, patch

        from server.app.modules.agents_hub.database.config_models import HubChatbot
        from server.tests.modules.agents_hub.unit.test_chat_endpoint import (
            _JWT_ENV,
            ORG_PRUEBA,
            _build_test_app,
            _make_mock_graph_astream_events,
            _make_token,
            _parse_sse_lines,
        )
        from fastapi.testclient import TestClient

        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()

        eventos = [
            {"event": "on_chain_end", "name": "detect_language",
             "data": {"output": {"language": "val"}}},
            {"event": "on_chain_end", "name": "merge",
             "data": {"output": {"translation_warning": False, "context_source_language": "val"}}},
            {"event": "on_chain_end", "name": "generate_answer",
             "data": {"output": {"sources": [], "fallback_used": False,
                                 "translation_warning": True, "lengua_de_la_respuesta": "es"}}},
        ]
        modulo = "server.app.modules.agents_hub.services.turno_de_chat"
        with patch.dict("os.environ", _JWT_ENV), patch(
            f"{modulo}.GraphFactory",
            return_value=MagicMock(build=AsyncMock(return_value=_make_mock_graph_astream_events(eventos))),
        ), patch(f"{modulo}.resolve_embedding_service", new_callable=AsyncMock), patch(
            f"{modulo}.get_model", new_callable=AsyncMock
        ):
            app = _build_test_app(chatbot)
            with TestClient(app) as cliente:
                with cliente.stream(
                    "POST", f"/api/v1/hub/chat/{chatbot.id}", json={"message": NOTA},
                    headers={"Authorization": f"Bearer {_make_token()}"},
                ) as respuesta:
                    lineas = list(respuesta.iter_lines())

        done = [p for e, p in _parse_sse_lines(lineas) if e == "done"][0]
        assert done["language_fallback"] is True
        assert "está" in done["translation_warning"], done["translation_warning"]


async def _ejecutar(politica, respuesta: str) -> dict:
    from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
        PublicGraphConfig,
    )
    from server.app.modules.agents_hub.agent.public_graphs.core.core_graph import CoreGraph
    from server.app.modules.agents_hub.agent.public_graphs.profiles.public_kb_rich import (
        GenericAnswerTemplateStrategy,
    )
    from server.app.modules.agents_hub.agent.public_graphs.strategies.protocols import (
        RetrievalOutput,
        RetrievalResult,
    )

    evidencia = EvidenceItem(
        source_id="reg", content="Art. 11. Recurs de reposició en el termini d'un mes.",
        source_url=URL, title=TITULO_VAL, score=0.9, language="val",
    )

    class _Retrieval:
        async def retrieve(self, query, chatbot_id, cfg, deps, language=None):
            return RetrievalOutput(buckets=[RetrievalResult(
                items=[evidencia], debug={}, context_source_language="val",
            )])

    class _Merge:
        def merge(self, output):
            return [i for b in output.buckets for i in b.items]

    class _Llm:
        async def ainvoke(self, mensajes, **kwargs):
            class _R:
                content = respuesta
            return _R()

    cfg = PublicGraphConfig(
        profile="PUBLIC_KB_RICH", retrieval_mode="RAG", language_mode="prefer",
        quality_threshold=0.0, min_retrieval_results=1, min_retrieval_score=0.0,
        reranker_enabled=False, answer_template="generic",
    )
    grafo = CoreGraph(
        retrieval_strategy=_Retrieval(), merge_strategy=_Merge(),
        template_strategy=GenericAnswerTemplateStrategy(base_system_prompt="x"),
        language_policy=politica, cfg=cfg, deps=object(), llm=_Llm(),
    )
    return await grafo.run(NOTA, str(uuid.uuid4()), lengua_de_la_pagina="val")
