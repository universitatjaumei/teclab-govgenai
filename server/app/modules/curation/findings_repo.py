"""Repositorio CRUD para HubContentFinding (9Q.1)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.operational_models import HubContentFinding
from server.app.modules.curation.contracts import (
    ContentFinding,
    InvalidFindingTransitionError,
    transiciones_permitidas,
)


#: Los estados de un hallazgo que **siguen pidiendo trabajo**. Lo demás está cerrado: descartado por
#: una persona o retirado por la reconciliación de CUR.9.
ESTADOS_ABIERTOS = ("new", "confirmed")

#: Valor del filtro que significa «los dos estados abiertos». Existe porque la cola por defecto es
#: lo abierto, y sin esto la pantalla tendría que pedir dos veces y unir, o mostrar 109 hallazgos
#: retirados con la etiqueta «Resuelto» —que es justo lo que el usuario pidió que dejara de pasar—.
FILTRO_ABIERTOS = "open"


async def paginas_de_navegacion(
    session: AsyncSession, site_id: uuid.UUID, page_id: uuid.UUID | None = None
) -> set[uuid.UUID]:
    """Los ids de las páginas del sitio con un hallazgo `navigation` abierto (#345).

    Una sola consulta para las tres puertas —proponer, Publicació y la ingesta manual—: si cada una
    tuviera la suya, una página bloqueada en una se colaría por otra. Abierto y no descartado:
    descartarlo es decir que el detector se equivocó, y entonces la página vuelve a poder usarse.
    """
    consulta = select(HubContentFinding.page_id).where(
        HubContentFinding.site_id == site_id,
        HubContentFinding.finding_type == "navigation",
        HubContentFinding.status.in_(ESTADOS_ABIERTOS),
    )
    if page_id is not None:
        consulta = consulta.where(HubContentFinding.page_id == page_id)
    return {fila for fila in (await session.execute(consulta)).scalars().all() if fila is not None}


class ContentFindingRepo:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, finding: ContentFinding) -> HubContentFinding:
        stmt = select(HubContentFinding).where(
            HubContentFinding.site_id == finding.site_id,
            HubContentFinding.finding_type == finding.finding_type,
            HubContentFinding.page_id == finding.page_id,
            HubContentFinding.related_page_id == finding.related_page_id,
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing is None:
            orm = HubContentFinding(
                id=finding.id,
                site_id=finding.site_id,
                finding_type=finding.finding_type,
                severity=finding.severity,
                confidence=finding.confidence,
                page_id=finding.page_id,
                related_page_id=finding.related_page_id,
                source_url=finding.source_url,
                signal_json=finding.signal,
                status=finding.status,
                detected_at=finding.detected_at,
                reviewed_at=finding.reviewed_at,
                reviewed_by=finding.reviewed_by,
                resolution_note=finding.resolution_note,
            )
            self._session.add(orm)
            await self._session.flush()
            return orm

        existing.severity = finding.severity
        existing.confidence = finding.confidence
        existing.source_url = finding.source_url
        existing.signal_json = finding.signal
        existing.detected_at = finding.detected_at
        await self._session.flush()
        return existing

    async def list_by_site(
        self,
        site_id: uuid.UUID,
        status: Optional[str] = None,
        finding_type: Optional[str] = None,
    ) -> list[HubContentFinding]:
        stmt = select(HubContentFinding).where(HubContentFinding.site_id == site_id)
        if status == FILTRO_ABIERTOS:
            stmt = stmt.where(HubContentFinding.status.in_(ESTADOS_ABIERTOS))
        elif status is not None:
            stmt = stmt.where(HubContentFinding.status == status)
        if finding_type is not None:
            stmt = stmt.where(HubContentFinding.finding_type == finding_type)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get(self, finding_id: uuid.UUID) -> Optional[HubContentFinding]:
        return await self._session.get(HubContentFinding, finding_id)

    async def transition(
        self,
        finding_id: uuid.UUID,
        new_status: str,
        reviewed_by: uuid.UUID,
        resolution_note: Optional[str] = None,
    ) -> HubContentFinding:
        orm = await self._session.get(HubContentFinding, finding_id)
        if orm is None:
            # El router ya comprobó que existe; si no está, es que se borró entre medias.
            raise LookupError(f"el hallazgo {finding_id} no existe")
        allowed = transiciones_permitidas(orm.status)
        if new_status not in allowed:
            raise InvalidFindingTransitionError(
                f"Cannot transition from '{orm.status}' to '{new_status}'"
            )
        orm.status = new_status
        orm.reviewed_by = reviewed_by
        orm.reviewed_at = datetime.now(timezone.utc)
        if resolution_note is not None:
            orm.resolution_note = resolution_note
        await self._session.flush()
        await self._session.refresh(orm)
        return orm
