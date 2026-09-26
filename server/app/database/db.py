"""Motor y sesiones de la base de datos del servidor (PostgreSQL + asyncpg).

**El esquema lo define Alembic, y sólo Alembic.** Este módulo abre el motor; no crea tablas.
Hasta BD.2 (2026-09-04) tenía un `init_server_db()` que hacía `create_all` en cada arranque, junto
con otro igual para los metadatos del Hub en `main.py`, además de las migraciones que aplica el
despliegue. Dos fuentes para lo mismo, y la que nunca borra ganaba: `create_all` crea lo declarado
y deja intacto lo que dejó de estarlo, así que cada modelo retirado dejaba su tabla — 36 en la base
de desarrollo cuando se midió, ninguna en producción, que siempre se creó sólo con Alembic.

Medido antes de quitarlo: la cadena de Alembic aplicada a una base vacía produce exactamente las
tablas que los modelos declaran. El `create_all` no aportaba ninguna.

Lo que garantiza que las dos cosas —modelos y migraciones— sigan diciendo lo mismo es
`alembic check` en CI, que compara y falla si divergen. Para arrancar en local:
`uv run alembic upgrade head` desde `server/`, como dice el README.
"""

import logging
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

# Los modelos se importan para que queden registrados en `SQLModel.metadata`, que es lo que lee
# `migrations/env.py` para el autogenerate y para `alembic check`.
from server.app.database import models  # noqa: F401

# Issue #18 — el sembrado de configuracion corre en el arranque del servidor. El prefijo
# «[SERVER DB]» que llevaba cada linea lo pone ya el nombre del modulo.
logger = logging.getLogger(__name__)

#: DSN de desarrollo. Es local y su credencial está publicada en el repositorio, igual que la
#: cuenta de desarrollo de `seeds.py`: no es un secreto, es un valor de conveniencia.
_DSN_DE_DESARROLLO = "postgresql+asyncpg://govgenai:govgenai_dev@localhost:5432/govgenai"


def _dsn() -> str:
    """El DSN, con el valor de desarrollo **sólo fuera de producción** (AIS.8).

    El fallback existe porque sin él no se puede arrancar en local ni correr la suite sin montar
    un `.env`, y eso es una fricción real que se paga todos los días. Lo que no puede pasar es
    que **producción** arranque con él: un despliegue al que se le olvide `DATABASE_URL` no
    fallaría, se conectaría a otra base con una credencial que cualquiera puede leer aquí, y el
    síntoma sería «faltan datos» en vez de «falta configuración».

    Es el mismo criterio con el que SEC.8.0 cerró el sembrado de la cuenta de desarrollo y con el
    que `core/config.py` rechaza el `JWT_SECRET_KEY` de ejemplo: el valor cómodo se conserva
    donde es cómodo y se prohíbe donde es peligroso.
    """
    declarado = os.environ.get("DATABASE_URL")
    if declarado:
        return declarado
    if os.getenv("ENVIRONMENT", "development") == "production":
        raise RuntimeError(
            "Falta DATABASE_URL en producción. No se usa el DSN de desarrollo como reserva: "
            "arrancaría contra otra base de datos con una credencial publicada en el "
            "repositorio, y el fallo se vería como datos que faltan y no como configuración "
            "que falta."
        )
    return _DSN_DE_DESARROLLO


#: Cuánto puede durar **una** consulta antes de que el servidor la corte, en milisegundos
#: (issue #159). Cero la desactiva.
#:
#: **Lo que arregla.** El 2026-09-24 una consulta interna sin acotar dejó el sitio 50 minutos sin
#: responder. Los techos de memoria de la #149 contienen ese daño —matan el contenedor en vez de
#: la VM— pero no impiden que la operación se desboque, y una consulta lenta se queda su conexión
#: indefinidamente. Esto la corta en el servidor y libera la conexión.
#:
#: **Lo que NO arregla**: no impide escribir una consulta cara. Impide que una consulta cara se
#: quede la conexión para siempre, que es lo que de verdad tumbó el servicio.
#:
#: Treinta segundos es generoso a propósito: lo que se corta aquí no es trabajo lento, es trabajo
#: patológico. Se puede subir —o desactivar con `0`— para una migración de datos o un barrido,
#: sin tener que quitar la protección del resto.
TIEMPO_MAXIMO_DE_CONSULTA_MS = int(os.getenv("DB_STATEMENT_TIMEOUT_MS", "30000"))


def opciones_de_conexion(url: str, timeout_ms: int) -> dict:
    """Los `connect_args` del motor: hoy, el tiempo máximo de consulta.

    **Sólo para asyncpg.** `server_settings` es suyo, y pasárselo a otro driver rompe la
    conexión: el codebase tiene que seguir sirviendo a otro despliegue cambiando variables de
    entorno, así que una protección no puede dejarlo sin arrancar en otro motor.

    Vive aquí, junto a `_dsn()`, porque hay **dos** fábricas de engine —ésta y la de
    `agents_hub/database/connection.py`— y ya divergieron una vez por el DSN de reserva. Dos
    copias del mismo valor acaban separándose, y la que no se toca es la que falla en silencio.
    """
    if timeout_ms <= 0 or "asyncpg" not in url:
        return {}
    return {"server_settings": {"statement_timeout": str(timeout_ms)}}


DATABASE_URL = _dsn()

server_engine = create_async_engine(
    DATABASE_URL,
    echo=False,
    future=True,
    connect_args=opciones_de_conexion(DATABASE_URL, TIEMPO_MAXIMO_DE_CONSULTA_MS),
)

AsyncSessionLocal = async_sessionmaker(
    server_engine, class_=AsyncSession, expire_on_commit=False
)


async def get_session() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session


async def seed_server_db():
    """Populates server DB with default configurations."""
    from server.app.database.models import AIConfig
    from sqlmodel import select

    async with AsyncSessionLocal() as session:
        logger.info("Comprobando la configuracion de modelos por rol")

        required_roles = {
            "logico_navegacion": {
                "provider": "google",
                "model_id": "gemini-3-flash-preview",
            },
            "supervision": {"provider": "google", "model_id": "gemini-3.1-pro-preview"},
            "extraccion_pdf": {
                "provider": "google",
                "model_id": "gemini-2.5-flash-lite",
            },
        }

        for role_key, default_cfg in required_roles.items():
            statement = select(AIConfig).where(AIConfig.role_key == role_key)
            results = await session.exec(statement)
            existing = results.first()

            if not existing:
                logger.info("Creando el rol de modelo «%s»", role_key)
                session.add(
                    AIConfig(
                        role_key=role_key,
                        provider=default_cfg["provider"],
                        model_id=default_cfg["model_id"],
                    )
                )

        await session.commit()
        logger.info("Configuracion de modelos por rol comprobada")
