"""USR.9 — quien administra una organización llega a las personas de su organización.

**El hueco, encontrado verificando USR.6**: USR.1 abrió `PATCH /hub/users/{id}/password` a quien
administra la organización de esa persona, a propósito y con su razón escrita —«quien da de alta
a sus probadores es quien administra su organización, y obligar a pasar por el superadministrador
convierte cada alta en un cuello de botella»—. Pero `GET /hub/users` seguía siendo **sólo
superadministrador**, así que para usar esa capacidad hacía falta saberse el UUID de la persona:
existía por API y no por pantalla. Y la pantalla, además, vive bajo el módulo `plataforma`, que un
administrador de organización no tiene ni debe tener —ahí están los modelos de LLM, las
organizaciones, los tokens y los módulos—.

**Se parte, no se abre.** Listar y fijar contraseña sí; crear personas, cambiar roles y borrar
**no**, y el motivo es el que ya está escrito en el docstring del router: *un admin que pudiera
crear personas con rol podría crearse un admin*. Abrir el listado no le da ese poder; abrir el
alta, sí.

**Y el listado se acota por tenencia.** Un administrador ve a las personas de sus organizaciones
y a nadie más. La acotación la hace `scope_query_to_orgs`, no un `if` en el endpoint, para que la
regla siga viviendo en un solo sitio; un principal con la lista de organizaciones vacía recibe
`IN ()`, o sea nada, que es la diferencia entre «no ve nada» y «no se filtra» (hallazgo A2).

**Las capacidades las dice el servidor.** La pantalla no puede calcular si se puede crear una
persona: eso es la regla maestra 2 y ya se rompió una vez con el propio `puede_fijar_contrasena`
antes de USR.3. `GET /hub/users/capacidades` devuelve `acciones_permitidas`, y la pantalla pinta
lo que hay en la lista.
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


@pytest.fixture(autouse=True)
async def _tablas_de_cuenta(db_session):
    """`list_users` lee también `superadminaccount` (REV.8), que vive en la otra base declarativa."""
    from sqlmodel import SQLModel

    import server.app.database.models  # noqa: F401

    conexion = await db_session.connection()
    await conexion.run_sync(SQLModel.metadata.create_all)
    await db_session.commit()


def _principal(role: str, orgs: tuple[str, ...] = ()) -> UserInfo:
    return UserInfo(
        user_id=f"quien-administra-{role}",
        email=f"{role}@uji.es",
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


async def _persona(session, org_id: uuid.UUID | None, correo: str) -> HubUser:
    fila = HubUser(
        id=uuid.uuid4(),
        email=correo,
        role="user",
        organizacion_id=org_id,
        origen="manual",
    )
    session.add(fila)
    await session.flush()
    return fila


class TestQuienPuedeListar:
    """La mitad que se abre: ver a quién administras."""

    async def test_should_let_an_admin_list_the_people_of_their_organization(self, db_session):
        org = await _organizacion(db_session, "UJI")
        await _persona(db_session, org.id, "probadora@uji.es")

        async with _cliente(db_session, _principal("admin", (str(org.id),))) as c:
            r = await c.get("/api/v1/hub/users")

        assert r.status_code == 200, r.text
        assert [p["email"] for p in r.json()["personas"]] == ["probadora@uji.es"]

    async def test_should_not_show_people_of_another_organization(self, db_session):
        """La acotación por tenencia, vista desde donde se nota."""
        mia = await _organizacion(db_session, "UJI")
        otra = await _organizacion(db_session, "Organización Demo")
        await _persona(db_session, mia.id, "dentro@uji.es")
        await _persona(db_session, otra.id, "fuera@demo.es")

        async with _cliente(db_session, _principal("admin", (str(mia.id),))) as c:
            r = await c.get("/api/v1/hub/users")

        assert [p["email"] for p in r.json()["personas"]] == ["dentro@uji.es"]

    async def test_should_show_nothing_to_an_admin_without_organizations(self, db_session):
        """`IN ()` y no «sin filtro»: es el hallazgo A2, y aquí es donde se comprueba."""
        org = await _organizacion(db_session, "UJI")
        await _persona(db_session, org.id, "dentro@uji.es")

        async with _cliente(db_session, _principal("admin")) as c:
            r = await c.get("/api/v1/hub/users")

        assert r.status_code == 200, r.text
        assert r.json()["personas"] == []

    async def test_should_still_show_everyone_to_a_superadmin(self, db_session):
        """Lo que ya funcionaba sigue igual: el superadministrador no se acota."""
        mia = await _organizacion(db_session, "UJI")
        otra = await _organizacion(db_session, "Organización Demo")
        await _persona(db_session, mia.id, "dentro@uji.es")
        await _persona(db_session, otra.id, "fuera@demo.es")

        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get("/api/v1/hub/users")

        correos = [p["email"] for p in r.json()["personas"]]
        assert "dentro@uji.es" in correos
        assert "fuera@demo.es" in correos

    async def test_should_not_show_the_boot_superadmins_to_an_admin(self, db_session):
        """Las cuentas de `superadminaccount` no son de ninguna organización.

        Se listan desde REV.8 porque el superadministrador principal no aparecía en ninguna
        parte. Enseñárselas a un administrador de organización sería filtrarle las cuentas de la
        plataforma, que es exactamente lo que la acotación por tenencia evita en `hub_users`.
        """
        from server.app.database.models import SuperAdminAccount

        db_session.add(
            SuperAdminAccount(
                email="root@plataforma.es",
                name="Cuenta de instalación",
                hashed_password="x" * 60,
            )
        )
        org = await _organizacion(db_session, "UJI")
        await _persona(db_session, org.id, "dentro@uji.es")
        await db_session.flush()

        async with _cliente(db_session, _principal("admin", (str(org.id),))) as c:
            r = await c.get("/api/v1/hub/users")

        assert [p["email"] for p in r.json()["personas"]] == ["dentro@uji.es"]

    async def test_should_keep_refusing_a_plain_user(self, db_session):
        org = await _organizacion(db_session, "UJI")

        async with _cliente(db_session, _principal("user", (str(org.id),))) as c:
            r = await c.get("/api/v1/hub/users")

        assert r.status_code == 403, r.text


class TestLoQueNoSeAbre:
    """La otra mitad, y su razón: quien puede crear personas con rol puede crearse un admin."""

    async def test_should_refuse_an_admin_creating_a_person(self, db_session):
        org = await _organizacion(db_session, "UJI")

        async with _cliente(db_session, _principal("admin", (str(org.id),))) as c:
            r = await c.post(
                "/api/v1/hub/users",
                json={
                    "email": "nueva@uji.es",
                    "role": "admin",
                    "organizacion_id": str(org.id),
                },
            )

        assert r.status_code == 403, r.text

    async def test_should_refuse_an_admin_changing_a_role(self, db_session):
        org = await _organizacion(db_session, "UJI")
        persona = await _persona(db_session, org.id, "probadora@uji.es")

        async with _cliente(db_session, _principal("admin", (str(org.id),))) as c:
            r = await c.patch(f"/api/v1/hub/users/{persona.id}", json={"role": "admin"})

        assert r.status_code == 403, r.text

    async def test_should_refuse_an_admin_deleting_a_person(self, db_session):
        org = await _organizacion(db_session, "UJI")
        persona = await _persona(db_session, org.id, "probadora@uji.es")

        async with _cliente(db_session, _principal("admin", (str(org.id),))) as c:
            r = await c.delete(f"/api/v1/hub/users/{persona.id}")

        assert r.status_code == 403, r.text


class TestLasCapacidadesLasDiceElServidor:
    """Regla maestra 2: la pantalla itera sobre `acciones_permitidas`, no las calcula."""

    async def test_should_give_a_superadmin_every_action(self, db_session):
        async with _cliente(db_session, _principal("superadmin")) as c:
            r = await c.get("/api/v1/hub/users/capacidades")

        assert r.status_code == 200, r.text
        assert set(r.json()["acciones_permitidas"]) == {
            "listar",
            "crear",
            "editar",
            "borrar",
            "fijar_contrasena",
        }

    async def test_should_give_an_admin_only_what_they_can_do(self, db_session):
        org = await _organizacion(db_session, "UJI")

        async with _cliente(db_session, _principal("admin", (str(org.id),))) as c:
            r = await c.get("/api/v1/hub/users/capacidades")

        assert r.status_code == 200, r.text
        assert set(r.json()["acciones_permitidas"]) == {"listar", "fijar_contrasena"}

    async def test_should_refuse_a_plain_user(self, db_session):
        """No es una lista vacía: quien no administra no tiene por qué saber que esto existe."""
        async with _cliente(db_session, _principal("user")) as c:
            r = await c.get("/api/v1/hub/users/capacidades")

        assert r.status_code == 403, r.text
