"""INF.7 — el acceso a cada módulo se concede, y el servidor lo dice.

Antes no había control de acceso por función: `App.tsx` metía todas las rutas bajo un
`PrivateRoute` que solo comprobaba que hubiera sesión, no existía un solo `role ===` en la capa
de navegación, y los routers de `redaccion` usaban `get_current_user` a secas. Con el módulo de
informes abierto a toda la organización, cualquier trabajador con cuenta podía listar y editar
los chatbots institucionales y la configuración de LLM.

Decisión del usuario (2026-08-20): **por módulos concedidos, no por rol nuevo**. Un rol
`redactor` explota en cuanto alguien necesite informes y curación pero no chatbots; y el rol
`informer` que ya existe es control de calidad de chatbots, no autoría de informes.
"""
from __future__ import annotations


import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from server.app.core.auth.models import UserInfo
from server.app.modules.agents_hub.database.config_models import HubModuleGrant as ModuleGrant, HubPlatformModule as PlatformModule
from server.app.routers.redaccion._actor import user_to_uuid

_MODULOS = ("chatbots", "curacion", "informes", "plataforma")


async def _catalogo(session, retirado: str | None = None) -> None:
    for codigo in _MODULOS:
        session.add(
            PlatformModule(code=codigo, label=codigo.title(), vigente=codigo != retirado)
        )
    await session.commit()


async def _conceder(session, user_id: str, *codigos: str) -> None:
    for codigo in codigos:
        session.add(
            ModuleGrant(subject_id=str(user_to_uuid(user_id)), module_code=codigo)
        )
    await session.commit()


@pytest.mark.sin_guarda_de_modulos
@pytest.mark.asyncio
async def test_should_grant_every_module_to_a_superadmin_without_a_row(db_url):
    """El superadmin entra en todo por su rol.

    Hacerlo depender de una fila deja una instalación recién creada con un superadmin encerrado
    fuera de todo: `bootstrap` crea la cuenta, no sus permisos.
    """
    from server.app.core.auth.modulos_service import modulos_del_usuario

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            await _catalogo(session)
            modulos = await modulos_del_usuario(
                session, UserInfo(user_id="1", email="x@uji.es", role="superadmin")
            )
            assert modulos == sorted(_MODULOS)
    finally:
        await engine.dispose()


@pytest.mark.sin_guarda_de_modulos
@pytest.mark.asyncio
async def test_should_give_a_plain_user_only_what_was_granted(db_url):
    from server.app.core.auth.modulos_service import modulos_del_usuario

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            await _catalogo(session)
            await _conceder(session, "trabajador-1", "informes")

            modulos = await modulos_del_usuario(
                session, UserInfo(user_id="trabajador-1", email="t@uji.es", role="user")
            )
            assert modulos == ["informes"]
    finally:
        await engine.dispose()


@pytest.mark.sin_guarda_de_modulos
@pytest.mark.asyncio
async def test_should_give_nothing_to_someone_with_no_grants(db_url):
    """Sin fila no hay acceso. Es el caso que hoy dejaba a cualquiera editar los chatbots."""
    from server.app.core.auth.modulos_service import modulos_del_usuario

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            await _catalogo(session)
            modulos = await modulos_del_usuario(
                session, UserInfo(user_id="nadie", email="n@uji.es", role="user")
            )
            assert modulos == []
    finally:
        await engine.dispose()


@pytest.mark.sin_guarda_de_modulos
@pytest.mark.asyncio
async def test_should_ignore_a_grant_to_a_retired_module(db_url):
    """La fila de una concesión es el histórico de quién tuvo acceso, no un permiso vivo."""
    from server.app.core.auth.modulos_service import modulos_del_usuario

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            await _catalogo(session, retirado="curacion")
            await _conceder(session, "trabajador-2", "curacion", "informes")

            modulos = await modulos_del_usuario(
                session, UserInfo(user_id="trabajador-2", email="t@uji.es", role="user")
            )
            assert modulos == ["informes"]
    finally:
        await engine.dispose()


@pytest.mark.sin_guarda_de_modulos
@pytest.mark.asyncio
async def test_should_refuse_the_endpoint_without_the_module_and_say_which_one(db_url):
    """El 403 nombra el módulo que falta: quien lo recibe tiene que poder pedirlo."""
    from server.app.api.deps import require_module

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            await _catalogo(session)
            await _conceder(session, "solo-informes", "informes")
            from server.app.core.auth.modulos_service import modulos_del_usuario

            usuario = UserInfo(user_id="solo-informes", email="t@uji.es", role="user")
            concedidos = await modulos_del_usuario(session, usuario)

            with pytest.raises(HTTPException) as fallo:
                await require_module("chatbots")(user=usuario, concedidos=concedidos)

            assert fallo.value.status_code == 403
            assert fallo.value.detail["modulo_requerido"] == "chatbots"
    finally:
        await engine.dispose()


@pytest.mark.sin_guarda_de_modulos
@pytest.mark.asyncio
async def test_should_let_through_the_endpoint_of_a_granted_module(db_url):
    from server.app.api.deps import require_module

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            await _catalogo(session)
            await _conceder(session, "solo-informes", "informes")

            from server.app.core.auth.modulos_service import modulos_del_usuario

            usuario = UserInfo(user_id="solo-informes", email="t@uji.es", role="user")
            concedidos = await modulos_del_usuario(session, usuario)
            devuelto = await require_module("informes")(user=usuario, concedidos=concedidos)
            assert devuelto is usuario
    finally:
        await engine.dispose()


@pytest.mark.sin_guarda_de_modulos
@pytest.mark.asyncio
async def test_should_expose_the_modules_in_auth_me(db_url):
    """La lista viaja en `/auth/me`: es de donde el frontend saca el menú y las rutas."""
    from server.app.routers.auth_router import get_me

    engine = create_async_engine(db_url)
    try:
        async with AsyncSession(engine) as session:
            await _catalogo(session)
            await _conceder(session, "trabajador-3", "informes", "curacion")

            salida = await get_me(
                current_user=UserInfo(user_id="trabajador-3", email="t@uji.es", role="user"),
                session=session,
            )

            assert salida.modulos == ["curacion", "informes"]
            # Y sigue trayendo lo de antes: nadie que dependiera de `/auth/me` se rompe.
            assert salida.email == "t@uji.es"
            assert salida.role == "user"
    finally:
        await engine.dispose()
