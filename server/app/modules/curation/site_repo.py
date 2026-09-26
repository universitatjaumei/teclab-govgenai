"""Repositorios CRUD de sitio/página/selección (9Q.0).

Deploy: edge.

Sin `relationship()` cross-base: las FK están al nivel del DDL pero la navegación
ORM se hace por consultas explícitas. Las reglas de la capa de selección viven
aquí porque no requieren BD.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.operational_models import (
    HubCorpusSelection,
    HubCrawledPage,
    HubWebSection,
    HubWebSite,
)
from server.app.modules.curation.secciones import casa, casa_patron, validar_patron


class WebSiteRepo:
    """CRUD del sitio rastreado."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        organizacion_id: uuid.UUID | None,
        name: str,
        root_url: str,
        sitemap_url: str | None = None,
        spider_type: str = "generic",
        config_json: dict[str, Any] | None = None,
        crawl_interval_hours: int = 24,
        audit_semantic_scope: str = "ingested",
    ) -> HubWebSite:
        site = HubWebSite(
            organizacion_id=organizacion_id,
            name=name,
            root_url=root_url,
            sitemap_url=sitemap_url,
            spider_type=spider_type,
            config_json=config_json or {},
            crawl_interval_hours=crawl_interval_hours,
            audit_semantic_scope=audit_semantic_scope,
        )
        self.session.add(site)
        await self.session.flush()
        await self.session.refresh(site)
        return site

    async def get(self, site_id: uuid.UUID) -> HubWebSite | None:
        return await self.session.get(HubWebSite, site_id)

    async def list_by_organizacion(self, organizacion_id: uuid.UUID) -> list[HubWebSite]:
        stmt = (
            select(HubWebSite)
            .where(HubWebSite.organizacion_id == organizacion_id)
            .order_by(HubWebSite.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, site_id: uuid.UUID, **fields: Any) -> HubWebSite | None:
        site = await self.get(site_id)
        if site is None:
            return None
        for key, value in fields.items():
            setattr(site, key, value)
        await self.session.flush()
        await self.session.refresh(site)
        return site

    async def delete(self, site_id: uuid.UUID) -> None:
        site = await self.get(site_id)
        if site is None:
            return
        await self.session.delete(site)
        await self.session.flush()


class WebSectionRepo:
    """CRUD de las secciones de un sitio (DIN.1).

    El patrón se valida **antes de escribir**: la lección de `CrawlConfig` en RAS.5 es que un
    patrón inválido rompería todos los rastreos de la sección y el fallo saldría lejos del
    formulario donde se escribió. DIN.3 lo convierte en un 422 por HTTP; aquí es una excepción
    que nadie puede saltarse llamando al repositorio directamente.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        site_id: uuid.UUID,
        name: str,
        pattern: str,
        pattern_kind: str = "path_prefix",
        crawl_interval_hours: int | None = None,
        mode: str = "manual",
        criteria_json: dict[str, Any] | None = None,
        owner: str | None = None,
    ) -> HubWebSection:
        section = HubWebSection(
            site_id=site_id,
            name=name,
            pattern=validar_patron(pattern_kind, pattern),
            pattern_kind=pattern_kind,
            crawl_interval_hours=crawl_interval_hours,
            mode=mode,
            criteria_json=criteria_json,
            owner=owner,
        )
        self.session.add(section)
        await self.session.flush()
        await self.session.refresh(section)
        return section

    async def get(self, section_id: uuid.UUID) -> HubWebSection | None:
        return await self.session.get(HubWebSection, section_id)

    async def list_by_site(
        self, site_id: uuid.UUID, *, only_active: bool = False
    ) -> list[HubWebSection]:
        stmt = select(HubWebSection).where(HubWebSection.site_id == site_id)
        if only_active:
            stmt = stmt.where(HubWebSection.is_active.is_(True))
        # Orden estable con desempate determinista (DET.1): dos secciones creadas en la misma
        # transacción comparten `created_at` al microsegundo.
        stmt = stmt.order_by(HubWebSection.created_at.desc(), HubWebSection.id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, section_id: uuid.UUID, **fields: Any) -> HubWebSection | None:
        section = await self.get(section_id)
        if section is None:
            return None
        if "pattern" in fields or "pattern_kind" in fields:
            fields["pattern"] = validar_patron(
                fields.get("pattern_kind", section.pattern_kind),
                fields.get("pattern", section.pattern),
            )
        for key, value in fields.items():
            setattr(section, key, value)
        await self.session.flush()
        await self.session.refresh(section)
        return section

    async def delete(self, section_id: uuid.UUID) -> None:
        section = await self.get(section_id)
        if section is None:
            return
        await self.session.delete(section)
        await self.session.flush()


class CrawledPageRepo:
    """CRUD + upsert de páginas rastreadas."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert(
        self,
        *,
        site_id: uuid.UUID,
        url: str,
        **fields: Any,
    ) -> HubCrawledPage:
        # `(site_id, url)` es único: una fila o ninguna. El `limit(1)` lo hace explícito
        # (issue #159).
        existing = (
            await self.session.execute(
                select(HubCrawledPage)
                .where(
                    HubCrawledPage.site_id == site_id,
                    HubCrawledPage.url == url,
                )
                .limit(1)
            )
        ).scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if existing is not None:
            for key, value in fields.items():
                setattr(existing, key, value)
            existing.last_seen_at = now
            await self.session.flush()
            await self.session.refresh(existing)
            return existing

        page = HubCrawledPage(site_id=site_id, url=url, **fields)
        page.first_seen_at = now
        page.last_seen_at = now
        self.session.add(page)
        await self.session.flush()
        await self.session.refresh(page)
        return page

    async def get(self, page_id: uuid.UUID) -> HubCrawledPage | None:
        return await self.session.get(HubCrawledPage, page_id)

    async def list_by_site(
        self,
        site_id: uuid.UUID,
        status: str | None = None,
    ) -> list[HubCrawledPage]:
        # recorrido-acotado: las paginas de un sitio, que alimenta el listado del panel. No
        # se pagina porque el contrato de `GET /hub/sites/{id}/pages` lo consume el frontend
        # y cambiarlo es una decision de producto, no una correccion de una operacion
        # desbocada. 352 paginas en el sitio mayor (issue #159).
        stmt = select(HubCrawledPage).where(HubCrawledPage.site_id == site_id)
        if status is not None:
            stmt = stmt.where(HubCrawledPage.status == status)
        stmt = stmt.order_by(HubCrawledPage.url)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_gone(self, page_ids: list[uuid.UUID]) -> int:
        if not page_ids:
            return 0
        stmt = (
            update(HubCrawledPage)
            .where(HubCrawledPage.id.in_(page_ids))
            .values(status="gone")
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.rowcount or 0

    async def get_by_canonical(
        self, site_id: uuid.UUID, canonical_url: str
    ) -> HubCrawledPage | None:
        # Igual que `get_by_url`: la pareja identifica una página (issue #159).
        stmt = (
            select(HubCrawledPage)
            .where(
                HubCrawledPage.site_id == site_id,
                HubCrawledPage.canonical_url == canonical_url,
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class SeccionNoCargada(RuntimeError):
    """Se ha preguntado si una selección casa una URL sin haber cargado su sección.

    **Nunca un «no casa» en silencio.** Es el fallo de VER.8 con las reglas inventadas: una
    selección activa que no puede casar nada se ve en pantalla como activa y vacía, sin nada que
    lo explique. Quien pregunta carga las secciones con `secciones_de` y las pasa.
    """


class CorpusSelectionRepo:
    """CRUD de selecciones N:M chatbot→sitio + evaluación de reglas."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        chatbot_id: uuid.UUID,
        site_id: uuid.UUID,
        rule_type: str,
        rule_value: str | None = None,
        auto_ingest_new: bool = True,
        section_id: uuid.UUID | None = None,
    ) -> HubCorpusSelection:
        selection = HubCorpusSelection(
            chatbot_id=chatbot_id,
            site_id=site_id,
            rule_type=rule_type,
            rule_value=rule_value,
            auto_ingest_new=auto_ingest_new,
            section_id=section_id,
        )
        self.session.add(selection)
        await self.session.flush()
        await self.session.refresh(selection)
        return selection

    async def list_by_chatbot(self, chatbot_id: uuid.UUID) -> list[HubCorpusSelection]:
        stmt = (
            select(HubCorpusSelection)
            .where(HubCorpusSelection.chatbot_id == chatbot_id)
            .order_by(HubCorpusSelection.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_site(self, site_id: uuid.UUID) -> list[HubCorpusSelection]:
        stmt = (
            select(HubCorpusSelection)
            .where(HubCorpusSelection.site_id == site_id)
            .order_by(HubCorpusSelection.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, selection_id: uuid.UUID) -> None:
        selection = await self.session.get(HubCorpusSelection, selection_id)
        if selection is None:
            return
        await self.session.delete(selection)
        await self.session.flush()

    async def secciones_de(self, selections: list) -> dict[uuid.UUID, HubWebSection]:
        """Las secciones a las que apuntan estas selecciones, para poder evaluarlas (DIN.3).

        Una sola consulta: `matches` es sincrónica —la evalúan bucles sobre cientos de páginas—,
        así que la carga se hace antes y de golpe.
        """
        ids = {s.section_id for s in selections if getattr(s, "section_id", None)}
        if not ids:
            return {}
        filas = (
            await self.session.execute(
                select(HubWebSection).where(HubWebSection.id.in_(ids))
            )
        ).scalars().all()
        return {fila.id: fila for fila in filas}

    def matches(
        self,
        selection: HubCorpusSelection,
        page_url: str,
        *,
        secciones: dict[uuid.UUID, HubWebSection] | None = None,
    ) -> bool:
        """Evalúa una regla de selección contra una URL de página.

        - **section_id puesto**: manda el patrón de la sección, y `rule_value` se ignora (DIN.3).
        - path_prefix: el path de la URL empieza por rule_value.
        - sitemap_section: marcador semántico — la asignación efectiva
          se materializa por crawl en 9Q.2 y aquí siempre devuelve False.
        - manual: selección explícita; la asociación efectiva se gestiona
          fuera de la regla, por lo que aquí siempre devuelve False.

        DIN.1 — la comparación la hace `curation/secciones.casa_patron`, no una copia local: una
        regla de selección y una sección con el mismo prefijo tienen que decidir igual, o la
        pantalla y el rastreo discreparían sobre qué entra al corpus.
        """
        section_id = getattr(selection, "section_id", None)
        if section_id is not None:
            seccion = (secciones or {}).get(section_id)
            if seccion is None:
                raise SeccionNoCargada(
                    f"la selección {getattr(selection, 'id', '?')} apunta a la sección "
                    f"{section_id} y no se ha cargado: cárgala con `secciones_de`"
                )
            return casa(seccion, page_url)

        if selection.rule_type == "path_prefix":
            if not selection.rule_value:
                return False
            return casa_patron("path_prefix", selection.rule_value, page_url)
        return False
