"""Tests RAG.9 — procedencia obligatoria y re-embedding masivo.

MOD.1 dejó la procedencia grabada pero **opcional**: un chunk podía no declarar modelo y la
guarda lo trataba como desconocido. Eso servía mientras existían filas anteriores; ahora que
se pueden rellenar, «desconocido» deja de ser un estado legítimo y pasa a ser un agujero por
el que se cuela justo la avería que MOD.1 vino a impedir.

Lo que estos tests fijan, en una frase: **el corpus siempre sabe con qué se embebió, y
volver a embeberlo produce el mismo texto que produjo la ingesta**. Un re-embed que embebe
un texto distinto del que embebió la ingesta no es un re-embed: es un segundo corpus
incompatible con el primero, y como el coseno no da error, nadie se entera.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from server.tests.dobles import completar_chatbot

from server.tests.modules.agents_hub.integration.test_metadata_filter import (
    _chunk,
    _documento,
)

# SEC.2: el chat y la ingesta exigen que el principal gestione la organizacion del
# chatbot. Estos tests prueban otra cosa, asi que doble y token comparten organizacion;
# la tenencia tiene su propio gate en `tests/api/test_tenant_isolation.py`.
ORG_PRUEBA = "00000000-0000-0000-0000-00000000dead"

MODELO = "BAAI/bge-m3"
DIMENSION = 1024


class _ServicioFalso:
    """Servicio de embeddings determinista: ni red, ni 1,1 GB de pesos."""

    def __init__(self, model_name: str = MODELO, dimensions: int = DIMENSION) -> None:
        self.model_name = model_name
        self.dimensions = dimensions
        self.textos_vistos: list[str] = []

    async def embed(self, text: str) -> list[float]:
        self.textos_vistos.append(text)
        return [0.5] * self.dimensions

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.textos_vistos.extend(texts)
        return [[0.5] * self.dimensions for _ in texts]


class TestProcedenciaObligatoria:

    @pytest.mark.asyncio
    async def test_should_reject_a_chunk_without_provenance(self, db_session):
        """`nullable=False` tras el backfill: no se puede escribir un vector anónimo.

        Es la diferencia entre una guarda que avisa y un invariante que no se puede violar.
        """
        from sqlalchemy.exc import IntegrityError

        cb = uuid.uuid4()
        doc = await _documento(db_session, cb)
        with pytest.raises(IntegrityError):
            await _chunk(
                db_session, cb, doc, "Text sense procedència",
                embedding_model=None, embedding_dim=None,
            )

    @pytest.mark.asyncio
    async def test_should_stamp_the_embedded_text_on_ingestion(self):
        """Se guarda el texto que SE EMBEBIÓ, no solo el que se muestra.

        Desde RAG.7 son distintos: `embedding_text` lleva delante título y jerarquía. Sin
        guardarlo, re-embeber a partir de `content` generaría vectores que la ingesta nunca
        habría producido — y la incoherencia no daría error, daría resultados peores.
        """
        from unittest.mock import AsyncMock, MagicMock

        from server.app.modules.agents_hub.database.operational_models import (
            HubDocument,
            HubDocumentChunk,
        )
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        session = AsyncMock()
        session.add = MagicMock()
        session.execute = AsyncMock()
        session.get = AsyncMock(return_value=None)

        watcher = IngestionWatcher(
            session=session,
            embedding_service=_ServicioFalso(),
            chatbot_provider=AsyncMock(),
        )
        doc = HubDocument(
            id=uuid.uuid4(), chatbot_id=uuid.uuid4(), title="Reglament de despeses",
            canonical_url="https://ej.com/n", markdown_content="# Reglament\n\nText.",
            content_hash="h" * 64, language="ca", source_kind="publicacio",
        )

        await watcher._regenerate_chunks_for_document(doc)

        chunks = [
            c.args[0] for c in session.add.call_args_list
            if isinstance(c.args[0], HubDocumentChunk)
        ]
        assert chunks
        assert all(c.embedding_text for c in chunks)
        assert all("Reglament de despeses" in c.embedding_text for c in chunks)

    @pytest.mark.asyncio
    async def test_should_stamp_provenance_on_user_uploads_too(self):
        """La subida de usuario escribe en la MISMA tabla y no estampaba nada.

        Con la columna opcional el agujero era invisible; con `nullable=False` la ingesta de
        adjuntos habría empezado a fallar en producción.
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        session = AsyncMock()
        session.add = MagicMock()
        session.execute = AsyncMock()

        watcher = IngestionWatcher(
            session=session,
            embedding_service=_ServicioFalso(),
            chatbot_provider=AsyncMock(),
        )

        # EXT.2: el contexto temporal se extrae con pdfplumber, no con Docling.
        with patch(
            "server.app.core.pdf_text.extraer_texto_de_pdf",
            return_value="# Adjunt\n\nContingut.",
        ):
            creados = await watcher.process_user_upload(
                source_url="file://adjunt.pdf",
                chatbot_id=uuid.uuid4(),
                owner_id=uuid.uuid4(),
            )

        assert creados
        assert all(c.embedding_model == MODELO for c in creados)
        assert all(c.embedding_dim == DIMENSION for c in creados)
        assert all(c.embedding_text for c in creados)


class TestPlanDeReembedding:

    @pytest.mark.asyncio
    async def test_should_report_plan_in_dry_run(self, db_session):
        """El dry-run cuenta sin tocar: cuántos van, cuántos se saltan y por qué."""
        from server.app.modules.agents_hub.ingestion.reembed import planificar_reembed

        cb = uuid.uuid4()
        doc = await _documento(db_session, cb)
        await _chunk(
            db_session, cb, doc, "Ja migrat", embedding_model=MODELO,
            embedding_dim=DIMENSION, embedding_text="Ja migrat",
        )
        await _chunk(
            db_session, cb, doc, "D'un altre model", embedding_model="gemini-embedding-001",
            embedding_dim=DIMENSION, embedding_text="D'un altre model",
        )
        await db_session.commit()

        plan = await planificar_reembed(db_session, cb, _ServicioFalso())

        assert plan.total == 2
        assert plan.pendientes == 1
        assert plan.al_dia == 1
        assert plan.sin_texto_embebido == 0
        assert plan.modelo_activo == MODELO

    @pytest.mark.asyncio
    async def test_should_count_chunks_that_cannot_be_reembedded(self, db_session):
        """Un chunk sin `embedding_text` no se puede re-embeber con fidelidad: se dice.

        Inventar el texto a partir de `content` daría un vector distinto del que produjo la
        ingesta. Se cuenta aparte y se remite a `recalculate-corpus`, que sí re-trocea.
        """
        from server.app.modules.agents_hub.ingestion.reembed import planificar_reembed

        cb = uuid.uuid4()
        doc = await _documento(db_session, cb)
        await _chunk(
            db_session, cb, doc, "Llegat", embedding_model="gemini-embedding-001",
            embedding_dim=DIMENSION, embedding_text=None,
        )
        await db_session.commit()

        plan = await planificar_reembed(db_session, cb, _ServicioFalso())

        assert plan.pendientes == 0
        assert plan.sin_texto_embebido == 1


class TestReembeddingMasivo:

    @pytest.mark.asyncio
    async def test_should_reembed_corpus_in_batches_via_cli(self, db_session):
        from server.app.modules.agents_hub.ingestion.reembed import reembeber_chatbot

        cb = uuid.uuid4()
        doc = await _documento(db_session, cb)
        for i in range(5):
            await _chunk(
                db_session, cb, doc, f"Article {i}",
                embedding_model="gemini-embedding-001", embedding_dim=DIMENSION,
                embedding_text=f"Reglament > Article {i}",
            )
        await db_session.commit()

        servicio = _ServicioFalso()
        procesados = await reembeber_chatbot(db_session, cb, servicio, batch_size=2)
        await db_session.commit()

        assert procesados == 5
        # Se embebe `embedding_text`, no `content`: es lo que embebió la ingesta.
        assert sorted(servicio.textos_vistos) == [f"Reglament > Article {i}" for i in range(5)]

        from server.app.modules.agents_hub.services.embedding_space import (
            describe_corpus_embedding_space,
        )
        # PIL.1: el espacio es una TRIPLETA. `None` es lo que declara un servicio sin tipos
        # de tarea —el local—, y es informacion, no un hueco.
        assert await describe_corpus_embedding_space(db_session, cb) == {
            (MODELO, DIMENSION, None)
        }

    @pytest.mark.asyncio
    async def test_should_skip_chunks_already_on_active_model(self, db_session):
        from server.app.modules.agents_hub.ingestion.reembed import reembeber_chatbot

        cb = uuid.uuid4()
        doc = await _documento(db_session, cb)
        await _chunk(
            db_session, cb, doc, "Ja migrat", embedding_model=MODELO,
            embedding_dim=DIMENSION, embedding_text="Ja migrat",
        )
        await db_session.commit()

        servicio = _ServicioFalso()
        procesados = await reembeber_chatbot(db_session, cb, servicio)

        assert procesados == 0
        assert servicio.textos_vistos == []

    @pytest.mark.asyncio
    async def test_should_reembed_everything_with_force(self, db_session):
        """`--force` existe para el caso en que el texto cambió sin cambiar el modelo:
        RAG.7 y RAG.8 alteraron `embedding_text` sin tocar BGE-M3."""
        from server.app.modules.agents_hub.ingestion.reembed import reembeber_chatbot

        cb = uuid.uuid4()
        doc = await _documento(db_session, cb)
        await _chunk(
            db_session, cb, doc, "Ja migrat", embedding_model=MODELO,
            embedding_dim=DIMENSION, embedding_text="Ja migrat",
        )
        await db_session.commit()

        servicio = _ServicioFalso()
        procesados = await reembeber_chatbot(db_session, cb, servicio, force=True)

        assert procesados == 1
        assert servicio.textos_vistos == ["Ja migrat"]


class TestGuardaEnConsulta:
    """El desajuste tiene que parar la consulta, no degradarla.

    Sin esto, preguntar a un corpus embebido con otro modelo devuelve las fuentes más
    parecidas *en un espacio que no es el suyo*: respuestas plausibles apoyadas en normas
    que no vienen a cuento. Es peor que un error, porque parece que funciona.
    """

    def _app_de_chat(self, chatbot):
        from unittest.mock import AsyncMock, MagicMock

        from fastapi import FastAPI
        from sqlalchemy.ext.asyncio import AsyncSession

        from server.app.api.v1.hub_chat import router as chat_router
        from server.app.modules.agents_hub.database.connection import get_async_session

        session = AsyncMock(spec=AsyncSession)
        resultado = MagicMock()
        resultado.scalar_one_or_none = MagicMock(return_value=chatbot)
        session.execute = AsyncMock(return_value=resultado)
        # SEC.4: la organización se lee para la cascada de cuotas; `None` = sin cuotas
        # heredadas. Con el doble por defecto, los límites serían números inventados.
        session.get = AsyncMock(return_value=None)

        async def _sesion():
            yield session

        app = FastAPI()
        app.dependency_overrides[get_async_session] = _sesion
        app.include_router(chat_router, prefix="/api/v1")
        return app

    def test_should_raise_clear_error_on_model_mismatch_at_query(self):
        import os
        from unittest.mock import AsyncMock, MagicMock, patch

        from fastapi.testclient import TestClient

        from server.app.modules.agents_hub.database.config_models import HubChatbot
        from server.app.modules.agents_hub.services.embedding_space import (
            EmbeddingSpaceMismatch,
        )

        os.environ.update({
            "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
            "JWT_ALGORITHM": "HS256",
            "JWT_EXPIRATION_MINUTES": "60",
        })
        from server.app.core.auth import UserInfo, create_token

        chatbot = MagicMock(spec=HubChatbot)

        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        chatbot.id = uuid.uuid4()
        # Los campos de configuracion del doble salen del ORM (`tests/dobles.py`):
        # un MagicMock inventa un valor por cada columna nueva, y eso ya rompio
        # estos tests tres veces —SEC.2.1, SEC.4 y SEC.4.1—.
        completar_chatbot(chatbot)
        token = create_token(UserInfo(user_id="u1", email="u@test.com", role="user", organizacion_ids=(ORG_PRUEBA,)))

        with patch(
            "server.app.api.v1.hub_chat.resolve_embedding_service", new_callable=AsyncMock
        ), patch(
            "server.app.api.v1.hub_chat.assert_embedding_space_matches",
            new=AsyncMock(side_effect=EmbeddingSpaceMismatch(
                "El corpus contiene vectores de BAAI/bge-m3 (1024), y el modelo activo es "
                "gemini-embedding-001 (1024)."
            )),
        ):
            with TestClient(self._app_de_chat(chatbot)) as client:
                resp = client.post(
                    f"/api/v1/hub/chat/{chatbot.id}",
                    json={"message": "Quina és la quantia?"},
                    headers={"Authorization": f"Bearer {token}"},
                )

        assert resp.status_code == 409
        assert "bge-m3" in resp.json()["detail"]
        assert "gemini-embedding-001" in resp.json()["detail"]


class TestValidacionAlCrearChatbot:

    def test_should_validate_embedding_service_on_chatbot_creation(self):
        """Fallar al crear es barato; fallar a mitad de una ingesta de 3.000 documentos no.

        Solo se comprueba en modo RAG: los otros dos no embeben nada, y exigirles un
        servicio operativo sería inventar un requisito.
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        from fastapi.testclient import TestClient

        from server.app.api.deps import get_current_user
        from server.app.core.auth.models import UserInfo
        from server.app.main import app
        from server.app.modules.agents_hub.database.connection import get_async_session

        session = MagicMock()
        # Crear comprueba que la configuración de LLM es de plataforma o de la organización.
        session.get = AsyncMock(return_value=SimpleNamespace(organizacion_id=None))
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        async def _sesion():
            yield session

        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            user_id="a1", email="a@test.com", role="admin"
        , organizacion_ids=(ORG_PRUEBA,))
        app.dependency_overrides[get_async_session] = _sesion
        try:
            with patch(
                "server.app.routers.hub_chatbots_router.resolve_embedding_service",
                new=AsyncMock(side_effect=RuntimeError("no hay claves de API")),
            ):
                resp = TestClient(app, raise_server_exceptions=False).post(
                    "/api/v1/hub/chatbots",
                    json={
                        "name": "Nou",
                        "organizacion_id": ORG_PRUEBA,
                        "llm_config_id": str(uuid.uuid4()),
                        "system_prompt": "Ets un assistent.",
                        "retrieval_mode": "RAG",
                    },
                )
            assert resp.status_code == 503
            assert "embedding" in resp.json()["detail"].lower()
            session.add.assert_not_called()
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_async_session, None)

    def test_should_not_require_embeddings_for_long_context(self):
        """ACT.8 — el modo del ejemplo era `MD_AGENT_SELECTOR`, y ese SI los necesita.

        `MD_LONG_CONTEXT` es el unico que de verdad no consulta el indice vectorial: inyecta
        documentos enteros. Exigirle un servicio de embeddings operativo seria inventarle un
        requisito que no tiene; exigirselo al agentico es fallar pronto en vez de tarde.
        """
        from unittest.mock import AsyncMock, MagicMock, patch

        from fastapi.testclient import TestClient

        from server.app.api.deps import get_current_user
        from server.app.core.auth.models import UserInfo
        from server.app.main import app
        from server.app.modules.agents_hub.database.connection import get_async_session

        session = MagicMock()
        # Crear comprueba que la configuración de LLM es de plataforma o de la organización.
        session.get = AsyncMock(return_value=SimpleNamespace(organizacion_id=None))
        session.add = MagicMock()
        session.commit = AsyncMock()

        async def _refresh(obj):
            from datetime import datetime, timezone
            obj.id = uuid.uuid4()
            obj.created_at = obj.updated_at = datetime.now(timezone.utc)

        session.refresh = _refresh

        async def _sesion():
            yield session

        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            user_id="a1", email="a@test.com", role="admin"
        , organizacion_ids=(ORG_PRUEBA,))
        app.dependency_overrides[get_async_session] = _sesion
        try:
            with patch(
                "server.app.routers.hub_chatbots_router.resolve_embedding_service",
                new=AsyncMock(side_effect=RuntimeError("no hay claves de API")),
            ) as resolutor:
                resp = TestClient(app, raise_server_exceptions=False).post(
                    "/api/v1/hub/chatbots",
                    json={
                        "name": "Selector",
                        "organizacion_id": ORG_PRUEBA,
                        "llm_config_id": str(uuid.uuid4()),
                        "system_prompt": "Ets un assistent.",
                        "retrieval_mode": "MD_LONG_CONTEXT",
                    },
                )
            assert resp.status_code == 201
            resolutor.assert_not_awaited()
        finally:
            app.dependency_overrides.pop(get_current_user, None)
            app.dependency_overrides.pop(get_async_session, None)
