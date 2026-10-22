"""VAS.2 (defecto encontrado verificando) — el PAT tiene que llevar la organización de su dueño.

**Cómo salió.** Con VAS.2 recién escrito, un `curl` real con un PAT real preguntando por un
documento **de la organización del dueño del token** devolvía 404. Los veinte tests del endpoint
estaban en verde, porque todos sobreescriben `get_current_user` y le entregan un principal con la
organización puesta a mano. El camino que nadie recorría era el de verdad: autenticar un PAT.

**Qué estaba mal.** `PatService._orgs_del_dueno` resolvía las organizaciones del dueño así:

    select(HubOrganizacion.id).where(HubOrganizacion.partner_id == owner_id)

Eso es el modelo de **partner**: una cuenta de partner posee organizaciones, y `partner_id` es su
código. Pero desde ROL/IDE la identidad de administración es un **`HubUser` con `role='admin'`**,
y un `HubUser` no posee organizaciones: **pertenece** a una, por su columna `organizacion_id`. Así
que la consulta comparaba un uuid de usuario con un código de partner —`60082aa4-…` contra
`uji`—, no encajaba nunca, y devolvía la tupla vacía.

**Y para un rol que no es superadmin, la tupla vacía significa «ninguna organización»** (I5). El
efecto en cascada:

- `scope_query_to_orgs` produce `IN ()` y el PAT no ve **nada** de su propia organización.
- `organizacion_unica_de` devuelve `None`, así que **`POST /api/v1/actividad` (REG.2) responde
  403 a todo integrador real**. Ese endpoint no ha funcionado nunca con un PAT de verdad; sus
  diecisiete tests pasan porque el principal se inyecta.

Es el patrón que el proyecto ya tiene anotado dos veces: un mock sin el camino real esconde el
bug, y la comprobación en vivo es la que lo encuentra. Estos tests recorren `PatService.verify`
de punta a punta contra la base, sin sobreescribir el principal.
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.fixture
async def db_session(db_url):
    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            yield session
    finally:
        await engine.dispose()


async def _organizacion(session, partner_id: str = "uji") -> uuid.UUID:
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion

    org = HubOrganizacion(
        id=uuid.uuid4(), name=f"Org {uuid.uuid4().hex[:6]}", partner_id=partner_id
    )
    session.add(org)
    await session.flush()
    return org.id


async def _admin(session, organizacion_id: uuid.UUID):
    from server.app.modules.agents_hub.database.config_models import HubUser

    usuario = HubUser(
        id=uuid.uuid4(),
        email=f"admin.{uuid.uuid4().hex[:6]}@uji.es",
        role="admin",
        organizacion_id=organizacion_id,
    )
    session.add(usuario)
    await session.flush()
    return usuario


async def _emite(session, dueno, scopes=("verificaciones:use",)) -> str:
    from server.app.core.auth.models import UserInfo
    from server.app.core.auth.pat.service import PatService

    _fila, plano = await PatService(session).create(
        owner=UserInfo(
            user_id=str(dueno.id),
            email=dueno.email,
            role=dueno.role,
            organizacion_ids=(str(dueno.organizacion_id),),
        ),
        name="prueba",
        scopes=list(scopes),
    )
    await session.flush()
    return plano


class TestElPatLlevaSuOrganizacion:

    async def test_should_carry_the_owners_organisation(self, db_session):
        """El caso que el `curl` destapó: un administrador y su propia organización."""
        from server.app.core.auth.pat.service import PatService

        org = await _organizacion(db_session)
        dueno = await _admin(db_session, org)
        plano = await _emite(db_session, dueno)

        principal = await PatService(db_session).verify(plano)

        assert principal.user_info.organizacion_ids == (str(org),), (
            "sin esto el PAT no ve nada de su organización y no puede decir en nombre de quién "
            "registra: `scope_query_to_orgs` da `IN ()` y `organizacion_unica_de` da `None`."
        )

    async def test_should_let_the_pat_determine_a_single_organisation(self, db_session):
        """Es lo que REG.2 necesita para saber en qué registro escribir.

        Con la tupla vacía, `POST /api/v1/actividad` responde 403 `ORGANIZACION_INDETERMINADA` a
        todo integrador real — y sus tests no lo ven porque inyectan el principal.
        """
        from server.app.core.auth.pat.service import PatService
        from server.app.core.auth.tenancy import organizacion_unica_de

        org = await _organizacion(db_session)
        dueno = await _admin(db_session, org)
        plano = await _emite(db_session, dueno, scopes=("actividad:write",))

        principal = await PatService(db_session).verify(plano)

        assert organizacion_unica_de(principal.user_info) == org

    async def test_should_keep_the_partner_path_working(self, db_session):
        """Un dueño que **sí** es un partner posee organizaciones por `partner_id`.

        Las dos formas de dueño son legítimas y la corrección no puede romper la que funcionaba:
        se prueba primero la identidad de usuario, que es la de ROL/IDE, y se cae al partner.
        """
        from server.app.core.auth.models import UserInfo
        from server.app.core.auth.pat.service import PatService

        partner = f"partner-{uuid.uuid4().hex[:6]}"
        # El dueño tiene que existir y estar activo: la cuenta del partner. La base de test se
        # monta con los metadatos del hub, y `adminaccount` es de los heredados (SQLModel).
        from server.app.database.models import AdminAccount

        conexion = await db_session.connection()
        await conexion.run_sync(lambda c: AdminAccount.__table__.create(c, checkfirst=True))
        db_session.add(AdminAccount(partner_id=partner, name="Partner", email=f"{partner}@uji.es"))
        await db_session.flush()
        primera = await _organizacion(db_session, partner_id=partner)
        segunda = await _organizacion(db_session, partner_id=partner)

        _fila, plano = await PatService(db_session).create(
            owner=UserInfo(user_id=partner, email="p@uji.es", role="admin"),
            name="del-partner",
            scopes=["verificaciones:use"],
        )
        await db_session.flush()

        principal = await PatService(db_session).verify(plano)

        assert set(principal.user_info.organizacion_ids) == {str(primera), str(segunda)}

    async def test_should_leave_a_superadmin_with_the_wildcard(self, db_session):
        """En un superadministrador la tupla vacía significa «todas», y ahí sí es lo correcto.

        La corrección no puede convertir el comodín en «ninguna»: son el mismo valor con dos
        significados según el rol, y ésa es la asimetría que `UserInfo` documenta.
        """
        from server.app.core.auth.pat.service import PatService

        from server.tests.core.auth._duenos import persona_real

        _fila, plano = await PatService(db_session).create(
            owner=await persona_real(db_session, "superadmin"),
            name="del-super",
            scopes=["verificaciones:use"],
        )
        await db_session.flush()

        principal = await PatService(db_session).verify(plano)

        assert principal.user_info.organizacion_ids == ()
