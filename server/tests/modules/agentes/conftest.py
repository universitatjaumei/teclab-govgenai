"""Fixtures del catálogo de agentes de unidad (#172).

Copia deliberada de la de `tests/modules/agents_hub/conftest.py`, como las de `curation` y
`redaccion`: los agentes viven en tablas operacionales, que están en la base desechable
de cada test.
"""
from __future__ import annotations

# ── Orden de importación obligatorio, no reordenar ─────────────────────────────
# En Windows, cargar torch DESPUÉS de abrir una conexión asyncpg aborta el proceso con
# «access violation»; al revés funciona. Es la regla de APER.16, y la vigila
# `tests/infra/test_aper16_los_conftest_cargan_torch_antes_que_asyncpg.py`, que se puso rojo
# en CI con este fichero. `langchain_text_splitters` arrastra torch.
import langchain_text_splitters  # noqa: F401  ← debe ir primero

import pytest


@pytest.fixture
async def db_session(db_url: str):
    """Sesión sobre la BD desechable. Sin drop_all: la BD entera se borra al final."""
    from server.app.modules.agents_hub.database.connection import (
        create_async_engine,
        create_session_factory,
    )

    engine = create_async_engine(db_url)
    session_factory = create_session_factory(engine)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def http(db_session):
    """Un cliente contra los dos routers de agentes, con la persona cambiable entre llamadas.

    Con la cabecera `X-Prueba-Scopes` la petición llega como la de un token personal: es lo que
    hace `get_current_user` al autenticar uno, dejar sus scopes en el estado.
    """
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from server.app.api.deps import get_current_user, get_session
    from server.app.routers.agentes_router import obtener_embedder, router, router_catalogo
    from server.tests.modules.agentes._comun import Quien
    from server.tests.modules.agentes.test_agu2_indice import EmbebedorFalso

    quien = Quien()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.include_router(router_catalogo, prefix="/api/v1")

    async def _sesion():
        yield db_session

    app.dependency_overrides[get_current_user] = lambda: quien.actual
    app.dependency_overrides[get_session] = _sesion
    app.dependency_overrides[obtener_embedder] = lambda: EmbebedorFalso()
    for dependencia in router.dependencies:
        app.dependency_overrides[dependencia.dependency] = lambda: quien.actual

    @app.middleware("http")
    async def _como_un_pat(request, call_next):
        if "x-prueba-scopes" in request.headers:
            request.state.pat_scopes = set(request.headers["x-prueba-scopes"].split(","))
        return await call_next(request)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://prueba") as c:
        yield c, quien

