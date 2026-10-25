"""RAG.2 — /hub/chat servido por public_graphs/CoreGraph (RED primero).

Lo que se verifica aquí, a nivel de endpoint:

- los tres retrieval_mode se sirven por el CoreGraph;
- el contrato SSE observable no cambia (snapshot de eventos y de claves del done);
- `fallback_reason` se persiste en HubInteraction;
- la cascada de config es visible en runtime (un override de organización llega al grafo);
- el router multi-materia sigue ejecutándose ANTES del grafo;
- no queda ninguna referencia al grafo retirado.
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.modules.agents_hub.database.config_models import HubChatbot
from server.tests.dobles import completar_chatbot

# SEC.2: el chat exige que el principal gestione la organización del chatbot. Estos
# tests prueban el grafo, no la tenencia —que tiene su gate en
# `tests/api/test_tenant_isolation.py`—, así que doble y token comparten organización.
ORG_PRUEBA = "00000000-0000-0000-0000-00000000dead"

_JWT_ENV = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}

SERVER = Path(__file__).resolve().parents[4]


def _token(user_id: str = "user-1") -> str:
    import os

    os.environ.update(_JWT_ENV)
    from server.app.core.auth import UserInfo, create_token

    return create_token(
        UserInfo(
            user_id=user_id, email="u@test.com", role="user",
            organizacion_ids=(ORG_PRUEBA,),
        )
    )


class _SesionCapturadora:
    """Sesión mock que recuerda los objetos añadidos (para inspeccionar HubInteraction)."""

    def __init__(self, chatbot):
        self.anadidos: list = []
        self._chatbot = chatbot

    def _mock(self):
        session = AsyncMock()
        scalar = MagicMock()
        scalar.scalar_one_or_none = MagicMock(return_value=self._chatbot)
        session.execute = AsyncMock(return_value=scalar)
        # SEC.4: la organización se lee para la cascada de cuotas; `None` = sin cuotas
        # heredadas. Con el doble por defecto, los límites serían números inventados.
        session.get = AsyncMock(return_value=None)
        session.add = MagicMock(side_effect=self.anadidos.append)
        session.commit = AsyncMock()
        return session


def _app(session) -> FastAPI:
    from server.app.api.v1.hub_chat import router as chat_router
    from server.app.api.deps import get_session

    async def _override():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_session] = _override
    app.include_router(chat_router, prefix="/api/v1")
    return app


def _grafo_mock(eventos: list[dict]) -> MagicMock:
    async def _astream(state, config=None, version="v2"):
        for ev in eventos:
            yield ev

    compilado = MagicMock()
    compilado.astream_events = _astream
    grafo = MagicMock()
    grafo.compile = MagicMock(return_value=compilado)
    return grafo


def _evidencia(url: str = "https://ej.es/a", title: str = "Norma A"):
    from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
        EvidenceItem,
    )

    return EvidenceItem(
        source_id=str(uuid.uuid4()), content="c", source_url=url, title=title, score=0.9
    )


def _eventos(sources=None, fallback_used=False, fallback_reason=None, answer=None, nodo="generate_answer"):
    return [
        {"event": "on_chain_start", "name": "detect_language", "data": {}},
        {"event": "on_chain_end", "name": "detect_language", "data": {"output": {"language": "es"}}},
        {"event": "on_chain_start", "name": "retrieve", "data": {}},
        {"event": "on_chain_end", "name": "merge", "data": {"output": {"translation_warning": False}}},
        {"event": "on_chain_start", "name": "generate_answer", "data": {}},
        {
            "event": "on_chain_end",
            "name": nodo,
            "data": {
                "output": {
                    "sources": sources or [],
                    "fallback_used": fallback_used,
                    "fallback_reason": fallback_reason,
                    "answer": answer,
                }
            },
        },
    ]


def _lanzar(chatbot, eventos, capturadora=None):
    cap = capturadora or _SesionCapturadora(chatbot)
    session = cap._mock()
    grafo = _grafo_mock(eventos)
    app = _app(session)
    with (
        patch(
            "server.app.modules.agents_hub.services.turno_de_chat.GraphFactory",
            return_value=MagicMock(build=AsyncMock(return_value=grafo)),
        ),
        patch("server.app.modules.agents_hub.services.turno_de_chat.resolve_embedding_service", new_callable=AsyncMock),
        patch("server.app.modules.agents_hub.services.turno_de_chat.get_model", new_callable=AsyncMock),
    ):
        with TestClient(app) as client:
            with client.stream(
                "POST",
                f"/api/v1/hub/chat/{chatbot.id}",
                json={"message": "¿Cuántos días de permiso?"},
                headers={"Authorization": f"Bearer {_token()}"},
            ) as r:
                lineas = list(r.iter_lines())
    return _parsear(lineas), cap


def _parsear(lineas: list[str]) -> list[tuple[str, dict]]:
    eventos: list[tuple[str, dict]] = []
    actual = "message"
    for linea in lineas:
        if linea.startswith("event:"):
            actual = linea.removeprefix("event:").strip()
        elif linea.startswith("data:"):
            eventos.append((actual, json.loads(linea.removeprefix("data:").strip())))
            actual = "message"
    return eventos


def _chatbot(mode: str = "RAG", kind: str = "atomic") -> MagicMock:
    cb = MagicMock(spec=HubChatbot)
    cb.id = uuid.uuid4()
    cb.organizacion_id = uuid.UUID(ORG_PRUEBA)
    # Los campos de configuracion del doble salen del ORM (`tests/dobles.py`):
    # un MagicMock inventa un valor por cada columna nueva, y eso ya rompio
    # estos tests tres veces —SEC.2.1, SEC.4 y SEC.4.1—.
    completar_chatbot(cb)
    cb.retrieval_mode = mode
    cb.kind = kind
    cb.name = "Bot"
    return cb


# ───────────────────────────── Los tres modos por el CoreGraph ─────────────────────────────


class TestCoreGraphServesAllModes:

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_serve_chat_via_coregraph_in_rag_mode(self):
        eventos, _ = _lanzar(_chatbot("RAG"), _eventos(sources=[_evidencia()]))

        done = [p for e, p in eventos if e == "done"]
        assert len(done) == 1
        assert done[0]["sources"][0]["title"] == "Norma A"

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_serve_chat_via_coregraph_in_long_context_mode(self):
        url = "https://www.uji.es/upo/rest/contenido/1175964720/raw?idioma=ca"
        eventos, _ = _lanzar(
            _chatbot("MD_LONG_CONTEXT"),
            _eventos(sources=[_evidencia(url=url, title="Reglament del Claustre")]),
        )

        done = [p for e, p in eventos if e == "done"][0]
        assert done["sources"][0]["url"] == url

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_serve_chat_via_coregraph_in_agent_selector_mode(self):
        """En modo selector sólo se citan los documentos leídos: las entradas de índice
        no aparecen en el done."""
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
            EvidenceItem,
        )

        leido = _evidencia(url="https://ej.es/leido", title="Leído")
        entrada_indice = EvidenceItem(
            source_id=str(uuid.uuid4()),
            content="Título (id: x)",
            source_url="https://ej.es/indexado",
            title="Indexado",
            metadata={"index_entry": True},
        )

        eventos, _ = _lanzar(
            _chatbot("MD_AGENT_SELECTOR"), _eventos(sources=[leido, entrada_indice])
        )

        done = [p for e, p in eventos if e == "done"][0]
        titulos = {s["title"] for s in done["sources"]}
        assert titulos == {"Leído"}


# ───────────────────────────── Contrato SSE sin cambios ─────────────────────────────


class TestSseContract:

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_keep_sse_event_contract_unchanged(self):
        """Snapshot: tipos de evento, claves del done y claves del status."""
        eventos, _ = _lanzar(_chatbot(), _eventos(sources=[_evidencia()]))

        tipos = [e for e, _ in eventos]
        assert tipos[-1] == "done"
        assert set(tipos) <= {"status", "token", "done", "error"}, (
            "RAG.2 no introduce tipos de evento nuevos"
        )

        done = [p for e, p in eventos if e == "done"][0]
        assert set(done.keys()) == {
            "interaction_id",
            "sources",
            "language_fallback",
            "translation_warning",
            # RES.2 — clave nueva y aditiva: dice si la respuesta salió de la segunda búsqueda,
            # con la consulta reformulada. Va en el `done` y no en un evento propio justo para
            # no introducir un tipo nuevo, que es lo que la línea de arriba prohíbe. Que el
            # widget lo muestre o no es decisión de producto; el backend expone el hecho.
            "reformulada",
        }
        assert set(done["sources"][0].keys()) == {"document_id", "title", "url", "score"}
        uuid.UUID(done["interaction_id"])

        for _, payload in [(e, p) for e, p in eventos if e == "status"]:
            assert set(payload.keys()) == {"node", "msg"}

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_keep_the_three_user_facing_status_messages(self):
        """Los nombres internos de los nodos cambiaron; los mensajes que ve el usuario no."""
        eventos, _ = _lanzar(_chatbot(), _eventos())

        mensajes = [p["msg"] for e, p in eventos if e == "status"]
        assert "Detectando idioma..." in mensajes
        assert "Buscando en la base de conocimiento..." in mensajes
        assert "Generando respuesta..." in mensajes

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_emit_the_fallback_answer_as_a_normal_token(self):
        """El fallback no pasa por el stream del LLM: el endpoint lo emite igualmente para
        que el usuario vea una respuesta en vez de un done vacío."""
        from server.app.modules.agents_hub.agent.citation_validator import (
            NO_CITATION_FALLBACK,
        )

        eventos, _ = _lanzar(
            _chatbot(),
            _eventos(
                fallback_used=True, fallback_reason="quality_gate", answer=NO_CITATION_FALLBACK,
                nodo="fallback",
            ),
        )

        tokens = "".join(p["delta"] for e, p in eventos if e == "token")
        assert tokens == NO_CITATION_FALLBACK


# ───────────────────────────── fallback_reason persistido ─────────────────────────────


class TestFallbackReasonPersistence:

    @patch.dict("os.environ", _JWT_ENV)
    @pytest.mark.parametrize("motivo", ["quality_gate", "citation"])
    def test_should_persist_fallback_reason_on_interaction(self, motivo):
        chatbot = _chatbot()
        cap = _SesionCapturadora(chatbot)
        _lanzar(
            chatbot,
            _eventos(fallback_used=True, fallback_reason=motivo, answer="texto"),
            capturadora=cap,
        )

        interacciones = [o for o in cap.anadidos if hasattr(o, "fallback_reason")]
        assert len(interacciones) == 1
        assert interacciones[0].fallback_reason == motivo

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_leave_fallback_reason_null_on_the_normal_path(self):
        chatbot = _chatbot()
        cap = _SesionCapturadora(chatbot)
        _lanzar(chatbot, _eventos(sources=[_evidencia()]), capturadora=cap)

        interacciones = [o for o in cap.anadidos if hasattr(o, "fallback_reason")]
        assert interacciones[0].fallback_reason is None


# ───────────────────────────── Cascada de config en runtime ─────────────────────────────


@pytest.mark.asyncio
class TestConfigCascadeInLiveChat:

    async def test_should_resolve_config_cascade_in_live_chat(self):
        """Un override de la organización es visible en el cfg del grafo que sirve el chat."""
        from server.app.modules.agents_hub.agent.public_graphs.core.graph_factory import (
            GraphFactory,
        )
        from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_pipeline_protocol import (
            GraphDeps,
        )

        chatbot = MagicMock(spec=HubChatbot)
        chatbot.id = uuid.uuid4()
        chatbot.organizacion_id = uuid.uuid4()
        chatbot.system_prompt = "Base del chatbot."
        for campo in (
            "public_graph_profile", "retrieval_mode", "language_mode", "quality_threshold",
            "min_retrieval_results", "min_retrieval_score", "reranker_enabled",
            "answer_template",
        ):
            setattr(chatbot, campo, None)

        organizacion = MagicMock()
        organizacion.default_public_graph_profile = None
        organizacion.default_retrieval_mode = None
        organizacion.default_language_mode = None
        organizacion.default_quality_threshold = 0.95   # override de organización
        organizacion.default_min_retrieval_results = None
        organizacion.default_min_retrieval_score = None
        organizacion.default_reranker_enabled = None
        organizacion.default_answer_template = None

        session = AsyncMock()
        session.get = AsyncMock(side_effect=[chatbot, organizacion])

        grafo = await GraphFactory().build(
            chatbot.id, GraphDeps(session=session, embedder=AsyncMock()), llm=None
        )

        assert grafo.cfg.quality_threshold == 0.95
        assert grafo.cfg.system_prompt == "Base del chatbot."


# ───────────────────────────── El router va antes del grafo ─────────────────────────────


class TestRouterBeforeGraph:

    @patch.dict("os.environ", _JWT_ENV)
    def test_should_route_router_kind_chatbot_before_graph(self):
        padre = _chatbot(kind="router")
        hijo = _chatbot()
        hijo.name = "Permisos y llicències"

        cap = _SesionCapturadora(padre)
        session = cap._mock()
        # 1ª consulta: el padre; 2ª: la guarda de espacio vectorial (RAG.9), que ve un corpus
        # vacío y no bloquea; 3ª: el hijo seleccionado.
        primera, espacio, segunda = MagicMock(), MagicMock(), MagicMock()
        primera.scalar_one_or_none = MagicMock(return_value=padre)
        espacio.all = MagicMock(return_value=[])
        segunda.scalar_one_or_none = MagicMock(return_value=hijo)

        # Las tres primeras consultas son las que este test mide; a partir de ahí van las
        # de la contabilidad de consumo (SEC.4), que no le importan. Con una lista pelada,
        # la cuarta reventaba el generador del stream con `StopAsyncIteration`.
        pendientes = [primera, espacio, segunda]

        async def _execute(*_args, **_kwargs):
            return pendientes.pop(0) if pendientes else MagicMock()

        session.execute = AsyncMock(side_effect=_execute)

        grafo = _grafo_mock(_eventos())
        app = _app(session)
        router_node = AsyncMock(return_value={"selected_child_id": str(hijo.id)})

        with (
            patch(
                "server.app.modules.agents_hub.services.turno_de_chat.GraphFactory",
                return_value=MagicMock(build=AsyncMock(return_value=grafo)),
            ),
            patch("server.app.modules.agents_hub.services.turno_de_chat.resolve_embedding_service", new_callable=AsyncMock),
            patch("server.app.modules.agents_hub.services.turno_de_chat.get_model", new_callable=AsyncMock),
            patch(
                "server.app.modules.agents_hub.services.turno_de_chat.build_route_to_subagent_node",
                return_value=router_node,
            ),
        ):
            with TestClient(app) as client:
                with client.stream(
                    "POST",
                    f"/api/v1/hub/chat/{padre.id}",
                    json={"message": "¿Cuántos días de permiso?"},
                    headers={"Authorization": f"Bearer {_token()}"},
                ) as r:
                    eventos = _parsear(list(r.iter_lines()))

        router_node.assert_awaited_once()
        mensajes = [p["msg"] for e, p in eventos if e == "status"]
        assert "Materia detectada: Permisos y llicències" in mensajes
        assert mensajes[0].startswith("Materia detectada"), (
            "el router se resuelve ANTES de que el grafo emita su primer status"
        )


# ───────────────────────────── Retirada del grafo antiguo ─────────────────────────────


class TestRetiredGraphIsGone:

    def test_should_have_no_references_to_retired_graph(self):
        """agent/graph.py, agent/state.py y agent/prompts.py se retiraron (Caso B)."""
        for retirado in (
            "app/modules/agents_hub/agent/graph.py",
            "app/modules/agents_hub/agent/state.py",
            "app/modules/agents_hub/agent/prompts.py",
        ):
            assert not (SERVER / retirado).exists(), f"{retirado} sigue existiendo"

        prohibidos = ("create_agent_graph", "agent.state", "agent.prompts", "AgentState")
        infractores: list[str] = []
        for path in list((SERVER / "app").rglob("*.py")) + list((SERVER / "tests").rglob("*.py")):
            if path.name == Path(__file__).name:
                continue
            texto = path.read_text(encoding="utf-8", errors="replace")
            for simbolo in prohibidos:
                if simbolo in texto:
                    infractores.append(f"{path.relative_to(SERVER)}: {simbolo}")
        assert infractores == [], f"referencias al grafo retirado: {infractores}"
