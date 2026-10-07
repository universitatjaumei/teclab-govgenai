"""USR.6 — varias personas administran la misma organización, y ninguna la de al lado.

**Es la capacidad que no era representable**, y el motivo por el que los seis probadores del
piloto acabaron siendo superadministradores con una contraseña compartida:
`AdminAccount.partner_id` es la clave primaria y las organizaciones se enlazan por
`HubOrganizacion.partner_id`, así que cuatro administradores de la UJI serían cuatro
`partner_id` distintos y tres abrirían el panel con la lista vacía.

La decisión de USR.6 —escrita en `docs/DECISION_IDENTIDAD_DE_ADMINISTRACION.md`— es que la
identidad de administración es **`HubUser` con `role='admin'`**. Con eso, «varias personas
administran la misma organización» son varias filas con el mismo `organizacion_id`, y este
fichero es lo que impide que eso se rompa sin que nadie lo note.

Los tests no comprueban que el modelo *permita* dos filas —eso es trivial—, sino **las tres
cosas que tienen que ser ciertas a la vez** para que la capacidad sirva:

1. Las dos personas **entran**, cada una con su contraseña.
2. Las dos llevan en el token **la misma organización**, así que la acotación por tenencia les
   deja ver lo mismo.
3. Ninguna de las dos alcanza la organización de al lado — que es lo que se comprueba con
   `puede_acceder` y con el endpoint de contraseña, no razonando sobre el claim.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import server.app.main  # noqa: F401

from server.app.api.deps import get_session
from server.app.core.security import hash_password
from server.app.modules.agents_hub.database.config_models import HubOrganizacion, HubUser
from server.app.routers.auth_router import router as auth_router

PASSWORD_UNA = "Administradora-una-2026"
PASSWORD_OTRA = "Administrador-otro-2026"


@pytest.fixture(autouse=True)
def _sin_cupo_gastado():
    from server.app.core.rate_limit import limitador

    limitador.reiniciar()
    yield
    limitador.reiniciar()


@pytest.fixture(autouse=True)
async def _tablas_de_cuenta(db_session):
    from sqlmodel import SQLModel

    import server.app.database.models  # noqa: F401

    conexion = await db_session.connection()
    await conexion.run_sync(SQLModel.metadata.create_all)
    await db_session.commit()


async def _sesion_como_en_produccion(db_session):
    """La clase de sesión que yield `deps.get_session`: la de SQLModel, que tiene `.exec()`."""
    from sqlmodel.ext.asyncio.session import AsyncSession as SesionSQLModel

    return SesionSQLModel(bind=await db_session.connection())


def _cliente(session) -> AsyncClient:
    async def _sesion():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_session] = _sesion
    app.include_router(auth_router, prefix="/api/v1")
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _organizacion(session, nombre: str) -> HubOrganizacion:
    org = HubOrganizacion(name=nombre, partner_id=f"p-{uuid.uuid4().hex[:8]}")
    session.add(org)
    await session.flush()
    return org


async def _administradora(session, org_id: uuid.UUID, password: str) -> HubUser:
    fila = HubUser(
        id=uuid.uuid4(),
        email=f"admin-{uuid.uuid4().hex[:8]}@uji.es",
        role="admin",
        organizacion_id=org_id,
        is_active=True,
        origen="manual",
        hashed_password=hash_password(password),
    )
    session.add(fila)
    await session.flush()
    return fila


async def _entra(db_session, persona: HubUser, password: str):
    from server.app.core.auth import decode_token

    async with _cliente(await _sesion_como_en_produccion(db_session)) as c:
        r = await c.post(
            "/api/v1/auth/user/login",
            json={"email": persona.email, "password": password},
        )
    assert r.status_code == 200, r.text
    return decode_token(r.json()["access_token"])


class TestDosPersonasLaMismaOrganizacion:

    async def test_should_let_both_administer_the_same_organization(self, db_session):
        """Lo que `AdminAccount` no podía expresar: dos filas, la misma organización."""
        uji = await _organizacion(db_session, "Universitat Jaume I")
        una = await _administradora(db_session, uji.id, PASSWORD_UNA)
        otra = await _administradora(db_session, uji.id, PASSWORD_OTRA)

        sesion_una = await _entra(db_session, una, PASSWORD_UNA)
        sesion_otra = await _entra(db_session, otra, PASSWORD_OTRA)

        assert sesion_una.role == "admin" and sesion_otra.role == "admin"
        assert sesion_una.organizacion_ids == (str(uji.id),)
        assert sesion_otra.organizacion_ids == (str(uji.id),)
        assert sesion_una.user_id != sesion_otra.user_id, (
            "cada una es una persona: la atribución por persona es justo lo que se perdía con "
            "la credencial compartida"
        )

    async def test_should_give_each_of_them_the_same_reach(self, db_session):
        """La misma organización quiere decir el mismo alcance, sin desempates."""
        from server.app.core.auth.tenancy import puede_acceder

        uji = await _organizacion(db_session, "Universitat Jaume I")
        una = await _administradora(db_session, uji.id, PASSWORD_UNA)
        otra = await _administradora(db_session, uji.id, PASSWORD_OTRA)

        for persona, clave in ((una, PASSWORD_UNA), (otra, PASSWORD_OTRA)):
            sesion = await _entra(db_session, persona, clave)
            assert puede_acceder(sesion, uji.id) is True

    async def test_should_keep_them_out_of_the_organization_next_door(self, db_session):
        """Y esto es la mitad del valor del test: que compartir no sea abrir."""
        from server.app.core.auth.tenancy import puede_acceder

        uji = await _organizacion(db_session, "Universitat Jaume I")
        vecina = await _organizacion(db_session, "Diputación de Castellón")
        una = await _administradora(db_session, uji.id, PASSWORD_UNA)

        sesion = await _entra(db_session, una, PASSWORD_UNA)

        assert puede_acceder(sesion, vecina.id) is False
        assert str(vecina.id) not in sesion.organizacion_ids


class TestLaPuertaDeLaContrasena:
    """Un administrador fija la contraseña de su gente, y sólo de la suya (USR.1 + USR.6)."""

    async def test_should_not_let_an_admin_set_the_password_of_a_fellow_admin(self, db_session):
        """Hasta el 2026-10-07 sí podía: era el mismo agujero que dejaba fijar la del
        superadministrador. La de otro administrador la fija sólo un superadministrador; un
        administrador, la de los usuarios e informadores de su organización."""
        from server.app.routers.hub_users_router import router as usuarios_router
        from server.app.modules.agents_hub.database.connection import get_async_session

        uji = await _organizacion(db_session, "Universitat Jaume I")
        una = await _administradora(db_session, uji.id, PASSWORD_UNA)
        companera = await _administradora(db_session, uji.id, PASSWORD_OTRA)

        sesion = await _entra(db_session, una, PASSWORD_UNA)

        async def _sesion_hub():
            yield db_session

        app = FastAPI()
        from server.app.api.deps import get_current_user

        app.dependency_overrides[get_current_user] = lambda: sesion
        app.dependency_overrides[get_async_session] = _sesion_hub
        app.include_router(usuarios_router, prefix="/api/v1")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.patch(
                f"/api/v1/hub/users/{companera.id}/password",
                json={"password": "una-contrasena-nueva-larga"},
            )

        assert r.status_code == 403, r.text

    async def test_should_refuse_an_admin_over_someone_of_another_organization(self, db_session):
        from server.app.routers.hub_users_router import router as usuarios_router
        from server.app.modules.agents_hub.database.connection import get_async_session
        from server.app.api.deps import get_current_user

        uji = await _organizacion(db_session, "Universitat Jaume I")
        vecina = await _organizacion(db_session, "Diputación de Castellón")
        una = await _administradora(db_session, uji.id, PASSWORD_UNA)
        ajena = await _administradora(db_session, vecina.id, PASSWORD_OTRA)

        sesion = await _entra(db_session, una, PASSWORD_UNA)

        async def _sesion_hub():
            yield db_session

        app = FastAPI()
        app.dependency_overrides[get_current_user] = lambda: sesion
        app.dependency_overrides[get_async_session] = _sesion_hub
        app.include_router(usuarios_router, prefix="/api/v1")

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.patch(
                f"/api/v1/hub/users/{ajena.id}/password",
                json={"password": "una-contrasena-nueva-larga"},
            )

        assert r.status_code == 403, r.text


class TestUnSuperadministradorNuevoSeCreaDesdeElPanel:
    """La tercera cosa que no se podía hacer, y que (b) resuelve sin código nuevo.

    `bootstrap.py` crea el superadministrador de instalación en `superadminaccount` y no había
    forma de crear otro ni de cambiarle la contraseña desde la aplicación. Con la identidad en
    `hub_users`, un superadministrador nuevo es un alta más y su contraseña la fija USR.1.
    """

    async def test_should_let_a_new_superadmin_be_created_as_a_person(self, db_session):
        fila = HubUser(
            id=uuid.uuid4(),
            email=f"root-{uuid.uuid4().hex[:8]}@uji.es",
            role="superadmin",
            organizacion_id=None,
            is_active=True,
            origen="manual",
            hashed_password=hash_password("Contrasena-de-superadmin-2026"),
        )
        db_session.add(fila)
        await db_session.flush()

        sesion = await _entra(db_session, fila, "Contrasena-de-superadmin-2026")

        assert sesion.role == "superadmin"
        from server.app.core.auth.tenancy import puede_acceder

        # En un superadministrador la lista vacía es el comodín «todas», al contrario que en
        # cualquier otro rol. Es la asimetría de la que depende `tenancy.py`.
        assert not sesion.organizacion_ids
        assert puede_acceder(sesion, uuid.uuid4()) is True
