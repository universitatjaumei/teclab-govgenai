"""Conexión asíncrona a PostgreSQL para agents_hub."""

from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine as sa_create_async_engine,
)


def create_async_engine(
    url: str | None = None, *, statement_timeout_ms: int | None = None, **kwargs: Any
) -> AsyncEngine:
    """El motor del hub, con el tiempo máximo de consulta puesto (issue #159).

    `statement_timeout_ms` es para los test y para los guiones que necesiten otro límite; sin él
    manda `TIEMPO_MAXIMO_DE_CONSULTA_MS`, que sale del entorno.
    """
    # AIS.8 — el mismo DSN de reserva vivía escrito dos veces, aquí y en `database/db.py`.
    # Dos copias del mismo valor por omisión acaban divergiendo, y la que no se toque
    # seguirá conectando a la base vieja sin que nadie lo note. Se resuelve en un sitio, y
    # ahí es donde está la guarda que lo prohíbe en producción. El tiempo máximo de consulta
    # va por el mismo camino y por la misma razón.
    from server.app.database.db import (
        TIEMPO_MAXIMO_DE_CONSULTA_MS,
        _dsn,
        opciones_de_conexion,
    )

    if url is None:
        url = _dsn()
    if statement_timeout_ms is None:
        statement_timeout_ms = TIEMPO_MAXIMO_DE_CONSULTA_MS
    kwargs.setdefault("connect_args", opciones_de_conexion(url, statement_timeout_ms))
    return sa_create_async_engine(url, echo=False, pool_pre_ping=True, **kwargs)


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


def get_engine() -> AsyncEngine:
    """El engine de la aplicación, que es uno: `database/db.server_engine` (#272).

    Hasta #272 éste creaba el suyo, con su propio pool, y su `get_session` era el tercer
    proveedor de sesión. Las peticiones usan `api/deps.get_session`; `create_async_engine` sigue
    aquí para los guiones que se conectan a otra base.
    """
    from server.app.database.db import server_engine

    return server_engine
