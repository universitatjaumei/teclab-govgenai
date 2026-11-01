"""Un rastreo a la vez por sitio, y constancia de los que un reinicio corta (#360).

Deploy: edge — el rastreo es trabajo sobre el portal de un cliente.

El rastreo corre dentro del proceso web (`BackgroundTasks` o el planificador) y no dejaba constancia
de estar en marcha. Dos podían coincidir sobre el mismo portal —a mano, desde otra pestaña, por otra
persona o con el programado—, un despliegue lo mataba sin dejar fila en el diario, y el panel tenía
que adivinar el desenlace.

Tres piezas:

- `reservar` marca el sitio con **una sola sentencia condicional**: dos peticiones a la vez no
  pueden ganar las dos, que es justo lo que una lectura seguida de una escritura no garantiza.
- `liberar` quita la marca **que puso esa reserva**, y sólo esa. La llama el trabajo al terminar,
  también si falla.
- `interrumpir_los_que_quedaron` corre al arrancar: con un solo proceso, cualquier marca que siga
  puesta es de un rastreo que el reinicio mató. Se quita y se anota en el diario, para que cortar
  no sea silencioso.

`CADUCIDAD` es la red de seguridad para lo que se escape a lo anterior: una marca más vieja no
bloquea, y el contrato tampoco la enseña. Es larga a propósito, porque un rastreo legítimo de un
portal grande con la pausa de cortesía puede durar horas.
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


def vigente(desde: datetime | None, now: datetime) -> bool:
    """Si una marca bloquea: puesta y no caducada. Lo usan la reserva y el contrato, para que el
    panel no enseñe «rastreando» donde el servidor ya dejaría lanzar otro."""
    return desde is not None and desde >= now - CADUCIDAD


async def reservar(
    session: Any, site_id: uuid.UUID, section_id: uuid.UUID | None, now: datetime
) -> datetime | None:
    """Marca el sitio como «rastreándose» con `now`. Devuelve `None` si lo ha reservado; si no,
    desde cuándo está ocupado, para que quien pidió el segundo sepa por qué no.

    **Sólo devuelve `None` si esta llamada ha puesto la marca.** Si el UPDATE no reserva y la
    marca ya no está —el que la tenía terminó entre medias—, se vuelve a intentar una vez; si el
    sitio no existe, cuenta como ocupado: un sitio borrado no se rastrea.

    Confirma su propia transacción: la marca tiene que verse desde otras sesiones antes de que
    empiece el rastreo, que corre en otra.
    """
    for _ in range(2):
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
        desde = (
            await session.execute(
                select(HubWebSite.rastreo_en_curso_desde).where(HubWebSite.id == site_id)
            )
        ).scalar_one_or_none()
        if desde is not None:
            return desde
    return now


async def liberar(
    session_factory: Any, site_id: uuid.UUID, reservado_en: datetime | None = None
) -> None:
    """Quita la marca. Con `reservado_en`, sólo si es **la suya**: un rastreo que dura más que la
    caducidad no puede borrar la marca del que tomó el relevo. Sin él, la quita sin mirar; es lo
    que hace el arranque, que libera marcas ajenas a propósito.

    Sesión propia: tiene que ocurrir aunque la del trabajo haya fallado.
    """
    consulta = update(HubWebSite).where(HubWebSite.id == site_id)
    if reservado_en is not None:
        consulta = consulta.where(HubWebSite.rastreo_en_curso_desde == reservado_en)
    async with session_factory() as session:
        await session.execute(
            consulta.values(rastreo_en_curso_desde=None, rastreo_en_curso_seccion_id=None)
            .execution_options(synchronize_session=False)
        )
        await session.commit()


async def interrumpir_los_que_quedaron(
    session_factory: Any, diario: Any, now: datetime
) -> int:
    """Al arrancar: da por interrumpidos los rastreos que siguen marcados y los anota.

    Sólo es correcto con **un** proceso que rastree, que es como se despliega (un `uvicorn` sin
    `--workers`): con dos, el que arranca cortaría la marca del que sigue rastreando.

    Cada sitio va por su cuenta: un fallo con uno no deja a los demás bloqueados.
    """
    from server.app.modules.agents_hub.database.operational_models import HubWebSection
    from server.app.modules.curation.quality_job import etiqueta_del_ambito

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

    interrumpidos = 0
    for site_id, desde, section_id in marcados:
        try:
            etiqueta = await etiqueta_del_ambito(session_factory, section_id)
            # Si la sección se borró a mitad, la fila va al sitio con su etiqueta: el diario
            # apunta a la sección con clave ajena, y una inexistente haría fallar la anotación.
            if section_id is not None:
                async with session_factory() as session:
                    if await session.get(HubWebSection, section_id) is None:
                        section_id = None
            await diario.registrar(
                site_id=site_id,
                section_id=section_id,
                scope_label=etiqueta,
                started_at=desde,
                finished_at=now,
                summary=_PasadaCortada(),
            )
        except Exception:  # el diario cuenta; si falla, la marca se quita igual
            logger.exception("No se pudo anotar el rastreo interrumpido del sitio %s", site_id)
        try:
            await liberar(session_factory, site_id)
            interrumpidos += 1
            logger.warning(
                "Rastreo del sitio %s interrumpido por un reinicio (desde %s)", site_id, desde
            )
        except Exception:
            logger.exception("No se pudo quitar la marca del sitio %s; caduca en %s", site_id, CADUCIDAD)
    return interrumpidos


class _PasadaCortada:
    """El resumen de una pasada que no terminó: sin cifras, con el motivo."""

    truncated = True
    stop_reason = MOTIVO_DEL_CORTE
    errors = [NOTA_DEL_CORTE]
