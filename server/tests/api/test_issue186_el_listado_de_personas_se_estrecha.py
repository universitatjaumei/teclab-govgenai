"""Issue #186 (MT.9) — estrechar el listado de Personas a la organización elegida.

**Lo que no falta, y va primero para que nadie lo lea como un agujero**: el listado ya está
acotado por tenencia desde USR.9, y la acotación la hace `scope_query_to_orgs`, no un `if` del
router. Quien administra una organización ve la suya y nada más. Esto es la capa de encima: la
comodidad de mirar una organización cada vez cuando se pueden ver varias.

**Por qué no entró en MT.8.** `hub_users` es `heredable`, no `organizacion`, y ahí la regla
cambia: en herencia «nulo» no significa «de nadie», significa «de plataforma». Un filtro ingenuo
escondería las cuentas que no pertenecen a ninguna —las de arranque, entre otras— y eso no es
acotar, es ocultar.

**Las tres decisiones, tomadas el 2026-09-28** y por eso esto ya se puede programar:

1. Al estrechar se enseñan **sólo las cuentas de esa organización**, y la pantalla **dice cuántas
   se dejan fuera**. Ocultar sin decirlo es lo que el proyecto viene evitando; ocultar diciéndolo
   es acotar. Por eso la respuesta deja de ser una lista pelada y pasa a llevar el recuento: el
   servidor lo dice, la pantalla lo pinta.
2. Las cuentas de arranque son de plataforma, así que entran en ese recuento y no en la lista.
3. El control es **el de la cabecera**, el mismo que el resto del panel: MT.8 acabó de hacer que
   la organización elegida sea una sola, y el alta de una persona ya la usa para preseleccionar.

El patrón del endpoint es el de `list_sites` (SEC.8.1) y `list_chatbots` (MT.8): tenencia
primero, filtro después, 403 si se pide una organización ajena.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

ORG_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
ORG_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


async def _persona(sesion, *, email: str, organizacion_id: uuid.UUID | None):
    from server.app.modules.agents_hub.database.config_models import HubUser

    fila = HubUser(
        id=uuid.uuid4(),
        email=email,
        display_name="Quien sea",
        role="user",
        organizacion_id=organizacion_id,
        is_active=True,
        origen="manual",
    )
    sesion.add(fila)
    await sesion.flush()
    return fila


async def _poblar(db_url: str):
    """Dos organizaciones y una cuenta que no es de ninguna."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from server.app.modules.agents_hub.database.config_models import HubOrganizacion

    from server.app.database.models import SuperAdminAccount

    motor = create_async_engine(db_url)
    # La base desechable la crean los metadatos del hub; `superadminaccount` vive en otra base
    # declarativa y el listado la lee (REV.8), así que sin esto el endpoint revienta con
    # `UndefinedTable` y el test mediría eso en vez de lo suyo.
    async with motor.begin() as conexion:
        await conexion.run_sync(
            SuperAdminAccount.metadata.create_all,
            tables=[SuperAdminAccount.__table__],
        )

    async with AsyncSession(motor, expire_on_commit=False) as sesion:
        sesion.add(
            SuperAdminAccount(
                name="Mantenedor", email="arranque@uji.es", hashed_password="x"
            )
        )
        for identificador, nombre in ((ORG_A, "Alfa"), (ORG_B, "Beta")):
            sesion.add(
                HubOrganizacion(id=identificador, name=nombre, partner_id=nombre.lower())
            )
        await sesion.flush()
        await _persona(sesion, email="de-alfa@uji.es", organizacion_id=ORG_A)
        await _persona(sesion, email="de-beta@uji.es", organizacion_id=ORG_B)
        await _persona(sesion, email="de-nadie@uji.es", organizacion_id=None)
        await sesion.commit()
    await motor.dispose()
    return motor


def _superadmin():
    from server.app.core.auth.models import UserInfo

    return UserInfo(user_id=str(uuid.uuid4()), email="jefe@uji.es", role="superadmin")


def _admin_de(*organizaciones):
    from server.app.core.auth.models import UserInfo

    return UserInfo(
        user_id=str(uuid.uuid4()),
        email="admin@uji.es",
        role="admin",
        organizacion_ids=tuple(str(o) for o in organizaciones),
    )


async def _listar(db_url, quien, organizacion_id=None):
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlmodel.ext.asyncio.session import AsyncSession

    from server.app.routers.hub_users_router import list_users

    motor = create_async_engine(db_url)
    try:
        async with AsyncSession(motor) as sesion:
            return await list_users(
                organizacion_id=organizacion_id, user=quien, session=sesion
            )
    finally:
        await motor.dispose()


class TestEstrecharALaOrganizacionElegida:

    @pytest.mark.asyncio
    async def test_sin_filtro_se_siguen_viendo_todas(self, db_url):
        """El comportamiento de siempre: el filtro es opcional y no cambia nada por existir."""
        await _poblar(db_url)

        listado = await _listar(db_url, _superadmin())

        correos = {p.email for p in listado.personas}
        assert {"de-alfa@uji.es", "de-beta@uji.es", "de-nadie@uji.es"} <= correos
        assert listado.de_plataforma_no_mostradas == 0

    @pytest.mark.asyncio
    async def test_con_filtro_solo_las_de_esa_organizacion(self, db_url):
        await _poblar(db_url)

        listado = await _listar(db_url, _superadmin(), organizacion_id=ORG_A)

        assert [p.email for p in listado.personas] == ["de-alfa@uji.es"]

    @pytest.mark.asyncio
    async def test_y_se_dice_cuantas_se_dejan_fuera(self, db_url):
        """Ocultar sin decirlo no es acotar. La cuenta de nadie y las de arranque cuentan."""
        await _poblar(db_url)

        listado = await _listar(db_url, _superadmin(), organizacion_id=ORG_A)

        assert listado.de_plataforma_no_mostradas >= 1, (
            "el listado estrechado esconde las cuentas que no son de ninguna organización sin "
            "decir que existen"
        )

    @pytest.mark.asyncio
    async def test_las_de_arranque_no_se_cuelan_en_el_listado_estrechado(self, db_url):
        """Son de plataforma: entran en el recuento, no en la lista."""
        await _poblar(db_url)

        listado = await _listar(db_url, _superadmin(), organizacion_id=ORG_A)

        assert all(p.origen != "superadminaccount" for p in listado.personas)


class TestLaTenenciaManda:
    """El filtro es comodidad; la frontera la sigue poniendo `scope_query_to_orgs`."""

    @pytest.mark.asyncio
    async def test_pedir_una_organizacion_ajena_es_403(self, db_url):
        await _poblar(db_url)

        with pytest.raises(HTTPException) as fallo:
            await _listar(db_url, _admin_de(ORG_A), organizacion_id=ORG_B)

        assert fallo.value.status_code == 403

    @pytest.mark.asyncio
    async def test_la_propia_si(self, db_url):
        """Sin esto, lo de arriba se cumpliría negándoselo también a quien la administra."""
        await _poblar(db_url)

        listado = await _listar(db_url, _admin_de(ORG_A), organizacion_id=ORG_A)

        assert [p.email for p in listado.personas] == ["de-alfa@uji.es"]

    @pytest.mark.asyncio
    async def test_sin_filtro_un_admin_sigue_viendo_solo_lo_suyo(self, db_url):
        """La acotación por tenencia no depende de que se pida el filtro."""
        await _poblar(db_url)

        listado = await _listar(db_url, _admin_de(ORG_A))

        assert [p.email for p in listado.personas] == ["de-alfa@uji.es"]
