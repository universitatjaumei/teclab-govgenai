"""HIB.H — la revisión deja una referencia reutilizable, no sólo un veredicto.

REV.1 dio a `hub_interactions` el veredicto de quien revisa: `good`/`bad`/`mixed`, con nota,
firma y fecha. Eso permite reformular la FAQ que produjo una mala respuesta, pero no permite
**volver a medir**: cada consulta revisada vale una vez, y la siguiente ablación —reranker sí o
no, padre sí o no, otro umbral— exige pedir de nuevo juicio humano sobre las mismas preguntas.
Es la razón concreta por la que las ablaciones no se hacían.

Con la fuente esperada estructurada al lado del veredicto, tres cosas se calculan solas para
siempre (`escenario_metricas.py`): si el documento que el informador esperaba entró en lo
recuperado, si el ancla de la cita abre el artículo correcto, y si un negativo se rechazó como
debía. Y el piloto pasa a producir **juicios de relevancia**, que es la forma que necesita tener
un banco de recuperación publicable.

Una decisión de forma que se prueba aquí: el mismo esquema para `hub_interactions` y para
`hub_test_scenarios`, validado por el mismo modelo Pydantic. Dos formas para la misma idea
divergen, y entonces el instrumental que cruza conversaciones reales con escenarios de prueba
deja de poder escribirse.

Deploy: edge
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-at-least-32-chars-long")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRATION_MINUTES", "60")

ORG = uuid.UUID("00000000-0000-0000-0000-0000000000b1")
URL_NORMA = "https://www.uji.es/norma/permanencia"


def _token(role: str = "admin") -> str:
    from server.app.core.auth import UserInfo, create_token

    return create_token(
        UserInfo(
            user_id="revisor-1",
            email="revisor@test.com",
            role=role,
            organizacion_ids=(str(ORG),),
        )
    )


def _interaccion(**kw):
    m = MagicMock()
    m.id = kw.get("id", uuid.uuid4())
    m.chatbot_id = kw.get("chatbot_id", uuid.uuid4())
    m.user_id = kw.get("user_id", "estudiant-3")
    m.user_message = kw.get("user_message", "Quants credits he de superar?")
    m.assistant_message = kw.get("assistant_message", "El 20%.")
    m.feedback_score = None
    m.feedback_text = None
    m.run_id = None
    m.review_verdict = kw.get("review_verdict", None)
    m.review_note = None
    m.review_by = None
    m.review_at = None
    m.review_expected_sources = kw.get("review_expected_sources", None)
    m.review_reference_answer = kw.get("review_reference_answer", None)
    m.created_at = datetime.now(timezone.utc)
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


def _peticion(**extra) -> dict:
    base = {"verdict": "good", "note": "Cita el articulo correcto"}
    base.update(extra)
    return base


class TestElModeloGuardaLaSolucion:

    def test_should_default_to_no_annotation(self):
        """Nulo es «no anotado», y no una lista vacía.

        Una lista vacía afirmaría que el informador miró y decidió que no hay fuente
        esperada, que es una cosa distinta de que nadie lo haya mirado. La diferencia
        importa al agregar: el denominador de «cuántas están anotadas» sale de aquí.
        """
        from server.app.modules.agents_hub.database.operational_models import HubInteraction

        interaccion = HubInteraction(
            chatbot_id=uuid.uuid4(),
            user_id="u1",
            user_message="p",
            assistant_message="r",
        )

        assert interaccion.review_expected_sources is None
        assert interaccion.review_reference_answer is None

    def test_should_offer_the_same_shape_on_the_test_scenario(self):
        """Un solo esquema para las dos tablas."""
        from server.app.modules.agents_hub.database.operational_models import (
            HubTestScenario,
        )

        escenario = HubTestScenario(
            chatbot_id=uuid.uuid4(), name="ORI-01", prompt="Quants credits?"
        )

        assert escenario.expected_sources is None
        # `expectation_note` no se sustituye: es la nota que lee quien juzga.
        assert hasattr(escenario, "expectation_note")


class TestElEndpointGuardaLaFuenteEsperada:

    def test_should_store_expected_sources_with_required_and_acceptable(self):
        interaccion = _interaccion()
        session = AsyncMock()
        session.get = AsyncMock(side_effect=[interaccion, _chatbot()])

        client = TestClient(_app(session))
        resp = client.patch(
            f"/api/v1/hub/feedback/interactions/{interaccion.id}/review",
            json=_peticion(
                expected_sources={
                    "required": [{"canonical_url": URL_NORMA, "anchor": "art-4"}],
                    "acceptable": [
                        {"canonical_url": "https://www.uji.es/norma/grado"}
                    ],
                },
                reference_answer="El 20% del total de creditos matriculados.",
            ),
            headers={"Authorization": f"Bearer {_token()}"},
        )

        assert resp.status_code == 200, resp.text
        guardadas = interaccion.review_expected_sources
        assert guardadas["required"][0]["anchor"] == "art-4"
        assert guardadas["required"][0]["canonical_url"] == URL_NORMA
        assert len(guardadas["acceptable"]) == 1
        assert interaccion.review_reference_answer.startswith("El 20%")
        assert resp.json()["review_expected_sources"]["required"][0]["anchor"] == "art-4"

    def test_should_keep_null_when_the_reviewer_gives_no_sources(self):
        """El veredicto se puede dar sin anotar fuente: es lo que se pide de TODAS.

        La fuente esperada sólo se pide de las consultas únicas tras deduplicar, porque
        cuesta mucho más por consulta. Exigirla siempre convertiría el veredicto —que es la
        métrica primaria y tiene que ser rápido— en un formulario.
        """
        interaccion = _interaccion()
        session = AsyncMock()
        session.get = AsyncMock(side_effect=[interaccion, _chatbot()])

        client = TestClient(_app(session))
        resp = client.patch(
            f"/api/v1/hub/feedback/interactions/{interaccion.id}/review",
            json=_peticion(),
            headers={"Authorization": f"Bearer {_token()}"},
        )

        assert resp.status_code == 200, resp.text
        assert interaccion.review_expected_sources is None
        assert interaccion.review_reference_answer is None

    def test_should_reject_a_source_without_a_document_identifier(self):
        """Un ancla suelta no identifica ningún documento."""
        interaccion = _interaccion()
        session = AsyncMock()
        session.get = AsyncMock(side_effect=[interaccion, _chatbot()])

        client = TestClient(_app(session))
        resp = client.patch(
            f"/api/v1/hub/feedback/interactions/{interaccion.id}/review",
            json=_peticion(expected_sources={"required": [{"anchor": "art-4"}]}),
            headers={"Authorization": f"Bearer {_token()}"},
        )

        assert resp.status_code == 422, resp.text

    def test_should_reject_a_free_text_url_that_is_not_a_url(self):
        """La URL se elige del corpus, no se escribe.

        Una URL escrita a mano no casa con `canonical_url` y la métrica se pierde en
        silencio: la fuente esperada nunca aparece «en lo recuperado» y el fallo se lee como
        un fallo de recuperación. Se valida la forma aquí y se ofrece el selector en la UI.
        """
        interaccion = _interaccion()
        session = AsyncMock()
        session.get = AsyncMock(side_effect=[interaccion, _chatbot()])

        client = TestClient(_app(session))
        resp = client.patch(
            f"/api/v1/hub/feedback/interactions/{interaccion.id}/review",
            json=_peticion(
                expected_sources={
                    "required": [{"canonical_url": "el reglamento de permanencia"}]
                }
            ),
            headers={"Authorization": f"Bearer {_token()}"},
        )

        assert resp.status_code == 422, resp.text
