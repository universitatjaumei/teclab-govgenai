"""USR.1 — una persona puede tener contraseña, y quién se la puede fijar.

`hub_users` era un registro de personas completo **sin columna de contraseña**: sus identidades
sólo podían venir del ACS de SAML. Mientras el IdP institucional no esté configurado —y eso no
tiene fecha—, los probadores del piloto no pueden entrar como ellos mismos, y la salida que se
tomó el 2026-09-01 fue elevarlos a superadministrador con una contraseña compartida.

Este prompt añade la columna y la vía para fijarla. Tres cosas que se leen mal si no están
dichas:

- **`hashed_password` NULL es «login local deshabilitado»**, jamás «pasa sin comprobar». Es la
  misma semántica que `AdminAccount.hashed_password` y por el mismo motivo: la lectura contraria
  es el hallazgo A1 de SEC.1 reabierto por la puerta de atrás. Quien lo lea al revés rompe el
  test de USR.2, que es donde vive esa comprobación.
- **Un admin puede fijar la contraseña de una persona DE SU organización**, y ahí este endpoint
  se separa a propósito de su gemelo `setAdminPassword`, que es sólo superadmin: quien da de
  alta a sus probadores es quien administra su organización, y obligar a pasar por el
  superadministrador convierte cada alta en un cuello de botella. La acotación la resuelve
  `core/auth/tenancy.py`; un `if` a mano en el endpoint sería la regla en dos sitios.
- **El hash no sale en ninguna respuesta.** `UsuarioRead` se construye campo a campo, así que
  colarlo es fácil y no se notaría hasta que alguien mirase el JSON.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import server.app.main  # noqa: F401

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo
from server.app.modules.agents_hub.database.config_models import HubOrganizacion, HubUser
from server.app.modules.agents_hub.database.connection import get_async_session
from server.app.routers.hub_users_router import router

CONTRASENA = "una-contrasena-larga-de-verdad"


@pytest.fixture(autouse=True)
async def _tablas_de_cuenta(db_session):
    """Igual que en IDE.3: `resolve_session` mira `superadminaccount` antes de `hub_users`."""
    from sqlmodel import SQLModel

    import server.app.database.models  # noqa: F401

    conexion = await db_session.connection()
    await conexion.run_sync(SQLModel.metadata.create_all)
    await db_session.commit()


def _principal(role: str = "superadmin", orgs: tuple[str, ...] = ()) -> UserInfo:
    return UserInfo(
        user_id="quien-administra",
        email="root@uji.es",
        role=role,
        organizacion_ids=orgs,
    )


def _cliente(session, principal: UserInfo) -> AsyncClient:
    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_async_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _organizacion(session, nombre: str) -> HubOrganizacion:
    org = HubOrganizacion(name=nombre, partner_id=f"p-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    return org


async def _persona(session, org_id: uuid.UUID | None) -> HubUser:
    fila = HubUser(
        id=uuid.uuid4(),
        email=f"probador-{uuid.uuid4().hex[:8]}@uji.es",
        role="user",
        organizacion_id=org_id,
        origen="manual",
    )
    session.add(fila)
    await session.flush()
    return fila


class TestQuienPuedeFijarla:

    async def test_should_let_a_superadmin_set_it(self, db_session):
        org = await _organizacion(db_session, "UJI")
        persona = await _persona(db_session, org.id)

        async with _cliente(db_session, _principal()) as c:
            r = await c.patch(
                f"/api/v1/hub/users/{persona.id}/password",
                json={"password": CONTRASENA},
            )

        assert r.status_code == 204, r.text

    async def test_should_let_an_admin_of_the_same_organization_set_it(self, db_session):
        """Es la diferencia deliberada con `setAdminPassword`, que es sólo superadmin."""
        org = await _organizacion(db_session, "UJI")
        persona = await _persona(db_session, org.id)

        principal = _principal("admin", orgs=(str(org.id),))
        async with _cliente(db_session, principal) as c:
            r = await c.patch(
                f"/api/v1/hub/users/{persona.id}/password",
                json={"password": CONTRASENA},
            )

        assert r.status_code == 204, r.text

    async def test_should_refuse_an_admin_of_another_organization(self, db_session):
        propia = await _organizacion(db_session, "Otra")
        ajena = await _organizacion(db_session, "UJI")
        persona = await _persona(db_session, ajena.id)

        principal = _principal("admin", orgs=(str(propia.id),))
        async with _cliente(db_session, principal) as c:
            r = await c.patch(
                f"/api/v1/hub/users/{persona.id}/password",
                json={"password": CONTRASENA},
            )

        assert r.status_code == 403, r.text

    async def test_should_refuse_a_plain_user_even_on_their_own_row(self, db_session):
        """Cambiar la propia contraseña exige conocer la anterior, y eso es USR.7."""
        org = await _organizacion(db_session, "UJI")
        persona = await _persona(db_session, org.id)

        principal = UserInfo(
            user_id=str(persona.id),
            email=persona.email,
            role="user",
            organizacion_ids=(str(org.id),),
        )
        async with _cliente(db_session, principal) as c:
            r = await c.patch(
                f"/api/v1/hub/users/{persona.id}/password",
                json={"password": CONTRASENA},
            )

        assert r.status_code == 403, r.text

    async def test_should_answer_404_for_a_person_that_does_not_exist(self, db_session):
        async with _cliente(db_session, _principal()) as c:
            r = await c.patch(
                f"/api/v1/hub/users/{uuid.uuid4()}/password",
                json={"password": CONTRASENA},
            )

        assert r.status_code == 404, r.text

    async def test_should_reject_a_short_password_with_the_shared_contract(self, db_session):
        """El mismo mínimo que `SetPasswordRequest`, no otro escrito aquí."""
        org = await _organizacion(db_session, "UJI")
        persona = await _persona(db_session, org.id)

        async with _cliente(db_session, _principal()) as c:
            r = await c.patch(
                f"/api/v1/hub/users/{persona.id}/password", json={"password": "corta"}
            )

        assert r.status_code == 422, r.text


class TestQueSeGuarda:

    async def test_should_store_a_hash_and_never_the_password(self, db_session):
        org = await _organizacion(db_session, "UJI")
        persona = await _persona(db_session, org.id)

        async with _cliente(db_session, _principal()) as c:
            await c.patch(
                f"/api/v1/hub/users/{persona.id}/password",
                json={"password": CONTRASENA},
            )

        await db_session.refresh(persona)
        assert persona.hashed_password, "la columna se ha quedado vacía"
        assert persona.hashed_password != CONTRASENA
        assert len(persona.hashed_password) == 60, (
            f"bcrypt son 60 caracteres; hay {len(persona.hashed_password)}"
        )

        from server.app.core.security import verify_password

        assert verify_password(CONTRASENA, persona.hashed_password)

    async def test_should_start_as_null_which_means_no_local_login(self, db_session):
        """NULL es «login local deshabilitado», y por eso el defecto es NULL y no una cadena."""
        persona = await _persona(db_session, None)
        await db_session.refresh(persona)

        assert persona.hashed_password is None


class TestElServidorDiceQuienPuedeFijarla:
    """USR.3 — `puede_fijar_contrasena` en el DTO, no un `if` en React.

    Vive en este fichero y no en uno propio porque es el mismo router y las mismas fixtures;
    partirlo habría duplicado el andamiaje para tres asertos.

    Es la regla maestra 2 aplicada otra vez: el frontend **no** calcula qué acciones están
    permitidas. Un `if (rol === 'superadmin')` en la pantalla sería la autorización escrita por
    segunda vez, y el día que un admin gestione su organización las dos copias dirían cosas
    distintas.
    """

    async def test_should_tell_a_superadmin_they_can(self, db_session):
        org = await _organizacion(db_session, "UJI")
        await _persona(db_session, org.id)

        async with _cliente(db_session, _principal()) as c:
            listado = await c.get("/api/v1/hub/users")

        personas = [f for f in listado.json()["personas"] if f["origen"] == "manual"]
        assert personas, "no hay ninguna persona en el listado"
        assert all(f["puede_fijar_contrasena"] for f in personas)

    async def test_should_say_no_for_the_bootstrap_superadmin_row(self, db_session):
        """Vive en otra tabla y su contraseña no se toca desde esta pantalla."""
        from server.app.core.security import hash_password
        from server.app.database.models import SuperAdminAccount

        db_session.add(
            SuperAdminAccount(
                email=f"root-{uuid.uuid4().hex[:6]}@uji.es",
                name="Arranque",
                hashed_password=hash_password(CONTRASENA),
                is_active=True,
            )
        )
        await db_session.flush()

        async with _cliente(db_session, _principal()) as c:
            listado = await c.get("/api/v1/hub/users")

        de_arranque = [f for f in listado.json()["personas"] if f["origen"] == "superadmin"]
        assert de_arranque, "la cuenta de arranque no aparece en el listado"
        assert not any(f["puede_fijar_contrasena"] for f in de_arranque)

    async def test_should_use_the_same_function_that_authorizes_the_endpoint(self, db_session):
        """Si el DTO dice que sí, el endpoint no puede contestar 403, y al revés.

        Se comprueba con una persona de otra organización y un admin acotado: el DTO dice que
        no puede, y el endpoint responde 403. Dos respuestas de la misma regla.
        """
        propia = await _organizacion(db_session, "Otra")
        ajena = await _organizacion(db_session, "UJI")
        persona = await _persona(db_session, ajena.id)

        from server.app.core.auth.tenancy import puede_acceder

        admin = _principal("admin", orgs=(str(propia.id),))
        assert puede_acceder(admin, persona.organizacion_id) is False

        async with _cliente(db_session, admin) as c:
            r = await c.patch(
                f"/api/v1/hub/users/{persona.id}/password",
                json={"password": CONTRASENA},
            )
        assert r.status_code == 403


class TestElHashNoCruzaLaFronteraEdge:
    """`hub_users` es `HubConfigBase`, o sea que se sincroniza cloud→edge.

    Medido el 2026-09-02: la sync API es todavía un *stub* que responde 501, y su instantánea
    enumera **campo a campo** clientes, chatbots, configuraciones de LLM y plantillas. `HubUser`
    no está, así que hoy el hash no viaja a ningún sitio.

    El test no comprueba lo de hoy —eso es trivial— sino lo de mañana: el día que alguien
    implemente `get_edge_config`, la tentación es volcar el ORM con un `model_dump`, y ahí el
    hash se iría al edge sin que nadie lo decidiera. Un nodo edge no necesita contraseñas de
    login local: quien entra al panel, entra en el cloud.
    """

    def test_should_not_declare_a_password_field_in_the_sync_snapshot(self):
        from pydantic import BaseModel

        from server.app.api.v1.edge_sync import EdgeConfigSnapshot

        def _campos(modelo: type[BaseModel], vistos: set[type] | None = None) -> set[str]:
            vistos = vistos if vistos is not None else set()
            if modelo in vistos:
                return set()
            vistos.add(modelo)
            nombres: set[str] = set()
            for nombre, campo in modelo.model_fields.items():
                nombres.add(nombre)
                for arg in (campo.annotation, *getattr(campo.annotation, "__args__", ())):
                    if isinstance(arg, type) and issubclass(arg, BaseModel):
                        nombres |= _campos(arg, vistos)
            return nombres

        declarados = _campos(EdgeConfigSnapshot)
        assert "hashed_password" not in declarados, (
            "La instantánea de sincronización declara un campo de contraseña. Un nodo edge no "
            "necesita credenciales de login local: quien entra al panel entra en el cloud."
        )


class TestElHashNoSale:

    async def test_should_not_leak_the_hash_in_the_listing(self, db_session):
        org = await _organizacion(db_session, "UJI")
        persona = await _persona(db_session, org.id)

        async with _cliente(db_session, _principal()) as c:
            await c.patch(
                f"/api/v1/hub/users/{persona.id}/password",
                json={"password": CONTRASENA},
            )
            listado = await c.get("/api/v1/hub/users")

        assert listado.status_code == 200, listado.text
        crudo = listado.text
        assert "hashed_password" not in crudo
        assert "$2b$" not in crudo, "hay un hash de bcrypt en la respuesta"

    async def test_should_not_leak_the_hash_when_creating_or_editing(self, db_session):
        org = await _organizacion(db_session, "UJI")

        async with _cliente(db_session, _principal()) as c:
            creada = await c.post(
                "/api/v1/hub/users",
                json={"email": f"n-{uuid.uuid4().hex[:8]}@uji.es",
                      "organizacion_id": str(org.id)},
            )
            assert creada.status_code == 201, creada.text
            uid = creada.json()["id"]
            await c.patch(f"/api/v1/hub/users/{uid}/password", json={"password": CONTRASENA})
            editada = await c.patch(
                f"/api/v1/hub/users/{uid}", json={"display_name": "Con contraseña"}
            )

        assert "hashed_password" not in creada.text
        assert editada.status_code == 200, editada.text
        assert "hashed_password" not in editada.text
        assert "$2b$" not in editada.text
