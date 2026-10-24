"""#272 — un solo engine y un solo `get_session`, y su comportamiento escrito.

Había tres proveedores de sesión sobre dos engines, y no se comportaban igual:

* `api/deps.get_session` abría una `AsyncSession` sobre `server_engine` **con** `expire_on_commit` —el valor
  por omisión—: commitear y leer después un atributo daba 500 (`MissingGreenlet`), y el fixture
  `db_session` de los tests no lo reproducía.
* `database/db.get_session`, sin uso, lo abría **sin** él.
* `agents_hub/database/connection.get_async_session` usaba **otro** engine global y además
  **commiteaba al acabar** la petición, cosa que los otros dos no hacían.

Queda uno, `api/deps.get_session`, con lo que ya daban por hecho los veinte routers del Hub:

* `expire_on_commit=False`: un objeto se puede leer después de commitear;
* se commitea al terminar la petición sin error, y se deshace si algo lanza.

Los routers que ya commiteaban a mano siguen igual: un commit sin nada pendiente no hace nada.
"""
from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from server.app.api import deps
from server.app.modules.agents_hub.database.config_models import HubOrganizacion

APP = Path(__file__).resolve().parents[2] / "app"


def _fuentes() -> list[tuple[str, str]]:
    return [
        (str(f.relative_to(APP)).replace("\\", "/"), f.read_text(encoding="utf-8"))
        for f in APP.rglob("*.py")
        if "__pycache__" not in f.parts
    ]


# ---------------------------------------------------------------------------
# El guardarraíl: que no vuelva a aparecer otro
# ---------------------------------------------------------------------------


def test_hay_un_solo_proveedor_de_sesion() -> None:
    definiciones = [
        ruta for ruta, texto in _fuentes()
        if re.search(r"^async def (get_session|get_async_session)\b", texto, re.MULTILINE)
    ]
    assert definiciones == ["api/deps.py"], definiciones


def test_nadie_abre_una_sesion_a_mano_sobre_el_engine() -> None:
    """Abrir una `AsyncSession` sobre el engine saltaba la fábrica y su `expire_on_commit`."""
    a_mano = [
        f"{ruta}: {linea.strip()}"
        for ruta, texto in _fuentes()
        for linea in texto.splitlines()
        if not linea.strip().startswith("#") and re.search(r"\bAsyncSession\(\s*\w*engine", linea)
    ]
    assert not a_mano, a_mano


def test_hay_un_solo_engine_de_la_aplicacion() -> None:
    """`get_engine()` del Hub devuelve el mismo engine que el resto, no uno suyo."""
    from server.app.database.db import server_engine
    from server.app.modules.agents_hub.database.connection import get_engine

    assert get_engine() is server_engine


# ---------------------------------------------------------------------------
# El comportamiento, por HTTP y contra una base desechable
# ---------------------------------------------------------------------------


@pytest.fixture
async def cliente(db_url, monkeypatch):
    engine = create_async_engine(db_url)
    fabrica = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(deps, "AsyncSessionLocal", fabrica)

    app = FastAPI()

    @app.post("/sin-commit/{nombre}")
    async def sin_commit(nombre: str, session: AsyncSession = Depends(deps.get_session)):
        session.add(HubOrganizacion(id=uuid.uuid4(), name=nombre, partner_id="uji"))
        return {"ok": True}

    @app.post("/falla/{nombre}")
    async def falla(nombre: str, session: AsyncSession = Depends(deps.get_session)):
        session.add(HubOrganizacion(id=uuid.uuid4(), name=nombre, partner_id="uji"))
        await session.flush()
        raise HTTPException(status_code=400, detail="no")

    @app.post("/commit-y-leer/{nombre}")
    async def commit_y_leer(nombre: str, session: AsyncSession = Depends(deps.get_session)):
        org = HubOrganizacion(id=uuid.uuid4(), name=nombre, partner_id="uji")
        session.add(org)
        await session.commit()
        return {"nombre": org.name}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c, engine
    await engine.dispose()


async def _existe(engine, nombre: str) -> bool:
    async with AsyncSession(engine) as s:
        return (await s.execute(select(HubOrganizacion).where(HubOrganizacion.name == nombre))).first() is not None


async def test_lo_que_queda_pendiente_se_commitea_al_acabar(cliente) -> None:
    c, engine = cliente
    assert (await c.post("/sin-commit/una")).status_code == 200
    assert await _existe(engine, "una")


async def test_si_la_peticion_falla_no_se_guarda_nada(cliente) -> None:
    c, engine = cliente
    assert (await c.post("/falla/otra")).status_code == 400
    assert not await _existe(engine, "otra")


async def test_se_puede_leer_un_objeto_despues_de_commitear(cliente) -> None:
    """El 500 conocido: con `expire_on_commit`, leer `org.name` disparaba una carga síncrona."""
    c, _ = cliente
    respuesta = await c.post("/commit-y-leer/tercera")
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"nombre": "tercera"}


def test_el_engine_unico_conserva_la_capacidad_de_los_dos() -> None:
    """Revisión de la PR #300: eran dos pools de 5+10, y el chat por SSE retiene su conexión
    mientras dura la respuesta. Con uno solo de 5+10, quince chats a la vez dejaban sin conexión
    al panel y al login. El único conserva los treinta que sumaban los dos."""
    from server.app.database.db import server_engine

    assert server_engine.pool.size() == 10
    assert server_engine.pool._max_overflow == 20
