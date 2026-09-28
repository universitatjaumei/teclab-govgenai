"""REV.8 — borrar una persona, ver al superadministrador, y no quedarse sin ninguno.

Tres carencias del primer repaso del usuario a la pantalla de Personas, que son la misma
conversación:

1. **Sólo se podía desactivar.** La decisión original —«desactivar, nunca borrar: quien ya entró
   tiene rastro en interacciones, informes y concesiones»— es correcta y demasiado absoluta: una
   persona dada de alta a mano que **nunca ha entrado** no tiene rastro de nada, y hoy no había
   forma de quitarla. La regla es `last_login_at IS NULL`, que es exactamente «esta fila se creó
   a mano y no se ha usado».

2. **El superadministrador principal no aparecía.** El listado lee `hub_users` y esa cuenta vive
   en `superadminaccount`: son cuatro tablas de identidad sin unificar (IDE.2 unificó una parte)
   y el docstring de la pantalla ya lo advertía. Aquí se **muestra**, en solo lectura, en vez de
   unificarlas — eso es una migración de otro tamaño.

3. **No había regla del último superadministrador.** Desactivar al único que queda deja la
   instalación sin nadie que administre y sin forma de arreglarlo desde la propia aplicación.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import server.app.main  # noqa: F401

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo
from server.app.modules.agents_hub.database.config_models import HubModuleGrant, HubUser
from server.app.modules.agents_hub.database.connection import get_async_session
from server.app.routers.hub_users_router import router


@pytest.fixture(autouse=True)
async def _tablas_de_cuenta(db_session):
    """El listado cruza a `superadminaccount`, que es de SQLModel y no del metadata del hub."""
    from sqlmodel import SQLModel

    import server.app.database.models  # noqa: F401

    conexion = await db_session.connection()
    await conexion.run_sync(SQLModel.metadata.create_all)
    await db_session.commit()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _cliente(session, role: str = "superadmin") -> AsyncClient:
    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: UserInfo(
        user_id="quien-administra", email="root@uji.es", role=role
    )
    app.dependency_overrides[get_async_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _persona(session, *, entro: bool = False, role: str = "user", activa: bool = True):
    fila = HubUser(
        email=f"p-{_uid()}@uji.es",
        display_name="Persona de prueba",
        role=role,
        origen="manual",
        is_active=activa,
        last_login_at=datetime.now(timezone.utc) if entro else None,
    )
    session.add(fila)
    await session.commit()
    await session.refresh(fila)
    return fila


async def _superadmin_de_arranque(session, email: str | None = None):
    from server.app.core.security import hash_password
    from server.app.database.models import SuperAdminAccount

    cuenta = SuperAdminAccount(
        name="SuperAdmin de arranque",
        email=email or f"root-{_uid()}@uji.es",
        hashed_password=hash_password("x" * 12),
        is_active=True,
    )
    session.add(cuenta)
    await session.commit()
    return cuenta


class TestBorrarAQuienNuncaEntro:

    @pytest.mark.asyncio
    async def test_should_delete_a_person_who_never_logged_in(self, db_session):
        persona = await _persona(db_session, entro=False)

        async with _cliente(db_session) as cliente:
            respuesta = await cliente.delete(f"/api/v1/hub/users/{persona.id}")

        assert respuesta.status_code == 204, respuesta.text
        assert await db_session.get(HubUser, persona.id) is None

    @pytest.mark.asyncio
    async def test_should_refuse_to_delete_someone_who_has_used_the_platform(self, db_session):
        """**El test del prompt.** Quien ya entró tiene rastro en interacciones, informes y
        revisiones, y borrarlo los dejaría sin dueño. Se rechaza diciendo qué hacer en su
        lugar, que es desactivar."""
        persona = await _persona(db_session, entro=True)

        async with _cliente(db_session) as cliente:
            respuesta = await cliente.delete(f"/api/v1/hub/users/{persona.id}")

        assert respuesta.status_code == 409, respuesta.text
        # Sin la tilde en la aserción: el mensaje dice «Desactívala» y en JSON la í puede llegar
        # escapada, así que buscar «desactiv» no encuentra nada y el test fallaría por su propia
        # redacción y no por el comportamiento.
        assert "Desact" in respuesta.text
        assert await db_session.get(HubUser, persona.id) is not None

    @pytest.mark.asyncio
    async def test_should_take_the_module_grants_with_it(self, db_session):
        """Una concesión a una persona que ya no existe es una fila colgando: nadie la va a
        ver en ninguna pantalla y seguiría ahí. Se va con ella, en la misma transacción."""
        persona = await _persona(db_session, entro=False)
        db_session.add(
            HubModuleGrant(
                subject_id=str(persona.id),
                subject_type="usuario",
                module_code="informes",
            )
        )
        await db_session.commit()

        async with _cliente(db_session) as cliente:
            respuesta = await cliente.delete(f"/api/v1/hub/users/{persona.id}")

        assert respuesta.status_code == 204, respuesta.text
        quedan = (
            await db_session.execute(
                select(HubModuleGrant).where(HubModuleGrant.subject_id == str(persona.id))
            )
        ).scalars().all()
        assert quedan == []

    @pytest.mark.asyncio
    async def test_should_404_someone_who_does_not_exist(self, db_session):
        async with _cliente(db_session) as cliente:
            respuesta = await cliente.delete(f"/api/v1/hub/users/{uuid.uuid4()}")

        assert respuesta.status_code == 404

    @pytest.mark.asyncio
    async def test_should_be_reserved_to_a_superadmin(self, db_session):
        persona = await _persona(db_session, entro=False)

        async with _cliente(db_session, role="admin") as cliente:
            respuesta = await cliente.delete(f"/api/v1/hub/users/{persona.id}")

        assert respuesta.status_code == 403
        assert await db_session.get(HubUser, persona.id) is not None


class TestLaPantallaNoDecideSiSePuedeBorrar:
    """El servidor dice si cada fila se puede borrar, y por qué no.

    Es la regla de `AGENTS.md`: el frontend no calcula qué acciones están permitidas. Si el
    React decidiera «si `last_login_at` es nulo, enseña el botón», esa regla viviría en dos
    sitios y un día dirían cosas distintas.
    """

    @pytest.mark.asyncio
    async def test_should_say_that_someone_who_never_logged_in_can_be_deleted(self, db_session):
        persona = await _persona(db_session, entro=False)

        async with _cliente(db_session) as cliente:
            cuerpo = (await cliente.get("/api/v1/hub/users")).json()["personas"]

        fila = next(f for f in cuerpo if f["email"] == persona.email)
        assert fila["puede_borrarse"] is True
        assert fila["motivo_no_borrable"] is None

    @pytest.mark.asyncio
    async def test_should_say_why_someone_who_has_used_it_cannot(self, db_session):
        persona = await _persona(db_session, entro=True)

        async with _cliente(db_session) as cliente:
            cuerpo = (await cliente.get("/api/v1/hub/users")).json()["personas"]

        fila = next(f for f in cuerpo if f["email"] == persona.email)
        assert fila["puede_borrarse"] is False
        assert fila["motivo_no_borrable"]


class TestElSuperadministradorSeVe:

    @pytest.mark.asyncio
    async def test_should_list_the_bootstrap_superadmin(self, db_session):
        """No aparecía en absoluto, y es la única cuenta real de una instalación nueva."""
        cuenta = await _superadmin_de_arranque(db_session)

        async with _cliente(db_session) as cliente:
            cuerpo = (await cliente.get("/api/v1/hub/users")).json()["personas"]

        fila = next((f for f in cuerpo if f["email"] == cuenta.email), None)
        assert fila is not None, "el superadministrador de arranque tiene que verse"
        assert fila["role"] == "superadmin"

    @pytest.mark.asyncio
    async def test_should_mark_it_as_coming_from_another_table(self, db_session):
        """Enseñarla como una fila más de `hub_users` haría creer que se puede editar y
        desactivar desde aquí, y no se puede: vive en otra tabla."""
        cuenta = await _superadmin_de_arranque(db_session)

        async with _cliente(db_session) as cliente:
            cuerpo = (await cliente.get("/api/v1/hub/users")).json()["personas"]

        fila = next(f for f in cuerpo if f["email"] == cuenta.email)
        assert fila["origen"] == "superadmin"
        assert fila["puede_borrarse"] is False
        assert fila["motivo_no_borrable"]


class TestNoQuedarseSinSuperadministrador:

    @pytest.mark.asyncio
    async def test_should_refuse_to_deactivate_the_last_active_one(self, db_session):
        """Desactivar al único que queda deja la instalación sin nadie que administre y sin
        forma de arreglarlo desde la propia aplicación."""
        unico = await _persona(db_session, role="superadmin", entro=True)

        async with _cliente(db_session) as cliente:
            respuesta = await cliente.patch(
                f"/api/v1/hub/users/{unico.id}", json={"is_active": False}
            )

        assert respuesta.status_code == 409, respuesta.text
        await db_session.refresh(unico)
        assert unico.is_active is True

    @pytest.mark.asyncio
    async def test_should_allow_it_when_another_one_stays_active(self, db_session):
        uno = await _persona(db_session, role="superadmin", entro=True)
        await _persona(db_session, role="superadmin", entro=True)

        async with _cliente(db_session) as cliente:
            respuesta = await cliente.patch(
                f"/api/v1/hub/users/{uno.id}", json={"is_active": False}
            )

        assert respuesta.status_code == 200, respuesta.text

    @pytest.mark.asyncio
    async def test_should_count_the_bootstrap_account_as_one_of_them(self, db_session):
        """Si sólo se contaran las filas de `hub_users`, la cuenta de arranque no valdría y la
        regla bloquearía una desactivación perfectamente segura."""
        await _superadmin_de_arranque(db_session)
        uno = await _persona(db_session, role="superadmin", entro=True)

        async with _cliente(db_session) as cliente:
            respuesta = await cliente.patch(
                f"/api/v1/hub/users/{uno.id}", json={"is_active": False}
            )

        assert respuesta.status_code == 200, respuesta.text

    @pytest.mark.asyncio
    async def test_should_refuse_to_delete_the_last_active_one(self, db_session):
        """El mismo agujero por la otra puerta: si sólo lo vigilara el `PATCH`, se llegaría al
        mismo sitio borrando."""
        unico = await _persona(db_session, role="superadmin", entro=False)

        async with _cliente(db_session) as cliente:
            respuesta = await cliente.delete(f"/api/v1/hub/users/{unico.id}")

        assert respuesta.status_code == 409, respuesta.text
        assert await db_session.get(HubUser, unico.id) is not None
