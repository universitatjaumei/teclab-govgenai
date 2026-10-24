"""DER.2 — borrar una norma que vive en varios asistentes.

Con el documento duplicado por chatbot (se descartó COR), borrar «la norma» es ambiguo:
puede significar quitarla de este asistente o retirarla del corpus de la organización. Son
dos cosas distintas y confundirlas es como se pierde una norma sin que nadie lo haya pedido.

**Por defecto se borra solo la copia de su chatbot.** Un borrado en cascada implícito sobre
corpus normativo no puede ser el comportamiento por defecto; pero la respuesta dice en
cuántos asistentes más está, para que quien borra sepa lo que no ha hecho.

Deploy: edge
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-at-least-32-chars-long")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRATION_MINUTES", "60")

# Import a nivel de módulo: importar el router a media sesión provoca un crash nativo de
# pyarrow en Windows (patrón documentado en `test_tenant_isolation.py`).
from server.app.routers.hub_ingestion_router import router  # noqa: E402
from server.app.api.deps import get_session

ORG = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
URL = "https://www.uji.es/normativa/instruccio-1-2019"


def _token():
    from server.app.core.auth import UserInfo, create_token

    return create_token(
        UserInfo(
            user_id="admin-1",
            email="admin@test.com",
            role="admin",
            organizacion_ids=(str(ORG),),
        )
    )


def _documento(chatbot_id, document_id=None):
    m = MagicMock()
    m.id = document_id or uuid.uuid4()
    m.chatbot_id = chatbot_id
    m.canonical_url = URL
    m.title = "Instrucció 1/2019"
    return m


def _app(session):
    async def _override():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_session] = _override
    app.include_router(router, prefix="/api/v1")
    return app


def _sesion(documento, chatbot, copias_en_otros):
    """`session.get` sirve el chatbot (autorización) y luego el documento."""
    session = AsyncMock()
    session.get = AsyncMock(side_effect=[chatbot, documento])

    hermanos = MagicMock()
    hermanos.scalars.return_value.all.return_value = list(copias_en_otros)
    # 1ª: chatbots de la organización. 2ª: copias hermanas. Las demás: borrados.
    otros_chatbots = MagicMock()
    otros_chatbots.scalars.return_value.all.return_value = [
        documento.chatbot_id,
        *[c.chatbot_id for c in copias_en_otros],
    ]
    session.execute = AsyncMock(
        side_effect=[otros_chatbots, hermanos, MagicMock(), MagicMock(), MagicMock()]
    )
    return session


class TestBorrarAvisaDeLasDemasCopias:

    def test_should_warn_how_many_chatbots_hold_the_document(self):
        bot = uuid.uuid4()
        doc = _documento(bot)
        chatbot = MagicMock(organizacion_id=ORG)
        session = _sesion(doc, chatbot, [_documento(uuid.uuid4()), _documento(uuid.uuid4())])

        client = TestClient(_app(session))
        resp = client.delete(
            f"/api/v1/hub/ingestion/{bot}/documents/{doc.id}",
            headers={"Authorization": f"Bearer {_token()}"},
        )

        assert resp.status_code == 200, resp.text
        cuerpo = resp.json()
        assert cuerpo["copias_en_otros_chatbots"] == 2
        assert len(cuerpo["chatbots_afectados"]) == 2

    def test_should_delete_only_in_this_chatbot_by_default(self):
        """Sin pedirlo explícitamente, las otras copias no se tocan."""
        bot = uuid.uuid4()
        doc = _documento(bot)
        hermana = _documento(uuid.uuid4())
        session = _sesion(doc, MagicMock(organizacion_id=ORG), [hermana])

        client = TestClient(_app(session))
        resp = client.delete(
            f"/api/v1/hub/ingestion/{bot}/documents/{doc.id}",
            headers={"Authorization": f"Bearer {_token()}"},
        )

        assert resp.json()["documentos_eliminados"] == 1

    def test_should_delete_in_all_chatbots_when_explicitly_asked(self):
        bot = uuid.uuid4()
        doc = _documento(bot)
        session = _sesion(
            doc, MagicMock(organizacion_id=ORG), [_documento(uuid.uuid4()), _documento(uuid.uuid4())]
        )

        client = TestClient(_app(session))
        resp = client.delete(
            f"/api/v1/hub/ingestion/{bot}/documents/{doc.id}?en_todos_los_chatbots=true",
            headers={"Authorization": f"Bearer {_token()}"},
        )

        assert resp.json()["documentos_eliminados"] == 3

    def test_should_report_zero_when_no_other_chatbot_holds_it(self):
        bot = uuid.uuid4()
        doc = _documento(bot)
        session = _sesion(doc, MagicMock(organizacion_id=ORG), [])

        client = TestClient(_app(session))
        resp = client.delete(
            f"/api/v1/hub/ingestion/{bot}/documents/{doc.id}",
            headers={"Authorization": f"Bearer {_token()}"},
        )

        cuerpo = resp.json()
        assert cuerpo["copias_en_otros_chatbots"] == 0
        assert cuerpo["documentos_eliminados"] == 1
