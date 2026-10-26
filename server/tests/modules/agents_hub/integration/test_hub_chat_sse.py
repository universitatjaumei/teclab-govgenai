"""Tests de integración SSE: evento done emite Source[] estructurado (9CBis.10).

Verifica que el evento 'done' serializa Source[] con (document_id, title, url, score)
en los tres modos de retrieval y que la selección de strategy es correcta.
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.modules.agents_hub.database.config_models import HubChatbot
from server.app.modules.agents_hub.services.retrieval.types import Source
from server.tests.dobles import completar_chatbot

# SEC.2: el chat exige que el principal gestione la organización del chatbot. Estos
# tests prueban el grafo, no la tenencia —que tiene su gate en
# `tests/api/test_tenant_isolation.py`—, así que doble y token comparten organización.
ORG_PRUEBA = "00000000-0000-0000-0000-00000000dead"


def _con_acceso(chatbot):
    """Declara el modo de acceso del doble (SEC.2.1).

    Sin esto, `access_mode` es un MagicMock y `assert_chatbot_access` cierra ante un modo
    que no reconoce —que es lo que debe hacer—. Estos tests miden el protocolo SSE; la
    autorización tiene su gate en `tests/api/test_chatbot_access_mode.py`.
    """
    return completar_chatbot(chatbot)

_JWT_ENV = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}


def _make_token(user_id: str = "user-1") -> str:
    import os
    os.environ.update(_JWT_ENV)
    from server.app.core.auth import UserInfo, create_token
    return create_token(
        UserInfo(
            user_id=user_id, email="user@test.com", role="user",
            organizacion_ids=(ORG_PRUEBA,),
        )
    )


def _build_test_app(chatbot_mock) -> FastAPI:
    from server.app.api.v1.hub_chat import router as chat_router
    from server.app.api.deps import get_session
    from sqlalchemy.ext.asyncio import AsyncSession

    mock_session = AsyncMock(spec=AsyncSession)
    mock_scalar = MagicMock()
    mock_scalar.scalar_one_or_none = MagicMock(return_value=chatbot_mock)
    mock_session.execute = AsyncMock(return_value=mock_scalar)
    # SEC.4: la organización se lee para la cascada de cuotas; `None` = sin cuotas
    # heredadas. Con el doble por defecto, los límites serían números inventados.
    mock_session.get = AsyncMock(return_value=None)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    async def _mock_session():
        yield mock_session

    app = FastAPI()
    app.dependency_overrides[get_session] = _mock_session
    app.include_router(chat_router, prefix="/api/v1")
    return app


def _parse_sse_lines(lines: list[str]) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    current_event = "message"
    for line in lines:
        if line.startswith("event:"):
            current_event = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            payload = json.loads(line.removeprefix("data:").strip())
            events.append((current_event, payload))
            current_event = "message"
    return events


def _make_mock_graph_with_sources(
    sources: list,
    language_fallback: bool = False,
    language: str = "es",
) -> MagicMock:
    """Grafo mock que emite on_chain_end/generate_response con las fuentes dadas."""
    raw_events = [
        {
            "event": "on_chain_end",
            "name": "generate_answer",
            "data": {
                "output": {
                    "sources": sources,
                    "language_fallback_triggered": language_fallback,
                    "language": language,
                }
            },
        }
    ]

    async def _astream(state, config=None, version="v2"):
        for ev in raw_events:
            yield ev

    mock_compiled = MagicMock()
    mock_compiled.astream_events = _astream
    mock_graph = MagicMock()
    mock_graph.compile = MagicMock(return_value=mock_compiled)
    return mock_graph


def _run_chat_and_get_done(chatbot, graph, token) -> dict:
    """Ejecuta el endpoint de chat y devuelve el payload del evento done."""
    app = _build_test_app(chatbot)
    with (
        patch("server.app.modules.agents_hub.services.turno_de_chat.GraphFactory",
                  return_value=MagicMock(build=AsyncMock(return_value=graph))),
        patch("server.app.modules.agents_hub.services.turno_de_chat.resolve_embedding_service", new_callable=AsyncMock),
        patch("server.app.modules.agents_hub.services.turno_de_chat.get_model", new_callable=AsyncMock),
    ):
        with TestClient(app) as client:
            with client.stream(
                "POST",
                f"/api/v1/hub/chat/{chatbot.id}",
                json={"message": "Test"},
                headers={"Authorization": f"Bearer {token}"},
            ) as response:
                lines = list(response.iter_lines())

    events = _parse_sse_lines(lines)
    done_events = [(e, p) for e, p in events if e == "done"]
    assert len(done_events) == 1, f"Se esperaba 1 evento 'done', encontrados: {len(done_events)}"
    return done_events[0][1]


# ──────────────────────────────────────────────────────────────────────────────
# Serialización estructurada de Source[]
# ──────────────────────────────────────────────────────────────────────────────

class TestDoneEventStructuredSources:

    @patch.dict("os.environ", _JWT_ENV)
    def test_done_event_includes_structured_sources_with_document_id(self) -> None:
        """El done incluye sources[].document_id como string UUID válido."""
        doc_id = uuid.uuid4()
        sources = [
            Source(
                document_id=doc_id,
                title="Reglament del Consell de Govern",
                url="https://www.uji.es/upo/rest/contenido/988181723/raw?idioma=ca",
                excerpt="text",
                score=0.92,
            )
        ]
        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        _con_acceso(chatbot)

        done = _run_chat_and_get_done(chatbot, _make_mock_graph_with_sources(sources), _make_token())

        assert len(done["sources"]) == 1
        src = done["sources"][0]
        assert "document_id" in src
        assert src["document_id"] == str(doc_id)
        uuid.UUID(src["document_id"])  # debe ser UUID válido

    @patch.dict("os.environ", _JWT_ENV)
    def test_done_event_sources_have_title_url_and_score(self) -> None:
        """Cada source tiene title, url y score redondeado a 3 decimales."""
        doc_id = uuid.uuid4()
        sources = [
            Source(
                document_id=doc_id,
                title="Estatuts UJI",
                url="https://dogv.gva.es/datos/2025/12/18/pdf/2025_50021_va.pdf",
                excerpt="text",
                score=0.876543,
            )
        ]
        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        _con_acceso(chatbot)

        done = _run_chat_and_get_done(chatbot, _make_mock_graph_with_sources(sources), _make_token())

        src = done["sources"][0]
        assert src["title"] == "Estatuts UJI"
        assert src["url"] == "https://dogv.gva.es/datos/2025/12/18/pdf/2025_50021_va.pdf"
        assert isinstance(src["score"], float)
        assert src["score"] == round(0.876543, 3)

    @patch.dict("os.environ", _JWT_ENV)
    def test_done_event_empty_sources_when_no_retrieval_happened(self) -> None:
        """Si generate_response devuelve sources=[], done emite sources=[]."""
        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        _con_acceso(chatbot)

        done = _run_chat_and_get_done(chatbot, _make_mock_graph_with_sources([]), _make_token())

        assert done["sources"] == []

    @patch.dict("os.environ", _JWT_ENV)
    def test_done_event_multiple_sources_all_serialized(self) -> None:
        """Todas las fuentes se serializan, no solo la primera."""
        sources = [
            Source(document_id=uuid.uuid4(), title=f"Doc {i}",
                   url=f"https://example.com/doc{i}.pdf",
                   excerpt="text", score=round(0.9 - i * 0.1, 1))
            for i in range(3)
        ]
        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        _con_acceso(chatbot)

        done = _run_chat_and_get_done(chatbot, _make_mock_graph_with_sources(sources), _make_token())

        assert len(done["sources"]) == 3
        titles = {s["title"] for s in done["sources"]}
        assert titles == {"Doc 0", "Doc 1", "Doc 2"}


# ──────────────────────────────────────────────────────────────────────────────
# Selección de RetrievalStrategy según retrieval_mode
# ──────────────────────────────────────────────────────────────────────────────

class TestRetrievalModeDispatch:
    """Reapuntado en RAG.2.

    Antes se comprobaba que el endpoint instanciara `LongContextRetrievalStrategy`,
    `AgenticRetrievalStrategy` o `VectorRetrievalStrategy` según el modo. Esa decisión ya
    no vive en el endpoint: la GraphFactory resuelve la cascada de config y
    `PipelineRetrievalStrategy` enruta al pipeline que corresponda a `cfg.retrieval_mode`.

    La aserción de comportamiento se conserva —cada modo acaba en su pipeline— pero
    apuntando al seam nuevo, que es donde ahora se toma la decisión.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("mode", "esperado"),
        [
            ("RAG", "RagVectorPipeline"),
            ("MD_LONG_CONTEXT", "MdLongContextPipeline"),
            ("MD_AGENT_SELECTOR", "MdAgentSelectorPipeline"),
        ],
    )
    async def test_each_retrieval_mode_dispatches_to_its_pipeline(self, mode, esperado):
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_factory import (
            get_pipeline,
        )

        assert type(get_pipeline(mode)).__name__ == esperado

    @pytest.mark.asyncio
    async def test_chatbot_retrieval_mode_reaches_the_graph_config(self):
        """El modo del chatbot llega al cfg del CoreGraph por la cascada, sin que el
        endpoint elija estrategia."""
        from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
            GraphFactory,
        )
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
            GraphDeps,
        )

        chatbot = MagicMock(spec=HubChatbot)

        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        _con_acceso(chatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.retrieval_mode = "MD_LONG_CONTEXT"
        chatbot.public_graph_profile = None
        chatbot.language_mode = None
        chatbot.quality_threshold = None
        chatbot.min_retrieval_results = None
        chatbot.min_retrieval_score = None
        chatbot.reranker_enabled = None
        chatbot.answer_template = None
        chatbot.system_prompt = "Eres un asistente."

        session = AsyncMock()
        session.get = AsyncMock(side_effect=[chatbot, None])

        graph = await GraphFactory().build(
            chatbot.id, GraphDeps(session=session, embedder=AsyncMock()), llm=None
        )

        assert graph.cfg.retrieval_mode == "MD_LONG_CONTEXT"
        assert graph.agentic_loop is None, "sólo el modo selector monta el loop agéntico"

    @pytest.mark.asyncio
    async def test_selector_mode_attaches_the_agentic_loop(self):
        from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
            build_agentic_loop_if_needed,
        )
        from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
            PublicGraphConfig,
        )
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
            GraphDeps,
        )

        def _cfg(mode):
            return PublicGraphConfig(
                profile="PUBLIC_KB_RICH", retrieval_mode=mode, language_mode="prefer",
                quality_threshold=0.6, min_retrieval_results=2, min_retrieval_score=0.25,
                reranker_enabled=False, answer_template="generic",
            )

        deps = GraphDeps(session=AsyncMock(), embedder=AsyncMock())
        assert build_agentic_loop_if_needed(_cfg("RAG"), deps) is None
        assert build_agentic_loop_if_needed(_cfg("MD_AGENT_SELECTOR"), deps) is not None

    @patch.dict("os.environ", _JWT_ENV)
    def test_long_context_mode_sources_marked_with_canonical_urls(self) -> None:
        """En modo long_context, los sources del done tienen la URL canónica del HubDocument."""
        canonical_url = "https://www.uji.es/upo/rest/contenido/1175964720/raw?idioma=ca"
        sources = [
            Source(
                document_id=uuid.uuid4(),
                title="Reglament del Claustre",
                url=canonical_url,
                excerpt="text complet",
                score=1.0,
            )
        ]
        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        _con_acceso(chatbot)
        chatbot.retrieval_mode = "MD_LONG_CONTEXT"

        done = _run_chat_and_get_done(chatbot, _make_mock_graph_with_sources(sources), _make_token())

        assert len(done["sources"]) == 1
        assert done["sources"][0]["url"] == canonical_url
        assert done["sources"][0]["score"] == 1.0

    @patch.dict("os.environ", _JWT_ENV)
    def test_agentic_mode_sources_only_include_documents_actually_read(self) -> None:
        """En modo agentic, solo aparecen en sources los documentos que el LLM leyó."""
        read_doc_id = uuid.uuid4()
        unread_doc_id = uuid.uuid4()
        # El grafo agentic solo incluye el doc leído, no el listado
        sources_read = [
            Source(
                document_id=read_doc_id,
                title="Reglament Electoral",
                url="https://www.uji.es/upo/rest/contenido/1175964715/raw?idioma=ca",
                excerpt="text",
                score=1.0,
            )
        ]
        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        _con_acceso(chatbot)
        chatbot.retrieval_mode = "MD_AGENT_SELECTOR"

        done = _run_chat_and_get_done(
            chatbot, _make_mock_graph_with_sources(sources_read), _make_token()
        )

        source_ids = {s["document_id"] for s in done["sources"]}
        assert str(read_doc_id) in source_ids
        assert str(unread_doc_id) not in source_ids


# ──────────────────────────────────────────────────────────────────────────────
# Fallback de citas
# ──────────────────────────────────────────────────────────────────────────────

class TestNoCitationFallback:

    @patch.dict("os.environ", _JWT_ENV)
    def test_no_citation_fallback_emits_done_with_empty_sources(self) -> None:
        """Cuando retrieval no encontró nada (sources=[]), done emite sources=[]
        sin lanzar error y con interaction_id válido."""
        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        _con_acceso(chatbot)

        done = _run_chat_and_get_done(chatbot, _make_mock_graph_with_sources([]), _make_token())

        assert done["sources"] == []
        assert "interaction_id" in done
        uuid.UUID(done["interaction_id"])
        assert done["language_fallback"] is False


class TestWidgetKeyAuth:
    """SEC.8.5 — el widget público se autentica con `X-Widget-Key`, sin sesión."""

    def test_anonymous_widget_chat_does_not_crash_without_a_session_user(self) -> None:
        """Sin `Authorization`, `user` es `None`: el manejador de Langfuse leía
        `user.user_id` sin comprobarlo antes (AttributeError -> 500), así que **todo**
        chat anónimo por widget reventaba. El actor efectivo (`actor.subject_id`) es lo
        que ya usa `HubInteraction.user_id` unas líneas más abajo -- es también lo que
        debe usar el manejador de Langfuse, porque para el anónimo no hay otra cosa."""
        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        chatbot.access_mode = "public_anon"
        _con_acceso(chatbot)

        widget_key_row = MagicMock()
        widget_key_row.chatbot_id = chatbot.id

        app = _build_test_app(chatbot)
        with (
            patch(
                "server.app.modules.agents_hub.services.turno_de_chat.GraphFactory",
                return_value=MagicMock(
                    build=AsyncMock(return_value=_make_mock_graph_with_sources([]))
                ),
            ),
            patch("server.app.modules.agents_hub.services.turno_de_chat.resolve_embedding_service", new_callable=AsyncMock),
            patch("server.app.modules.agents_hub.services.turno_de_chat.get_model", new_callable=AsyncMock),
            patch(
                "server.app.api.v1.hub_chat.resolver_widget_key",
                new=AsyncMock(return_value=widget_key_row),
            ),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    f"/api/v1/hub/chat/{chatbot.id}",
                    json={"message": "hola"},
                    headers={"X-Widget-Key": "clave-de-prueba"},
                )

        assert response.status_code == 200, response.text
