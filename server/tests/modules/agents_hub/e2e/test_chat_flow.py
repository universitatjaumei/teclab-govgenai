"""Tests E2E del flujo completo de chat (Prompt 6.1, actualizado Prompt 9.8.2).

Requieren PostgreSQL con pgvector corriendo.
El LLM se mockea para evitar llamadas reales a la API.
Usan httpx.AsyncClient + ASGITransport para ejecutar todo en el mismo
event loop que los fixtures async de BD (evita conflictos de loop).

Protocolo SSE (Prompt 9.8.2):
  event: status   data: {"node": "...", "msg": "..."}
  event: token    data: {"delta": "..."}
  event: done     data: {"interaction_id": "...", "sources": [...],
                          "language_fallback": bool, "translation_warning": str | null}
  event: error    data: {"message": "..."}

Rutas reales (monorepo):
  tests/e2e/test_chat_flow.py → server/tests/modules/agents_hub/e2e/test_chat_flow.py
"""
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
    PublicGraphConfig,
)

# SEC.2: el chat y la ingesta exigen que el principal gestione la organizacion del
# chatbot. Estos tests prueban otra cosa, asi que doble y token comparten organizacion;
# la tenencia tiene su propio gate en `tests/api/test_tenant_isolation.py`.
ORG_PRUEBA = "00000000-0000-0000-0000-00000000dead"


class _ServicioDelCorpus:
    """El mismo modelo con el que la fixture embebió los chunks (RAG.9).

    Sin esto, el doble era un `AsyncMock` pelado cuyo `model_name` es otro mock, así que la
    guarda de espacio vectorial veía un desajuste real y devolvía 409. Que estos E2E tengan
    que declararlo es la señal de que la guarda está de verdad en el camino de la consulta.
    """

    model_name = "BAAI/bge-m3"
    dimensions = 1024

    async def embed(self, text: str) -> list[float]:
        return [0.1] * 1024


_SERVICIO_DEL_CORPUS = _ServicioDelCorpus()


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


# HIB.I hizo que el endpoint leyera `core_graph.cfg` para escribir la traza en
# `interaction_metadata`, que es una columna JSON. Con un `MagicMock` pelado, `cfg.retrieval_mode`
# es otro mock y el INSERT de la interaccion muere serializandolo: o sea, el doble del grafo tiene
# que declarar la configuracion igual que declara `compile()`. Va la configuracion REAL y no un
# mock con `spec` porque lo que la traza necesita son valores serializables, no una firma.
_CFG_DEL_DOBLE = PublicGraphConfig(
    profile="PUBLIC_KB_RICH",
    retrieval_mode="RAG",
    language_mode="prefer",
    quality_threshold=0.65,
    min_retrieval_results=2,
    min_retrieval_score=0.0,
    reranker_enabled=False,
    answer_template="generic",
)


def _make_mock_graph_astream_events(events_to_yield: list[dict]):
    """Crea un grafo mock cuyo compiled.astream_events devuelve los eventos dados."""
    async def _mock_astream_events(state, config=None, version="v2"):
        for ev in events_to_yield:
            yield ev

    mock_compiled = MagicMock()
    mock_compiled.astream_events = _mock_astream_events
    mock_graph = MagicMock()
    mock_graph.compile = MagicMock(return_value=mock_compiled)
    mock_graph.cfg = _CFG_DEL_DOBLE
    return mock_graph


class TestChatFlowE2E:

    @pytest.mark.asyncio
    async def test_full_chat_flow(self, test_app, setup_chatbot, auth_headers) -> None:
        """Flujo completo: petición → agente LangGraph → respuesta SSE con evento done."""
        chatbot = setup_chatbot

        chunk = MagicMock()
        chunk.content = "Python es muy versátil."

        raw_events = [
            {
                "event": "on_chat_model_stream",
                "name": "ChatGoogleGenerativeAI",
                "data": {"chunk": chunk},
            },
            {
                "event": "on_chain_end",
                "name": "generate_answer",
                "data": {
                    "output": {
                        "sources": [],
                        "language_fallback_triggered": False,
                        "language": "es",
                    }
                },
            },
        ]
        mock_graph = _make_mock_graph_astream_events(raw_events)

        with (
            patch("server.app.modules.agents_hub.services.turno_de_chat.GraphFactory",
                  return_value=MagicMock(build=AsyncMock(return_value=mock_graph))),
            patch("server.app.modules.agents_hub.services.turno_de_chat.resolve_embedding_service",
                  new=AsyncMock(return_value=_SERVICIO_DEL_CORPUS)),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                async with client.stream(
                    "POST",
                    f"/api/v1/hub/chat/{chatbot.id}",
                    json={"message": "¿Qué es Python?"},
                    headers=auth_headers,
                ) as response:
                    assert response.status_code == 200
                    assert "text/event-stream" in response.headers.get("content-type", "")
                    lines = [elemento async for elemento in response.aiter_lines()]

        events = _parse_sse_lines(lines)
        token_events = [(e, p) for e, p in events if e == "token"]
        done_events = [(e, p) for e, p in events if e == "done"]

        assert len(token_events) >= 1
        assert token_events[0][1]["delta"] == "Python es muy versátil."
        assert len(done_events) == 1
        assert done_events[0][1]["language_fallback"] is False

    @pytest.mark.asyncio
    async def test_chat_stores_interaction(
        self, test_app, setup_chatbot, auth_headers, db_session
    ) -> None:
        """Tras el chat, la interacción queda guardada en hub_interactions."""
        from server.app.modules.agents_hub.database.operational_models import HubInteraction

        chatbot = setup_chatbot

        chunk = MagicMock()
        chunk.content = "Respuesta guardada"

        raw_events = [
            {
                "event": "on_chat_model_stream",
                "name": "ChatGoogleGenerativeAI",
                "data": {"chunk": chunk},
            },
            {
                "event": "on_chain_end",
                "name": "generate_answer",
                "data": {
                    "output": {
                        "sources": [],
                        "language_fallback_triggered": False,
                        "language": "es",
                    }
                },
            },
        ]
        mock_graph = _make_mock_graph_astream_events(raw_events)

        with (
            patch("server.app.modules.agents_hub.services.turno_de_chat.GraphFactory",
                  return_value=MagicMock(build=AsyncMock(return_value=mock_graph))),
            patch("server.app.modules.agents_hub.services.turno_de_chat.resolve_embedding_service",
                  new=AsyncMock(return_value=_SERVICIO_DEL_CORPUS)),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                async with client.stream(
                    "POST",
                    f"/api/v1/hub/chat/{chatbot.id}",
                    json={"message": "Pregunta de prueba"},
                    headers=auth_headers,
                ) as response:
                    lines = [elemento async for elemento in response.aiter_lines()]

        events = _parse_sse_lines(lines)
        done_events = [(e, p) for e, p in events if e == "done"]
        assert len(done_events) == 1
        interaction_id = uuid.UUID(done_events[0][1]["interaction_id"])

        # Verificar persistencia en BD
        result = await db_session.execute(
            select(HubInteraction).where(HubInteraction.run_id == interaction_id)
        )
        interaction = result.scalar_one_or_none()
        assert interaction is not None
        assert interaction.user_message == "Pregunta de prueba"
        assert interaction.assistant_message == "Respuesta guardada"
        assert interaction.chatbot_id == chatbot.id


class TestExportFlowE2E:

    @pytest.mark.asyncio
    async def test_export_after_chat(
        self, test_app, setup_chatbot, auth_headers
    ) -> None:
        """El usuario puede exportar la interacción como Markdown tras el chat."""
        chatbot = setup_chatbot

        chunk = MagicMock()
        chunk.content = "## Respuesta\n\nContenido exportable."

        raw_events = [
            {
                "event": "on_chat_model_stream",
                "name": "ChatGoogleGenerativeAI",
                "data": {"chunk": chunk},
            },
            {
                "event": "on_chain_end",
                "name": "generate_answer",
                "data": {
                    "output": {
                        "sources": [],
                        "language_fallback_triggered": False,
                        "language": "es",
                    }
                },
            },
        ]
        mock_graph = _make_mock_graph_astream_events(raw_events)

        with (
            patch("server.app.modules.agents_hub.services.turno_de_chat.GraphFactory",
                  return_value=MagicMock(build=AsyncMock(return_value=mock_graph))),
            patch("server.app.modules.agents_hub.services.turno_de_chat.resolve_embedding_service",
                  new=AsyncMock(return_value=_SERVICIO_DEL_CORPUS)),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                async with client.stream(
                    "POST",
                    f"/api/v1/hub/chat/{chatbot.id}",
                    json={"message": "Genera un informe"},
                    headers=auth_headers,
                ) as response:
                    lines = [elemento async for elemento in response.aiter_lines()]

                events = _parse_sse_lines(lines)
                done_events = [(e, p) for e, p in events if e == "done"]
                interaction_id = done_events[0][1]["interaction_id"]

                export_response = await client.get(
                    f"/api/v1/hub/tasks/export/{interaction_id}",
                    headers=auth_headers,
                )
                assert export_response.status_code == 200
                assert "Genera un informe" in export_response.text
                assert "Respuesta" in export_response.text

    @pytest.mark.asyncio
    async def test_export_forbidden_for_other_user(
        self, test_app, setup_chatbot, auth_headers
    ) -> None:
        """Otro usuario no puede exportar una interacción que no le pertenece."""
        from server.app.core.auth import UserInfo, create_token

        chatbot = setup_chatbot

        chunk = MagicMock()
        chunk.content = "Datos privados"

        raw_events = [
            {
                "event": "on_chat_model_stream",
                "name": "ChatGoogleGenerativeAI",
                "data": {"chunk": chunk},
            },
            {
                "event": "on_chain_end",
                "name": "generate_answer",
                "data": {
                    "output": {
                        "sources": [],
                        "language_fallback_triggered": False,
                        "language": "es",
                    }
                },
            },
        ]
        mock_graph = _make_mock_graph_astream_events(raw_events)

        other_token = create_token(
            UserInfo(user_id="intruder-99", email="intruder@test.com", role="user", organizacion_ids=(ORG_PRUEBA,))
        )
        other_headers = {"Authorization": f"Bearer {other_token}"}

        with (
            patch("server.app.modules.agents_hub.services.turno_de_chat.GraphFactory",
                  return_value=MagicMock(build=AsyncMock(return_value=mock_graph))),
            patch("server.app.modules.agents_hub.services.turno_de_chat.resolve_embedding_service",
                  new=AsyncMock(return_value=_SERVICIO_DEL_CORPUS)),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=test_app), base_url="http://test"
            ) as client:
                async with client.stream(
                    "POST",
                    f"/api/v1/hub/chat/{chatbot.id}",
                    json={"message": "Mensaje privado"},
                    headers=auth_headers,
                ) as response:
                    lines = [elemento async for elemento in response.aiter_lines()]

                events = _parse_sse_lines(lines)
                done_events = [(e, p) for e, p in events if e == "done"]
                interaction_id = done_events[0][1]["interaction_id"]

                forbidden = await client.get(
                    f"/api/v1/hub/tasks/export/{interaction_id}",
                    headers=other_headers,
                )
                assert forbidden.status_code == 403
