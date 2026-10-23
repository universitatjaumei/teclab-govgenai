"""Vigencia temporal y presupuesto acumulado (Prompt SEC.4.1).

Un chatbot de campaña —plazo de matrícula, convocatoria, alegaciones— tiene que caducar
solo. Hasta aquí la única palanca era que alguien se acordara de apagarlo el día que tocaba.

Lo que estos tests fijan, y no es evidente leyendo el código:

- **El estado no se guarda en ninguna columna.** Se calcula. Un flag persistido se queda
  obsoleto en cuanto pasa la fecha y obligaría a un job que lo refresque.
- **El 403 lleva el motivo y el mensaje del admin.** «El plazo terminó el 30 de septiembre»
  es una respuesta; «Forbidden» es un callejón.
- **El presupuesto lee el contador `total`**, no el diario: un techo acumulado que se
  reiniciara cada noche no sería un techo.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

# `server.app.main` primero, y no es decorativo: importar `hub_chatbots_router` a secas mata
# el proceso en Windows con `access violation` al cargar pyarrow por la cadena
# chunker→sentence_transformers→datasets. Importar la app antes fija un orden de carga que
# no lo provoca —lo mismo que hace `tests/api/hub/test_chatbots.py`—. Comprobado: sin esta
# línea, este fichero ni siquiera llega a recolectarse.
import server.app.main  # noqa: F401
from server.app.routers.hub_chatbots_router import ChatbotCreate, ChatbotRead

AHORA = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)


def _chatbot(**campos):
    base = {
        "id": uuid.uuid4(),
        "valid_from": None,
        "valid_until": None,
        "total_token_budget": None,
        "unavailable_message": "",
    }
    base.update(campos)
    return SimpleNamespace(**base)


class _SesionConGasto:
    """Doble de sesión que devuelve el acumulado pedido, sea cual sea la consulta."""

    def __init__(self, gastados: int = 0) -> None:
        self.gastados = gastados
        self.ventanas: list = []

    async def execute(self, sentencia):
        from unittest.mock import MagicMock

        # Se guarda la sentencia compilada para poder afirmar sobre la ventana consultada.
        self.ventanas.append(str(sentencia.compile(compile_kwargs={"literal_binds": True})))
        resultado = MagicMock()
        resultado.scalars.return_value.first.return_value = self.gastados
        return resultado


@pytest.mark.asyncio
class TestLaVentanaDeVigencia:

    async def test_should_allow_when_window_fields_are_null(self):
        """Comportamiento actual preservado: sin ventana, el chatbot no caduca."""
        from server.app.core.chatbot_availability import assert_chatbot_available

        await assert_chatbot_available(_SesionConGasto(), _chatbot(), AHORA)  # no lanza

    async def test_should_403_when_valid_until_in_the_past(self):
        from server.app.core.chatbot_availability import assert_chatbot_available

        caducado = _chatbot(valid_until=AHORA - timedelta(days=1))

        with pytest.raises(HTTPException) as exc:
            await assert_chatbot_available(_SesionConGasto(), caducado, AHORA)

        assert exc.value.status_code == 403
        assert exc.value.detail["code"] == "CHATBOT_UNAVAILABLE"
        assert exc.value.detail["reason"] == "expired"

    async def test_should_403_when_valid_from_in_the_future(self):
        from server.app.core.chatbot_availability import assert_chatbot_available

        futuro = _chatbot(valid_from=AHORA + timedelta(days=3))

        with pytest.raises(HTTPException) as exc:
            await assert_chatbot_available(_SesionConGasto(), futuro, AHORA)

        assert exc.value.detail["reason"] == "not_yet_open"

    async def test_should_allow_when_now_inside_window(self):
        from server.app.core.chatbot_availability import assert_chatbot_available

        abierto = _chatbot(
            valid_from=AHORA - timedelta(days=1), valid_until=AHORA + timedelta(days=1)
        )

        await assert_chatbot_available(_SesionConGasto(), abierto, AHORA)  # no lanza

    async def test_should_read_a_naive_datetime_as_utc(self):
        """Una fecha sin zona no puede tirar la comprobación con un `TypeError`.

        Postgres devuelve `timestamptz`, pero un doble o una fila escrita por otra
        herramienta pueden traerla suelta, y caerse aquí dejaría el chatbot inaccesible por
        un detalle de tipos.
        """
        from server.app.core.chatbot_availability import calcular_disponibilidad

        sin_zona = _chatbot(valid_until=datetime(2026, 8, 1, 12, 0))

        estado = await calcular_disponibilidad(_SesionConGasto(), sin_zona, AHORA)
        assert estado.state == "expired"


@pytest.mark.asyncio
class TestElPresupuestoAcumulado:

    async def test_should_403_when_total_token_budget_exhausted(self):
        from server.app.core.chatbot_availability import assert_chatbot_available

        con_techo = _chatbot(
            total_token_budget=1_000, unavailable_message="Se agotó el presupuesto."
        )

        with pytest.raises(HTTPException) as exc:
            await assert_chatbot_available(_SesionConGasto(1_000), con_techo, AHORA)

        assert exc.value.detail["reason"] == "budget_exhausted"

    async def test_should_allow_below_the_budget(self):
        from server.app.core.chatbot_availability import assert_chatbot_available

        con_techo = _chatbot(total_token_budget=1_000)

        await assert_chatbot_available(_SesionConGasto(999), con_techo, AHORA)  # no lanza

    async def test_should_use_total_window_counter_not_daily(self):
        """Un techo acumulado que se reiniciara cada noche no sería un techo."""
        from server.app.core.chatbot_availability import calcular_disponibilidad

        sesion = _SesionConGasto(10)
        await calcular_disponibilidad(sesion, _chatbot(total_token_budget=100), AHORA)

        consultada = " ".join(sesion.ventanas)
        assert "'total'" in consultada
        assert datetime.now(timezone.utc).date().isoformat() not in consultada

    async def test_should_treat_a_zero_budget_as_no_ceiling(self):
        """Mismo criterio que las cuotas de SEC.4: `0` es «sin límite», no «bloqueado»."""
        from server.app.core.chatbot_availability import assert_chatbot_available

        await assert_chatbot_available(
            _SesionConGasto(10_000), _chatbot(total_token_budget=0), AHORA
        )  # no lanza

    async def test_should_return_admin_unavailable_message_in_403_body(self):
        from server.app.core.chatbot_availability import assert_chatbot_available

        mensaje = "El plazo de matrícula terminó el 30 de septiembre."
        caducado = _chatbot(
            valid_until=AHORA - timedelta(days=1), unavailable_message=mensaje
        )

        with pytest.raises(HTTPException) as exc:
            await assert_chatbot_available(_SesionConGasto(), caducado, AHORA)

        assert exc.value.detail["message"] == mensaje

    async def test_should_send_no_message_when_the_admin_wrote_none(self):
        """Vacío es `None` en el contrato, para que el frontend ponga su texto i18n."""
        from server.app.core.chatbot_availability import assert_chatbot_available

        with pytest.raises(HTTPException) as exc:
            await assert_chatbot_available(
                _SesionConGasto(), _chatbot(valid_until=AHORA - timedelta(days=1)), AHORA
            )

        assert exc.value.detail["message"] is None


class TestEstadoDerivadoYNoAlmacenado:

    def test_should_not_persist_availability_state_in_db(self):
        """Ni `closed_reason` ni volteo de `is_active`: el estado se calcula."""
        from server.app.modules.agents_hub.database.config_models import HubChatbot

        columnas = set(HubChatbot.__table__.c.keys())
        assert "closed_reason" not in columnas
        assert "availability_state" not in columnas
        assert "tokens_used" not in columnas, (
            "el consumo es dato operacional: en una tabla de configuración se "
            "sincronizaría al cloud"
        )

    def test_should_keep_the_four_configuration_fields(self):
        from server.app.modules.agents_hub.database.config_models import HubChatbot

        columnas = set(HubChatbot.__table__.c.keys())
        assert {
            "valid_from", "valid_until", "total_token_budget", "unavailable_message"
        } <= columnas

    def test_should_expose_derived_availability_in_chatbot_read(self):
        assert "availability" in ChatbotRead.model_fields
        # De solo lectura: aceptarlo al crear dejaría al cliente declarar su propio estado.
        assert "availability" not in ChatbotCreate.model_fields

    def test_should_check_availability_after_access_and_before_quota(self):
        """El orden importa: contarle a alguien que el plazo se cerró es contarle que el
        trámite existe, y eso solo se le dice a quien podría usarlo."""
        texto = Path("app/api/v1/hub_chat.py").read_text(encoding="utf-8")

        acceso = texto.index("assert_chatbot_access(")
        disponibilidad = texto.index("assert_chatbot_available(")
        cuota = texto.index("assert_within_quota(")

        assert acceso < disponibilidad < cuota


class TestPoderQuitarLaFecha:
    """FIX.3 — `null` en la ventana significa quitar la fecha, no «no tocar».

    Con `model_dump(exclude_none=True)` a secas no había forma de reabrir un chatbot
    caducado: el cliente mandaba `valid_until: null`, el campo se descartaba y la fecha
    seguía puesta. El formulario del panel hace exactamente eso al vaciar el campo.
    """

    def _app(self, chatbot):
        from unittest.mock import AsyncMock, MagicMock

        from fastapi import FastAPI

        from server.app.api.deps import get_current_user
        from server.app.core.auth.models import UserInfo
        from server.app.api.deps import get_session
        from server.app.routers.hub_chatbots_router import router

        session = MagicMock()
        session.get = AsyncMock(return_value=chatbot)
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        resultado = MagicMock()
        resultado.scalars.return_value.first.return_value = 0
        session.execute = AsyncMock(return_value=resultado)

        async def _sesion():
            yield session

        app = FastAPI()
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            user_id="a1",
            email="a@uji.es",
            role="admin",
            organizacion_ids=(str(chatbot.organizacion_id),),
        )
        app.dependency_overrides[get_session] = _sesion
        app.include_router(router, prefix="/api/v1")
        return app, chatbot

    def _chatbot_completo(self, **campos):
        """Doble con todas las columnas, para que `ChatbotRead` valide la respuesta."""
        from unittest.mock import MagicMock

        from server.app.modules.agents_hub.database.config_models import HubChatbot
        from server.tests.dobles import completar_chatbot

        doble = MagicMock(spec=HubChatbot)
        completar_chatbot(
            doble,
            id=uuid.uuid4(),
            organizacion_id=uuid.uuid4(),
            # Las tres columnas sin default en el ORM: `completar_chatbot` las deja en None
            # —que es la verdad, no tienen default— y `ChatbotRead` las exige al responder.
            name="Bot",
            system_prompt="Eres útil.",
            llm_config_id=uuid.uuid4(),
            **campos,
        )
        return doble

    def test_should_clear_the_date_when_the_client_sends_null(self):
        from fastapi.testclient import TestClient

        caducado = self._chatbot_completo(valid_until=AHORA - timedelta(days=1))
        app, chatbot = self._app(caducado)

        respuesta = TestClient(app).patch(
            f"/api/v1/hub/chatbots/{chatbot.id}", json={"valid_until": None}
        )

        assert respuesta.status_code == 200, respuesta.text
        assert chatbot.valid_until is None, "la fecha siguió puesta: el chatbot no se reabre"

    def test_should_leave_the_date_alone_when_the_field_is_absent(self):
        """Lo que no se envía no se toca: guardar el nombre no puede borrar la ventana."""
        from fastapi.testclient import TestClient

        hasta = AHORA + timedelta(days=5)
        abierto = self._chatbot_completo(valid_until=hasta)
        app, chatbot = self._app(abierto)

        respuesta = TestClient(app).patch(
            f"/api/v1/hub/chatbots/{chatbot.id}", json={"name": "Otro nombre"}
        )

        assert respuesta.status_code == 200, respuesta.text
        assert chatbot.valid_until == hasta

    def test_should_reject_a_field_the_server_does_not_know(self):
        """El fallo que hizo invisible un servidor desactualizado: un 200 que no guarda.

        Con `extra="forbid"`, el mismo caso responde 422 y dice qué campo sobra.
        """
        from fastapi.testclient import TestClient

        app, chatbot = self._app(self._chatbot_completo())

        respuesta = TestClient(app).patch(
            f"/api/v1/hub/chatbots/{chatbot.id}",
            json={"campo_del_futuro": "algo"},
        )

        assert respuesta.status_code == 422
        assert "campo_del_futuro" in respuesta.text
