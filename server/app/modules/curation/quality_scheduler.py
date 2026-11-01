"""Scheduler de calidad de contenido web (9Q.5, ampliado en DIN.2).

Deploy: edge.

Mantiene un APScheduler que, cada N horas, selecciona los **ámbitos** vencidos y lanza
`SiteQualityAnalysisJob.run_for_site` sobre cada uno. Un ámbito es una sección de un sitio
(DIN.1) o, en un sitio sin secciones, el sitio entero — que es el comportamiento de siempre.

La función `_get_due_scopes` está expuesta para facilitar los tests unitarios.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AmbitoVencido:
    """Lo que hay que rastrear: un sitio, con su sección si la pasada es de una sección."""

    site: Any
    section: Any | None = None

    @property
    def site_id(self) -> uuid.UUID:
        return self.site.id

    @property
    def section_id(self) -> uuid.UUID | None:
        return None if self.section is None else self.section.id

    @property
    def ambito(self) -> str:
        return "sitio" if self.section is None else str(self.section.id)


def _ha_vencido(last_crawled_at: datetime | None, intervalo: int, now: datetime) -> bool:
    """Nunca rastreado vence, igual que un sitio nuevo; si no, cuando pasa su intervalo."""
    if last_crawled_at is None:
        return True
    return now - last_crawled_at >= timedelta(hours=intervalo)


async def _get_due_scopes(session: Any, now: datetime) -> list[AmbitoVencido]:
    """Los ámbitos vencidos: secciones por su cadencia efectiva, sitios sin secciones por la suya.

    **Un sitio con secciones vence por sección, no además como sitio.** Si venciera por los dos
    caminos, cada pasada del sitio entero volvería a rastrear lo que la sección acaba de mirar, y
    con cadencias distintas eso es el doble de peticiones contra el mismo servidor. Lo que queda
    fuera de toda sección sigue en manos de quien cura, con el rastreo del sitio a mano.

    Cada sección lleva **su propio reloj** (`last_crawled_at`): es lo que permite que un apartado
    de eventos se mire cada seis horas y el resto del portal cada semana.
    """
    from sqlalchemy import select

    from server.app.modules.agents_hub.database.operational_models import (
        HubWebSection,
        HubWebSite,
    )
    from server.app.modules.curation.secciones import parametros_efectivos

    sites = (
        (await session.execute(select(HubWebSite).where(HubWebSite.status == "active")))
        .scalars()
        .all()
    )
    if not sites:
        return []

    secciones = (
        (
            await session.execute(
                select(HubWebSection)
                .where(HubWebSection.site_id.in_([s.id for s in sites]))
                .where(HubWebSection.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )

    # El filtro de `is_active` se comprueba también aquí, y no es redundancia defensiva: es lo
    # que hace comprobable en un test sin base de datos que una sección desactivada no vence.
    por_sitio: dict[Any, list] = {}
    for seccion in secciones:
        if seccion.is_active:
            por_sitio.setdefault(seccion.site_id, []).append(seccion)

    due: list[AmbitoVencido] = []
    for site in sites:
        suyas = por_sitio.get(site.id, [])
        if not suyas:
            if _ha_vencido(site.last_crawled_at, site.crawl_interval_hours, now):
                due.append(AmbitoVencido(site=site))
            continue
        for seccion in suyas:
            intervalo = parametros_efectivos(site, seccion).crawl_interval_hours
            if _ha_vencido(seccion.last_crawled_at, intervalo, now):
                due.append(AmbitoVencido(site=site, section=seccion))
    return due


def create_quality_scheduler(
    session_factory: Any,
    site_quality_job: Any,
    *,
    interval_hours: int = 24,
    enabled: bool = True,
) -> Any:
    """Crea y configura el APScheduler de calidad de contenido.

    Args:
        session_factory: async context manager que cede una AsyncSession.
        site_quality_job: instancia de SiteQualityAnalysisJob.
        interval_hours: cadencia del job maestro (default: 24 h).
        enabled: si False, devuelve el scheduler sin jobs (para CONTENT_QUALITY_ENABLED=False).
    """
    import asyncio

    from apscheduler.schedulers.asyncio import AsyncIOScheduler

    scheduler = AsyncIOScheduler()
    # #360 — referencias fuertes a las tareas por sitio: el bucle sólo guarda débiles, y una tarea
    # recogida a mitad dejaría el sitio reservado hasta el arranque siguiente o la caducidad.
    en_marcha: set[asyncio.Task] = set()

    if not enabled:
        return scheduler

    async def check_all_sites() -> None:
        logger.info("[QualityScheduler] check_all_sites started")
        now = datetime.now(timezone.utc)
        try:
            async with session_factory() as session:
                due = await _get_due_scopes(session, now)
        except Exception as exc:
            logger.exception("[QualityScheduler] Failed to get due scopes: %s", exc)
            return

        logger.info("[QualityScheduler] %d scopes due for quality check", len(due))
        # #360 — una tarea por **sitio**, que recorre sus ámbitos en serie. Lanzar uno por ámbito
        # ponía a rastrear a la vez todas las secciones vencidas del mismo portal; con la marca
        # de «rastreo en curso», que es del sitio, todas menos una chocarían y esperarían a la
        # pasada siguiente del planificador.
        por_sitio: dict[uuid.UUID, list[AmbitoVencido]] = {}
        for ambito in due:
            por_sitio.setdefault(ambito.site_id, []).append(ambito)
        for site_id, ambitos in por_sitio.items():
            tarea = asyncio.create_task(
                _rastrear_el_sitio(session_factory, site_quality_job, ambitos),
                name=f"quality-{site_id}",
            )
            en_marcha.add(tarea)
            tarea.add_done_callback(en_marcha.discard)

    scheduler.add_job(
        check_all_sites,
        trigger="interval",
        hours=interval_hours,
        id="content_quality_check_all_sites",
    )

    return scheduler


async def _rastrear_el_sitio(
    session_factory: Any, site_quality_job: Any, ambitos: list[AmbitoVencido]
) -> None:
    """Los ámbitos vencidos de un sitio, uno detrás de otro, reservando el sitio para cada uno.

    Si el sitio ya se está rastreando —a mano o por otra vía— se deja para la pasada siguiente:
    siguen vencidos, porque su «Último rastreo» sólo cambia al terminar.
    """
    from server.app.modules.curation import rastreo_en_curso

    for ambito in ambitos:
        ahora = datetime.now(timezone.utc)
        try:
            async with session_factory() as session:
                ocupado_desde = await rastreo_en_curso.reservar(
                    session, ambito.site_id, ambito.section_id, ahora
                )
        except Exception:
            logger.exception("[QualityScheduler] No se pudo reservar el sitio %s", ambito.site_id)
            return
        if ocupado_desde is not None:
            logger.info(
                "[QualityScheduler] site %s ya se está rastreando desde %s: se deja para la "
                "pasada siguiente",
                ambito.site_id,
                ocupado_desde,
            )
            return
        await _run_site_safe(site_quality_job, ambito.site_id, ambito.section_id, ahora)


async def _run_site_safe(
    site_quality_job: Any,
    site_id: uuid.UUID,
    section_id: uuid.UUID | None = None,
    reservado_en: datetime | None = None,
) -> None:
    """Ejecuta el job de calidad para un ámbito sin propagar excepciones."""
    ambito = "sitio" if section_id is None else str(section_id)
    try:
        summary = await site_quality_job.run_for_site(
            site_id, section_id=section_id, reservado_en=reservado_en
        )
        logger.info(
            "[QualityScheduler] site %s (%s) done: new=%d superseded=%d auto_ingested=%d "
            "errors=%d",
            site_id,
            ambito,
            summary.pages_new,
            summary.pages_marked_superseded,
            summary.documents_auto_ingested,
            len(summary.errors),
        )
        if summary.errors:
            for err in summary.errors:
                logger.warning(
                    "[QualityScheduler] site %s (%s) error: %s", site_id, ambito, err
                )
    except Exception as exc:
        logger.exception(
            "[QualityScheduler] Unexpected failure for site %s (%s): %s",
            site_id,
            ambito,
            exc,
        )
