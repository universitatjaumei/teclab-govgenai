"""Contabilidad de tokens y cuotas en cascada (Prompt SEC.4, Partes 2 y 3).

Antes de esto no había cuota posible, solo conteo de peticiones: nadie guardaba cuántos
tokens costaba una conversación, y una petición puede costar mil veces más que otra.

Los tres puntos donde esto se rompe si no está fijado por un test:

- **`0` es «sin límite» y `None` es «heredar».** Si `0` significara «bloqueado», poner un
  límite a cero para levantar la restricción dejaría al chatbot mudo.
- **El 429 dice qué sujeto se agotó.** Un límite que no se explica es indistinguible de una
  avería para quien lo sufre.
- **La cuota se le carga al actor efectivo, no al dueño del PAT.** Si no, el cliente de
  confianza que atiende a cien personas agota la cuota de una sola.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

ORG = str(uuid.UUID("00000000-0000-0000-0000-0000000000a1"))


def _actor(subject_id: str = "persona-1", delegated: bool = False):
    from server.app.core.auth.delegated_actor import EffectiveActor

    return EffectiveActor(
        subject_id=subject_id,
        email="p@uji.es",
        role="user",
        organizacion_ids=(ORG,),
        saml_groups=(),
        delegated=delegated,
    )


def _chatbot(**cuotas):
    base = {
        "user_daily_token_quota": None,
        "chatbot_daily_token_quota": None,
        "anon_ip_daily_token_quota": None,
    }
    base.update(cuotas)
    return SimpleNamespace(id=uuid.uuid4(), organizacion_id=uuid.UUID(ORG), **base)


def _organizacion(**cuotas):
    base = {
        "default_user_daily_token_quota": None,
        "default_user_monthly_token_quota": None,
        "monthly_token_quota": None,
        "default_chatbot_daily_token_quota": None,
    }
    base.update(cuotas)
    return SimpleNamespace(id=uuid.UUID(ORG), **base)


class TestLaCascada:

    def test_should_cascade_quota_from_org_default_to_chatbot(self):
        from server.app.core.quotas import limites_aplicables

        limites = limites_aplicables(
            _actor(),
            _chatbot(),
            _organizacion(default_user_daily_token_quota=5_000),
        )

        usuario_dia = [limite for limite in limites if limite.subject_type == "user" and limite.ventana == "day"]
        assert usuario_dia and usuario_dia[0].limite == 5_000

    def test_should_let_the_chatbot_override_the_org_default(self):
        from server.app.core.quotas import limites_aplicables

        limites = limites_aplicables(
            _actor(),
            _chatbot(user_daily_token_quota=100),
            _organizacion(default_user_daily_token_quota=5_000),
        )

        usuario_dia = [limite for limite in limites if limite.subject_type == "user" and limite.ventana == "day"]
        assert usuario_dia[0].limite == 100

    def test_should_treat_zero_as_unlimited_and_none_as_inherit(self):
        """El test que evita el fallo caro: `0` levanta la restricción, no la endurece."""
        from server.app.core.quotas import limites_aplicables

        sin_limite = limites_aplicables(
            _actor(),
            _chatbot(user_daily_token_quota=0),
            _organizacion(default_user_daily_token_quota=5_000),
        )
        assert not [elemento for elemento in sin_limite if elemento.subject_type == "user"]

        heredado = limites_aplicables(
            _actor(),
            _chatbot(user_daily_token_quota=None),
            _organizacion(default_user_daily_token_quota=5_000),
        )
        assert [elemento for elemento in heredado if elemento.subject_type == "user"]

    def test_should_produce_no_limits_when_nobody_configured_any(self):
        from server.app.core.quotas import limites_aplicables

        assert limites_aplicables(_actor(), _chatbot(), _organizacion()) == []

    def test_should_only_apply_the_ip_limit_to_anonymous_traffic(self):
        """Con sesión el sujeto es la persona; limitar además por IP castigaría al NAT."""
        from server.app.core.quotas import limites_aplicables

        chatbot = _chatbot(anon_ip_daily_token_quota=1_000)

        con_sesion = limites_aplicables(_actor(), chatbot, _organizacion())
        anonimo = limites_aplicables(None, chatbot, _organizacion(), ip="1.2.3.4")

        assert not [elemento for elemento in con_sesion if elemento.subject_type == "ip"]
        assert [elemento for elemento in anonimo if elemento.subject_type == "ip"]

    def test_should_check_subjects_in_the_documented_order(self):
        """Usuario/día → usuario/mes → chatbot/día → organización/mes → IP/día."""
        from server.app.core.quotas import limites_aplicables

        limites = limites_aplicables(
            _actor(),
            _chatbot(user_daily_token_quota=1, chatbot_daily_token_quota=1,
                     anon_ip_daily_token_quota=1),
            _organizacion(default_user_monthly_token_quota=1, monthly_token_quota=1),
            ip="1.2.3.4",
        )

        assert [(limite.subject_type, limite.ventana) for limite in limites] == [
            ("user", "day"),
            ("user", "month"),
            ("chatbot", "day"),
            ("organizacion", "month"),
            ("ip", "day"),
        ]


class TestVentanas:

    def test_should_key_the_day_and_month_windows_by_calendar(self):
        from datetime import datetime, timezone

        from server.app.core.quotas import clave_de_ventana

        momento = datetime(2026, 8, 2, 13, 0, tzinfo=timezone.utc)

        assert clave_de_ventana("day", momento) == "2026-08-02"
        assert clave_de_ventana("month", momento) == "2026-08"
        assert clave_de_ventana("total", momento) == "total"


@pytest.mark.asyncio
class TestConLaBaseDeDatos:
    """Sobre la BD desechable: el UPSERT es SQL de Postgres y un doble no lo probaría."""

    async def _sesion(self, db_url):
        from server.app.modules.agents_hub.database.connection import (
            create_async_engine,
            create_session_factory,
        )

        motor = create_async_engine(db_url)
        return motor, create_session_factory(motor)

    async def test_should_upsert_usage_counter_atomically_under_concurrency(self, db_url):
        """Diez sumas concurrentes tienen que dar diez, no «alguna cosa entre una y diez».

        Es el motivo de usar `ON CONFLICT ... DO UPDATE` y no leer-sumar-escribir: con
        read-modify-write, dos respuestas simultáneas del mismo usuario se pisan el contador,
        y ese es el hueco por el que se salta una cuota.
        """
        import asyncio

        from server.app.core.quotas import consumo_de, registrar_consumo

        motor, factoria = await self._sesion(db_url)
        try:
            async def _sumar():
                async with factoria() as sesion:
                    await registrar_consumo(sesion, "user", "concurrente", "day", 10)
                    await sesion.commit()

            await asyncio.gather(*[_sumar() for _ in range(10)])

            async with factoria() as sesion:
                assert await consumo_de(sesion, "user", "concurrente", "day") == 100
        finally:
            await motor.dispose()

    async def test_should_429_chat_when_user_daily_token_quota_exceeded(self, db_url):
        from server.app.core.quotas import assert_within_quota, registrar_consumo

        motor, factoria = await self._sesion(db_url)
        try:
            actor = _actor()
            chatbot = _chatbot(user_daily_token_quota=100)

            async with factoria() as sesion:
                await registrar_consumo(sesion, "user", actor.subject_id, "day", 100)
                await sesion.commit()

                with pytest.raises(HTTPException) as exc:
                    await assert_within_quota(sesion, actor, chatbot, _organizacion())

            assert exc.value.status_code == 429
            assert exc.value.detail["code"] == "QUOTA_EXCEEDED"
        finally:
            await motor.dispose()

    async def test_should_429_chat_when_user_monthly_token_quota_exceeded(self, db_url):
        from server.app.core.quotas import assert_within_quota, registrar_consumo

        motor, factoria = await self._sesion(db_url)
        try:
            actor = _actor("persona-mes")
            async with factoria() as sesion:
                await registrar_consumo(sesion, "user", actor.subject_id, "month", 500)
                await sesion.commit()

                with pytest.raises(HTTPException) as exc:
                    await assert_within_quota(
                        sesion,
                        actor,
                        _chatbot(),
                        _organizacion(default_user_monthly_token_quota=500),
                    )

            assert exc.value.detail["window"] == "month"
        finally:
            await motor.dispose()

    async def test_should_429_chat_when_chatbot_daily_quota_exceeded(self, db_url):
        from server.app.core.quotas import assert_within_quota, registrar_consumo

        motor, factoria = await self._sesion(db_url)
        try:
            chatbot = _chatbot(chatbot_daily_token_quota=50)
            async with factoria() as sesion:
                await registrar_consumo(sesion, "chatbot", chatbot.id, "day", 50)
                await sesion.commit()

                with pytest.raises(HTTPException) as exc:
                    await assert_within_quota(sesion, _actor(), chatbot, _organizacion())

            assert exc.value.detail["subject"] == "chatbot"
        finally:
            await motor.dispose()

    async def test_should_429_when_organizacion_monthly_quota_exceeded(self, db_url):
        from server.app.core.quotas import assert_within_quota, registrar_consumo

        motor, factoria = await self._sesion(db_url)
        try:
            chatbot = _chatbot()
            async with factoria() as sesion:
                await registrar_consumo(
                    sesion, "organizacion", chatbot.organizacion_id, "month", 9_000
                )
                await sesion.commit()

                with pytest.raises(HTTPException) as exc:
                    await assert_within_quota(
                        sesion, _actor(), chatbot, _organizacion(monthly_token_quota=9_000)
                    )

            assert exc.value.detail["subject"] == "organizacion"
        finally:
            await motor.dispose()

    async def test_should_report_which_subject_exhausted_the_quota(self, db_url):
        """El cuerpo del 429 tiene que servir para actuar, no solo para saber que falló."""
        from server.app.core.quotas import assert_within_quota, registrar_consumo

        motor, factoria = await self._sesion(db_url)
        try:
            actor = _actor("persona-detalle")
            async with factoria() as sesion:
                await registrar_consumo(sesion, "user", actor.subject_id, "day", 120)
                await sesion.commit()

                with pytest.raises(HTTPException) as exc:
                    await assert_within_quota(
                        sesion, actor, _chatbot(user_daily_token_quota=100), _organizacion()
                    )

            detalle = exc.value.detail
            assert detalle == {
                "code": "QUOTA_EXCEEDED",
                "subject": "user",
                "window": "day",
                "limit": 100,
                "used": 120,
            }
            assert int(exc.value.headers["Retry-After"]) > 0
        finally:
            await motor.dispose()

    async def test_should_charge_quota_to_delegated_actor_not_pat_owner(self, db_url):
        """Integra SEC.2.1: quien gasta es quien pregunta, no la credencial que entró."""
        from server.app.core.quotas import consumo_de, contabilizar_interaccion

        motor, factoria = await self._sesion(db_url)
        try:
            delegado = _actor("persona-delegada", delegated=True)
            chatbot = _chatbot()

            async with factoria() as sesion:
                await contabilizar_interaccion(sesion, delegado, chatbot, 250)
                await sesion.commit()

                assert await consumo_de(sesion, "user", "persona-delegada", "day") == 250
                assert await consumo_de(sesion, "user", "duenyo-del-pat", "day") == 0
        finally:
            await motor.dispose()

    async def test_should_count_even_when_no_quota_is_configured(self, db_url):
        """Sin histórico no hay forma de elegir el límite el día que haga falta ponerlo."""
        from server.app.core.quotas import consumo_de, contabilizar_interaccion

        motor, factoria = await self._sesion(db_url)
        try:
            chatbot = _chatbot()
            async with factoria() as sesion:
                await contabilizar_interaccion(sesion, _actor("sin-cuota"), chatbot, 40)
                await sesion.commit()

                assert await consumo_de(sesion, "user", "sin-cuota", "day") == 40
                assert await consumo_de(sesion, "chatbot", chatbot.id, "total") == 40
        finally:
            await motor.dispose()

    async def test_should_let_a_request_through_below_the_limit(self, db_url):
        from server.app.core.quotas import assert_within_quota, registrar_consumo

        motor, factoria = await self._sesion(db_url)
        try:
            actor = _actor("persona-holgada")
            async with factoria() as sesion:
                await registrar_consumo(sesion, "user", actor.subject_id, "day", 99)
                await sesion.commit()

                await assert_within_quota(
                    sesion, actor, _chatbot(user_daily_token_quota=100), _organizacion()
                )  # no lanza
        finally:
            await motor.dispose()


class TestLaFronteraEdgeCloud:

    def test_should_keep_the_counter_out_of_the_config_tables(self):
        """Un contador en una tabla de configuración se sincronizaría al cloud (P8)."""
        from server.app.modules.agents_hub.database.base import HubOperationalBase
        from server.app.modules.agents_hub.database.config_models import (
            HubChatbot,
            HubOrganizacion,
        )
        from server.app.modules.agents_hub.database.operational_models import HubUsageCounter

        assert issubclass(HubUsageCounter, HubOperationalBase)

        for modelo in (HubChatbot, HubOrganizacion):
            contadores = [
                c.name
                for c in modelo.__table__.columns
                if c.name.endswith(("_used", "_consumed", "_tokens_spent"))
            ]
            assert not contadores, (
                f"{modelo.__name__} lleva contadores de consumo: {contadores}. Son datos "
                "operacionales del cliente y no pueden viajar con la configuración."
            )


class TestElUnicoPuntoDeDecision:

    SUPERFICIES = (
        "app/api/v1/hub_chat.py",
        "app/api/v1/openai_compat.py",
        "app/api/v1/widget_chat.py",
    )

    def test_should_route_every_conversation_surface_through_assert_within_quota(self):
        from pathlib import Path

        sin_cuota = [
            ruta
            for ruta in self.SUPERFICIES
            if Path(ruta).is_file()
            and "assert_within_quota" not in Path(ruta).read_text(encoding="utf-8")
        ]
        assert not sin_cuota, (
            f"estas superficies invocan al modelo sin comprobar cuota: {sin_cuota}"
        )


class TestContabilidadEnLaInteraccion:
    """Los tokens que se guardan con la conversación (Parte 2).

    Van en el MISMO commit que la `HubInteraction` y no en un segundo write: separarlos
    dejaría, ante un fallo entre los dos, respuestas servidas sin contabilizar —o contadas
    sin servir—, y la cuota dejaría de cuadrar con lo que la persona ha recibido.
    """

    def test_should_read_the_usage_the_provider_declares(self):
        from types import SimpleNamespace

        from server.app.api.v1.hub_chat import _uso_del_evento

        evento = {
            "data": {
                "output": SimpleNamespace(
                    usage_metadata={"input_tokens": 120, "output_tokens": 45}
                )
            }
        }
        assert _uso_del_evento(evento) == (120, 45)

    def test_should_also_read_the_older_response_metadata_shape(self):
        """El proveedor se elige por configuración: no se puede saber cuál responderá."""
        from types import SimpleNamespace

        from server.app.api.v1.hub_chat import _uso_del_evento

        evento = {
            "data": {
                "output": SimpleNamespace(
                    usage_metadata=None,
                    response_metadata={
                        "token_usage": {"prompt_tokens": 7, "completion_tokens": 3}
                    },
                )
            }
        }
        assert _uso_del_evento(evento) == (7, 3)

    def test_should_report_nothing_when_the_provider_is_silent(self):
        from types import SimpleNamespace

        from server.app.api.v1.hub_chat import _uso_del_evento

        vacio = SimpleNamespace(usage_metadata=None, response_metadata={})
        assert _uso_del_evento({"data": {"output": vacio}}) == (0, 0)

    def test_should_mark_usage_source_when_estimated(self):
        """Una cuota apoyada en una estimación **silenciosa** no se puede defender.

        Se comprueba sobre el código del endpoint porque el valor se escribe en el mismo
        sitio donde se decide estimarlo, y separarlos para poder probarlo inventaría una
        indirección que solo existiría para el test.
        """
        from pathlib import Path

        texto = Path("app/api/v1/hub_chat.py").read_text(encoding="utf-8")

        assert "usage_source" in texto
        assert '"estimated"' in texto
        assert '"provider"' in texto

    def test_should_persist_prompt_and_completion_tokens_on_interaction(self):
        from server.app.modules.agents_hub.database.operational_models import HubInteraction

        columnas = HubInteraction.__table__.c
        assert "prompt_tokens" in columnas
        assert "completion_tokens" in columnas
        # Nullable: lo histórico no tiene el dato, y un cero diría «no gastó nada».
        assert columnas["prompt_tokens"].nullable
        assert columnas["completion_tokens"].nullable

    def test_should_estimate_by_length_when_nothing_else_is_available(self):
        from server.app.api.v1.hub_chat import _tokens_estimados

        assert _tokens_estimados("") == 0
        assert _tokens_estimados("a" * 400) == 100


class TestElEndpointDeConsumo:
    """`GET /hub/usage/me`: sin esto, un 429 es indistinguible de una avería."""

    def _app(self, actor_orgs, chatbot, organizacion):
        from fastapi import FastAPI

        from server.app.api.deps import get_current_user
        from server.app.api.v1.hub_usage import router
        from server.app.core.auth.models import UserInfo
        from server.app.modules.agents_hub.database.connection import get_async_session

        class _Sesion:
            """Doble mínimo: `get` por tipo y `execute` devolviendo el contador pedido."""

            def __init__(self, consumido):
                self.consumido = consumido

            async def get(self, modelo, clave):
                return chatbot if modelo.__name__ == "HubChatbot" else organizacion

            async def execute(self, _sentencia):
                from unittest.mock import MagicMock

                resultado = MagicMock()
                resultado.scalars.return_value.first.return_value = self.consumido
                return resultado

        async def _sesion():
            yield _Sesion(30)

        app = FastAPI()
        app.dependency_overrides[get_current_user] = lambda: UserInfo(
            user_id="persona-1", email="p@uji.es", role="user", organizacion_ids=actor_orgs
        )
        app.dependency_overrides[get_async_session] = _sesion
        app.include_router(router, prefix="/api/v1")
        return app

    def test_should_return_remaining_quota_on_usage_me(self):
        from fastapi.testclient import TestClient

        chatbot = _chatbot(user_daily_token_quota=100)
        chatbot.access_mode = "authenticated"
        chatbot.allowed_roles = []
        chatbot.allowed_saml_groups = []

        cliente = TestClient(self._app((ORG,), chatbot, _organizacion()))
        respuesta = cliente.get(f"/api/v1/hub/usage/me?chatbot_id={chatbot.id}")

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["actor"] == "persona-1"
        assert cuerpo["delegated"] is False
        assert cuerpo["quotas"] == [
            {"subject": "user", "window": "day", "limit": 100, "used": 30, "remaining": 70}
        ]

    def test_should_not_reveal_the_quotas_of_a_chatbot_you_cannot_use(self):
        """La frontera de acceso vale también aquí: la configuración de cuotas de otra
        organización dice cuánto se gasta y cuánta gente la usa."""
        from fastapi.testclient import TestClient

        chatbot = _chatbot()
        chatbot.access_mode = "authenticated"
        chatbot.allowed_roles = []
        chatbot.allowed_saml_groups = []

        ajena = (str(uuid.UUID("00000000-0000-0000-0000-0000000000b2")),)
        cliente = TestClient(self._app(ajena, chatbot, _organizacion()))

        respuesta = cliente.get(f"/api/v1/hub/usage/me?chatbot_id={chatbot.id}")
        assert respuesta.status_code == 403


class TestLaIpNoSeGuardaEnClaro:
    """#250 — el contador del anónimo del widget guardaba su IP tal cual, una fila por IP y día.

    Una IP es dato personal, y para contar una cuota diaria no hace falta saber cuál es: basta
    con reconocer la misma el mismo día. Así que el sujeto es una **huella con clave y con el
    día dentro**: la misma IP da la misma huella todo el día y otra al siguiente, y sin el
    secreto del servidor no se puede ir de la huella a la IP probando las cuatro mil millones
    que hay.
    """

    def test_should_give_the_same_fingerprint_to_the_same_ip_on_the_same_day(self):
        from datetime import datetime, timezone

        from server.app.core.quotas import huella_de_ip

        mañana = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
        noche = datetime(2026, 10, 9, 22, 0, tzinfo=timezone.utc)

        assert huella_de_ip("1.2.3.4", mañana) == huella_de_ip("1.2.3.4", noche)
        assert huella_de_ip("1.2.3.4", mañana) != huella_de_ip("1.2.3.5", mañana)

    def test_should_change_the_fingerprint_from_one_day_to_the_next(self):
        """Sin esto, la huella seguiría a la misma persona día tras día."""
        from datetime import datetime, timezone

        from server.app.core.quotas import huella_de_ip

        hoy = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
        mañana = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)

        assert huella_de_ip("1.2.3.4", hoy) != huella_de_ip("1.2.3.4", mañana)

    def test_should_not_be_recoverable_without_the_server_secret(self):
        """Un hash sin clave se deshace probando todas las IPv4: hacen falta minutos."""
        import hashlib
        from datetime import datetime, timezone

        from server.app.core.quotas import huella_de_ip

        dia = datetime(2026, 10, 9, tzinfo=timezone.utc)
        huella = huella_de_ip("1.2.3.4", dia)

        assert "1.2.3.4" not in huella
        for sin_clave in ("1.2.3.4", "2026-10-09:1.2.3.4", "cuota-ip:2026-10-09:1.2.3.4"):
            assert hashlib.sha256(sin_clave.encode()).hexdigest()[: len(huella)] != huella

    def test_should_never_put_the_ip_in_the_limit_subject(self):
        from server.app.core.quotas import limites_aplicables

        limites = limites_aplicables(
            None, _chatbot(anon_ip_daily_token_quota=1_000), _organizacion(), ip="1.2.3.4"
        )
        del_ip = [limite for limite in limites if limite.subject_type == "ip"]

        assert del_ip and all("1.2.3.4" not in limite.subject_id for limite in del_ip)


@pytest.mark.asyncio
class TestLaIpNoSeGuardaEnClaroEnLaBase:
    async def test_should_count_and_block_the_same_ip_without_storing_it(self, db_url):
        """De punta a punta: se acumula, bloquea, y en la tabla no queda la IP."""
        from sqlalchemy import select

        from server.app.core.quotas import assert_within_quota, contabilizar_interaccion
        from server.app.modules.agents_hub.database.connection import (
            create_async_engine,
            create_session_factory,
        )
        from server.app.modules.agents_hub.database.operational_models import HubUsageCounter

        motor = create_async_engine(db_url)
        factoria = create_session_factory(motor)
        chatbot = _chatbot(anon_ip_daily_token_quota=100)
        try:
            async with factoria() as sesion:
                await contabilizar_interaccion(sesion, None, chatbot, 150, ip="203.0.113.7")
                await sesion.commit()

                with pytest.raises(HTTPException) as agotada:
                    await assert_within_quota(
                        sesion, None, chatbot, _organizacion(), ip="203.0.113.7"
                    )
                assert agotada.value.detail["subject"] == "ip"

                # Otra IP no hereda lo gastado por la primera.
                await assert_within_quota(
                    sesion, None, chatbot, _organizacion(), ip="203.0.113.8"
                )

                sujetos = (
                    await sesion.execute(
                        select(HubUsageCounter.subject_id).where(
                            HubUsageCounter.subject_type == "ip"
                        )
                    )
                ).scalars().all()
                assert sujetos and not [s for s in sujetos if "203.0.113" in s]
        finally:
            await motor.dispose()


def test_hay_una_migracion_que_borra_las_ips_ya_guardadas():
    """El código nuevo no guarda IPs, pero las que ya estaban seguirían ahí sin plazo."""
    from pathlib import Path

    versiones = Path(__file__).resolve().parents[2] / "migrations" / "versions"
    assert any(
        "#250" in texto and "DELETE FROM hub_usage_counters WHERE subject_type = 'ip'" in texto
        for texto in (f.read_text(encoding="utf-8") for f in versiones.glob("*.py"))
    )
