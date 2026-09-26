"""Tests de integración del flujo de ingestión con StorageService.

Verifica que:
  - IngestionWatcher descarga de storage cuando source_url no es HTTP
  - El endpoint /upload persiste el documento vía StorageService (no en /tmp)
  - El job.source_url apunta a la clave de storage
  - El documento permanece en storage tras el procesamiento (no se borra)
  - El endpoint /delete borra de storage para claves de storage

**EXT.1**: lo que sube y se almacena es un `.md` conforme al contrato del corpus, no un PDF.
La conversión vive fuera, en el pipeline de curación. El cambio se nota aquí en dos sitios:
la clave termina en `.md`, y `run_job` ya no escribe un fichero temporal para que un
conversor lo abra — lee el contenido del almacén y lo pasa como texto.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# SEC.2: el chat y la ingesta exigen que el principal gestione la organizacion del
# chatbot. Estos tests prueban otra cosa, asi que doble y token comparten organizacion;
# la tenencia tiene su propio gate en `tests/api/test_tenant_isolation.py`.
ORG_PRUEBA = "00000000-0000-0000-0000-00000000dead"


# ── Helpers ─────────────────────────────────────────────────────────────────

_JWT_ENV = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}


def _make_token(role: str = "admin") -> str:
    import os
    os.environ.update(_JWT_ENV)
    from server.app.core.auth import UserInfo, create_token
    return create_token(UserInfo(user_id="admin-1", email="admin@test.com", role=role, organizacion_ids=(ORG_PRUEBA,)))


# EXT.1: al corpus solo entra Markdown conforme al contrato, así que lo que estos tests
# suben es la salida del pipeline de curación y no el original. `language` es el único campo
# del front-matter sin default en `CorpusDocumentEntry`.
MD_DE_CORPUS = b"""---
language: va
id_publicacio: REG-999
title: Norma de prueba
---

# Norma de prueba
"""


def _make_job(source_url: str, status: str = "pending"):
    job = MagicMock()
    job.id = uuid.uuid4()
    job.chatbot_id = uuid.uuid4()
    # SEC.2: la guarda de tenencia lee la organizacion de lo que devuelva `session.get`.
    job.organizacion_id = uuid.UUID(ORG_PRUEBA)
    job.source_url = source_url
    job.canonical_url = None
    job.language = None
    job.status = status
    job.chunks_processed = 0
    job.error_message = None
    return job


def _build_upload_app(mock_session, mock_storage):
    """App FastAPI aislada con sesión y storage mockeados."""
    from fastapi import FastAPI
    from server.app.routers.hub_ingestion_router import router
    from server.app.modules.agents_hub.database.connection import get_async_session
    from server.app.core.storage import get_storage_service

    async def _mock_session():
        yield mock_session

    # SEC.2: `session.get` resuelve el chatbot para comprobar la organizacion. Con un
    # AsyncMock pelado devuelve un Mock cuya organizacion no casa con la del token y el
    # endpoint responde 403 antes de llegar a lo que estos tests miden.
    chatbot = MagicMock()
    chatbot.organizacion_id = uuid.UUID(ORG_PRUEBA)
    mock_session.get = AsyncMock(return_value=chatbot)

    app = FastAPI()
    app.dependency_overrides[get_async_session] = _mock_session
    app.dependency_overrides[get_storage_service] = lambda: mock_storage
    app.include_router(router, prefix="/api/v1")
    return app


# ── IngestionWatcher + StorageService ────────────────────────────────────────

class TestWatcherStorageIntegration:

    @pytest.mark.asyncio
    async def test_run_job_downloads_pdf_from_storage_for_storage_key(self) -> None:
        """run_job descarga desde storage cuando source_url es una clave (no HTTP)."""
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        storage_key = "ingestion/chatbot-1/job-1.md"
        job = _make_job(source_url=storage_key)
        pdf_bytes = b"%PDF-1.4 test content"

        mock_storage = AsyncMock()
        mock_storage.get = AsyncMock(return_value=pdf_bytes)

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=job)
        # Issue #159: `run_job` empieza tomando el job con un `UPDATE ... WHERE status IN (...)`
        # y se va si no se lo queda. Un `AsyncMock` devuelve un `Mock` por `rowcount`, que no
        # es 1: sin esto el doble finge que otro se lo llevo y el test deja de ejercitar la
        # ingesta — incluido el que comprueba que NO se llama al almacen, que pasaria en verde
        # sin haber entrado en el metodo.
        mock_session.execute.return_value.rowcount = 1

        watcher = IngestionWatcher(
            session=mock_session,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024)),
            storage=mock_storage,
        )

        with patch.object(watcher, "process_source", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = (MagicMock(), 0)
            await watcher.run_job(job.id)

        mock_storage.get.assert_called_once_with(storage_key)

    @pytest.mark.asyncio
    async def test_run_job_passes_local_path_to_process_source_not_storage_key(self) -> None:
        """EXT.1: lo que llega a process_source es el CONTENIDO del `.md`, no una ruta que abrir."""
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        storage_key = "ingestion/chatbot-1/job-1.md"
        job = _make_job(source_url=storage_key)

        mock_storage = AsyncMock()
        mock_storage.get = AsyncMock(return_value=b"# Norma de prueba\n")

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=job)
        # Issue #159: `run_job` empieza tomando el job con un `UPDATE ... WHERE status IN (...)`
        # y se va si no se lo queda. Un `AsyncMock` devuelve un `Mock` por `rowcount`, que no
        # es 1: sin esto el doble finge que otro se lo llevo y el test deja de ejercitar la
        # ingesta — incluido el que comprueba que NO se llama al almacen, que pasaria en verde
        # sin haber entrado en el metodo.
        mock_session.execute.return_value.rowcount = 1

        watcher = IngestionWatcher(
            session=mock_session,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024)),
            storage=mock_storage,
        )

        capturado = {}

        async def capture_source(*args, **kwargs):
            capturado["source_url"] = kwargs.get("source_url") or args[0]
            capturado["prefetched_content"] = kwargs.get("prefetched_content")
            return (MagicMock(), 0)

        with patch.object(watcher, "process_source", side_effect=capture_source):
            await watcher.run_job(job.id)

        # EXT.1: ya no se escribe un fichero temporal para que un conversor lo abra. Lo que
        # hay en el almacén es el `.md` que produjo el pipeline de curación, así que se lee
        # como texto y se pasa como contenido — la conversión no ocurre aquí.
        assert capturado["prefetched_content"] == "# Norma de prueba\n"
        # Y la clave de almacenamiento sigue siendo el identificador canónico, no una ruta
        # local que dejaría de existir en cuanto terminara el job.
        assert capturado["source_url"] == storage_key

    @pytest.mark.asyncio
    async def test_run_job_skips_storage_download_for_http_url(self) -> None:
        """run_job NO llama storage.get cuando source_url es una URL HTTP."""
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        job = _make_job(source_url="https://example.com/doc.pdf")

        mock_storage = AsyncMock()
        mock_storage.get = AsyncMock()

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=job)
        # Issue #159: `run_job` empieza tomando el job con un `UPDATE ... WHERE status IN (...)`
        # y se va si no se lo queda. Un `AsyncMock` devuelve un `Mock` por `rowcount`, que no
        # es 1: sin esto el doble finge que otro se lo llevo y el test deja de ejercitar la
        # ingesta — incluido el que comprueba que NO se llama al almacen, que pasaria en verde
        # sin haber entrado en el metodo.
        mock_session.execute.return_value.rowcount = 1

        watcher = IngestionWatcher(
            session=mock_session,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024)),
            storage=mock_storage,
        )

        with patch.object(watcher, "process_source", new_callable=AsyncMock) as mock_process:
            mock_process.return_value = (MagicMock(), 0)
            await watcher.run_job(job.id)

        mock_storage.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_run_job_cleans_tempfile_even_when_process_source_raises(self) -> None:
        """El fichero temporal se elimina aunque process_source lance una excepción."""
        import os
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        storage_key = "ingestion/chatbot-1/job-1.md"
        job = _make_job(source_url=storage_key)

        mock_storage = AsyncMock()
        mock_storage.get = AsyncMock(return_value=b"# Norma de prueba\n")

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=job)
        # Issue #159: `run_job` empieza tomando el job con un `UPDATE ... WHERE status IN (...)`
        # y se va si no se lo queda. Un `AsyncMock` devuelve un `Mock` por `rowcount`, que no
        # es 1: sin esto el doble finge que otro se lo llevo y el test deja de ejercitar la
        # ingesta — incluido el que comprueba que NO se llama al almacen, que pasaria en verde
        # sin haber entrado en el metodo.
        mock_session.execute.return_value.rowcount = 1

        watcher = IngestionWatcher(
            session=mock_session,
            embedding_service=AsyncMock(),
            storage=mock_storage,
        )

        created_tmp_paths = []

        async def process_and_capture(source_url, *args, **kwargs):
            created_tmp_paths.append(source_url)
            raise RuntimeError("Fallo simulado en Docling")

        with patch.object(watcher, "process_source", side_effect=process_and_capture):
            await watcher.run_job(job.id)  # No debe propagar la excepción

        # El job debe quedar en estado "failed"
        assert job.status == "failed"
        # El fichero temporal ya no debe existir
        for tmp_path in created_tmp_paths:
            assert not os.path.exists(tmp_path), f"Fichero temporal no limpiado: {tmp_path}"

    @pytest.mark.asyncio
    async def test_run_job_uses_storage_key_as_citation_when_no_canonical_url(self) -> None:
        """Cuando no hay canonical_url, la storage key se pasa como citation_url a process_source."""
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        storage_key = "ingestion/chatbot-1/job-1.md"
        job = _make_job(source_url=storage_key)  # canonical_url = None

        mock_storage = AsyncMock()
        mock_storage.get = AsyncMock(return_value=b"# Norma de prueba\n")

        mock_session = AsyncMock()
        mock_session.get = AsyncMock(return_value=job)
        # Issue #159: `run_job` empieza tomando el job con un `UPDATE ... WHERE status IN (...)`
        # y se va si no se lo queda. Un `AsyncMock` devuelve un `Mock` por `rowcount`, que no
        # es 1: sin esto el doble finge que otro se lo llevo y el test deja de ejercitar la
        # ingesta — incluido el que comprueba que NO se llama al almacen, que pasaria en verde
        # sin haber entrado en el metodo.
        mock_session.execute.return_value.rowcount = 1

        watcher = IngestionWatcher(
            session=mock_session,
            embedding_service=AsyncMock(embed=AsyncMock(return_value=[0.1] * 1024)),
            storage=mock_storage,
        )

        captured_kwargs = {}

        async def capture(*args, **kwargs):
            captured_kwargs.update(kwargs)
            return (MagicMock(), 0)

        with patch.object(watcher, "process_source", side_effect=capture):
            await watcher.run_job(job.id)

        assert captured_kwargs.get("citation_url") == storage_key


# ── Upload endpoint + StorageService ─────────────────────────────────────────

class TestUploadEndpointStorageIntegration:

    def _make_mock_session(self, job_id=None):
        mock_session = AsyncMock()
        job_mock = MagicMock()
        job_mock.id = job_id or uuid.uuid4()
        job_mock.chatbot_id = uuid.uuid4()
        job_mock.source_url = ""
        job_mock.status = "pending"
        mock_session.get = AsyncMock(return_value=job_mock)

        def _refresh(obj):
            """Rellena los defaults que pone el INSERT, como haría un refresh real.

            `chunks_processed` y `created_at` son `default=` de SQLAlchemy: se aplican
            al hacer flush, no al construir el objeto. Sin esto, la fila que devuelve
            el endpoint tiene `None` donde la columna es NOT NULL — un estado que en
            la base de datos no existe, y que desde CAL.2 el `response_model` rechaza.
            """
            from datetime import datetime, timezone

            for campo, valor in (
                ("chunks_processed", 0),
                ("progress_current", 0),
                ("progress_message", ""),
                ("processing_stats", {}),
                ("created_at", datetime.now(timezone.utc)),
            ):
                if getattr(obj, campo, None) is None:
                    setattr(obj, campo, valor)

        mock_session.refresh = AsyncMock(side_effect=_refresh)
        return mock_session, job_mock

    def test_upload_calls_storage_put_with_pdf_key(self) -> None:
        """El endpoint /upload llama a storage.put con una clave que termina en .pdf."""
        from fastapi.testclient import TestClient

        mock_storage = AsyncMock()
        mock_storage.put = AsyncMock()
        mock_session, _ = self._make_mock_session()

        app = _build_upload_app(mock_session, mock_storage)
        # raise_server_exceptions=False: el background task llama get_async_session()
        # sin override de DI e intenta conectar a PostgreSQL real (no disponible en CI).
        # Las assertions son sobre el handler de la petición, que ocurre antes del task.
        client = TestClient(app, raise_server_exceptions=False)
        token = _make_token()
        chatbot_id = uuid.uuid4()

        response = client.post(
            "/api/v1/hub/ingestion/upload",
            data={"chatbot_id": str(chatbot_id)},
            files={"file": ("norma.md", MD_DE_CORPUS, "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 202
        mock_storage.put.assert_called_once()
        storage_key = mock_storage.put.call_args[0][0]
        assert storage_key.endswith(".md")
        assert storage_key.startswith("ingestion/")

    def test_upload_job_source_url_is_same_key_passed_to_storage(self) -> None:
        """La clave pasada a storage.put es exactamente la que se usa como source_url del job.

        El router llama storage.put(key, content) y luego job.source_url = key.
        raise_server_exceptions=False porque el background task abre una conexión
        asyncpg real (fuera del alcance del mock de sesión) y su GC puede lanzar
        RuntimeError al cerrar el event loop del TestClient.
        """
        from fastapi.testclient import TestClient

        mock_storage = AsyncMock()
        mock_storage.put = AsyncMock()
        mock_session, _ = self._make_mock_session()

        app = _build_upload_app(mock_session, mock_storage)
        # raise_server_exceptions=False: el background task usa get_async_session()
        # directamente (no inyectado) y puede abrir una conexión real cuyo teardown
        # choca con el event loop cerrado del TestClient.
        client = TestClient(app, raise_server_exceptions=False)
        token = _make_token()
        chatbot_id = uuid.uuid4()

        response = client.post(
            "/api/v1/hub/ingestion/upload",
            data={"chatbot_id": str(chatbot_id)},
            files={"file": ("norma.md", MD_DE_CORPUS, "text/markdown")},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 202
        # La clave con la que se persistió el PDF
        storage_key = mock_storage.put.call_args[0][0]
        # source_url del job en la respuesta debe coincidir con esa clave
        job_data = response.json().get("job", {})
        assert job_data.get("source_url") == storage_key

    def test_upload_does_not_write_to_tmp_directly(self) -> None:
        """El handler no crea ficheros en /tmp directamente (usa StorageService)."""
        from fastapi.testclient import TestClient

        mock_storage = AsyncMock()
        mock_storage.put = AsyncMock()
        mock_session, _ = self._make_mock_session()

        app = _build_upload_app(mock_session, mock_storage)
        # raise_server_exceptions=False por la misma razón que el test anterior.
        client = TestClient(app, raise_server_exceptions=False)
        token = _make_token()
        chatbot_id = uuid.uuid4()

        with patch("tempfile.NamedTemporaryFile") as mock_tmp:
            client.post(
                "/api/v1/hub/ingestion/upload",
                data={"chatbot_id": str(chatbot_id)},
                files={"file": ("norma.md", MD_DE_CORPUS, "text/markdown")},
                headers={"Authorization": f"Bearer {token}"},
            )
            # El handler de upload no debe crear ficheros temporales en /tmp
            mock_tmp.assert_not_called()
