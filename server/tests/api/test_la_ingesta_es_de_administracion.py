"""Escribir en el corpus de un chatbot es administración, no pertenencia a la organización.

El router de ingesta comprobaba la organización del chatbot y nada más, así que cualquier
persona de la organización —un `user` aprovisionado al entrar con la cuenta institucional—
podía subir, sustituir y borrar documentos y vaciar el corpus entero. `validar_vigencia` ya
estaba reservado a administración; las escrituras, que hacen más daño, no.

Lo que se fija aquí es el comportamiento observable: un 403 **antes** de tocar la base, y que
un administrador de la organización sigue pudiendo.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from server.app.core.auth.models import UserInfo
from server.app.routers.hub_ingestion_router import router as ingestion_router
from server.tests.dobles import almacenamiento

ORG = str(uuid.UUID("00000000-0000-0000-0000-0000000000a1"))
CHATBOT = uuid.UUID("00000000-0000-0000-0000-00000000c0c0")
DOC = uuid.UUID("00000000-0000-0000-0000-00000000d0c0")
JOB = uuid.UUID("00000000-0000-0000-0000-00000000a0b0")
MD = b"---\nlanguage: es\n---\n\n# Norma\n\nTexto.\n"


def _persona(role: str) -> UserInfo:
    return UserInfo(user_id=f"{role}-1", email=f"{role}@uji.es", role=role, organizacion_ids=(ORG,))


def _sesion():
    session = MagicMock()
    session.get = AsyncMock(
        return_value=SimpleNamespace(id=CHATBOT, organizacion_id=uuid.UUID(ORG), chatbot_id=CHATBOT)
    )
    resultado = MagicMock()
    resultado.scalars.return_value.all.return_value = []
    resultado.scalar_one_or_none = MagicMock(return_value=None)
    session.execute = AsyncMock(return_value=resultado)
    session.commit = AsyncMock()
    session.delete = AsyncMock()
    session.add = MagicMock()
    session.refresh = AsyncMock()
    return session


def _cliente(principal: UserInfo, session):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from server.app.api.deps import get_current_user
    from server.app.core.storage import get_storage_service
    from server.app.api.deps import get_session

    async def _s():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_session] = _s
    app.dependency_overrides[get_storage_service] = lambda: almacenamiento()
    app.include_router(ingestion_router, prefix="/api/v1")
    return TestClient(app, raise_server_exceptions=False)


BASE = f"/api/v1/hub/ingestion/{CHATBOT}"

ESCRITURAS = [
    ("delete", f"{BASE}/chunks", {}),
    ("delete", f"{BASE}/documents/{DOC}", {}),
    ("delete", f"{BASE}/jobs/{JOB}", {}),
    (
        "post",
        "/api/v1/hub/ingestion/upload",
        {"data": {"chatbot_id": str(CHATBOT)}, "files": {"file": ("norma.md", MD, "text/markdown")}},
    ),
]


class TestUnaPersonaSinAdministracionNoEscribeEnElCorpus:

    @pytest.mark.parametrize(
        ("metodo", "ruta", "extra"), ESCRITURAS, ids=["vaciar", "borrar", "borrar-trabajo", "subir"]
    )
    @pytest.mark.parametrize("role", ["user", "informer"])
    def test_should_refuse_before_touching_the_database(self, metodo, ruta, extra, role):
        session = _sesion()

        respuesta = getattr(_cliente(_persona(role), session), metodo)(ruta, **extra)

        assert respuesta.status_code == 403, respuesta.text
        session.execute.assert_not_awaited()
        session.commit.assert_not_awaited()

    @pytest.mark.parametrize("role", ["user", "informer"])
    def test_should_refuse_the_html_analysis_too(self, role):
        """Invoca el modelo con HTML arbitrario: gasto de la organización a cuenta de cualquiera."""
        respuesta = _cliente(_persona(role), _sesion()).post(
            "/api/v1/hub/ingestion/analyze-html", json={"html": "<p>x</p>", "url": "https://a.es"}
        )

        assert respuesta.status_code == 403, respuesta.text


class TestUnAdministradorSigueEscribiendo:

    @pytest.mark.parametrize("role", ["admin", "superadmin"])
    def test_should_let_an_administrator_empty_the_collection(self, role):
        session = _sesion()

        respuesta = _cliente(_persona(role), session).delete(f"{BASE}/chunks")

        assert respuesta.status_code != 403, respuesta.text
        session.execute.assert_awaited()
