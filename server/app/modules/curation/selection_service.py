"""Servicio de selección de corpus: candidatas, ingestión manual y retirada (9Q.7).

Deploy: edge.

Gestiona la relación N:M entre páginas rastreadas y chatbots:
- candidates: páginas activas del sitio aún no ingeridas para un chatbot.
- ingest_page: ingesta manual de una página concreta.
- retire_page: retira los documentos de una página para un chatbot.
"""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select


class CorpusSelectionService:
    """Orquesta la selección de corpus para un par (sitio, chatbot)."""

    def __init__(
        self,
        session: Any,
        page_repo: Any,
        selection_repo: Any,
        watcher: Any,
    ) -> None:
        self._session = session
        self._page_repo = page_repo
        self._selection_repo = selection_repo
        self._watcher = watcher

    async def candidates(
        self, site_id: uuid.UUID, chatbot_id: uuid.UUID
    ) -> list:
        """Páginas activas del sitio, con su estado frente al corpus de este chatbot.

        Incluye tanto las que casan una selección path_prefix como las que
        son nuevas (sin regla que las case). El campo is_new=True indica que
        la página no está cubierta por ninguna regla de selección activa.

        CUR.5 — las ya ingeridas **también se devuelven**, marcadas con `is_ingested`. Antes se
        descartaban, y esconder la fila no es lo mismo que decir que ya está en el corpus: quien
        publica no distinguía «ingerida» de «nunca fue candidata», y al pulsar «Ingerir» la fila
        desaparecía sin confirmar nada. La pantalla es quien decide no volver a ofrecerla.
        """
        from server.app.modules.agents_hub.database.operational_models import HubDocument
        from server.app.modules.curation.selection_contracts import (
            CandidatePageView,
        )

        # 1. Páginas activas del sitio
        pages = await self._page_repo.list_by_site(site_id, status="active")

        # 2. IDs de páginas ya ingeridas para este chatbot
        stmt = (
            select(HubDocument.crawled_page_id)
            .where(HubDocument.chatbot_id == chatbot_id)
            .where(HubDocument.crawled_page_id.isnot(None))
        )
        result = await self._session.execute(stmt)
        ingested_ids: set[uuid.UUID] = {row[0] for row in result.all()}

        # 3. Selecciones de este chatbot para el sitio
        all_sels = await self._selection_repo.list_by_chatbot(chatbot_id)
        site_sels = [s for s in all_sels if s.site_id == site_id]

        # DIN.3 — las secciones a las que apuntan, cargadas antes del bucle: `matches` es
        # sincrónica y aquí se evalúa una vez por página.
        secciones = await self._selection_repo.secciones_de(site_sels)

        # 4. Construir candidatas
        candidates = []
        for page in pages:
            matched_rule: str | None = None
            for sel in site_sels:
                if self._selection_repo.matches(sel, page.url, secciones=secciones):
                    # Con `section_id` puesto, lo que casó fue el patrón de la sección: decir
                    # `rule_value` mentiría sobre por qué está seleccionada esta página.
                    seccion = secciones.get(getattr(sel, "section_id", None))
                    matched_rule = seccion.pattern if seccion is not None else sel.rule_value
                    break

            candidates.append(
                CandidatePageView(
                    page_id=page.id,
                    url=page.url,
                    title=getattr(page, "title", None),
                    matched_rule=matched_rule,
                    is_new=(matched_rule is None),
                    is_ingested=(page.id in ingested_ids),
                    propuesta_at=getattr(page, "propuesta_at", None),
                    propuesta_por=getattr(page, "propuesta_por", None),
                )
            )

        return candidates

    async def ingest_page(self, chatbot_id: uuid.UUID, page_id: uuid.UUID) -> Any:
        """Ingesta manual de una página concreta en un chatbot.

        Idempotente: si ya existe un documento con el mismo contenido, el
        watcher lo actualiza sin duplicar.
        """
        page = await self._page_repo.get(page_id)
        if page is None:
            raise ValueError(f"Page {page_id} not found")

        doc, _ = await self._watcher.process_source(
            source_url=page.url,
            chatbot_id=chatbot_id,
            prefetched_content=getattr(page, "markdown_content", None),
            title=getattr(page, "title", None),
            crawled_page_id=page.id,
        )
        return doc

    async def retire_page(self, chatbot_id: uuid.UUID, page_id: uuid.UUID) -> int:
        """Retira todos los HubDocument de esta página para el chatbot y sus chunks.

        Devuelve el número de documentos eliminados.
        """
        from server.app.modules.agents_hub.database.operational_models import (
            HubDocument,
            HubDocumentChunk,
        )

        stmt = select(HubDocument).where(
            HubDocument.chatbot_id == chatbot_id,
            HubDocument.crawled_page_id == page_id,
        )
        result = await self._session.execute(stmt)
        docs = result.scalars().all()

        count = 0
        for doc in docs:
            await self._session.execute(
                delete(HubDocumentChunk).where(HubDocumentChunk.document_id == doc.id)
            )
            await self._session.delete(doc)
            count += 1

        if count:
            await self._session.flush()

        return count
