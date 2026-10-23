"""Tests TDD para el endpoint de chat con streaming SSE (Prompt 9.8.2).

Protocolo SSE testeado:
  event: status   data: {"node": "...", "msg": "..."}
  event: token    data: {"delta": "..."}
  event: done     data: {"interaction_id": "...", "sources": [...],
                          "language_fallback": bool, "translation_warning": str | null}
  event: error    data: {"message": "..."}

Rutas reales (monorepo):
  src/api/routers/chat.py → server/app/api/v1/hub_chat.py
  tests/e2e/test_chat_endpoint.py → server/tests/modules/agents_hub/unit/test_chat_endpoint.py
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.modules.agents_hub.database.config_models import HubChatbot
from server.tests.dobles import completar_chatbot

# SEC.2: el chat exige que el principal gestione la organización del chatbot. Estos
# tests prueban el grafo, no la tenencia —que tiene su gate en
# `tests/api/test_tenant_isolation.py`—, así que doble y token comparten organización.
ORG_PRUEBA = "00000000-0000-0000-0000-00000000dead"

# JWT env para tests
_JWT_ENV = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}


def _make_token(role: str = "user", user_id: str = "user-1") -> str:
    import os
    os.environ.update(_JWT_ENV)
    from server.app.core.auth import UserInfo, create_token
    return create_token(
        UserInfo(
            user_id=user_id, email="user@test.com", role=role,
            organizacion_ids=(ORG_PRUEBA,),
        )
    )


def _build_test_app(chatbot_mock) -> FastAPI:
    """Crea una app FastAPI aislada con la sesión mockeada.

    SEC.2.1: al doble se le pone el modo de acceso aquí, en un solo sitio. Sin declararlo,
    `access_mode` sería un MagicMock y `assert_chatbot_access` cerraría —correctamente— ante
    un modo que no reconoce. Estos tests miden el protocolo SSE, no la autorización, que
    tiene su gate en `tests/api/test_chatbot_access_mode.py`.
    """
    if chatbot_mock is not None:
        completar_chatbot(chatbot_mock)
    from fastapi import FastAPI
    from server.app.api.v1.hub_chat import router as chat_router
    from server.app.api.deps import get_session
    from sqlalchemy.ext.asyncio import AsyncSession

    mock_session = AsyncMock(spec=AsyncSession)
    mock_scalar = MagicMock()
    mock_scalar.scalar_one_or_none = MagicMock(return_value=chatbot_mock)
    mock_session.execute = AsyncMock(return_value=mock_scalar)
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    # SEC.4: el chat lee la organización para resolver la cascada de cuotas. Sin declararlo,
    # el doble devuelve un MagicMock cuyos límites son números inventados y la petición se
    # va en 429. `None` = organización no encontrada = ninguna cuota heredada, que es lo que
    # estos tests quieren: aquí se mide el protocolo SSE, no las cuotas.
    mock_session.get = AsyncMock(return_value=None)

    async def _mock_session():
        yield mock_session

    app = FastAPI()
    app.dependency_overrides[get_session] = _mock_session
    app.include_router(chat_router, prefix="/api/v1")
    return app


def _parse_sse_lines(lines: list[str]) -> list[tuple[str, dict]]:
    """Parsea líneas SSE y devuelve lista de (event_name, payload)."""
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


def _make_mock_graph_astream_events(events_to_yield: list[dict]):
    """Crea un grafo mock cuyo compiled.astream_events devuelve los eventos dados."""
    async def _mock_astream_events(state, config=None, version="v2"):
        for ev in events_to_yield:
            yield ev

    mock_compiled = MagicMock()
    mock_compiled.astream_events = _mock_astream_events
    mock_graph = MagicMock()
    mock_graph.compile = MagicMock(return_value=mock_compiled)
    return mock_graph


# ──────────────────────────────────────────────────────────────────────────────
# Autenticación
# ──────────────────────────────────────────────────────────────────────────────

class TestChatEndpointAuthentication:

    def test_chat_requires_authentication(self) -> None:
        """Sin token → 401."""
        from server.app.api.v1.hub_chat import router as chat_router
        app = FastAPI()
        app.include_router(chat_router, prefix="/api/v1")

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                f"/api/v1/hub/chat/{uuid.uuid4()}",
                json={"message": "Hola"},
            )
        assert response.status_code == 401

    @patch.dict("os.environ", _JWT_ENV)
    def test_chat_rejects_empty_message(self) -> None:
        """Mensaje vacío → 422."""
        chatbot = MagicMock()
        chatbot.id = uuid.uuid4()
        app = _build_test_app(chatbot)

        token = _make_token()
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                f"/api/v1/hub/chat/{chatbot.id}",
                json={"message": ""},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 422


# ──────────────────────────────────────────────────────────────────────────────
# Chatbot
# ──────────────────────────────────────────────────────────────────────────────

class TestChatEndpointChatbot:

    @patch.dict("os.environ", _JWT_ENV)
    def test_chat_chatbot_not_found_returns_404(self) -> None:
        """Chatbot inexistente → 404."""
        app = _build_test_app(chatbot_mock=None)

        token = _make_token()
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(
                f"/api/v1/hub/chat/{uuid.uuid4()}",
                json={"message": "Hola"},
                headers={"Authorization": f"Bearer {token}"},
            )
        assert response.status_code == 404


# ──────────────────────────────────────────────────────────────────────────────
# Streaming SSE (Prompt 9.8.2)
# ──────────────────────────────────────────────────────────────────────────────

class TestChatEndpointSSE:

    @patch.dict("os.environ", _JWT_ENV)
    def test_chat_endpoint_returns_streaming_response(self) -> None:
        """Petición válida → 200 con Content-Type text/event-stream y cabeceras anti-buffering."""
        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        app = _build_test_app(chatbot)

        mock_graph = _make_mock_graph_astream_events([])  # sin eventos, solo done

        token = _make_token()
        with (
            patch("server.app.api.v1.hub_chat.GraphFactory",
                  return_value=MagicMock(build=AsyncMock(return_value=mock_graph))),
            patch("server.app.api.v1.hub_chat.resolve_embedding_service", new_callable=AsyncMock),
            patch("server.app.api.v1.hub_chat.get_model", new_callable=AsyncMock),
        ):
            with TestClient(app) as client:
                with client.stream(
                    "POST",
                    f"/api/v1/hub/chat/{chatbot.id}",
                    json={"message": "Hola"},
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    assert response.status_code == 200
                    ct = response.headers.get("content-type", "")
                    assert "text/event-stream" in ct
                    # Cabeceras anti-buffering
                    assert response.headers.get("cache-control") == "no-cache"
                    assert response.headers.get("x-accel-buffering") == "no"
                    # Consumir el stream
                    list(response.iter_lines())

    @patch.dict("os.environ", _JWT_ENV)
    def test_chat_endpoint_emits_status_events_per_node(self) -> None:
        """Cada nodo LangGraph que comienza emite un evento SSE 'status'."""
        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        app = _build_test_app(chatbot)

        # Simular on_chain_start para dos nodos conocidos
        raw_events = [
            {"event": "on_chain_start", "name": "detect_language", "data": {}},
            {"event": "on_chain_start", "name": "generate_answer", "data": {}},
        ]
        mock_graph = _make_mock_graph_astream_events(raw_events)

        token = _make_token()
        all_lines: list[str] = []
        with (
            patch("server.app.api.v1.hub_chat.GraphFactory",
                  return_value=MagicMock(build=AsyncMock(return_value=mock_graph))),
            patch("server.app.api.v1.hub_chat.resolve_embedding_service", new_callable=AsyncMock),
            patch("server.app.api.v1.hub_chat.get_model", new_callable=AsyncMock),
        ):
            with TestClient(app) as client:
                with client.stream(
                    "POST",
                    f"/api/v1/hub/chat/{chatbot.id}",
                    json={"message": "Test"},
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    all_lines = list(response.iter_lines())

        events = _parse_sse_lines(all_lines)
        status_events = [(e, p) for e, p in events if e == "status"]
        assert len(status_events) >= 2

        nodes_emitted = [p["node"] for _, p in status_events]
        assert "detect_language" in nodes_emitted
        assert "generate_answer" in nodes_emitted

        # Verificar que los mensajes de progreso son los esperados
        for _, payload in status_events:
            assert "node" in payload
            assert "msg" in payload
            assert len(payload["msg"]) > 0

    @patch.dict("os.environ", _JWT_ENV)
    def test_chat_endpoint_emits_token_events(self) -> None:
        """Cada fragmento del LLM emite un evento SSE 'token' con campo 'delta'."""
        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        app = _build_test_app(chatbot)

        # Simular fragmentos del modelo
        chunk1 = MagicMock()
        chunk1.content = "Hola "
        chunk2 = MagicMock()
        chunk2.content = "mundo"

        raw_events = [
            {"event": "on_chat_model_stream", "name": "ChatGoogleGenerativeAI",
             "data": {"chunk": chunk1}},
            {"event": "on_chat_model_stream", "name": "ChatGoogleGenerativeAI",
             "data": {"chunk": chunk2}},
        ]
        mock_graph = _make_mock_graph_astream_events(raw_events)

        token = _make_token()
        all_lines: list[str] = []
        with (
            patch("server.app.api.v1.hub_chat.GraphFactory",
                  return_value=MagicMock(build=AsyncMock(return_value=mock_graph))),
            patch("server.app.api.v1.hub_chat.resolve_embedding_service", new_callable=AsyncMock),
            patch("server.app.api.v1.hub_chat.get_model", new_callable=AsyncMock),
        ):
            with TestClient(app) as client:
                with client.stream(
                    "POST",
                    f"/api/v1/hub/chat/{chatbot.id}",
                    json={"message": "Test"},
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    all_lines = list(response.iter_lines())

        events = _parse_sse_lines(all_lines)
        token_events = [(e, p) for e, p in events if e == "token"]
        assert len(token_events) == 2

        deltas = [p["delta"] for _, p in token_events]
        assert "Hola " in deltas
        assert "mundo" in deltas

    @patch.dict("os.environ", _JWT_ENV)
    def test_chat_endpoint_emits_done_event_with_sources(self) -> None:
        """El evento 'done' incluye interaction_id, sources (lista de dicts) y language_fallback=False."""
        import uuid as _uuid
        from server.app.modules.agents_hub.services.retrieval.types import Source

        chatbot = MagicMock(spec=HubChatbot)

        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        app = _build_test_app(chatbot)

        # Simular fin del nodo generate_response con fuentes (Source objects)
        doc_id = _uuid.uuid4()
        sources = [
            Source(document_id=doc_id, title="Norma A", url="https://ej.com/a.pdf",
                   excerpt="texto", score=0.9),
        ]
        raw_events = [
            {
                "event": "on_chain_end",
                "name": "generate_answer",
                "data": {
                    "output": {
                        "sources": sources,
                        "language_fallback_triggered": False,
                        "language": "es",
                    }
                },
            }
        ]
        mock_graph = _make_mock_graph_astream_events(raw_events)

        token = _make_token()
        all_lines: list[str] = []
        with (
            patch("server.app.api.v1.hub_chat.GraphFactory",
                  return_value=MagicMock(build=AsyncMock(return_value=mock_graph))),
            patch("server.app.api.v1.hub_chat.resolve_embedding_service", new_callable=AsyncMock),
            patch("server.app.api.v1.hub_chat.get_model", new_callable=AsyncMock),
        ):
            with TestClient(app) as client:
                with client.stream(
                    "POST",
                    f"/api/v1/hub/chat/{chatbot.id}",
                    json={"message": "Test"},
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    all_lines = list(response.iter_lines())

        events = _parse_sse_lines(all_lines)
        done_events = [(e, p) for e, p in events if e == "done"]
        assert len(done_events) == 1

        _, done_payload = done_events[0]
        assert "interaction_id" in done_payload
        assert len(done_payload["sources"]) == 1
        src = done_payload["sources"][0]
        assert src["document_id"] == str(doc_id)
        assert src["title"] == "Norma A"
        assert src["url"] == "https://ej.com/a.pdf"
        assert src["score"] == round(0.9, 3)
        assert done_payload["language_fallback"] is False
        assert done_payload["translation_warning"] is None
        uuid.UUID(done_payload["interaction_id"])

    @patch.dict("os.environ", _JWT_ENV)
    def test_chat_endpoint_includes_translation_warning_when_language_fallback(self) -> None:
        """Si language_fallback_triggered=True, done incluye translation_warning no nulo."""
        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        app = _build_test_app(chatbot)

        # Reapuntado en RAG.2: el idioma detectado sale del nodo detect_language y el aviso
        # de traducción del nodo merge (que es donde la LanguagePolicy lo decide), en vez de
        # venir ambos en la salida del nodo de generación.
        raw_events = [
            {
                "event": "on_chain_end",
                "name": "detect_language",
                "data": {"output": {"language": "ca"}},
            },
            {
                "event": "on_chain_end",
                "name": "merge",
                # VIS.5 — el nodo emite también **en qué lengua está la evidencia**, que es con
                # la que se redacta el aviso. Antes el texto se construía con la lengua de la
                # pregunta, que es la que quien pregunta ya conoce; sin este dato no hay aviso,
                # porque no se puede afirmar que las dos lenguas difieran.
                "data": {
                    "output": {
                        "translation_warning": True,
                        "context_source_language": "es",
                    }
                },
            },
            {
                "event": "on_chain_end",
                "name": "generate_answer",
                "data": {"output": {"sources": [], "fallback_used": False}},
            },
        ]
        mock_graph = _make_mock_graph_astream_events(raw_events)

        token = _make_token()
        all_lines: list[str] = []
        with (
            patch("server.app.api.v1.hub_chat.GraphFactory",
                  return_value=MagicMock(build=AsyncMock(return_value=mock_graph))),
            patch("server.app.api.v1.hub_chat.resolve_embedding_service", new_callable=AsyncMock),
            patch("server.app.api.v1.hub_chat.get_model", new_callable=AsyncMock),
        ):
            with TestClient(app) as client:
                with client.stream(
                    "POST",
                    f"/api/v1/hub/chat/{chatbot.id}",
                    json={"message": "Ajuda'm si us plau"},
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    all_lines = list(response.iter_lines())

        events = _parse_sse_lines(all_lines)
        done_events = [(e, p) for e, p in events if e == "done"]
        assert len(done_events) == 1

        _, done_payload = done_events[0]
        assert done_payload["language_fallback"] is True
        assert done_payload["translation_warning"] is not None
        assert "⚠️" in done_payload["translation_warning"]

    @patch.dict("os.environ", _JWT_ENV)
    def test_chat_endpoint_emits_error_event_on_graph_failure(self) -> None:
        """Si el grafo lanza una excepción, el stream emite evento 'error' y termina."""
        chatbot = MagicMock(spec=HubChatbot)
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        app = _build_test_app(chatbot)

        async def _failing_astream_events(state, config=None, version="v2"):
            raise RuntimeError("LangGraph internal error")
            yield  # make it a generator

        mock_compiled = MagicMock()
        mock_compiled.astream_events = _failing_astream_events
        mock_graph = MagicMock()
        mock_graph.compile = MagicMock(return_value=mock_compiled)

        token = _make_token()
        all_lines: list[str] = []
        with (
            patch("server.app.api.v1.hub_chat.GraphFactory",
                  return_value=MagicMock(build=AsyncMock(return_value=mock_graph))),
            patch("server.app.api.v1.hub_chat.resolve_embedding_service", new_callable=AsyncMock),
            patch("server.app.api.v1.hub_chat.get_model", new_callable=AsyncMock),
        ):
            with TestClient(app, raise_server_exceptions=False) as client:
                with client.stream(
                    "POST",
                    f"/api/v1/hub/chat/{chatbot.id}",
                    json={"message": "Test error"},
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    all_lines = list(response.iter_lines())

        events = _parse_sse_lines(all_lines)
        error_events = [(e, p) for e, p in events if e == "error"]
        assert len(error_events) == 1
        _, error_payload = error_events[0]
        assert "message" in error_payload
        # Issue #147: el cliente recibe un mensaje estable, **no** el texto de la excepción.
        # Este test comprobaba lo contrario —que `LangGraph internal error` llegara al
        # cliente— y esa afirmación era el defecto escrito como especificación: el widget del
        # chatbot es público, así que cualquiera podía provocar un error y leer el detalle
        # interno. Lo que se conserva del test es lo que sí importaba: que haya un evento
        # `error` y que no haya `done` detrás.
        from server.app.api.v1.hub_chat import MENSAJE_DE_ERROR

        assert error_payload["message"] == MENSAJE_DE_ERROR
        assert "LangGraph internal error" not in error_payload["message"]
        # No debe haber evento done tras el error
        done_events = [(e, p) for e, p in events if e == "done"]
        assert len(done_events) == 0
