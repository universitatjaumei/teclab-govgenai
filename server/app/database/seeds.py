"""
Seeds de multitenancy para desarrollo.

Este módulo crea los datos iniciales necesarios para desarrollo:
- SuperAdmin de desarrollo
- Admin de desarrollo (ex-partner)
- Cliente de desarrollo
- Licencia de desarrollo con cuota amplia

Credenciales de desarrollo:
  SuperAdmin: DEV_ADMIN_EMAIL (por omisión `admin@example.local`) / DEV_ADMIN_PASSWORD
  Admin:      dev@automatia.local / hash de DEV_ADMIN_PASSWORD

**El login de administrador sí verifica la contraseña** desde SEC.1. Esta cabecera afirmaba lo
contrario —que valía cualquiera— desde antes de que ese prompt existiera, y un comentario que
describe un agujero ya cerrado hace perder el tiempo a quien audita el código.

La clave de licencia de desarrollo es: DEV_LICENSE_KEY_12345
"""

import hashlib
import logging
import os
from datetime import datetime, timedelta
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from server.app.database.db import server_engine
from server.app.database.models import (
    SuperAdminAccount,
    AdminAccount,
    ClientAccount,
    License,
)
from server.app.core.security import hash_password
from automatia_shared.enums import LicenseStatus

# Issue #18 — esto NO es una herramienta de consola aunque lo parezca por el prefijo «[SEED]»:
# `main.py` lo llama en el arranque del servidor, asi que en produccion su salida iba a la
# salida estandar sin nivel ni marca de tiempo. El prefijo lo pone ya el nombre del modulo.
logger = logging.getLogger(__name__)


# Constante para desarrollo - usar en tests y desarrollo local
DEV_LICENSE_KEY = "DEV_LICENSE_KEY_12345"

# AIS.2 — por entorno y con un valor neutro por omisión. Aquí había un correo real, el del
# mantenedor del principal, así que **todo fork que arrancara en local creaba un
# superadministrador con el correo de otra persona** — y quien lo heredara tendría que averiguar
# por qué. Es exactamente lo que `CONTRIBUTING.md` manda dejar en el fork: configuración de una
# institución (aquí, de una persona) fuera del repositorio principal.
#
# Sigue siendo una credencial **pública y de desarrollo**: la protección no es que sea secreta,
# es el gate de `seed_multitenancy_defaults` (SEC.8.0), que no siembra nada fuera de
# `ENVIRONMENT=development`.
DEV_ADMIN_EMAIL = os.getenv("DEV_ADMIN_EMAIL", "admin@example.local")
DEV_ADMIN_PASSWORD = os.getenv("DEV_ADMIN_PASSWORD", "admin1234")


async def seed_multitenancy_defaults():
    """
    Crea los datos de multitenancy para desarrollo.

    Esta función es IDEMPOTENTE: ejecutarla múltiples veces
    no duplicará los datos.

    Crea:
    - 1 SuperAdminAccount (DEV_ADMIN_EMAIL / DEV_ADMIN_PASSWORD)
    - 1 AdminAccount (partner_dev, ex-partner)
    - 1 ClientAccount (client_dev)
    - 1 License (lic_dev) con 10M tokens de cuota

    **Solo en desarrollo.** La credencial del SuperAdmin de desarrollo es pública
    (está en este mismo módulo), así que sembrarla en producción crearía una cuenta
    con acceso a todos los tenants y contraseña conocida. En producción el SuperAdmin
    se provisiona con `python -m server.app.scripts.bootstrap` (lo llama setup.sh),
    que toma la credencial de SUPERADMIN_EMAIL/SUPERADMIN_PASSWORD y no hardcodea nada.
    """
    if os.getenv("ENVIRONMENT", "development") != "development":
        logger.info(
            "Entorno no-desarrollo: se omiten los datos de desarrollo "
            "(SuperAdmin/admin/cliente/licencia de prueba). Provisiona el SuperAdmin "
            "con `python -m server.app.scripts.bootstrap`."
        )
        return

    async with AsyncSession(server_engine) as session:
        # 0. Crear SuperAdmin de desarrollo
        await _seed_dev_superadmin(session)

        # 1. Crear Admin de desarrollo (ex-partner)
        await _seed_dev_admin(session)

        # 2. Crear Cliente de desarrollo
        await _seed_dev_client(session)

        # 3. Crear Licencia de desarrollo
        await _seed_dev_license(session)

        await session.commit()
        logger.info("Multitenencia de desarrollo creada o verificada")


async def _seed_dev_superadmin(session: AsyncSession):
    """Crea el SuperAdminAccount de desarrollo si no existe."""
    result = await session.execute(
        select(SuperAdminAccount).where(SuperAdminAccount.email == DEV_ADMIN_EMAIL)
    )
    existing = result.scalar_one_or_none()

    if not existing:
        superadmin = SuperAdminAccount(
            name="SuperAdmin Desarrollo",
            email=DEV_ADMIN_EMAIL,
            hashed_password=hash_password(DEV_ADMIN_PASSWORD),
            is_active=True,
        )
        session.add(superadmin)
        logger.info("SuperAdmin de desarrollo creado: %s", DEV_ADMIN_EMAIL)
    else:
        logger.debug("El SuperAdmin de desarrollo ya existe")


async def _seed_dev_admin(session: AsyncSession):
    """Crea el AdminAccount de desarrollo (ex-partner) si no existe."""
    result = await session.execute(
        select(AdminAccount).where(AdminAccount.partner_id == "partner_dev")
    )
    existing = result.scalar_one_or_none()

    if not existing:
        admin = AdminAccount(
            partner_id="partner_dev",
            name="Admin Desarrollo",
            email="dev@automatia.local",
            credits_balance=1000000,  # 1M de créditos para desarrollo
            is_active=True,
        )
        session.add(admin)
        logger.info("Admin de desarrollo creado: partner_dev")
    else:
        logger.debug("El admin de desarrollo ya existe")


async def _seed_dev_client(session: AsyncSession):
    """Crea el Cliente de desarrollo si no existe."""
    result = await session.execute(
        select(ClientAccount).where(ClientAccount.client_id == "client_dev")
    )
    existing = result.scalar_one_or_none()

    if not existing:
        # Hash de la license_key para almacenamiento seguro
        license_key_hash = hashlib.sha256(DEV_LICENSE_KEY.encode()).hexdigest()

        client = ClientAccount(
            client_id="client_dev",
            partner_id="partner_dev",
            name="Cliente Desarrollo Local",
            email="client@automatia.local",
            license_key=license_key_hash,
            is_active=True,
        )
        session.add(client)
        logger.info("Cliente de desarrollo creado: client_dev")
    else:
        logger.debug("El cliente de desarrollo ya existe")


async def _seed_dev_license(session: AsyncSession):
    """Crea la Licencia de desarrollo si no existe."""
    result = await session.execute(
        select(License).where(License.license_id == "lic_dev")
    )
    existing = result.scalar_one_or_none()

    if not existing:
        license = License(
            license_id="lic_dev",
            client_id="client_dev",
            quota_tokens=10000000,  # 10M tokens para desarrollo
            consumed_tokens=0,
            valid_until=datetime.utcnow() + timedelta(days=365),  # 1 año
            status=LicenseStatus.ACTIVE.value,
        )
        session.add(license)
        logger.info("Licencia de desarrollo creada: lic_dev")
    else:
        logger.debug("La licencia de desarrollo ya existe")



async def seed_all():
    """
    Ejecuta todos los seeds del servidor.

    Incluye:
    - Seeds de multitenancy (desarrollo)
    - Seeds de configuración AI (si existen)
    """
    from server.app.database.db import seed_server_db

    # 1. Seeds de configuración AI existentes
    await seed_server_db()

    # 2. Seeds de multitenancy
    await seed_multitenancy_defaults()

    # LEG.2 — aquí se sembraban en **cada arranque** los ocho prompts de la época de AutomatIA en
    # `extraction_service_config` y `system_prompt`. Escribir en la base de datos al arrancar es
    # lo que choca con la suite: el servidor siembra mientras los tests reinicializan, y salta
    # cualquiera de los dos. Los prompts vivos son `HubPromptTemplate` (por asistente) y
    # `HubActivityPrompt` (por actividad), que no se siembran al arrancar.
    #
    # Lo que decían esos ocho prompts, y qué se salvó de ellos, está en
    # `docs/COMPARATIVA_PROMPTS_LEGACY.md`.

    logger.info("Sembrado del servidor completado")
