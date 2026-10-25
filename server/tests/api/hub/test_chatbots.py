"""Tests para el endpoint /api/v1/hub/chatbots."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from server.app.core.auth.models import UserInfo
from server.app.main import app
from server.app.api.deps import get_session
from server.app.api.deps import get_current_user

DEV_LLM_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
DEV_CLIENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")
DEV_CHATBOT_ID = uuid.UUID("00000000-0000-0000-0000-000000000100")

# SEC.2: un admin ahora lleva sus organizaciones en el token. Sin el claim no ve
# nada, que es justo lo que la frontera de tenencia garantiza.
_ADMIN = UserInfo(
    user_id="admin-1",
    email="admin@test.com",
    role="admin",
    organizacion_ids=(str(DEV_CLIENT_ID),),
)


def _make_chatbot(
    name: str = "Demo",
    is_active: bool = True,
    kind: str = "atomic",
    parent_chatbot_id: uuid.UUID | None = None,
    chatbot_id: uuid.UUID = DEV_CHATBOT_ID,
    organizacion_id: uuid.UUID = DEV_CLIENT_ID,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=chatbot_id,
        name=name,
        organizacion_id=organizacion_id,
        llm_config_id=DEV_LLM_ID,
        system_prompt="Eres un asistente.",
        sources=[],
        theme_config={},
        is_active=is_active,
        retrieval_mode="MD_AGENT_SELECTOR",
        retrieval_top_k=8,
        use_prompt_caching=False,
        cache_ttl=3600,
        kind=kind,
        parent_chatbot_id=parent_chatbot_id,
        # SEC.2.1: el chatbot declara para quién es. Los dobles llevan el default del
        # modelo; quien prueba el modo de acceso es `tests/api/test_chatbot_access_mode.py`.
        access_mode="authenticated",
        allowed_roles=[],
        allowed_saml_groups=[],
        # SEC.4.1: sin ventana ni techo. `availability` no se declara: es derivado y lo
        # calcula el servidor al leer, que es justo lo que prueba
        # `tests/api/test_chatbot_availability.py`.
        valid_from=None,
        valid_until=None,
        total_token_budget=None,
        unavailable_message="",
        public_graph_profile="PUBLIC_KB_RICH",
        language_mode="prefer",
        quality_threshold=0.6,
        min_retrieval_results=2,
        min_retrieval_score=0.25,
        reranker_enabled=True,
        answer_template="generic",
        context_token_budget=None,  # VIS.2: None = heredar de la cascada
        chunk_size=None,  # RAG.8: idem para los parametros de troceado
        chunk_overlap=None,
        chunking_strategy=None,
        query_rewriting_enabled=None,  # RAG.10
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def _session_with(rows: list):
    session = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=result)
    session.get = AsyncMock(return_value=rows[0] if rows else None)
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.delete = AsyncMock()
    return session


def _override_session(session):
    async def _dep():
        yield session
    return _dep


@pytest.fixture(autouse=True)
def override_auth():
    app.dependency_overrides[get_current_user] = lambda: _ADMIN
    yield
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


class TestListChatbots:
    def test_returns_list_of_chatbots(self, client):
        chatbot = _make_chatbot()
        app.dependency_overrides[get_session] = _override_session(_session_with([chatbot]))
        try:
            resp = client.get("/api/v1/hub/chatbots")
            assert resp.status_code == 200
            data = resp.json()
            assert isinstance(data, list)
            assert data[0]["name"] == "Demo"
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_returns_empty_list(self, client):
        app.dependency_overrides[get_session] = _override_session(_session_with([]))
        try:
            resp = client.get("/api/v1/hub/chatbots")
            assert resp.status_code == 200
            assert resp.json() == []
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_requires_auth(self, client):
        app.dependency_overrides.pop(get_current_user, None)
        try:
            resp = client.get("/api/v1/hub/chatbots")
            assert resp.status_code == 401
        finally:
            app.dependency_overrides[get_current_user] = lambda: _ADMIN


class TestCreateChatbot:
    def test_creates_chatbot_returns_201(self, client):
        created = _make_chatbot("Nuevo Bot")
        session = _session_with([])

        async def _refresh(obj):
            obj.id = DEV_CHATBOT_ID
            obj.created_at = created.created_at
            obj.updated_at = created.updated_at

        session.refresh = _refresh
        # Crear comprueba que la configuración de LLM es de plataforma o de la organización.
        from types import SimpleNamespace

        session.get = AsyncMock(return_value=SimpleNamespace(id=DEV_LLM_ID, organizacion_id=None))
        app.dependency_overrides[get_session] = _override_session(session)
        # RAG.9: crear un chatbot RAG comprueba antes que el servicio de embeddings responde
        # —fallar aquí es barato, fallar a mitad de una ingesta no—, así que un test que crea
        # uno tiene que controlar esa dependencia. Sin el parche, el resolutor lee la sesión
        # simulada y la interpreta como configuración ilegible, que es lo correcto.
        with patch(
            "server.app.routers.hub_chatbots_router.resolve_embedding_service",
            new=AsyncMock(return_value=object()),
        ):
            try:
                resp = client.post(
                    "/api/v1/hub/chatbots",
                    json={
                        "name": "Nuevo Bot",
                        "organizacion_id": str(DEV_CLIENT_ID),
                        "llm_config_id": str(DEV_LLM_ID),
                        "system_prompt": "Eres útil.",
                    },
                )
                assert resp.json()["name"] == "Nuevo Bot"
            finally:
                app.dependency_overrides.pop(get_session, None)


class TestUpdateChatbot:
    def test_updates_name_returns_200(self, client):
        chatbot = _make_chatbot("Original")

        async def _refresh(obj):
            pass

        session = _session_with([chatbot])
        session.refresh = _refresh
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.patch(
                f"/api/v1/hub/chatbots/{DEV_CHATBOT_ID}",
                json={"name": "Actualizado"},
            )
            assert resp.status_code == 200
            assert resp.json()["name"] == "Actualizado"
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_returns_404_for_unknown_id(self, client):
        session = _session_with([])
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.patch(
                f"/api/v1/hub/chatbots/{uuid.uuid4()}",
                json={"name": "x"},
            )
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_session, None)


class TestDeleteChatbot:
    def test_deletes_chatbot_returns_204(self, client):
        chatbot = _make_chatbot()
        session = _session_with([chatbot])
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.delete(f"/api/v1/hub/chatbots/{DEV_CHATBOT_ID}")
            assert resp.status_code == 204
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_returns_404_for_unknown_id(self, client):
        session = _session_with([])
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.delete(f"/api/v1/hub/chatbots/{uuid.uuid4()}")
            assert resp.status_code == 404
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_should_purge_the_corpus_before_deleting_the_chatbot(self, client, monkeypatch):
        """PIL.2: el endpoint no puede borrar la fila y dejar el corpus huerfano.

        Lo que hace la purga se prueba contra BD real en
        `test_chatbot_deletion_purges_corpus.py`; aqui se fija que el endpoint la llama, y
        que la llama ANTES de borrar el chatbot: al reves, un fallo a mitad dejaria un
        corpus sin dueno y sin forma de encontrarlo.
        """
        import server.app.routers.hub_chatbots_router as router_mod

        # El tipo se importa de su propio modulo, no del router: el router no lo usa -solo
        # llama a la purga y descarta lo que devuelve-, asi que alcanzarlo por su namespace
        # obligaba a mantener alli un import muerto que el linter tumba.
        from server.app.modules.agents_hub.services.corpus_purge import CorpusRetirado

        orden: list[str] = []
        chatbot = _make_chatbot()
        session = _session_with([chatbot])

        async def _purga_espia(_session, chatbot_id):
            orden.append(f"purga:{chatbot_id}")
            return CorpusRetirado(documentos=3, fragmentos=12)

        ejecutar_original = session.execute

        async def _execute_espia(stmt, *a, **kw):
            if "hub_chatbots" in str(stmt).lower() and str(stmt).lower().startswith("delete"):
                orden.append("borra_chatbot")
            return await ejecutar_original(stmt, *a, **kw)

        monkeypatch.setattr(router_mod, "purgar_corpus_del_chatbot", _purga_espia)
        session.execute = _execute_espia
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.delete(f"/api/v1/hub/chatbots/{DEV_CHATBOT_ID}")

            assert resp.status_code == 204
            assert orden, f"la purga no se llamo primero: {orden}"
            assert orden[0] == f"purga:{DEV_CHATBOT_ID}", f"la purga no se llamo primero: {orden}"
        finally:
            app.dependency_overrides.pop(get_session, None)


class TestChatbotRetrievalMode:
    def _mount_session_for_stats(self, chatbot, *, total_docs=2, total_tokens=120000, by_language=None):
        if by_language is None:
            by_language = [("es", 100000), ("ca", 20000)]

        session = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.add = MagicMock()
        session.delete = AsyncMock()
        session.get = AsyncMock(return_value=chatbot)

        async def _execute(stmt):
            text = str(stmt)
            result = MagicMock()

            if "count(hub_documents.id)" in text:
                result.scalar_one.return_value = total_docs
                return result

            if "sum(hub_documents.token_count)" in text and "GROUP BY" not in text:
                result.scalar_one.return_value = total_tokens
                return result

            if "GROUP BY hub_documents.language" in text:
                result.all.return_value = by_language
                return result

            if "FROM hub_documents" in text:
                result.scalars.return_value.all.return_value = by_language
                return result

            result.scalar_one.return_value = 0
            result.scalars.return_value.all.return_value = []
            result.all.return_value = []
            return result

        session.execute = AsyncMock(side_effect=_execute)
        return session

    def test_corpus_stats_returns_total_tokens_and_recommendation(self, client):
        chatbot = _make_chatbot()
        session = self._mount_session_for_stats(chatbot, total_docs=2, total_tokens=120000)
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.get(f"/api/v1/hub/chatbots/{chatbot.id}/corpus-stats")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_documents"] == 2
            assert data["total_tokens"] == 120000
            assert data["recommended_mode"] == "MD_AGENT_SELECTOR"
            assert "Recomendado MD_AGENT_SELECTOR" in data["recommendation_reason"]
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_corpus_stats_groups_by_language(self, client):
        chatbot = _make_chatbot()
        session = self._mount_session_for_stats(
            chatbot,
            total_docs=3,
            total_tokens=150000,
            by_language=[("es", 120000), ("ca", 30000)],
        )
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.get(f"/api/v1/hub/chatbots/{chatbot.id}/corpus-stats")
            assert resp.status_code == 200
            data = resp.json()
            assert data["by_language"]["es"] == 120000
            assert data["by_language"]["ca"] == 30000
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_blocks_long_context_when_corpus_exceeds_limit(self, client):
        chatbot = _make_chatbot()
        session = self._mount_session_for_stats(chatbot, total_tokens=200001)
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.patch(
                f"/api/v1/hub/chatbots/{chatbot.id}",
                json={"retrieval_mode": "MD_LONG_CONTEXT"},
            )
            assert resp.status_code == 400
            assert "128K tokens" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_regenerate_chunks_blocked_for_non_vector_mode(self, client):
        chatbot = _make_chatbot()
        chatbot.retrieval_mode = "MD_AGENT_SELECTOR"
        session = self._mount_session_for_stats(chatbot)
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.post(f"/api/v1/hub/chatbots/{chatbot.id}/regenerate-chunks")
            assert resp.status_code == 400
            assert "retrieval_mode == 'RAG'" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_regenerate_chunks_creates_chunks_for_existing_documents(self, client):
        chatbot = _make_chatbot()
        chatbot.retrieval_mode = "RAG"
        doc1 = SimpleNamespace(id=uuid.uuid4())
        doc2 = SimpleNamespace(id=uuid.uuid4())

        session = self._mount_session_for_stats(chatbot, by_language=[doc1, doc2])
        app.dependency_overrides[get_session] = _override_session(session)

        with patch("server.app.routers.hub_chatbots_router.resolve_embedding_service", new_callable=AsyncMock, return_value=object()):
            with patch("server.app.routers.hub_chatbots_router.IngestionWatcher") as watcher_cls:
                watcher = watcher_cls.return_value
                watcher._regenerate_chunks_for_document = AsyncMock(side_effect=[3, 5])

                try:
                    resp = client.post(f"/api/v1/hub/chatbots/{chatbot.id}/regenerate-chunks")
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["documents_processed"] == 2
                    assert data["chunks_created"] == 8
                    assert isinstance(data["task_id"], str)
                    assert len(data["task_id"]) > 0
                finally:
                    app.dependency_overrides.pop(get_session, None)

    def test_recalculate_corpus_returns_202_with_task_id(self, client):
        chatbot = _make_chatbot()
        chatbot.retrieval_mode = "RAG"
        session = self._mount_session_for_stats(chatbot)
        app.dependency_overrides[get_session] = _override_session(session)

        # MOD.2: el endpoint resuelve el servicio de embeddings por configuración, así que
        # un test que lo ejerce tiene que controlar esa dependencia. Sin el parche, el
        # resolutor consulta la sesión simulada, interpreta el mock como una configuración
        # de proveedor y falla — que es el comportamiento correcto ante una config ilegible.
        with patch(
            "server.app.routers.hub_chatbots_router.resolve_embedding_service",
            new=AsyncMock(return_value=object()),
        ), patch(
            "server.app.routers.hub_chatbots_router.recalculate_corpus",
            new=AsyncMock(return_value=(4, 20, 0)),
        ):
            try:
                resp = client.post(f"/api/v1/hub/chatbots/{chatbot.id}/recalculate-corpus")
                assert resp.status_code == 202
                data = resp.json()
                assert isinstance(data["task_id"], str)
                assert len(data["task_id"]) > 0
                assert data["documents_queued"] == 4
                assert data["chunks_created"] == 20
                assert data["chunks_deleted"] == 0
            finally:
                app.dependency_overrides.pop(get_session, None)

    def test_recalculate_corpus_rejects_embedding_space_mismatch(self, client):
        """El endpoint traduce el desajuste de espacio vectorial a un 409 con su motivo.

        **Este test probaba antes una ficción** (MOD.1): montaba
        `SimpleNamespace(embedding_dimensions=1536)`, un campo que no existe en `HubLLMConfig`,
        así que verificaba que la guarda salta con un atributo inventado. Contra el modelo
        real ese `getattr` caía siempre al default y la guarda no podía dispararse — el test
        en verde es justo la razón de que nadie lo notara.

        La detección de verdad se prueba contra BD real en `test_embedding_provenance.py`;
        aquí solo la traducción a HTTP, que es lo que le toca al endpoint.
        """
        from server.app.modules.agents_hub.services.embedding_space import (
            EmbeddingSpaceMismatch,
        )

        chatbot = _make_chatbot()
        chatbot.retrieval_mode = "RAG"
        session = self._mount_session_for_stats(chatbot)
        app.dependency_overrides[get_session] = _override_session(session)

        with patch(
            "server.app.routers.hub_chatbots_router.resolve_embedding_service",
            new=AsyncMock(return_value=object()),
        ), patch(
            "server.app.routers.hub_chatbots_router.assert_embedding_space_matches",
            side_effect=EmbeddingSpaceMismatch(
                "El corpus contiene vectores de BAAI/bge-m3 (1024), y el modelo activo es "
                "gemini-embedding-001 (1024)."
            ),
        ):
            try:
                resp = client.post(f"/api/v1/hub/chatbots/{chatbot.id}/recalculate-corpus")
                assert resp.status_code == 409
                assert "bge-m3" in resp.json()["detail"]
                assert "gemini-embedding-001" in resp.json()["detail"]
            finally:
                app.dependency_overrides.pop(get_session, None)


class TestChatbotHierarchy:
    def _mount_session(self, router_cb, child_cb, *, children_list=None):
        session = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        session.add = MagicMock()

        by_id = {
            router_cb.id: router_cb,
            child_cb.id: child_cb if child_cb is not None else None,
        }

        async def _get(model, chatbot_id):
            return by_id.get(chatbot_id)

        async def _execute(stmt):
            text = str(stmt)
            result = MagicMock()
            if "parent_chatbot_id" in text:
                result.scalars.return_value.all.return_value = children_list or []
            else:
                result.scalars.return_value.all.return_value = []
            return result

        session.get = AsyncMock(side_effect=_get)
        session.execute = AsyncMock(side_effect=_execute)
        return session

    def test_assign_child_to_router_succeeds(self, client):
        router_id = uuid.uuid4()
        child_id = uuid.uuid4()
        router_cb = _make_chatbot(name="UJI", kind="router", chatbot_id=router_id)
        child_cb = _make_chatbot(name="RRHH", kind="atomic", chatbot_id=child_id)

        session = self._mount_session(router_cb, child_cb)
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.post(
                f"/api/v1/hub/chatbots/{router_id}/children",
                json={"child_chatbot_id": str(child_id)},
            )
            assert resp.status_code == 200
            assert resp.json()["id"] == str(child_id)
            assert child_cb.parent_chatbot_id == router_id
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_cannot_assign_child_with_kind_router(self, client):
        router_id = uuid.uuid4()
        child_id = uuid.uuid4()
        router_cb = _make_chatbot(name="Router A", kind="router", chatbot_id=router_id)
        child_router = _make_chatbot(name="Router B", kind="router", chatbot_id=child_id)

        session = self._mount_session(router_cb, child_router)
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.post(
                f"/api/v1/hub/chatbots/{router_id}/children",
                json={"child_chatbot_id": str(child_id)},
            )
            assert resp.status_code == 400
            assert "tipo router" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_cannot_create_grandchild_hierarchy(self, client):
        router_id = uuid.uuid4()
        child_id = uuid.uuid4()
        parent_router = uuid.uuid4()

        router_cb = _make_chatbot(
            name="Router Hijo",
            kind="router",
            chatbot_id=router_id,
            parent_chatbot_id=parent_router,
        )
        child_cb = _make_chatbot(name="Atomic", kind="atomic", chatbot_id=child_id)

        session = self._mount_session(router_cb, child_cb)
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.post(
                f"/api/v1/hub/chatbots/{router_id}/children",
                json={"child_chatbot_id": str(child_id)},
            )
            assert resp.status_code == 400
            assert "2 niveles" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_cannot_assign_child_from_different_organizacion(self, client):
        router_id = uuid.uuid4()
        child_id = uuid.uuid4()

        router_cb = _make_chatbot(
            name="UJI Router",
            kind="router",
            chatbot_id=router_id,
            organizacion_id=uuid.uuid4(),
        )
        child_cb = _make_chatbot(
            name="Otro cliente",
            kind="atomic",
            chatbot_id=child_id,
            organizacion_id=uuid.uuid4(),
        )

        session = self._mount_session(router_cb, child_cb)
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.post(
                f"/api/v1/hub/chatbots/{router_id}/children",
                json={"child_chatbot_id": str(child_id)},
            )
            # SEC.2 cambió el veredicto de 400 a 403, y es más correcto: para este admin,
            # que no gestiona ninguna de las dos organizaciones del montaje, esos chatbots
            # no son un recurso mal combinado — son un recurso al que no tiene acceso. La
            # regla de negocio («deben ser de la misma organización») sigue cubierta abajo,
            # con un principal que sí ve las dos.
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_cannot_assign_child_from_different_organizacion_even_seeing_both(self, client):
        """La regla de negocio, con un superadmin que sí ve las dos organizaciones."""
        from server.app.api.deps import get_current_user

        router_id, child_id = uuid.uuid4(), uuid.uuid4()
        router_cb = _make_chatbot(
            name="UJI Router", kind="router", chatbot_id=router_id,
            organizacion_id=uuid.uuid4(),
        )
        child_cb = _make_chatbot(
            name="Otro cliente", kind="atomic", chatbot_id=child_id,
            organizacion_id=uuid.uuid4(),
        )

        session = self._mount_session(router_cb, child_cb)
        app.dependency_overrides[get_session] = _override_session(session)
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            user_id="root", email="root@test.com", role="superadmin"
        )
        try:
            resp = client.post(
                f"/api/v1/hub/chatbots/{router_id}/children",
                json={"child_chatbot_id": str(child_id)},
            )
            assert resp.status_code == 400
            assert "misma organización" in resp.json()["detail"]
        finally:
            app.dependency_overrides.pop(get_session, None)
            app.dependency_overrides.pop(get_current_user, None)

    def test_list_children_returns_only_direct_children(self, client):
        router_id = uuid.uuid4()
        child_id = uuid.uuid4()
        router_cb = _make_chatbot(name="UJI", kind="router", chatbot_id=router_id)
        child_cb = _make_chatbot(
            name="Normativa",
            kind="atomic",
            chatbot_id=child_id,
            parent_chatbot_id=router_id,
        )

        session = self._mount_session(router_cb, child_cb, children_list=[child_cb])
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.get(f"/api/v1/hub/chatbots/{router_id}/children")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data) == 1
            assert data[0]["id"] == str(child_id)
            assert data[0]["parent_chatbot_id"] == str(router_id)
        finally:
            app.dependency_overrides.pop(get_session, None)

    def test_unassign_child_clears_parent_chatbot_id(self, client):
        router_id = uuid.uuid4()
        child_id = uuid.uuid4()
        router_cb = _make_chatbot(name="UJI", kind="router", chatbot_id=router_id)
        child_cb = _make_chatbot(
            name="RRHH",
            kind="atomic",
            chatbot_id=child_id,
            parent_chatbot_id=router_id,
        )

        session = self._mount_session(router_cb, child_cb)
        app.dependency_overrides[get_session] = _override_session(session)
        try:
            resp = client.delete(f"/api/v1/hub/chatbots/{router_id}/children/{child_id}")
            assert resp.status_code == 204
            assert child_cb.parent_chatbot_id is None
        finally:
            app.dependency_overrides.pop(get_session, None)
