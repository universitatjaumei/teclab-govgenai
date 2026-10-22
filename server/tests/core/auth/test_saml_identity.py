"""Tests de provisioning JIT + mapeo de rol + emisión de JWT desde SAML (AUTH.2).

Las pruebas de ``resolve_session`` y el ACS completo usan el PostgreSQL de desarrollo
(fixture ``db`` de ``conftest.py``, que limpia las filas creadas).
"""

import uuid

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient


def _uid() -> str:
    return uuid.uuid4().hex[:12]


# --------------------------------------------------------------------------- #
# resolve_role (puro, sin BD)                                                   #
# --------------------------------------------------------------------------- #
def test_resolve_role_explicit_attribute(saml_ctx):
    from server.app.core.auth.saml.role_mapping import resolve_role

    assert resolve_role({"role": ["admin"]}) == "admin"


def test_resolve_role_from_group_map(saml_ctx, monkeypatch):
    from server.app.core.auth.saml.role_mapping import resolve_role

    monkeypatch.setenv("SAML_GROUP_ROLE_MAP", '{"pas-informatica": "admin"}')
    assert resolve_role({"groups": ["pas-informatica"]}) == "admin"


def test_resolve_role_default_when_nothing(saml_ctx):
    from server.app.core.auth.saml.role_mapping import resolve_role

    assert resolve_role({}) == "user"  # SAML_DEFAULT_ROLE


def test_resolve_role_precedence_superadmin_over_admin(saml_ctx, monkeypatch):
    from server.app.core.auth.saml.role_mapping import resolve_role

    monkeypatch.setenv(
        "SAML_GROUP_ROLE_MAP",
        '{"grupo-super": "superadmin", "grupo-admin": "admin"}',
    )
    role = resolve_role({"groups": ["grupo-admin", "grupo-super"]})
    assert role == "superadmin"


# --------------------------------------------------------------------------- #
# resolve_session (BD)                                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_resolve_session_known_superadmin(saml_ctx, db):
    from server.app.core.auth.saml.identity_service import SamlIdentityService
    from server.app.database.models import SuperAdminAccount
    from server.app.modules.agents_hub.database.config_models import HubUser
    from sqlalchemy import select

    email = f"superadmin-{_uid()}@uji.es"
    db.track(email)
    db.session.add(
        SuperAdminAccount(name="SuperAdmin Test", email=email, hashed_password="x", is_active=True)
    )
    await db.session.commit()

    info = await SamlIdentityService(db.session).resolve_session(
        nameid=email, attributes={"mail": [email]}
    )
    assert info.role == "superadmin"
    assert info.email == email
    # No se crea HubUser para una cuenta superadmin existente.
    sso = (
        await db.session.execute(select(HubUser).where(HubUser.email == email))
    ).scalars().first()
    assert sso is None


@pytest.mark.asyncio
async def test_resolve_session_known_admin(saml_ctx, db):
    from server.app.core.auth.saml.identity_service import SamlIdentityService
    from server.app.database.models import AdminAccount

    email = f"admin-{_uid()}@uji.es"
    db.track(email)
    db.session.add(
        AdminAccount(partner_id=f"p-{_uid()}", name="Admin Test", email=email)
    )
    await db.session.commit()

    info = await SamlIdentityService(db.session).resolve_session(
        nameid=email, attributes={"mail": [email]}
    )
    assert info.role == "admin"
    assert info.email == email


@pytest.mark.asyncio
async def test_resolve_session_jit_provision_with_group_role(saml_ctx, db, monkeypatch):
    from server.app.core.auth.saml.identity_service import SamlIdentityService
    from server.app.modules.agents_hub.database.config_models import HubUser
    from sqlalchemy import select

    # IDE.1 — el mapeo grupo->rol solo manda cuando la autoridad del rol es el IdP. Con el
    # defecto (`app`) se ignora a propósito: el rol lo pone una persona, y un IdP que emitiera
    # `superadmin` acuñaría un superadministrador en el primer inicio de sesión. Lo que este
    # test comprueba —que el mapeo funciona— sigue siendo cierto, ahora en su modo.
    monkeypatch.setenv("IDENTITY_ROLE_AUTHORITY", "idp")
    monkeypatch.setenv("SAML_GROUP_ROLE_MAP", '{"pas-info": "admin"}')
    email = f"jit-{_uid()}@uji.es"
    db.track(email)

    info = await SamlIdentityService(db.session).resolve_session(
        nameid=email,
        attributes={
            "mail": [email],
            "displayName": ["JIT User"],
            "groups": ["pas-info"],
        },
    )
    assert info.role == "admin"
    sso = (
        await db.session.execute(select(HubUser).where(HubUser.email == email))
    ).scalars().first()
    assert sso is not None
    assert sso.role == "admin"
    assert sso.display_name == "JIT User"


@pytest.mark.asyncio
async def test_resolve_session_jit_default_role(saml_ctx, db):
    from server.app.core.auth.saml.identity_service import SamlIdentityService

    email = f"jit-{_uid()}@uji.es"
    db.track(email)
    info = await SamlIdentityService(db.session).resolve_session(
        nameid=email, attributes={"mail": [email]}
    )
    assert info.role == "user"


@pytest.mark.asyncio
async def test_resolve_session_second_login_no_duplicate(saml_ctx, db):
    from server.app.core.auth.saml.identity_service import SamlIdentityService
    from server.app.modules.agents_hub.database.config_models import HubUser
    from sqlalchemy import func, select

    email = f"jit-{_uid()}@uji.es"
    db.track(email)
    service = SamlIdentityService(db.session)
    await service.resolve_session(nameid=email, attributes={"mail": [email]})
    await service.resolve_session(nameid=email, attributes={"mail": [email]})

    count = (
        await db.session.execute(
            select(func.count()).select_from(HubUser).where(HubUser.email == email)
        )
    ).scalar_one()
    assert count == 1
    sso = (
        await db.session.execute(select(HubUser).where(HubUser.email == email))
    ).scalars().first()
    assert sso.last_login_at is not None


@pytest.mark.asyncio
async def test_resolve_session_missing_email_raises(saml_ctx, db):
    from server.app.core.auth.saml.identity_service import (
        SamlIdentityService,
        SamlMissingEmailError,
    )

    with pytest.raises(SamlMissingEmailError):
        await SamlIdentityService(db.session).resolve_session(
            nameid="no-email", attributes={"displayName": ["No Email"]}
        )


# --------------------------------------------------------------------------- #
# ACS completo: aserción firmada → JWT → redirect                               #
# --------------------------------------------------------------------------- #
def test_acs_issues_jwt_and_redirects(saml_ctx, db, db_url):
    from sqlalchemy.ext.asyncio import create_async_engine

    from server.app.api.deps import get_session
    from server.app.core.auth import decode_token
    from server.app.routers.saml_auth_router import router
    from sqlmodel.ext.asyncio.session import AsyncSession

    email = f"ada-{_uid()}@uji.es"

    # Contra la BD desechable del test (`db_url`), no contra `DATABASE_URL`. La versión
    # anterior leía el DSN del entorno y acababa apuntando al PostgreSQL del desarrollador:
    # en local pasaba —ese servidor tiene el esquema migrado— y de paso dejaba escrita una
    # fila de usuario real, que es lo que TST.2 vino a cerrar. En CI no se ejecutan las
    # migraciones: el servicio de Postgres arranca vacío y el esquema lo crea el fixture
    # `db` sobre la copia desechable, así que el test moría con
    # `relation "superadminaccount" does not exist`. `db` ya ha hecho el `create_all` de
    # SQLModel sobre esta misma BD, que es la que el router tiene que ver.

    async def _override_session():
        # Engine creado dentro del request → vive en el loop del TestClient.
        eng = create_async_engine(db_url)
        try:
            async with AsyncSession(eng) as s:
                yield s
        finally:
            await eng.dispose()

    app = FastAPI()
    app.dependency_overrides[get_session] = _override_session
    app.include_router(router, prefix="/api/v1")
    client = TestClient(app, base_url=saml_ctx.base_url)

    # El SP sólo acepta la respuesta a una petición suya hecha desde este navegador: primero el
    # login, que deja el ID de la petición en una cookie, y la respuesta contesta a ese ID.
    assert client.get("/api/v1/auth/saml/login", follow_redirects=False).status_code == 302
    peticion = client.cookies.get("govgenai_saml_peticion")

    saml_response = saml_ctx.make_response(
        email=email,
        attributes={"mail": [email], "displayName": ["Ada Lovelace"]},
        in_response_to=peticion,
    )
    resp = client.post(
        "/api/v1/auth/saml/acs",
        data={"SAMLResponse": saml_response},
        follow_redirects=False,
    )
    assert resp.status_code == 302, resp.text
    location = resp.headers["location"]
    assert location.startswith(saml_ctx.return_url + "#token=")

    token = location.split("#token=", 1)[1]
    info = decode_token(token)
    assert info.email == email
    assert info.role == "user"


# --------------------------------------------------------------------------- #
# La organización de un usuario SAML (SEC.2.1, encargo heredado de SEC.2)       #
#                                                                               #
# SEC.2 dejó a los usuarios provisionados por SSO con el claim vacío y, por su  #
# propia regla, sin acceso a ningún recurso de organización. Se cierra aquí, y  #
# la decisión es de dónde sale el dato: **de la configuración del IdP, nunca de #
# la aserción**. Si viniera de fuera, quien controla el IdP podría declarar a   #
# qué organización pertenece cada persona que entra. Un IdP institucional       #
# pertenece a una institución, y esa relación la fija quien despliega.          #
# --------------------------------------------------------------------------- #
ORG_DEL_IDP = "00000000-0000-0000-0000-0000000000f1"
ORG_RECLAMADA = "00000000-0000-0000-0000-0000000000f2"


async def _crear_organizacion(db, organizacion_id: str) -> None:
    """La organización tiene que existir: `hub_users.organizacion_id` es una FK."""
    import uuid as _uuid

    from server.app.modules.agents_hub.database.config_models import HubOrganizacion

    db.session.add(
        HubOrganizacion(
            id=_uuid.UUID(organizacion_id),
            name=f"Org {organizacion_id[-4:]}",
            partner_id=f"partner-{_uid()}",
        )
    )
    await db.session.commit()


@pytest.mark.asyncio
async def test_should_take_the_organizacion_from_the_idp_configuration(
    saml_ctx, db, monkeypatch
):
    from server.app.core.auth.saml.identity_service import SamlIdentityService
    from server.app.modules.agents_hub.database.config_models import HubUser
    from sqlalchemy import select

    monkeypatch.setenv("SAML_ORGANIZACION_ID", ORG_DEL_IDP)
    await _crear_organizacion(db, ORG_DEL_IDP)
    email = f"org-idp-{_uid()}@uji.es"
    db.track(email)

    info = await SamlIdentityService(db.session).resolve_session(
        nameid=email, attributes={"mail": [email]}
    )

    assert info.organizacion_ids == (ORG_DEL_IDP,)
    sso = (
        await db.session.execute(select(HubUser).where(HubUser.email == email))
    ).scalars().first()
    assert str(sso.organizacion_id) == ORG_DEL_IDP


@pytest.mark.asyncio
async def test_should_ignore_an_organizacion_claimed_in_the_assertion(
    saml_ctx, db, monkeypatch
):
    """Anti-escalada: el atributo de la aserción no concede organización."""
    from server.app.core.auth.saml.identity_service import SamlIdentityService

    monkeypatch.setenv("SAML_ORGANIZACION_ID", ORG_DEL_IDP)
    await _crear_organizacion(db, ORG_DEL_IDP)
    email = f"org-escalada-{_uid()}@uji.es"
    db.track(email)

    info = await SamlIdentityService(db.session).resolve_session(
        nameid=email,
        attributes={
            "mail": [email],
            "organizacion_id": [ORG_RECLAMADA],
            "orgs": [ORG_RECLAMADA],
        },
    )

    assert info.organizacion_ids == (ORG_DEL_IDP,)
    assert ORG_RECLAMADA not in info.organizacion_ids


@pytest.mark.asyncio
async def test_should_provision_without_organizacion_when_the_idp_declares_none(
    saml_ctx, db, monkeypatch
):
    """Fail-closed: sin configuración no se inventa una organización."""
    from server.app.core.auth.saml.identity_service import SamlIdentityService

    monkeypatch.delenv("SAML_ORGANIZACION_ID", raising=False)
    email = f"org-vacia-{_uid()}@uji.es"
    db.track(email)

    info = await SamlIdentityService(db.session).resolve_session(
        nameid=email, attributes={"mail": [email]}
    )

    assert info.organizacion_ids == ()


@pytest.mark.asyncio
async def test_should_not_break_the_login_when_the_configured_organizacion_is_unknown(
    saml_ctx, db, monkeypatch
):
    """Un id mal escrito en la configuración no puede tirar el login por la clave ajena.

    Caerse al entrar es peor que no dar acceso: el usuario entra sin organización —el mismo
    fallo seguro que sin configurar nada— y el despliegue se entera por el log.
    """
    from server.app.core.auth.saml.identity_service import SamlIdentityService

    monkeypatch.setenv("SAML_ORGANIZACION_ID", "00000000-0000-0000-0000-0000000000ff")
    email = f"org-inexistente-{_uid()}@uji.es"
    db.track(email)

    info = await SamlIdentityService(db.session).resolve_session(
        nameid=email, attributes={"mail": [email]}
    )

    assert info.organizacion_ids == ()


@pytest.mark.asyncio
async def test_should_carry_the_saml_groups_into_the_session(saml_ctx, db):
    """Los grupos viajan en la sesión: `restricted` de SEC.2.1 los necesita."""
    from server.app.core.auth.saml.identity_service import SamlIdentityService

    email = f"grupos-{_uid()}@uji.es"
    db.track(email)

    info = await SamlIdentityService(db.session).resolve_session(
        nameid=email, attributes={"mail": [email], "groups": ["gerencia", "pas"]}
    )

    assert info.saml_groups == ("gerencia", "pas")


def test_should_leave_existing_sso_users_without_organizacion_after_migration():
    """Ningún usuario SSO existente hereda una organización al migrar.

    Que la columna quede nullable y sin default lo comprueba, ejecutando la migración,
    `tests/infra/test_migrations_fresh_install.py`. Lo que solo se ve leyendo el fichero es
    la ausencia de un `UPDATE`: una instalación limpia no tiene usuarios previos a los que
    repartir organización, así que allí un backfill pasaría inadvertido.
    """
    from pathlib import Path

    # Se busca la migración que **añade la columna**, no «la más reciente que mencione las dos
    # palabras»: con ese criterio, la de IDE.2 —que renombra la tabla y por eso nombra los
    # índices `ix_hub_sso_users_organizacion_id`— pasó a ser la elegida y el test se puso rojo
    # sin que nada de lo que vigila hubiera cambiado.
    ficheros = [
        f
        for f in Path("migrations/versions").glob("*.py")
        if 'sa.Column("organizacion_id"' in f.read_text(encoding="utf-8")
        and "hub_sso_users" in f.read_text(encoding="utf-8")
    ]
    assert ficheros, "ninguna migración añade organizacion_id a hub_sso_users"
    assert len(ficheros) == 1, f"se esperaba una sola migración que añada la columna: {ficheros}"
    texto = ficheros[0].read_text(encoding="utf-8")
    arriba = texto.split("def downgrade")[0]

    assert "nullable=True" in arriba
    assert "UPDATE hub_sso_users" not in arriba, (
        "ningún usuario SSO existente puede heredar una organización por migración"
    )
