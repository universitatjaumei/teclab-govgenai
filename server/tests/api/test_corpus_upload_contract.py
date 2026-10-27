"""Tests EXT.1 — al corpus solo entra `.md` conforme al contrato.

`/hub/ingestion/upload` aceptaba un PDF y lo convertía con Docling **dentro de la petición**.
Lo que salía de ahí no tiene front-matter, ni anclas de artículo, ni estado de vigencia: es
decir, contenido que el asistente **no puede citar como norma** entrando por la misma puerta
que el corpus curado, y quedando indistinguible de él una vez dentro.

La asimetría con el contexto temporal (EXT.2) es deliberada: allí la persona tiene el
documento delante y ve si la extracción salió mal; aquí una extracción mala se convierte en
una cita errónea que no detecta nadie y que sale con la autoridad de una norma.

El pipeline de conversión vive fuera —hoy el proyecto de curación, previsiblemente plantilla
+ pandoc— y es donde está el OCR, con `origen_del_text` para declarar que un texto viene de
una transcripción automática. Ver `docs/DECISION_EXTRACCION_Y_DESPLIEGUE.md`.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# El router se importa aquí arriba y no dentro de cada test: arrastra el chunker y, con él,
# pyarrow, cuya carga nativa revienta el proceso en Windows si ocurre a mitad de la sesión de
# pytest. Lo documentan `test_tenant_isolation.py` y `test_theme_for_chatbot.py` por el mismo
# motivo, y de ahí sale también el `import server.app.main` de abajo: fija el orden de carga.
import server.app.main  # noqa: F401
from server.app.core.storage import get_storage_service
from server.app.api.deps import get_session
from server.app.routers.hub_ingestion_router import router as ingestion_router
from server.tests.dobles import almacenamiento

ORG = "00000000-0000-0000-0000-00000000dead"

_JWT_ENV = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}

# Front-matter mínimo que el contrato admite. `language` es el único campo sin default en
# `CorpusDocumentEntry`; el resto se rellena solo.
MD_VALIDO = """---
language: va
id_publicacio: REG-999
title: Reglament de prova
estat_vigencia: vigent
us_assistents: si
---

# Reglament de prova

##### Article 1. Objecte {#art-1}

Este reglament regula la prova.
"""

MD_SIN_FRONTMATTER = "# Un documento cualquiera\n\nSin front-matter.\n"

MD_QUE_INCUMPLE = """---
language: va
us_assistents: 'True'
---

# Documento con el booleano de Python en vez del vocabulario del contrato
"""


def _token(role: str = "admin") -> str:
    import os

    os.environ.update(_JWT_ENV)
    from server.app.core.auth import UserInfo, create_token

    return create_token(
        UserInfo(
            user_id="admin-1",
            email="admin@test.com",
            role=role,
            organizacion_ids=(ORG,),
        )
    )


def _app(storage=None):
    from fastapi import FastAPI

    session = AsyncMock()
    chatbot = MagicMock()
    chatbot.organizacion_id = uuid.UUID(ORG)
    session.get = AsyncMock(return_value=chatbot)
    session.scalar = AsyncMock(return_value=0)
    session.commit = AsyncMock()
    session.add = MagicMock()

    async def _refresh(obj, *_args, **_kwargs):
        """Rellena lo que en la BD real ponen los defaults del servidor.

        Sin esto la respuesta no valida contra `UploadDocumentOut` —`created_at` y los
        contadores quedan a `None`— y el 202 se convierte en un 500 que no dice nada del
        endpoint, solo del doble.
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

    session.refresh = AsyncMock(side_effect=_refresh)

    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_session] = _sesion
    app.dependency_overrides[get_storage_service] = lambda: storage or almacenamiento()
    app.include_router(ingestion_router, prefix="/api/v1")
    return app, session


def _subir(fichero: tuple, storage=None):
    from fastapi.testclient import TestClient

    app, session = _app(storage)
    with TestClient(app, raise_server_exceptions=False) as cliente:
        respuesta = cliente.post(
            "/api/v1/hub/ingestion/upload",
            data={"chatbot_id": str(uuid.uuid4())},
            files={"file": fichero},
            headers={"Authorization": f"Bearer {_token()}"},
        )
    return respuesta, session


class TestLaPuertaDelCorpus:

    def test_should_reject_a_pdf_upload_to_the_corpus_with_415(self):
        """El PDF no es que se convierta mal: es que no debe convertirse aquí."""
        respuesta, _ = _subir(("norma.pdf", b"%PDF-1.4 contenido", "application/pdf"))

        assert respuesta.status_code == 415, respuesta.text

    def test_should_tell_where_to_convert_instead_of_just_refusing(self):
        """Un 415 a secas deja a quien sube sin saber qué hacer. El mensaje tiene que
        nombrar el camino: el documento se convierte en el pipeline de curación."""
        respuesta, _ = _subir(("norma.pdf", b"%PDF-1.4 contenido", "application/pdf"))

        detalle = respuesta.text.lower()
        assert ".md" in detalle or "markdown" in detalle

    def test_should_accept_a_markdown_that_conforms_to_the_contract(self):
        almacen = AsyncMock()
        respuesta, _ = _subir(
            ("REG-999.md", MD_VALIDO.encode("utf-8"), "text/markdown"), almacen
        )

        assert respuesta.status_code == 202, respuesta.text
        almacen.put.assert_awaited_once()

    def test_should_store_the_document_as_markdown_not_as_pdf(self):
        """La clave de almacenamiento decía `.pdf` porque lo que entraba era un PDF."""
        almacen = AsyncMock()
        _subir(("REG-999.md", MD_VALIDO.encode("utf-8"), "text/markdown"), almacen)

        clave = almacen.put.await_args.args[0]
        assert clave.endswith(".md"), clave


class TestElContratoSeValidaAlSubir:
    """Validar aquí y no al procesar: un `.md` que no cumple el contrato tiene que
    rechazarse en el momento, mientras la persona está delante y sabe qué subió."""

    def test_should_reject_a_markdown_without_frontmatter(self):
        respuesta, _ = _subir(
            ("suelto.md", MD_SIN_FRONTMATTER.encode("utf-8"), "text/markdown")
        )

        assert respuesta.status_code == 422, respuesta.text

    def test_should_list_every_offending_field_not_just_the_first(self):
        """Quien prepara un documento necesita la lista completa para corregirla de una
        pasada. Es el mismo criterio que `assert_vocabulary` en la carga por CLI."""
        respuesta, _ = _subir(
            ("malo.md", MD_QUE_INCUMPLE.encode("utf-8"), "text/markdown")
        )

        assert respuesta.status_code == 422, respuesta.text
        assert "us_assistents" in respuesta.text

    def test_should_not_store_anything_when_the_contract_is_not_met(self):
        """Un documento rechazado no puede dejar el fichero en el almacén: lo que queda
        ahí sin fila en la base no lo mira nadie."""
        almacen = AsyncMock()
        _subir(("malo.md", MD_QUE_INCUMPLE.encode("utf-8"), "text/markdown"), almacen)

        almacen.put.assert_not_awaited()


class TestElCorpusYaNoPasaPorDocling:

    async def test_should_refuse_to_convert_from_the_corpus_path(self):
        """`process_source` convertía con Docling cuando no recibía `prefetched_content`.
        Ahora exigirlo es una condición, no un `if`: los cuatro llamantes ya pasaban el
        cuerpo, y que falle en vez de convertir es lo que impide que mañana se reabra la
        vía de conversión en caliente sin que nadie se dé cuenta de lo que reabre.

        (`process_user_upload`, el contexto temporal, sigue con Docling hasta EXT.2: es
        otra vía y tiene otras exigencias.)
        """
        from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher

        watcher = IngestionWatcher(session=AsyncMock(), embedding_service=MagicMock())

        with pytest.raises(ValueError, match="(?i)markdown|curación|curacion"):
            await watcher.process_source(
                "algo.pdf", uuid.uuid4(), prefetched_content=None
            )
