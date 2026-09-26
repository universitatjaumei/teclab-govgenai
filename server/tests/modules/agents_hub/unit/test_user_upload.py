"""Tests para la ingestiÃ³n de documentos de usuario (contexto temporal)."""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import select


class TestUserUploadIngestion:

    @pytest.mark.asyncio
    async def test_user_upload_is_not_visible_to_other_users(self) -> None:
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        user_a = uuid.uuid4()
        user_b = uuid.uuid4()
        chatbot_id = uuid.uuid4()

        # EXT.2: el contexto temporal se extrae con pdfplumber, no con Docling.
        with patch(
            'server.app.core.pdf_text.extraer_texto_de_pdf',
            return_value="# Doc A\n\nContenido privado.",
        ):

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(
                return_value=Mock(
                    scalar_one_or_none=Mock(return_value=None),
                    scalars=Mock(return_value=[]),
                )
            )

            watcher = IngestionWatcher(
                session=mock_session,
                embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024)),
            )

            chunks = await watcher.process_user_upload(
                source_url="https://example.com/doc_a.pdf",
                chatbot_id=chatbot_id,
                owner_id=user_a,
            )

        # Los chunks creados pertenecen a user_a y son temporales
        assert all(c.owner_id == user_a for c in chunks)
        assert all(c.is_temporary for c in chunks)

        # user_b no es owner de ninguno
        assert not any(c.owner_id == user_b for c in chunks)

    @pytest.mark.asyncio
    async def test_temporary_chunks_cleanup(self, db_session) -> None:
        """Se borra el temporal caducado y **solo** ese (issue #159).

        Antes esto se comprobaba con un doble de sesion que devolvia tres objetos y esperaba
        una llamada a `session.delete`. Ya no vale, y no porque el test estuviera mal escrito:
        el filtro se movio al `WHERE` de un `DELETE` porque la version anterior traia los
        163.762 fragmentos temporales como objetos ORM —cada uno con su vector— y comparaba la
        fecha en Python. Un doble no puede ver la diferencia entre filtrar en SQL y filtrar
        despues, que es justamente lo que hay que comprobar, asi que se comprueba contra la
        base.
        """
        from server.app.modules.agents_hub.database.operational_models import HubDocumentChunk
        from server.app.modules.agents_hub.ingestion.watcher import cleanup_temporary_chunks

        chatbot_id = uuid.uuid4()
        cutoff = datetime.now(timezone.utc) - timedelta(hours=24)

        def _fragmento(temporal: bool, creado) -> HubDocumentChunk:
            return HubDocumentChunk(
                id=uuid.uuid4(),
                chatbot_id=chatbot_id,
                content="Texto.",
                source_url="https://example.com/doc.pdf",
                content_hash=uuid.uuid4().hex,
                language="val",
                embedding_model="de-prueba",
                embedding_dim=1024,
                is_temporary=temporal,
                created_at=creado,
            )

        caducado = _fragmento(True, cutoff - timedelta(hours=1))
        reciente = _fragmento(True, cutoff + timedelta(hours=1))
        permanente = _fragmento(False, cutoff - timedelta(hours=1))
        db_session.add_all([caducado, reciente, permanente])
        await db_session.commit()

        borrados = await cleanup_temporary_chunks(db_session, ttl_hours=24)

        assert borrados == 1
        vivos = {
            fila
            for (fila,) in (
                await db_session.execute(
                    select(HubDocumentChunk.id).where(
                        HubDocumentChunk.chatbot_id == chatbot_id
                    )
                )
            ).all()
        }
        assert vivos == {reciente.id, permanente.id}


@pytest.fixture
async def db_session(db_url: str):
    """Una sesion contra la base desechable del conftest."""
    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )

    motor = create_async_engine(db_url)
    fabrica = create_session_factory(motor)
    async with fabrica() as sesion:
        yield sesion
    await motor.dispose()
