"""IDE.3 — dar de alta a una persona, y que el SSO la reconozca en vez de crearla.

Hoy una persona solo existe si entra por SSO, y entra con el rol que resuelva la aserción —por
defecto `user`—. Promocionar a alguien exige un `UPDATE` a mano en Postgres, que es justo lo que
no se le puede pedir a otra administración que despliegue esto. Con IDE.1 el rol ya sobrevive al
siguiente inicio de sesión; falta poder ponerlo **antes** de que la persona entre.

Si el alta manual crea la fila primero, el ACS **la encuentra** por correo en vez de crearla, y
la persona entra con el rol que le pusieron. Eso es exactamente lo que pidió el usuario: «dar
usuarios con roles manualmente y que el SSO se utilice para identificar a los usuarios».

Tres cosas que se leen mal si no están dichas:

- **El alta no crea contraseña.** Crea la identidad y sus permisos; quien entra, entra por SSO.
  La ausencia se lee como un olvido si no está explicada, así que el contrato **rechaza** un
  campo de contraseña en vez de ignorarlo en silencio.
- **El correo es la clave del reencuentro**, así que se normaliza al guardar y al buscar.
  `Persona@Example.ORG` y `persona@example.org` tienen que ser la misma persona, o el alta
  manual no sirve.
- **`is_active = false` niega la entrada**, no solo oculta la fila del listado. La columna
  existía desde AUTH.2 y **nadie la miraba**: una persona desactivada seguía entrando.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import server.app.main  # noqa: F401

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo
from server.app.modules.agents_hub.database.connection import get_async_session
from server.app.routers.hub_users_router import router


@pytest.fixture(autouse=True)
async def _tablas_de_cuenta(db_session):
    """`db_session` trae las tablas del hub y no las de SQLModel, a propósito.

    Pero `resolve_session` consulta `superadminaccount` y `adminaccount` antes de mirar
    `hub_users` —el orden de precedencia de AUTH.2—, así que este fichero cruza esa frontera y
    le toca traerlas. Sin esto el fallo llega como `UndefinedTableError` y parece de la lógica
    que se está probando.
    """
    from sqlmodel import SQLModel

    import server.app.database.models  # noqa: F401

    conexion = await db_session.connection()
    await conexion.run_sync(SQLModel.metadata.create_all)
    await db_session.commit()


def _uid() -> str:
    return uuid.uuid4().hex[:12]


def _principal(role: str = "superadmin") -> UserInfo:
    return UserInfo(user_id="quien-administra", email="root@uji.es", role=role)


def _cliente(session, principal: UserInfo) -> AsyncClient:
    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_async_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _entrar_por_sso(session, email: str, attributes: dict | None = None):
    from server.app.core.auth.saml.identity_service import SamlIdentityService

    return await SamlIdentityService(session).resolve_session(
        nameid=email, attributes={"mail": [email], **(attributes or {})}
    )


async def _fila(session, email: str):
    from sqlalchemy import select

    from server.app.modules.agents_hub.database.config_models import HubUser

    return (
        await session.execute(select(HubUser).where(HubUser.email == email))
    ).scalars().first()


# ───────────────────────── El alta manual ─────────────────────────


class TestElAltaManual:

    @pytest.mark.asyncio
    async def test_should_create_a_person_with_the_role_it_was_given(self, db_session):
        email = f"alta-{_uid()}@uji.es"

        async with _cliente(db_session, _principal()) as cliente:
            respuesta = await cliente.post(
                "/api/v1/hub/users", json={"email": email, "role": "admin"}
            )

        assert respuesta.status_code == 201, respuesta.text
        cuerpo = respuesta.json()
        assert cuerpo["email"] == email
        assert cuerpo["role"] == "admin"
        assert cuerpo["origen"] == "manual"

    @pytest.mark.asyncio
    async def test_should_record_who_created_it(self, db_session):
        """`HubModuleGrant` ya lleva `granted_by` con el argumento escrito —«un permiso sin
        autoría no se puede auditar»—. Un alta tampoco."""
        email = f"autoria-{_uid()}@uji.es"

        async with _cliente(db_session, _principal()) as cliente:
            await cliente.post("/api/v1/hub/users", json={"email": email, "role": "user"})

        fila = await _fila(db_session, email)
        assert fila.created_by == "quien-administra"
        assert fila.created_at is not None

    @pytest.mark.asyncio
    async def test_should_refuse_a_password_field_instead_of_ignoring_it(self, db_session):
        """Rechazar y no ignorar: un campo aceptado en silencio hace creer que se guardó una
        credencial que no existe."""
        async with _cliente(db_session, _principal()) as cliente:
            respuesta = await cliente.post(
                "/api/v1/hub/users",
                json={"email": f"pwd-{_uid()}@uji.es", "role": "user", "password": "x" * 20},
            )

        assert respuesta.status_code == 422

    @pytest.mark.asyncio
    async def test_should_refuse_a_role_that_is_not_a_role(self, db_session):
        async with _cliente(db_session, _principal()) as cliente:
            respuesta = await cliente.post(
                "/api/v1/hub/users", json={"email": f"rol-{_uid()}@uji.es", "role": "jefe"}
            )

        assert respuesta.status_code == 422

    @pytest.mark.asyncio
    async def test_should_refuse_a_second_person_with_the_same_email(self, db_session):
        email = f"repe-{_uid()}@uji.es"

        async with _cliente(db_session, _principal()) as cliente:
            primera = await cliente.post("/api/v1/hub/users", json={"email": email})
            segunda = await cliente.post("/api/v1/hub/users", json={"email": email})

        assert primera.status_code == 201
        assert segunda.status_code == 409

    @pytest.mark.asyncio
    async def test_should_be_reserved_to_a_superadmin(self, db_session):
        """Un admin que pudiera crear personas con rol podría crearse un admin."""
        async with _cliente(db_session, _principal(role="admin")) as cliente:
            respuesta = await cliente.post(
                "/api/v1/hub/users", json={"email": f"gate-{_uid()}@uji.es"}
            )

        assert respuesta.status_code == 403


# ───────────────────────── El correo, normalizado ─────────────────────────


class TestElCorreoEsLaClaveDelReencuentro:

    @pytest.mark.asyncio
    async def test_should_store_the_email_normalised(self, db_session):
        crudo = f"  Alta-{_uid()}@UJI.es  "

        async with _cliente(db_session, _principal()) as cliente:
            respuesta = await cliente.post("/api/v1/hub/users", json={"email": crudo})

        assert respuesta.json()["email"] == crudo.strip().lower()

    @pytest.mark.asyncio
    async def test_should_find_the_manual_row_when_the_idp_sends_another_case(self, db_session):
        """**El test del prompt**: alta con una capitalización, entrada con otra, y **una sola
        fila**. Sin esto el alta manual no sirve para nada."""
        base = f"reencuentro-{_uid()}"

        async with _cliente(db_session, _principal()) as cliente:
            await cliente.post(
                "/api/v1/hub/users", json={"email": f"{base}@UJI.es", "role": "admin"}
            )

        info = await _entrar_por_sso(db_session, f"  {base}@uji.ES ")

        assert info.role == "admin"
        from sqlalchemy import func, select

        from server.app.modules.agents_hub.database.config_models import HubUser

        cuantas = (
            await db_session.execute(
                select(func.count()).select_from(HubUser).where(HubUser.email.like(f"{base}%"))
            )
        ).scalar_one()
        assert cuantas == 1

    @pytest.mark.asyncio
    async def test_should_keep_the_manual_origin_after_the_first_login(self, db_session):
        """Quien entró por SSO sobre una fila creada a mano **sigue siendo** manual: el origen
        cuenta quién la creó, no quién la usó."""
        email = f"origen-{_uid()}@uji.es"

        async with _cliente(db_session, _principal()) as cliente:
            await cliente.post("/api/v1/hub/users", json={"email": email})

        await _entrar_por_sso(db_session, email)

        assert (await _fila(db_session, email)).origen == "manual"


# ───────────────────────── Desactivar cierra la puerta ─────────────────────────


class TestDesactivarNiegaLaEntrada:

    @pytest.mark.asyncio
    async def test_should_refuse_a_deactivated_person_even_if_the_idp_validates_them(
        self, db_session
    ):
        """`is_active` existía desde AUTH.2 y **nadie la miraba**: desactivar a alguien lo
        quitaba del listado y lo dejaba entrando."""
        from server.app.core.auth.saml.identity_service import SamlUserInactiveError

        email = f"baja-{_uid()}@uji.es"

        async with _cliente(db_session, _principal()) as cliente:
            creada = await cliente.post("/api/v1/hub/users", json={"email": email})
            await cliente.patch(
                f"/api/v1/hub/users/{creada.json()['id']}", json={"is_active": False}
            )

        with pytest.raises(SamlUserInactiveError):
            await _entrar_por_sso(db_session, email)

    @pytest.mark.asyncio
    async def test_should_let_an_active_person_in(self, db_session):
        email = f"alta-activa-{_uid()}@uji.es"

        async with _cliente(db_session, _principal()) as cliente:
            await cliente.post("/api/v1/hub/users", json={"email": email, "role": "informer"})

        info = await _entrar_por_sso(db_session, email)

        assert info.role == "informer"


# ───────────────────────── Edición y listado ─────────────────────────


class TestEdicionYListado:

    @pytest.mark.asyncio
    async def test_should_change_the_role_of_an_existing_person(self, db_session):
        email = f"promo-{_uid()}@uji.es"

        async with _cliente(db_session, _principal()) as cliente:
            creada = await cliente.post("/api/v1/hub/users", json={"email": email})
            respuesta = await cliente.patch(
                f"/api/v1/hub/users/{creada.json()['id']}", json={"role": "admin"}
            )

        assert respuesta.status_code == 200
        assert respuesta.json()["role"] == "admin"

    @pytest.mark.asyncio
    async def test_should_not_let_the_email_be_edited(self, db_session):
        """El correo es la clave del reencuentro con el IdP: cambiarlo desde el panel
        desengancha a la persona de su identidad sin que se note hasta que intente entrar."""
        email = f"inmutable-{_uid()}@uji.es"

        async with _cliente(db_session, _principal()) as cliente:
            creada = await cliente.post("/api/v1/hub/users", json={"email": email})
            respuesta = await cliente.patch(
                f"/api/v1/hub/users/{creada.json()['id']}", json={"email": "otro@uji.es"}
            )

        assert respuesta.status_code == 422

    @pytest.mark.asyncio
    async def test_should_list_both_origins(self, db_session):
        manual = f"lista-manual-{_uid()}@uji.es"
        por_sso = f"lista-sso-{_uid()}@uji.es"

        async with _cliente(db_session, _principal()) as cliente:
            await cliente.post("/api/v1/hub/users", json={"email": manual})
            await _entrar_por_sso(db_session, por_sso)
            respuesta = await cliente.get("/api/v1/hub/users")

        origenes = {u["email"]: u["origen"] for u in respuesta.json()["personas"]}
        assert origenes[manual] == "manual"
        assert origenes[por_sso] == "sso"

    @pytest.mark.asyncio
    async def test_should_reserve_the_listing_to_whoever_administers(self, db_session):
        """USR.9 — el listado se abrió a quien administra una organización, **acotado**.

        Lo que IDE.3 fijaba aquí era que no lo viera cualquiera, y eso sigue: un `user` recibe
        403. Lo que cambió es que un `admin` también administra —USR.1 ya le había dado fijar la
        contraseña de alguien de su organización, y sin el listado esa capacidad existía por API
        y no por pantalla—. El reparto y la acotación se miden en
        `test_usr9_personas_de_mi_organizacion.py`.
        """
        async with _cliente(db_session, _principal(role="user")) as cliente:
            respuesta = await cliente.get("/api/v1/hub/users")

        assert respuesta.status_code == 403

    @pytest.mark.asyncio
    async def test_should_return_404_for_someone_who_does_not_exist(self, db_session):
        async with _cliente(db_session, _principal()) as cliente:
            respuesta = await cliente.patch(
                f"/api/v1/hub/users/{uuid.uuid4()}", json={"role": "admin"}
            )

        assert respuesta.status_code == 404
