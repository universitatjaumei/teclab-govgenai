"""Un rastreo a la vez por sitio, y constancia de los que un reinicio corta (#360).

Deploy: edge — el rastreo es trabajo sobre el portal de un cliente.

El rastreo corre dentro del proceso web (`BackgroundTasks` o el planificador) y no dejaba constancia
de estar en marcha. Dos podían coincidir sobre el mismo portal —a mano, desde otra pestaña, por otra
persona o con el programado—, un despliegue lo mataba sin dejar fila en el diario, y el panel tenía
que adivinar el desenlace.

Tres piezas:

- `reservar` marca el sitio con **una sola sentencia condicional**: dos peticiones a la vez no
  pueden ganar las dos, que es justo lo que una lectura seguida de una escritura no garantiza.
- `liberar` quita la marca. La llama el trabajo al terminar, también si falla.
- `interrumpir_los_que_quedaron` corre al arrancar: con un solo proceso, cualquier marca que siga
  puesta es de un rastreo que el reinicio mató. Se quita y se anota en el diario, para que cortar
  no sea silencioso.

`CADUCIDAD` es la red de seguridad para lo que se escape a lo anterior: una marca más vieja no
bloquea. Es larga a propósito, porque un rastreo legítimo de un portal grande con la pausa de
cortesía puede durar horas.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, update

from server.app.modules.agents_hub.database.operational_models import HubWebSite

logger = logging.getLogger(__name__)

CADUCIDAD = timedelta(hours=24)

#: Lo que el diario dice de una pasada que el reinicio cortó.
MOTIVO_DEL_CORTE = "reinicio del servidor"
NOTA_DEL_CORTE = (
    "La pasada no terminó: el servidor se reinició (un despliegue o una caída) mientras rastreaba. "
    "Lo que llegó a rastrear se conserva; vuelve a rastrear para completarla."
)


async def reservar(
    session: Any, site_id: uuid.UUID, section_id: uuid.UUID | None, now: datetime
) -> datetime | None:
    """Marca el sitio como «rastreándose». Devuelve `None` si lo ha reservado; si ya había un
    rastreo en marcha, desde cuándo, para que quien pidió el segundo sepa por qué no.

    Confirma su propia transacción: la marca tiene que verse desde otras sesiones antes de que
    empiece el rastreo, que corre en otra.
    """
    reservado = (
        await session.execute(
            update(HubWebSite)
            .where(HubWebSite.id == site_id)
            .where(
                or_(
                    HubWebSite.rastreo_en_curso_desde.is_(None),
                    HubWebSite.rastreo_en_curso_desde < now - CADUCIDAD,
                )
            )
            .values(rastreo_en_curso_desde=now, rastreo_en_curso_seccion_id=section_id)
            .returning(HubWebSite.id)
            .execution_options(synchronize_session=False)
        )
    ).first()
    await session.commit()
    if reservado is not None:
        return None
    return (
        await session.execute(
            select(HubWebSite.rastreo_en_curso_desde).where(HubWebSite.id == site_id)
        )
    ).scalar_one_or_none()


async def liberar(session_factory: Any, site_id: uuid.UUID) -> None:
    """Quita la marca. Sesión propia: tiene que ocurrir aunque la del trabajo haya fallado."""
    async with session_factory() as session:
        await session.execute(
            update(HubWebSite)
            .where(HubWebSite.id == site_id)
            .values(rastreo_en_curso_desde=None, rastreo_en_curso_seccion_id=None)
            .execution_options(synchronize_session=False)
        )
        await session.commit()


async def interrumpir_los_que_quedaron(
    session_factory: Any, diario: Any, now: datetime
) -> int:
    """Al arrancar: da por interrumpidos los rastreos que siguen marcados y los anota.

    Sólo es correcto con **un** proceso que rastree, que es como se despliega (un `uvicorn` sin
    `--workers`): con dos, el que arranca cortaría la marca del que sigue rastreando.
    """
    async with session_factory() as session:
        marcados = (
            await session.execute(
                select(
                    HubWebSite.id,
                    HubWebSite.rastreo_en_curso_desde,
                    HubWebSite.rastreo_en_curso_seccion_id,
                ).where(HubWebSite.rastreo_en_curso_desde.is_not(None))
            )
        ).all()

    for site_id, desde, section_id in marcados:
        try:
            await diario.registrar(
                site_id=site_id,
                section_id=section_id,
                scope_label=await _etiqueta(session_factory, section_id),
                started_at=desde,
                finished_at=now,
                summary=_PasadaCortada(),
            )
        except Exception:  # el diario cuenta; si falla, la marca se quita igual
            logger.exception("No se pudo anotar el rastreo interrumpido del sitio %s", site_id)
        await liberar(session_factory, site_id)
        logger.warning("Rastreo del sitio %s interrumpido por un reinicio (desde %s)", site_id, desde)
    return len(marcados)


async def _etiqueta(session_factory: Any, section_id: uuid.UUID | None) -> str:
    """El nombre de la sección, como lo anota el trabajo; «sitio» si la pasada era del sitio, y
    también si la sección ya no existe."""
    from server.app.modules.agents_hub.database.operational_models import HubWebSection
    from server.app.modules.curation.quality_job import ETIQUETA_DEL_SITIO_ENTERO

    if section_id is None:
        return ETIQUETA_DEL_SITIO_ENTERO
    async with session_factory() as session:
        nombre = (
            await session.execute(select(HubWebSection.name).where(HubWebSection.id == section_id))
        ).scalar_one_or_none()
    return nombre or ETIQUETA_DEL_SITIO_ENTERO


class _PasadaCortada:
    """El resumen de una pasada que no terminó: sin cifras, con el motivo."""

    truncated = True
    stop_reason = MOTIVO_DEL_CORTE
    errors = [NOTA_DEL_CORTE]
