"""UTL — un módulo **de oficio** lo tiene cualquier persona de la plataforma, sin concesión.

Decisión del usuario (2026-10-02): las utilidades son de todo el mundo. Unir dos PDF o quitarle
los datos personales a un listado no es una capacidad que haya que repartir; lo que había que
evitar es que alguien tuviera que ir a buscarla fuera.

**Una marca del catálogo y no una concesión por persona.** Conceder a cada cuenta obligaría a
acordarse en cada alta —también en las que llegan por Google o por SAML—, y la que se olvidara
dejaría a alguien sin el módulo y sin que nada lo dijera. Con `de_oficio` en `hub_platform_modules`
la regla está en un sitio, es dato y no código, y vale para quien entre mañana.

Lo que fija este fichero:

* cualquier rol la tiene sin fila; **retirada del catálogo, nadie**;
* su origen se dice: «de oficio», no una concesión que no existe;
* concederla no tiene sentido, y se rechaza en vez de escribir una fila que no cambia nada;
* el catálogo lo enseña, para que la pantalla de concesiones no la ofrezca.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from server.app.core.auth.models import UserInfo
from server.app.modules.agents_hub.database.config_models import (
    HubPlatformModule as PlatformModule,
)


async def _catalogo(session, *, utilidades_vigente: bool = True) -> None:
    session.add(PlatformModule(code="informes", label="Informes", vigente=True))
    session.add(
        PlatformModule(
            code="utilidades", label="Utilidades", vigente=utilidades_vigente, de_oficio=True
        )
    )
    await session.commit()


def _persona(rol: str = "user") -> UserInfo:
    return UserInfo(user_id=f"persona-{rol}", email="p@uji.es", role=rol)


@pytest.mark.sin_guarda_de_modulos
@pytest.mark.asyncio
@pytest.mark.parametrize("rol", ["user", "informer", "admin"])
async def test_cualquier_rol_la_tiene_sin_concesion(db_url, rol):
    from server.app.core.auth.modulos_service import modulos_del_usuario

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            await _catalogo(session)
            assert await modulos_del_usuario(session, _persona(rol)) == ["utilidades"]
    finally:
        await engine.dispose()


@pytest.mark.sin_guarda_de_modulos
@pytest.mark.asyncio
async def test_retirada_del_catalogo_no_la_tiene_nadie(db_url):
    from server.app.core.auth.modulos_service import modulos_del_usuario

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            await _catalogo(session, utilidades_vigente=False)
            assert await modulos_del_usuario(session, _persona()) == []
    finally:
        await engine.dispose()


@pytest.mark.sin_guarda_de_modulos
@pytest.mark.asyncio
async def test_su_origen_es_de_oficio(db_url):
    """Un permiso cuyo origen no se ve es un permiso que nadie sabe de dónde viene."""
    from server.app.core.auth.modulos_service import modulos_con_origen

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            await _catalogo(session)
            origen = await modulos_con_origen(session, _persona())
            assert origen == {
                "utilidades": [{"tipo": "de_oficio", "sujeto": "", "organizacion": ""}]
            }
    finally:
        await engine.dispose()


@pytest.mark.sin_guarda_de_modulos
@pytest.mark.asyncio
async def test_concederla_se_rechaza(db_url):
    from server.app.routers.hub_modulos_router import ConcesionCreate, conceder

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            await _catalogo(session)
            with pytest.raises(HTTPException) as fallo:
                await conceder(
                    body=ConcesionCreate(
                        subject_type="usuario", subject_id="alguien", module_code="utilidades"
                    ),
                    user=_persona("superadmin"),
                    session=session,
                )
            assert fallo.value.status_code == 400
            assert "de oficio" in fallo.value.detail
    finally:
        await engine.dispose()


@pytest.mark.sin_guarda_de_modulos
@pytest.mark.asyncio
async def test_el_catalogo_lo_dice(db_url):
    from server.app.routers.hub_modulos_router import get_catalogo

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            await _catalogo(session)
            catalogo = {m.code: m for m in await get_catalogo(_=_persona("superadmin"), session=session)}
            assert catalogo["utilidades"].de_oficio is True
            assert catalogo["informes"].de_oficio is False
    finally:
        await engine.dispose()
