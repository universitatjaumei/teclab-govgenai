"""#265 — Un `.md` subido por el panel se trata igual que uno cargado por consola.

El panel valida el contrato del corpus antes de aceptar la subida (`_assert_cumple_el_contrato`,
con el mismo `entry_from_frontmatter` que `corpus.load`), pero la ingesta sólo usaba `language`
del front-matter: el documento quedaba con el nombre del fichero como título, sin
`id_publicacio`, sin vigencia y con la clave de almacenamiento como URL. Ahora la subida pasa
por el mismo `CorpusReconciler` que la consola.

Lo único que el panel añade son los dos campos que la persona rellena en el formulario —URL e
idioma—, que mandan cuando están puestos: es lo que hace funcionar «Sustituir documento», que
los rellena con los del documento que se sustituye.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from server.app.modules.agents_hub.database.operational_models import (
    HubDocument,
    HubIngestionJob,
)
from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher


class _Embedding:
    model_name = "BAAI/bge-m3"
    dimensions = 1024

    async def embed(self, text: str) -> list[float]:
        return [0.1] * 1024

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.1] * 1024 for _ in texts]


class _Provider:
    async def get_retrieval_mode(self, chatbot_id):
        return "RAG"


class _StorageDeUnSoloFichero:
    def __init__(self, contenido: str) -> None:
        self._contenido = contenido
        self.pedidas: list[str] = []

    async def get(self, key: str) -> bytes:
        self.pedidas.append(key)
        return self._contenido.encode("utf-8")


def _md(**campos: str) -> str:
    cabecera = "\n".join(f"{k}: {v}" for k, v in campos.items())
    return (
        f"---\n{cabecera}\n---\n\n# Reglament de prova\n\n"
        "##### Article 1. Objecte {#art-1}\n\nEste reglament regula la prova.\n"
    )


NORMA = dict(
    language="va",
    id_publicacio="REG-265",
    title="Reglament de prova del 265",
    estat_vigencia="vigent",
    us_assistents="si",
    url_oficial="https://www.uji.es/reg-265",
)


async def _subir(
    session,
    chatbot_id: uuid.UUID,
    contenido: str,
    *,
    canonical_url: str | None = None,
    language: str | None = None,
) -> HubIngestionJob:
    """Lo que hace `upload_document` y luego la tarea de fondo, sin HTTP."""
    job = HubIngestionJob(
        chatbot_id=chatbot_id,
        source_url=f"ingestion/{chatbot_id}/{uuid.uuid4()}.md",
        original_filename="reg-265-subido.md",
        canonical_url=canonical_url,
        language=language,
        status="pending",
    )
    session.add(job)
    await session.commit()
    almacen = _StorageDeUnSoloFichero(contenido)
    watcher = IngestionWatcher(
        session, _Embedding(), storage=almacen, chatbot_provider=_Provider()
    )
    await watcher.run_job(job.id)
    await session.refresh(job)
    # Lo que se ingiere es lo que el panel guardó, y se pide por la clave del job.
    assert almacen.pedidas == [job.source_url]
    return job


async def _documentos(session, chatbot_id: uuid.UUID) -> list[HubDocument]:
    return list(
        (
            await session.execute(
                select(HubDocument).where(HubDocument.chatbot_id == chatbot_id)
            )
        ).scalars()
    )


class TestLaSubidaAplicaLosMetadatosDelContrato:

    @pytest.mark.asyncio
    async def test_should_take_title_identity_and_url_from_the_frontmatter(self, db_session):
        chatbot_id = uuid.uuid4()
        job = await _subir(db_session, chatbot_id, _md(**NORMA))

        assert job.status == "completed", job.error_message
        [doc] = await _documentos(db_session, chatbot_id)
        assert doc.title == "Reglament de prova del 265"
        assert doc.id_publicacio == "REG-265"
        assert doc.estat_vigencia == "vigent"
        assert doc.canonical_url == "https://www.uji.es/reg-265"
        assert doc.language == "va"

    @pytest.mark.asyncio
    async def test_should_still_be_shown_as_an_upload(self, db_session):
        # La tabla del panel distingue lo subido de lo rastreado por `source_kind`.
        chatbot_id = uuid.uuid4()
        await _subir(db_session, chatbot_id, _md(**NORMA))

        [doc] = await _documentos(db_session, chatbot_id)
        assert doc.source_kind == "upload"

    @pytest.mark.asyncio
    async def test_should_not_ingest_what_the_corpus_marks_as_not_for_assistants(
        self, db_session
    ):
        chatbot_id = uuid.uuid4()
        job = await _subir(
            db_session,
            chatbot_id,
            # Entre comillas, como en el corpus: sin ellas YAML lo lee como `False`.
            _md(**{**NORMA, "us_assistents": "'no'", "motiu_exclusio": "derogada"}),
        )

        assert await _documentos(db_session, chatbot_id) == []
        assert job.status == "completed"
        assert "us_assistents=no" in (job.error_message or "")

    @pytest.mark.asyncio
    async def test_should_leave_a_single_job_row(self, db_session):
        # El reconciliador anota su propio resumen cuando lo lanza la consola; la subida ya
        # tiene su job y una segunda fila sería ruido en «Jobs (tècnic)».
        chatbot_id = uuid.uuid4()
        await _subir(db_session, chatbot_id, _md(**NORMA))

        jobs = (
            await db_session.execute(
                select(HubIngestionJob).where(HubIngestionJob.chatbot_id == chatbot_id)
            )
        ).scalars().all()
        assert len(jobs) == 1


class TestLoQueRellenaLaPersonaManda:

    @pytest.mark.asyncio
    async def test_should_replace_the_substituted_document(self, db_session):
        # Un documento subido antes de #265: sin `id_publicacio`, con la URL del panel.
        chatbot_id = uuid.uuid4()
        sin_id = {k: v for k, v in NORMA.items() if k not in ("id_publicacio", "url_oficial")}
        await _subir(
            db_session, chatbot_id, _md(**sin_id),
            canonical_url="https://www.uji.es/la-del-panel", language="va",
        )

        # «Sustituir documento» rellena URL e idioma con los del documento sustituido.
        nuevo = {**NORMA, "title": "Reglament de prova, versió nova"}
        job = await _subir(
            db_session, chatbot_id, _md(**nuevo).replace("la prova.", "la prova, de nou."),
            canonical_url="https://www.uji.es/la-del-panel", language="va",
        )

        assert job.status == "completed", job.error_message
        [doc] = await _documentos(db_session, chatbot_id)
        assert doc.title == "Reglament de prova, versió nova"
        assert doc.id_publicacio == "REG-265"
        assert doc.canonical_url == "https://www.uji.es/la-del-panel"


class TestLaSubidaNoPierdeLaIdentidadDelDocumento:
    """#265b — dos regresiones del propio arreglo de #265, de la revisión de la PR #283."""

    @pytest.mark.asyncio
    async def test_should_keep_two_different_uploads_with_the_same_filename_and_no_url(
        self, db_session
    ):
        # Sin URL en el formulario ni `url_oficial`, la URL era el nombre del fichero, y el
        # segundo documento sustituía al primero. `_subir` usa siempre el mismo nombre.
        chatbot_id = uuid.uuid4()
        sin_url = {k: v for k, v in NORMA.items() if k != "url_oficial"}
        primero = await _subir(db_session, chatbot_id, _md(**sin_url))
        segundo = await _subir(
            db_session,
            chatbot_id,
            _md(**{**sin_url, "id_publicacio": "REG-265-B", "title": "Un altre reglament"}),
        )

        assert primero.status == "completed", primero.error_message
        assert segundo.status == "completed", segundo.error_message
        documentos = await _documentos(db_session, chatbot_id)
        assert sorted(d.title for d in documentos) == [
            "Reglament de prova del 265",
            "Un altre reglament",
        ]
        assert {d.canonical_url for d in documentos} == {primero.source_url, segundo.source_url}

    @pytest.mark.asyncio
    async def test_should_store_the_form_language_as_the_corpus_code(self, db_session):
        # El selector del panel manda `ca`; el corpus escribe `val`.
        chatbot_id = uuid.uuid4()
        job = await _subir(db_session, chatbot_id, _md(**NORMA), language="ca")

        assert job.status == "completed", job.error_message
        [doc] = await _documentos(db_session, chatbot_id)
        assert doc.language == "val"
