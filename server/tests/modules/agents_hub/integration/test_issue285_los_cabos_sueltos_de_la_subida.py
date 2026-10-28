"""#285 — lo que dejó suelto la subida por el reconciliador (#265), punto por punto.

Eran hallazgos de la revisión de la PR #283, leídos en el código y no reproducidos. Aquí se
reproduce cada uno contra la base desechable antes de arreglarlo.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from server.app.modules.agents_hub.database.operational_models import HubDocumentChunk
from server.app.modules.agents_hub.ingestion.corpus.source import MarkdownSubido
from server.app.modules.agents_hub.services.retrieval.citations import url_de_cita
from server.tests.modules.agents_hub.integration.test_corpus_reconciler import (
    _dos_chatbots_de_la_misma_organizacion,
    _escribir,
    _FakeEmbedding,
    _reconciliar,
)
from server.tests.modules.agents_hub.integration.test_issue265_la_subida_aplica_el_contrato import (
    NORMA,
    _documentos,
    _md,
    _subir,
)


class TestLaCitaDeUnaSubidaNoApuntaAUnaPaginaQueNoExiste:
    """El sitio publicado se genera del repositorio del corpus, no de lo que se sube al panel:
    `documento (1).md` no tiene página, y citarla daba un 404 en producción."""

    def test_should_cite_the_document_url_and_not_a_site_page(self, monkeypatch):
        monkeypatch.setenv("CORPUS_SITE_BASE_URL", "https://normativa.uji.es")
        subido = SimpleNamespace(
            doc_metadata={"relative_path": "documento (1).md"},
            source_kind="upload",
            canonical_url="https://www.uji.es/reglament.pdf",
        )

        assert url_de_cita(subido, {"ancora": "art-1"}) == "https://www.uji.es/reglament.pdf"

    def test_should_keep_citing_the_site_page_of_a_published_document(self, monkeypatch):
        monkeypatch.setenv("CORPUS_SITE_BASE_URL", "https://normativa.uji.es")
        publicado = SimpleNamespace(
            doc_metadata={"relative_path": "reglament-de-prova.md"},
            source_kind="publicacio",
            canonical_url="https://www.uji.es/reglament.pdf",
        )

        assert (
            url_de_cita(publicado, {"ancora": "art-1"})
            == "https://normativa.uji.es/html/reglament-de-prova.html#art-1"
        )


class TestUnaSubidaQueFallaAMediasNoDejaHuerfanos:

    @pytest.mark.asyncio
    async def test_should_leave_no_document_when_it_fails_after_ingesting(
        self, db_session, monkeypatch
    ):
        # El watcher confirmaba el documento y sus fragmentos antes de que el reconciliador le
        # pusiera los metadatos: un fallo ahí dejaba un documento buscable sin vigencia, sin
        # `us_assistents` y sin `source_kind`, fuera de los filtros.
        from server.app.modules.agents_hub.ingestion.corpus import reconciler

        async def _revienta(*_a, **_k):
            raise RuntimeError("fallo después de ingerir")

        monkeypatch.setattr(reconciler, "refrescar_puente_bilingue", _revienta)
        chatbot_id = uuid.uuid4()

        job = await _subir(db_session, chatbot_id, _md(**NORMA))

        assert job.status == "failed", (job.status, job.error_message)
        assert await _documentos(db_session, chatbot_id) == []
        fragmentos = (
            await db_session.execute(
                select(HubDocumentChunk).where(HubDocumentChunk.chatbot_id == chatbot_id)
            )
        ).scalars().all()
        assert fragmentos == []


class TestSustituirPorUnaVersionQueNoEsParaAsistentes:

    @pytest.mark.asyncio
    async def test_should_retire_the_version_it_replaces(self, db_session):
        chatbot_id = uuid.uuid4()
        await _subir(db_session, chatbot_id, _md(**NORMA))

        job = await _subir(
            db_session,
            chatbot_id,
            _md(**{**NORMA, "us_assistents": "'no'", "motiu_exclusio": "derogada"}),
        )

        assert job.status == "completed"
        [doc] = await _documentos(db_session, chatbot_id)
        assert doc.us_assistents == "no", "la versión anterior seguía respondiendo"


class TestLoQueDiceElTrabajo:

    @pytest.mark.asyncio
    async def test_should_not_put_notes_in_the_error_of_a_completed_job(self, db_session):
        chatbot_id = uuid.uuid4()
        job = await _subir(
            db_session,
            chatbot_id,
            _md(**{**NORMA, "us_assistents": "'no'", "motiu_exclusio": "derogada"}),
        )

        assert job.status == "completed"
        assert job.error_message is None, "en el panel un completado con error parece un fallo"
        assert any("us_assistents=no" in a for a in job.processing_stats["avisos"])

    @pytest.mark.asyncio
    async def test_should_count_the_fragments_copied_from_a_twin(self, db_session, tmp_path):
        _escribir(tmp_path, "REG-285", body="El text de la norma que es repetix.")
        origen, destino = await _dos_chatbots_de_la_misma_organizacion(db_session)
        await _reconciliar(db_session, tmp_path, origen, embedding=_FakeEmbedding())
        await db_session.commit()

        informe = await _reconciliar(db_session, tmp_path, destino, embedding=_FakeEmbedding())

        assert informe.copiados == 1
        copiados = (
            await db_session.execute(
                select(HubDocumentChunk).where(HubDocumentChunk.chatbot_id == destino)
            )
        ).scalars().all()
        assert informe.fragmentos == len(copiados) > 0


class TestElTituloDeUnaSubidaSinTitulo:

    @pytest.mark.asyncio
    async def test_should_take_the_h1_and_not_the_filename(self):
        sin_titulo = {k: v for k, v in NORMA.items() if k != "title"}

        [entrada] = await MarkdownSubido("norma.md", _md(**sin_titulo)).list_entries()

        assert entrada.title == "Reglament de prova"

    @pytest.mark.asyncio
    async def test_should_drop_the_extension_when_there_is_no_h1(self):
        sin_titulo = {k: v for k, v in NORMA.items() if k != "title"}
        texto = _md(**sin_titulo).replace("# Reglament de prova\n", "")

        [entrada] = await MarkdownSubido("norma.md", texto).list_entries()

        assert entrada.title == "norma"


class TestLaPodaNoBorraLaCuentaDeLasSustituciones:
    """Revisión de la PR #313: la poda asignaba `retirados` en vez de sumar, y se comía las
    versiones que la rama de `us_assistents=no` acababa de retirar en la misma pasada."""

    @pytest.mark.asyncio
    async def test_should_count_both_kinds_of_retirement(self, db_session, tmp_path):
        chatbot_id = uuid.uuid4()
        for n in range(1, 21):
            _escribir(tmp_path, f"REG-3{n:02d}")
        await _reconciliar(db_session, tmp_path, chatbot_id, census=True)
        await db_session.commit()
        _escribir(tmp_path, "REG-301", extra="us_assistents: 'no'\nmotiu_exclusio: derogat\n")
        (tmp_path / "REG-305.md").unlink()

        informe = await _reconciliar(db_session, tmp_path, chatbot_id, census=True, prune=True)

        assert informe.retirados == 2
