"""Subir dos veces el mismo documento no puede reventar el trabajo de ingesta.

`hub_documents` tiene unicidad `(chatbot_id, content_hash)`, así que volver a subir el mismo
fichero al mismo asistente choca con la restricción. Eso es correcto y está previsto: el
código lo captura y reutiliza el documento que ya existe.

**Lo que no funcionaba es la captura.** `self._session.add(doc)` se hacía FUERA del
`begin_nested()`, así que el objeto entraba en la transacción exterior y el fallo del flush
dejaba la sesión marcada para deshacer. El `SELECT` que venía justo después —el que busca el
documento existente— moría con `PendingRollbackError`, y el job terminaba en «falló» con una
traza de SQLAlchemy en el log en lugar de reutilizar el documento.

Visto en los logs del servidor de desarrollo al subir dos veces el mismo `.md`.

Contra BD real y no con la sesión mockeada: un `AsyncMock` no tiene restricciones de
unicidad, no envenena nada y habría dado verde con el fallo dentro.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

CONTENIDO = (
    "# Norma de prova {#art-1}\n\n"
    "Este es el mismo contenido en las dos subidas, para que el `content_hash` coincida.\n"
)

#: Lo que sube el panel: el mismo cuerpo, con el front-matter que exige el contrato.
SUBIDO = "---\nlanguage: va\ntitle: Norma de prova\nus_assistents: si\n---\n\n" + CONTENIDO


class _Almacen:
    """`run_job` lee el `.md` subido del almacén por su clave (#265)."""

    async def get(self, key: str) -> bytes:
        return SUBIDO.encode("utf-8")


class _EmbeddingFalso:
    model_name = "BAAI/bge-m3"
    dimensions = 1024

    async def embed(self, text: str, purpose: str = "RETRIEVAL_QUERY") -> list[float]:
        return [0.1] * 1024

    async def embed_batch(
        self, texts: list[str], purpose: str = "RETRIEVAL_DOCUMENT"
    ) -> list[list[float]]:
        return [[0.1] * 1024 for _ in texts]


def _watcher(session):
    from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

    proveedor = AsyncMock()
    # MD_LONG_CONTEXT evita el troceado: lo que se prueba aquí es el choque de unicidad,
    # no el embebido.
    proveedor.get_retrieval_mode = AsyncMock(return_value="MD_LONG_CONTEXT")
    return IngestionWatcher(
        session=session,
        embedding_service=_EmbeddingFalso(),
        chatbot_provider=proveedor,
        storage=_Almacen(),
    )


async def _job(session, chatbot_id: uuid.UUID):
    """Una fila de trabajo, como la que crea la subida del panel."""
    from server.app.modules.agents_hub.database.operational_models import HubIngestionJob

    job = HubIngestionJob(
        chatbot_id=chatbot_id,
        status="pending",
        source_url=f"ingestion/{chatbot_id}/{uuid.uuid4()}.md",
        original_filename="norma-repetida.md",
        canonical_url="https://uji.es/norma-repetida",
        language="ca",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


class TestElTrabajoDeIngestaConDuplicado:
    """La reproducción fiel del log: por `run_job`, no llamando a `process_source`.

    La diferencia importa: `run_job` deja la fila del trabajo SUCIA en la misma sesión
    —escribe el progreso sin comprometer, a propósito— y es esa mezcla la que convierte un
    choque de unicidad previsto en una sesión envenenada.
    """

    @pytest.mark.asyncio
    async def test_should_complete_the_second_job_reusing_the_document(self, db_session):
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        chatbot = uuid.uuid4()
        watcher = _watcher(db_session)

        primero = await _job(db_session, chatbot)
        await watcher.run_job(primero.id)
        await db_session.refresh(primero)
        assert primero.status == "completed"

        segundo = await _job(db_session, chatbot)
        await watcher.run_job(segundo.id)
        await db_session.refresh(segundo)

        assert segundo.status == "completed", (
            f"el segundo trabajo fallo: {segundo.error_message}"
        )
        cuantos = await db_session.execute(
            select(func.count(HubDocument.id)).where(HubDocument.chatbot_id == chatbot)
        )
        assert int(cuantos.scalar_one()) == 1


class TestDosTrabajosALaVez:
    """La reproducción de verdad: dos subidas aceptadas antes de que ninguna termine.

    Es lo que muestra el log —dos `POST /upload` con 202 seguidos— y lo que el propio
    comentario del código dice estar cubriendo: «dos jobs concurrentes procesaron el mismo
    contenido». Cada trabajo corre en su propia sesión, así que ninguno ve la fila del otro
    hasta que confirma, y el choque llega en el `flush`.
    """

    @pytest.mark.asyncio
    async def test_should_not_poison_the_session_when_two_jobs_race(self, db_url):
        import asyncio

        from server.app.modules.agents_hub.database.connection import (
            create_async_engine,
            create_session_factory,
        )
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        chatbot = uuid.uuid4()
        engine = create_async_engine(db_url)
        factory = create_session_factory(engine)
        try:
            async def subir() -> str:
                async with factory() as sesion:
                    job = await _job(sesion, chatbot)
                    await _watcher(sesion).run_job(job.id)
                    await sesion.refresh(job)
                    return job.status or ""

            estados = await asyncio.gather(subir(), subir())

            assert estados == ["completed", "completed"], (
                f"un trabajo se quedo en {estados}: el choque de unicidad no se absorbio"
            )
            async with factory() as sesion:
                cuantos = await sesion.execute(
                    select(func.count(HubDocument.id)).where(
                        HubDocument.chatbot_id == chatbot
                    )
                )
                assert int(cuantos.scalar_one()) == 1
        finally:
            await engine.dispose()


class TestSubirDosVecesElMismoDocumento:

    @pytest.mark.asyncio
    async def test_should_reuse_the_existing_document_instead_of_failing(self, db_session):
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        chatbot = uuid.uuid4()
        watcher = _watcher(db_session)

        primero, _ = await watcher.process_source(
            "https://uji.es/norma-repetida",
            chatbot,
            language="ca",
            prefetched_content=CONTENIDO,
            title="Norma repetida",
        )
        # La segunda subida es la que choca con `uq_document_chatbot_hash`.
        segundo, _ = await watcher.process_source(
            "https://uji.es/norma-repetida",
            chatbot,
            language="ca",
            prefetched_content=CONTENIDO,
            title="Norma repetida",
        )

        assert segundo.id == primero.id, "no reutilizo el documento que ya existia"
        cuantos = await db_session.execute(
            select(func.count(HubDocument.id)).where(HubDocument.chatbot_id == chatbot)
        )
        assert int(cuantos.scalar_one()) == 1

    @pytest.mark.asyncio
    async def test_should_leave_the_session_usable_after_the_clash(self, db_session):
        """La sesión tiene que seguir sirviendo: el job hace más cosas después.

        Este es el sintoma que se veia en el log —`PendingRollbackError`—, y es lo que
        convertia un caso previsto en un trabajo fallido.
        """
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        chatbot = uuid.uuid4()
        watcher = _watcher(db_session)
        for _ in range(2):
            await watcher.process_source(
                "https://uji.es/otra-norma",
                chatbot,
                language="ca",
                prefetched_content=CONTENIDO,
                title="Otra norma",
            )

        # Cualquier consulta posterior con la MISMA sesión: si quedó envenenada, revienta.
        filas = await db_session.execute(select(HubDocument).limit(1))
        assert filas.scalars().first() is not None

    @pytest.mark.asyncio
    async def test_should_keep_documents_of_other_chatbots_apart(self, db_session):
        """La unicidad es por chatbot: el mismo texto en dos asistentes son dos documentos."""
        from server.app.modules.agents_hub.database.operational_models import HubDocument

        uno, dos = uuid.uuid4(), uuid.uuid4()
        watcher = _watcher(db_session)

        a, _ = await watcher.process_source(
            "https://uji.es/compartida", uno, language="ca",
            prefetched_content=CONTENIDO, title="Compartida",
        )
        b, _ = await watcher.process_source(
            "https://uji.es/compartida", dos, language="ca",
            prefetched_content=CONTENIDO, title="Compartida",
        )

        assert a.id != b.id
        total = await db_session.execute(
            select(func.count(HubDocument.id)).where(
                HubDocument.chatbot_id.in_([uno, dos])
            )
        )
        assert int(total.scalar_one()) == 2
