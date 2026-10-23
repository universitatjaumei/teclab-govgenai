"""REV.1 — el veredicto de quien revisa, sobre conversaciones reales.

`feedback_score`/`feedback_text` son la valoración del **usuario final**. Gerencia necesita
otra cosa: decir «esta respuesta no es adecuada» y que quede constancia de **quién** lo dijo,
para después reformular la FAQ que la produjo.

El patrón ya existe en el proyecto —`HubTestRun` tiene `verdict`/`verdict_note`/`verdict_by`
desde RAG.13— pero solo sobre escenarios de prueba, no sobre lo que se le respondió a una
persona de verdad.

Deploy: edge
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-at-least-32-chars-long")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRATION_MINUTES", "60")

ORG = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
OTRA_ORG = uuid.UUID("00000000-0000-0000-0000-0000000000b2")


def _token(role: str = "admin", orgs: tuple[str, ...] = (str(ORG),)) -> str:
    from server.app.core.auth import UserInfo, create_token

    return create_token(
        UserInfo(
            user_id="revisor-1",
            email="revisor@test.com",
            role=role,
            organizacion_ids=orgs,
        )
    )


def _interaccion(**kw):
    m = MagicMock()
    m.id = kw.get("id", uuid.uuid4())
    m.chatbot_id = kw.get("chatbot_id", uuid.uuid4())
    m.user_id = kw.get("user_id", "funcionario-7")
    m.user_message = kw.get("user_message", "¿Puedo fraccionar un contrato menor?")
    m.assistant_message = kw.get("assistant_message", "No.")
    m.feedback_score = kw.get("feedback_score", None)
    m.feedback_text = kw.get("feedback_text", None)
    m.run_id = kw.get("run_id", None)
    m.review_verdict = kw.get("review_verdict", None)
    m.review_note = kw.get("review_note", None)
    m.review_by = kw.get("review_by", None)
    m.review_at = kw.get("review_at", None)
    # HIB.H — declarados explícitamente aunque este fichero no los use: un `MagicMock` sin
    # `spec` fabrica un hijo para cualquier atributo que se le pida, así que al añadirlos al
    # modelo el contrato de salida recibía dos mocks donde promete dict y str. El fallo no
    # estaba en el código nuevo sino en una fixture que no describía la fila.
    m.review_expected_sources = kw.get("review_expected_sources", None)
    m.review_reference_answer = kw.get("review_reference_answer", None)
    m.created_at = kw.get("created_at", datetime.now(timezone.utc))
    return m


def _chatbot(organizacion_id=ORG):
    m = MagicMock()
    m.id = uuid.uuid4()
    m.organizacion_id = organizacion_id
    return m


def _app(session):
    from server.app.api.v1.hub_feedback import router
    from server.app.api.deps import get_session

    async def _override():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_session] = _override
    app.include_router(router, prefix="/api/v1")
    return app


class TestElModeloGuardaElVeredicto:

    def test_should_default_to_unreviewed(self):
        """Sin revisar es el estado por defecto, y es lo que alimenta la cola.

        `None` y no `'pending'`: un texto por defecto sería un veredicto más, y habría que
        acordarse de excluirlo en cada consulta. Nulo es «nadie ha mirado esto».
        """
        from server.app.modules.agents_hub.database.operational_models import HubInteraction

        interaccion = HubInteraction(
            chatbot_id=uuid.uuid4(),
            user_id="u1",
            user_message="p",
            assistant_message="r",
        )

        assert interaccion.review_verdict is None
        assert interaccion.review_note is None
        assert interaccion.review_by is None
        assert interaccion.review_at is None

    def test_should_use_the_same_vocabulary_as_the_test_run_verdict(self):
        """Mismos tres valores que `HubTestRun`, a propósito.

        Dos vocabularios distintos para la misma idea acaban divergiendo, y entonces un
        informe que cruce ambas fuentes deja de poder escribirse.
        """
        from server.app.modules.agents_hub.database.operational_models import HubInteraction

        restricciones = {
            c.name: str(c.sqltext)
            for c in HubInteraction.__table__.constraints
            if hasattr(c, "sqltext")
        }
        veredicto = restricciones.get("ck_interaction_review_verdict")

        assert veredicto is not None, f"Restricciones presentes: {list(restricciones)}"
        for valor in ("good", "bad", "mixed"):
            assert f"'{valor}'" in veredicto, veredicto


class TestElEndpointDeRevision:

    def test_should_record_who_reviewed_and_when(self):
        interaccion = _interaccion()
        session = AsyncMock()
        session.get = AsyncMock(side_effect=[interaccion, _chatbot()])

        client = TestClient(_app(session))
        resp = client.patch(
            f"/api/v1/hub/feedback/interactions/{interaccion.id}/review",
            json={"verdict": "good", "note": "Cita el artículo correcto"},
            headers={"Authorization": f"Bearer {_token()}"},
        )

        assert resp.status_code == 200, resp.text
        assert interaccion.review_verdict == "good"
        assert interaccion.review_note == "Cita el artículo correcto"
        assert interaccion.review_by == "revisor@test.com"
        assert interaccion.review_at is not None

    def test_should_require_a_note_when_the_verdict_is_bad(self):
        """Un «mal» sin motivo no reformula nada.

        El propósito entero de la revisión es saber **qué** había que cambiar; un veredicto
        negativo sin texto deja a quien reescribe la FAQ exactamente donde estaba.
        """
        interaccion = _interaccion()
        session = AsyncMock()
        session.get = AsyncMock(side_effect=[interaccion, _chatbot()])

        client = TestClient(_app(session))
        resp = client.patch(
            f"/api/v1/hub/feedback/interactions/{interaccion.id}/review",
            json={"verdict": "bad"},
            headers={"Authorization": f"Bearer {_token()}"},
        )

        assert resp.status_code == 422, resp.text
        assert interaccion.review_verdict is None

    def test_should_serialize_run_id_when_the_interaction_has_one(self):
        """Toda conversación real tiene `run_id` (es el `interaction_id` del chat, RAG.2);
        los tests anteriores lo dejan en `None` por defecto y por eso no vieron esto.

        `HubInteraction.run_id` es UUID en la base de datos; `InteractionReviewOut.run_id`
        es `str` (mismo contrato que el GET, que hace `str(i.run_id)` a mano). Sin esa
        conversión, FastAPI intenta servir un UUID donde promete un string y la
        serialización de la respuesta revienta con 500 -- después de escribir ya el
        veredicto en la fila, que es lo que hace este fallo especialmente traicionero: la
        revisión SÍ queda grabada aunque quien revisa vea un error.
        """
        interaccion = _interaccion(run_id=uuid.uuid4())
        session = AsyncMock()
        session.get = AsyncMock(side_effect=[interaccion, _chatbot()])

        client = TestClient(_app(session))
        resp = client.patch(
            f"/api/v1/hub/feedback/interactions/{interaccion.id}/review",
            json={"verdict": "good"},
            headers={"Authorization": f"Bearer {_token()}"},
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["run_id"] == str(interaccion.run_id)

    def test_should_forbid_reviewing_an_interaction_of_another_organization(self):
        """La guarda de SEC.8.1. Estas conversaciones llevan preguntas de personas
        identificadas: leerlas ya era grave, anotarlas lo es igual."""
        interaccion = _interaccion()
        session = AsyncMock()
        session.get = AsyncMock(side_effect=[interaccion, _chatbot(organizacion_id=OTRA_ORG)])

        client = TestClient(_app(session))
        resp = client.patch(
            f"/api/v1/hub/feedback/interactions/{interaccion.id}/review",
            json={"verdict": "good"},
            headers={"Authorization": f"Bearer {_token()}"},
        )

        assert resp.status_code == 403, resp.text
        assert interaccion.review_verdict is None

    def test_should_return_404_for_an_unknown_interaction(self):
        session = AsyncMock()
        session.get = AsyncMock(return_value=None)

        client = TestClient(_app(session))
        resp = client.patch(
            f"/api/v1/hub/feedback/interactions/{uuid.uuid4()}/review",
            json={"verdict": "good"},
            headers={"Authorization": f"Bearer {_token()}"},
        )

        assert resp.status_code == 404, resp.text


class TestLaColaDeRevision:

    @pytest.mark.asyncio
    async def test_should_list_only_pending_interactions_by_default(self):
        """Por defecto, lo que falta por mirar — no todo el historial.

        Se comprueba sobre el SQL generado y no sobre filas, porque lo que se está fijando
        es que el filtro viaja a la base: filtrar en Python daría el mismo resultado con 50
        filas y ninguno con 50.000.
        """
        from server.app.modules.agents_hub.services.feedback_service import FeedbackService

        session = AsyncMock()
        resultado = MagicMock()
        resultado.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=resultado)

        await FeedbackService(session).get_interactions_for_review(chatbot_id=uuid.uuid4())

        sql = str(session.execute.await_args.args[0])
        assert "review_verdict IS NULL" in sql, sql

    @pytest.mark.asyncio
    async def test_should_list_everything_when_asked_for_all(self):
        from server.app.modules.agents_hub.services.feedback_service import FeedbackService

        session = AsyncMock()
        resultado = MagicMock()
        resultado.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=resultado)

        await FeedbackService(session).get_interactions_for_review(
            chatbot_id=uuid.uuid4(), review_status="all"
        )

        sql = str(session.execute.await_args.args[0])
        assert "review_verdict IS NULL" not in sql, sql

    @pytest.mark.asyncio
    async def test_should_filter_by_verdict(self):
        from server.app.modules.agents_hub.services.feedback_service import FeedbackService

        session = AsyncMock()
        resultado = MagicMock()
        resultado.scalars.return_value.all.return_value = []
        session.execute = AsyncMock(return_value=resultado)

        await FeedbackService(session).get_interactions_for_review(
            chatbot_id=uuid.uuid4(), review_status="reviewed", verdict="bad"
        )

        sql = str(session.execute.await_args.args[0])
        assert "review_verdict = " in sql, sql

    def test_should_serve_the_review_fields_to_the_page(self):
        """Lo que la pantalla tabula y exporta sale del contrato, no de campos redeclarados
        a mano en el frontend (CAL.2)."""
        from server.app.api.v1.hub_feedback import InteractionReviewOut

        campos = InteractionReviewOut.model_fields
        for campo in ("review_verdict", "review_note", "review_by", "review_at"):
            assert campo in campos, list(campos)
