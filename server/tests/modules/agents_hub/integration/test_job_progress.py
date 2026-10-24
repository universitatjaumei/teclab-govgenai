"""Tests RAG.12 — progreso y estadísticas por etapa de los jobs de ingesta.

Hoy un job solo dice `pending | running | completed | failed`, y una conversión de Docling
sobre un PDF largo puede tardar minutos: desde fuera es indistinguible de un job colgado. Lo
que falta no es más log, es **estado consultable**.

Dos cosas que estos tests fijan y que son fáciles de hacer mal:

- **Una escritura por etapa/lote, nunca por fragmento.** Un corpus de 3.000 documentos con
  un UPDATE por chunk convierte la barra de progreso en la parte cara de la ingesta.
- **Las estadísticas parciales sobreviven al fallo.** Justo cuando un job revienta es
  cuando interesa saber por dónde iba, y el `rollback` del manejador de errores se las
  llevaría por delante si se escribieran al final.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# SEC.2: el chat y la ingesta exigen que el principal gestione la organizacion del
# chatbot. Estos tests prueban otra cosa, asi que doble y token comparten organizacion;
# la tenencia tiene su propio gate en `tests/api/test_tenant_isolation.py`.
ORG_PRUEBA = "00000000-0000-0000-0000-00000000dead"


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


DOCUMENTO_LARGO = "\n\n".join(
    ["---\nlanguage: va\ntitle: Reglament\nus_assistents: si\n---\n\n# Reglament\n"]
    + [f"##### Article {i}. Objecte {{#art-{i}}}\n\n" + ("text " * 120) for i in range(1, 9)]
)


class _Almacen:
    """El `.md` que subió el panel: `run_job` lo lee del almacén por su clave (#265)."""

    async def get(self, key: str) -> bytes:
        return DOCUMENTO_LARGO.encode("utf-8")


_ALMACEN = _Almacen()


async def _job(session, chatbot_id: uuid.UUID):
    from server.app.modules.agents_hub.database.operational_models import HubIngestionJob

    job = HubIngestionJob(
        chatbot_id=chatbot_id,
        source_url=f"ingestion/{chatbot_id}/{uuid.uuid4()}.md",
        original_filename="reglament.md",
        language="ca",
    )
    session.add(job)
    await session.flush()
    return job


class TestEsquema:

    @pytest.mark.asyncio
    async def test_should_expose_the_progress_columns(self, db_session):
        from server.app.modules.agents_hub.database.operational_models import HubIngestionJob

        job = await _job(db_session, uuid.uuid4())
        await db_session.commit()
        await db_session.refresh(job)

        assert job.progress_current == 0
        assert job.progress_total is None
        assert job.progress_message == ""
        assert job.processing_stats == {}
        assert job.processing_started_at is None
        assert job.processing_completed_at is None
        assert isinstance(job, HubIngestionJob)


class TestProgresoDuranteElJob:

    @pytest.mark.asyncio
    async def test_should_update_progress_per_stage(self, db_session):
        """Las etapas se anuncian: trocear, embeber, persistir.

        Eran cuatro: EXT.1 quitó la de convertir, porque al corpus entra Markdown que ya
        produjo el pipeline de curación."""
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        chatbot_id = uuid.uuid4()
        job = await _job(db_session, chatbot_id)
        await db_session.commit()

        vistos: list[tuple[int, int | None, str]] = []

        watcher = IngestionWatcher(db_session, _Embedding(), chatbot_provider=_Provider(), storage=_ALMACEN)
        await watcher.run_job(
            job.id,
            progress_callback=lambda c, t, m: vistos.append((c, t, m)),
        )

        etapas = [m for _, _, m in vistos]
        # EXT.1: la etapa "convert" desapareció con la conversión. Al corpus entra Markdown
        # ya producido por el pipeline de curación, así que el job empieza a trocear.
        assert not any("convert" in e for e in etapas), (
            f"sigue habiendo una etapa de conversión en la ingesta del corpus: {etapas}"
        )
        assert any("chunk" in e for e in etapas), etapas
        assert any("embed" in e for e in etapas), etapas
        assert any("persist" in e for e in etapas), etapas

    @pytest.mark.asyncio
    async def test_should_throttle_progress_writes_per_batch(self, db_session):
        """Con 8 artículos y lotes de embedding, el número de escrituras se cuenta con los
        dedos. Si creciera con los fragmentos, la barra costaría más que la ingesta."""
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        chatbot_id = uuid.uuid4()
        job = await _job(db_session, chatbot_id)
        await db_session.commit()

        escrituras: list[str] = []
        watcher = IngestionWatcher(db_session, _Embedding(), chatbot_provider=_Provider(), storage=_ALMACEN)
        await watcher.run_job(
            job.id,
            progress_callback=lambda c, t, m: escrituras.append(m),
        )

        await db_session.refresh(job)
        n_chunks = job.chunks_processed
        assert n_chunks >= 4, f"el documento de prueba solo dio {n_chunks} fragmentos"
        assert len(escrituras) <= 8, (
            f"{len(escrituras)} avisos de progreso para {n_chunks} fragmentos: "
            "el throttle es por etapa/lote, no por fragmento"
        )

    @pytest.mark.asyncio
    async def test_should_record_stage_timings_in_processing_stats(self, db_session):
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        job = await _job(db_session, uuid.uuid4())
        await db_session.commit()

        watcher = IngestionWatcher(db_session, _Embedding(), chatbot_provider=_Provider(), storage=_ALMACEN)
        await watcher.run_job(job.id)

        await db_session.refresh(job)
        stats = job.processing_stats
        assert stats["n_chunks"] >= 4
        assert stats["total_chars"] > 0
        assert stats["n_batches"] >= 1
        assert stats["embedding_model"] == "BAAI/bge-m3"
        # Duraciones por etapa, en ms: es el dato con el que se decide dónde optimizar.
        for etapa in ("chunk", "embed", "persist"):
            assert etapa in stats["stage_ms"], stats["stage_ms"]
            assert stats["stage_ms"][etapa] >= 0
        assert job.processing_started_at is not None
        assert job.processing_completed_at is not None

    @pytest.mark.asyncio
    async def test_should_persist_partial_stats_on_failure(self, db_session):
        """El `except` hace rollback, así que unas stats escritas al final se perderían
        justo en el caso en que más falta hacen."""
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        job = await _job(db_session, uuid.uuid4())
        await db_session.commit()

        class _EmbeddingQueRevienta(_Embedding):
            async def embed_batch(self, texts):
                raise RuntimeError("el proveedor de embeddings devuelve 500")

        watcher = IngestionWatcher(
            db_session, _EmbeddingQueRevienta(), chatbot_provider=_Provider(), storage=_ALMACEN
        )
        await watcher.run_job(job.id)

        await db_session.refresh(job)
        assert job.status == "failed"
        assert "500" in (job.error_message or "")
        assert job.processing_stats.get("stage_ms", {}).get("chunk") is not None, (
            "se perdió lo que ya se había medido antes del fallo"
        )
        assert job.processing_stats.get("failed_stage") == "embed"

    @pytest.mark.asyncio
    async def test_should_work_without_a_callback(self, db_session):
        """El callback es opcional: la ingesta normal no tiene a nadie a quien informar."""
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        job = await _job(db_session, uuid.uuid4())
        await db_session.commit()

        watcher = IngestionWatcher(db_session, _Embedding(), chatbot_provider=_Provider(), storage=_ALMACEN)
        await watcher.run_job(job.id)

        await db_session.refresh(job)
        assert job.status == "completed"


class TestExposicion:

    def test_should_expose_progress_fields_in_job_status_endpoint(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from server.app.api.deps import get_current_user
        from server.app.core.auth.models import UserInfo
        from server.app.api.deps import get_session
        from server.app.routers.hub_ingestion_router import router as ingestion_router

        from datetime import datetime, timezone

        from server.app.modules.agents_hub.database.operational_models import HubIngestionJob

        job = HubIngestionJob(
            id=uuid.uuid4(),
            chatbot_id=uuid.uuid4(),
            source_url="https://www.uji.es/REG-020",
            status="running",
            progress_current=3,
            progress_total=8,
            progress_message="embed: lote 2/3",
            processing_stats={"n_chunks": 8, "stage_ms": {"convert": 120}},
            processing_started_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
            # `chunks_processed` y `created_at` son NOT NULL con `default=` de
            # SQLAlchemy: una fila leída de la base de datos siempre los trae. Aquí el
            # objeto no pasa por el flush, así que hay que ponerlos a mano para que el
            # doble se parezca a lo que el endpoint lee de verdad.
            chunks_processed=0,
            created_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )

        session = MagicMock()
        resultado = MagicMock()
        resultado.scalars.return_value.all.return_value = [job]
        session.execute = AsyncMock(return_value=resultado)
        # SEC.2: el endpoint lee antes el chatbot para comprobar la organización.
        chatbot = MagicMock()
        chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
        session.get = AsyncMock(return_value=chatbot)

        async def _sesion():
            yield session

        app = FastAPI()
        app.dependency_overrides[get_session] = _sesion
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            user_id="a1", email="a@test.com", role="admin"
        , organizacion_ids=(ORG_PRUEBA,))
        app.include_router(ingestion_router, prefix="/api/v1")

        resp = TestClient(app).get(f"/api/v1/hub/ingestion/{job.chatbot_id}/jobs")

        assert resp.status_code == 200
        devuelto = resp.json()["jobs"][0]
        assert devuelto["progress_current"] == 3
        assert devuelto["progress_total"] == 8
        assert devuelto["progress_message"] == "embed: lote 2/3"
        assert devuelto["processing_stats"]["n_chunks"] == 8


class TestCLIDeCorpus:

    def test_should_report_progress_in_bulk_corpus_cli(self, capsys):
        """La carga masiva usa el mismo callback: una sola forma de contar el progreso."""
        from server.app.modules.agents_hub.ingestion.corpus.load import (
            progreso_por_consola,
        )

        progreso_por_consola(3, 8, "embed: lote 2/3")

        salida = capsys.readouterr().out
        assert "3/8" in salida
        assert "embed" in salida

    def test_should_not_break_when_total_is_unknown(self):
        """El total no se conoce hasta después de trocear; hasta entonces es None."""
        from server.app.modules.agents_hub.ingestion.corpus.load import (
            progreso_por_consola,
        )

        progreso_por_consola(1, None, "convert: docling")  # no revienta
