"""Un token personal vale lo que vale hoy su dueño, no lo que valía al emitirlo.

`PatService.verify` construía el principal con el rol **guardado en la fila del token** y no
miraba si la persona seguía existiendo o activa. Así, desactivar, borrar o rebajar a alguien no
tocaba los tokens que ya había emitido, y como la caducidad era opcional, podían no caducar
nunca. Tampoco había forma de que un superadministrador revocara el token de otra persona.

Se fija:

* un token deja de valer si su dueño ya no existe, está inactivo o **ya no tiene el rol** con el
  que lo emitió —el alcance se decidió con el techo de ese rol, así que no se reinterpreta: se
  emite otro—;
* un token nuevo caduca siempre: por omisión a los 90 días, y nunca más allá de un año;
* un superadministrador revoca el token de cualquiera.

Contra la base y sin sobreescribir el principal, que es el camino que ya escondió un defecto
en VAS.2.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from server.app.core.auth.models import UserInfo
from server.app.core.auth.pat.service import PatForbiddenError, PatInvalidError, PatService


@pytest.fixture
async def sesion(db_url):
    from server.app.database.models import AdminAccount

    engine = create_async_engine(db_url)
    # La plantilla de tests sólo lleva las tablas del hub; la de cuentas de partner hace falta
    # porque un dueño con forma de uuid que no es persona se busca también ahí.
    async with engine.begin() as conexion:
        await conexion.run_sync(AdminAccount.__table__.create, checkfirst=True)  # type: ignore[attr-defined]
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session
    finally:
        await engine.dispose()


async def _persona(session, role: str = "admin"):
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion, HubUser

    org = HubOrganizacion(id=uuid.uuid4(), name=f"Org {uuid.uuid4().hex[:6]}", partner_id="uji")
    session.add(org)
    await session.flush()
    persona = HubUser(
        id=uuid.uuid4(),
        email=f"{role}.{uuid.uuid4().hex[:6]}@uji.es",
        role=role,
        organizacion_id=org.id,
    )
    session.add(persona)
    await session.commit()
    principal = UserInfo(
        user_id=str(persona.id), email=persona.email, role=role, organizacion_ids=(str(org.id),)
    )
    return persona, principal


class TestElTokenDejaDeValerConSuDueno:

    async def test_should_still_work_for_an_active_owner(self, sesion):
        persona, principal = await _persona(sesion)
        _, token = await PatService(sesion).create(principal, "t", ["actividad:write"])

        verificado = await PatService(sesion).verify(token)

        assert verificado.user_info.user_id == str(persona.id)

    async def test_should_stop_working_when_the_owner_is_deactivated(self, sesion):
        persona, principal = await _persona(sesion)
        _, token = await PatService(sesion).create(principal, "t", ["actividad:write"])

        persona.is_active = False
        await sesion.commit()

        with pytest.raises(PatInvalidError):
            await PatService(sesion).verify(token)

    async def test_should_stop_working_when_the_owner_is_deleted(self, sesion):
        persona, principal = await _persona(sesion)
        _, token = await PatService(sesion).create(principal, "t", ["actividad:write"])

        await sesion.delete(persona)
        await sesion.commit()

        with pytest.raises(PatInvalidError):
            await PatService(sesion).verify(token)

    async def test_should_stop_working_when_the_owner_loses_the_role(self, sesion):
        persona, principal = await _persona(sesion, role="admin")
        _, token = await PatService(sesion).create(principal, "t", ["actividad:write"])

        persona.role = "user"
        await sesion.commit()

        with pytest.raises(PatInvalidError):
            await PatService(sesion).verify(token)


class TestUnTokenNuevoCaducaSiempre:

    async def test_should_expire_in_90_days_when_nothing_is_said(self, sesion):
        _, principal = await _persona(sesion)

        fila, _ = await PatService(sesion).create(principal, "t", ["actividad:write"])

        dias = (fila.expires_at - datetime.now(timezone.utc)).days
        assert 89 <= dias <= 90

    async def test_should_refuse_an_expiry_beyond_a_year(self, sesion):
        _, principal = await _persona(sesion)

        with pytest.raises(PatForbiddenError):
            await PatService(sesion).create(
                principal,
                "t",
                ["actividad:write"],
                expires_at=datetime.now(timezone.utc) + timedelta(days=400),
            )


class TestUnSuperadministradorRevocaElDeCualquiera:

    async def test_should_let_a_superadmin_revoke_someone_elses_token(self, sesion):
        _, principal = await _persona(sesion)
        fila, token = await PatService(sesion).create(principal, "t", ["actividad:write"])
        root = UserInfo(user_id="root", email="root@uji.es", role="superadmin")

        await PatService(sesion).revoke(root, fila.id)

        with pytest.raises(PatInvalidError):
            await PatService(sesion).verify(token)

    async def test_should_still_refuse_an_admin_revoking_someone_elses_token(self, sesion):
        _, principal = await _persona(sesion)
        fila, _ = await PatService(sesion).create(principal, "t", ["actividad:write"])
        _, otro = await _persona(sesion)

        with pytest.raises(PatInvalidError):
            await PatService(sesion).revoke(otro, fila.id)


class TestCadaFormaDeDuenoSeReconoce:
    """Revisión de la PR #294: el `partner_id` de una cuenta de partner es texto libre."""

    async def test_should_accept_a_partner_admin_whose_code_looks_like_a_uuid(self, sesion):
        from server.app.database.models import AdminAccount

        codigo = str(uuid.uuid4())
        sesion.add(AdminAccount(partner_id=codigo, name="Partner", email=f"p.{codigo[:8]}@uji.es"))
        await sesion.commit()
        principal = UserInfo(user_id=codigo, email="p@uji.es", role="admin")
        _, token = await PatService(sesion).create(principal, "t", ["actividad:write"])

        verificado = await PatService(sesion).verify(token)

        assert verificado.user_info.user_id == codigo


class TestUnaFechaSinZonaSeLeeEnUTC:

    async def test_should_take_a_naive_expiry_as_utc_instead_of_failing(self, sesion):
        _, principal = await _persona(sesion)
        sin_zona = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30)

        fila, _ = await PatService(sesion).create(
            principal, "t", ["actividad:write"], expires_at=sin_zona
        )

        assert 29 <= (fila.expires_at - datetime.now(timezone.utc)).days <= 30
