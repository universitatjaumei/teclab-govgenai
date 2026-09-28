"""Issue #94 — una contraseña que restablece otra persona vale una sola vez.

**Lo que ya estaba, y la issue no decía.** El botón de restablecer **sí está** en el panel desde
USR.3: `puede_fijar_contrasena` viaja en cada fila de Personas y `UsuariosPage` lo pinta, con el
permiso decidido por el servidor. El texto de la issue se escribió antes y se quedó atrás.

**Lo que faltaba de verdad**, y es lo que esta issue llama «lo que hace defendible el mediado»:
no había manera de marcar una contraseña como temporal. Quien restablece **conoce una contraseña
que sigue siendo válida indefinidamente**, y eso es exactamente lo que costó el incidente del
2026-09-01: seis cuentas con el mismo secreto, cualquiera podía entrar como otro, y la atribución
de las valoraciones valía lo que valiera ese secreto.

Con la marca, ese conocimiento queda acotado a **un solo uso**: se entra con ella y lo único que
se puede hacer es cambiarla.

**Y se hace cumplir en el servidor, no en la pantalla.** Un aviso en el panel dejaría la
contraseña viva para cualquiera que llame a la API a mano — que es justo quien preocupa. El token
que se emite mientras el cambio está pendiente **no sirve para nada más**.

**Se adelanta a su disparador, y conviene que conste.** La issue decía esperar a que restablezca
alguien que no sea el mantenedor; hoy sigue siendo él. Se hace ahora porque cierra el Bloque 4, no
porque el riesgo se haya materializado.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

import contextlib


@contextlib.asynccontextmanager
async def _sesion(db_url: str):
    """Una sesión sobre la base desechable. `tests/api` no tiene fixture propia.

    `expire_on_commit=False` para poder leer el identificador después del commit sin que
    SQLAlchemy dispare una recarga perezosa fuera de su greenlet — el `MissingGreenlet` que ya
    costó un 500 en USR.4. El precio es que lo que queda en memoria deja de ser prueba de nada,
    así que **todo lo que se comprueba se lee en una sesión nueva**.
    """
    motor = create_async_engine(db_url)
    try:
        async with AsyncSession(motor, expire_on_commit=False) as sesion:
            yield sesion
    finally:
        await motor.dispose()


async def _persona(db_url: str, *, email: str, pendiente: bool = False) -> uuid.UUID:
    """Deja una persona con login local en la base y devuelve su identificador."""
    from server.app.core.security import hash_password
    from server.app.modules.agents_hub.database.config_models import HubUser

    identificador = uuid.uuid4()
    async with _sesion(db_url) as sesion:
        sesion.add(
            HubUser(
                id=identificador,
                email=email,
                display_name="Quien sea",
                role="user",
                hashed_password=hash_password("la-de-siempre"),
                is_active=True,
                origen="manual",
                debe_cambiar_contrasena=pendiente,
            )
        )
        await sesion.commit()
    return identificador


async def _leer(db_url: str, identificador: uuid.UUID):
    """La fila **desde la base**, en una sesión nueva: lo que quedó en memoria no prueba nada."""
    from server.app.modules.agents_hub.database.config_models import HubUser

    async with _sesion(db_url) as sesion:
        return await sesion.get(HubUser, identificador)


class TestRestablecerDejaLaContrasenaMarcada:

    @pytest.mark.asyncio
    async def test_el_restablecimiento_marca_el_cambio_como_pendiente(self, db_url):
        from server.app.core.auth.models import UserInfo
        from server.app.routers.hub_users_router import (
            SetPasswordRequest,
            set_usuario_password,
        )

        identificador = await _persona(db_url, email="persona@uji.es")

        async with _sesion(db_url) as sesion:
            await set_usuario_password(
                identificador,
                SetPasswordRequest(password="temporal-larga-1234"),
                user=UserInfo(user_id="admin-1", email="admin@uji.es", role="superadmin"),
                session=sesion,
            )

        despues = await _leer(db_url, identificador)
        assert despues.debe_cambiar_contrasena is True, (
            "la contraseña que fija otra persona no queda marcada, así que sigue siendo válida "
            "indefinidamente y quien la puso la conoce"
        )

    @pytest.mark.asyncio
    async def test_queda_dicho_quien_restablecio_y_cuando(self, db_url):
        """La traza: sin ella, un restablecimiento es indistinguible de un cambio propio."""
        from server.app.core.auth.models import UserInfo
        from server.app.routers.hub_users_router import (
            SetPasswordRequest,
            set_usuario_password,
        )

        identificador = await _persona(db_url, email="otra@uji.es")

        async with _sesion(db_url) as sesion:
            await set_usuario_password(
                identificador,
                SetPasswordRequest(password="temporal-larga-1234"),
                user=UserInfo(user_id="admin-1", email="admin@uji.es", role="superadmin"),
                session=sesion,
            )

        despues = await _leer(db_url, identificador)
        assert despues.password_reset_by == "admin-1"
        assert despues.password_reset_at is not None

    @pytest.mark.asyncio
    async def test_una_persona_recien_creada_no_arrastra_nada(self, db_url):
        """Sin esto, lo de arriba se cumpliría marcándolas a todas."""
        identificador = await _persona(db_url, email="recien@uji.es")

        assert (await _leer(db_url, identificador)).debe_cambiar_contrasena is False

    @pytest.mark.asyncio
    async def test_cambiarla_uno_mismo_acaba_con_el_pendiente(self, db_url):
        """El camino bueno, que es lo que impide que la marca deje la cuenta inservible."""
        from starlette.requests import Request

        from server.app.core.auth.models import UserInfo
        from server.app.routers.auth_router import (
            CambioDeContrasenaRequest,
            cambiar_mi_password,
        )

        identificador = await _persona(db_url, email="cambia@uji.es", pendiente=True)
        peticion = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/auth/me/password",
                "headers": [],
                "client": ("10.0.0.1", 1234),
            }
        )

        async with _sesion(db_url) as sesion:
            await cambiar_mi_password(
                CambioDeContrasenaRequest(
                    password_actual="la-de-siempre",
                    password_nueva="la-mia-de-verdad-1234",
                ),
                peticion,
                current_user=UserInfo(
                    user_id=str(identificador),
                    email="cambia@uji.es",
                    role="user",
                    cambio_pendiente=True,
                ),
                session=sesion,
            )

        assert (await _leer(db_url, identificador)).debe_cambiar_contrasena is False, (
            "cambiarla uno mismo no levanta el pendiente, así que la cuenta se queda encerrada "
            "en la pantalla de cambio para siempre"
        )


class TestElTokenPendienteNoSirveParaNadaMas:
    """Lo que hace que la marca signifique algo fuera de la pantalla."""

    def _app(self):
        from fastapi import Depends, FastAPI

        from server.app.api.deps import get_current_user

        app = FastAPI()

        @app.get("/api/v1/hub/chatbots")
        async def _cualquier_cosa(user=Depends(get_current_user)):
            return {"ok": True}

        @app.post("/api/v1/auth/me/password")
        async def _cambiar(user=Depends(get_current_user)):
            return {"ok": True}

        return app

    def _token(self, *, pendiente: bool) -> str:
        from server.app.core.auth.jwt_handler import create_token
        from server.app.core.auth.models import UserInfo

        return create_token(
            UserInfo(
                user_id=str(uuid.uuid4()),
                email="persona@uji.es",
                role="user",
                cambio_pendiente=pendiente,
            )
        )

    @pytest.mark.asyncio
    async def test_no_deja_llamar_a_otra_cosa(self):
        app = self._app()
        cabecera = {"Authorization": f"Bearer {self._token(pendiente=True)}"}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as cliente:
            respuesta = await cliente.get("/api/v1/hub/chatbots", headers=cabecera)

        assert respuesta.status_code == 403, (
            "con el cambio pendiente el token abre el resto de la aplicación, así que la "
            "contraseña que puso otra persona sigue sirviendo para todo"
        )

    @pytest.mark.asyncio
    async def test_si_deja_cambiar_la_contrasena(self):
        """Si bloqueara también esto, la marca dejaría la cuenta inservible."""
        app = self._app()
        cabecera = {"Authorization": f"Bearer {self._token(pendiente=True)}"}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as cliente:
            respuesta = await cliente.post("/api/v1/auth/me/password", headers=cabecera)

        assert respuesta.status_code == 200

    @pytest.mark.asyncio
    async def test_sin_cambio_pendiente_no_estorba_a_nadie(self):
        """El camino de siempre, sin el cual lo de arriba se cumpliría bloqueándolo todo."""
        app = self._app()
        cabecera = {"Authorization": f"Bearer {self._token(pendiente=False)}"}

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as cliente:
            respuesta = await cliente.get("/api/v1/hub/chatbots", headers=cabecera)

        assert respuesta.status_code == 200

    @pytest.mark.asyncio
    async def test_si_deja_preguntar_quien_soy(self):
        """Sin `/auth/me`, el panel recarga la página y no sabe ni que debe pedir el cambio."""
        from fastapi import Depends, FastAPI

        from server.app.api.deps import get_current_user

        app = FastAPI()

        @app.get("/api/v1/auth/me")
        async def _me(user=Depends(get_current_user)):
            return user.to_dict()

        cabecera = {"Authorization": f"Bearer {self._token(pendiente=True)}"}
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://t"
        ) as cliente:
            respuesta = await cliente.get("/api/v1/auth/me", headers=cabecera)

        assert respuesta.status_code == 200
        assert respuesta.json()["cambio_pendiente"] is True

    def test_un_token_viejo_no_trae_el_claim_y_no_se_bloquea(self):
        """Un token emitido antes de esto no puede quedarse fuera: se lee como «sin pendiente»."""
        from server.app.core.auth.jwt_handler import decode_token
        from server.app.core.auth.models import UserInfo
        from server.app.core.auth.jwt_handler import create_token

        viejo = create_token(UserInfo(user_id="x", email="x@uji.es", role="user"))

        assert decode_token(viejo).cambio_pendiente is False
