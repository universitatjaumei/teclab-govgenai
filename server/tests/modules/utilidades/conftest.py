"""Fixtures de las utilidades de uso directo (UTL).

Copia deliberada de la de `tests/modules/agents_hub/conftest.py`, como las de `curation` y
`redaccion`: las utilidades anotan su uso en `hub_actividad_ia`, que vive en la base desechable
de cada test.
"""
from __future__ import annotations

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
