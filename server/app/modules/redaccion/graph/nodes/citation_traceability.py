"""CitationAndTraceabilityNode — adjunta citaciones a bloques IA referenciando datos origen (9R.6.3/9R.5.9)."""
from __future__ import annotations

from datetime import datetime, timezone

from server.app.modules.redaccion.contracts.runtime import Citation, WorkspaceState

_AI_BLOCK_KINDS = frozenset({"AI_ASSISTED_TEXT", "AI_SUMMARY", "AI_REWRITE"})


def _page_from_content(content: dict) -> int | None:
    """Extrae el número de la primera página del documento enriquecido (9R.5.9)."""
    doc = content.get("document")
    if not isinstance(doc, dict):
        return None
    pages = doc.get("pages") or []
    if pages and isinstance(pages[0], dict):
        return pages[0].get("page_num")
    return None


class CitationAndTraceabilityNode:
    """Para cada bloque IA en estado ai_generated, adjunta Citation de los bloques fuente (depends_on)."""

    async def __call__(self, state: WorkspaceState) -> dict:
        if state.spec is None:
            return {}

        updated_blocks = dict(state.blocks)

        for block_contract in state.spec.blocks:
            if block_contract.kind not in _AI_BLOCK_KINDS:
                continue

            block_id = block_contract.id
            block_state = updated_blocks.get(block_id)
            if block_state is None or block_state.status != "ai_generated":
                continue

            citations: list[Citation] = []
            for ref in block_contract.depends_on:
                source_state = state.blocks.get(ref.block_id)
                if source_state is None or not source_state.content:
                    continue

                excerpt: str | None = None
                if ref.projection == "field" and ref.field_path:
                    excerpt = str(source_state.content.get(ref.field_path, ""))[:300]
                elif ref.projection == "summary":
                    excerpt = str(source_state.content.get("free_text", ""))[:300]
                else:
                    excerpt = str(source_state.content)[:300]

                page = _page_from_content(source_state.content) if source_state.content else None

                citations.append(Citation(
                    source_document=ref.block_id,
                    page=page,
                    excerpt=excerpt or None,
                ))

            if citations:
                updated_blocks[block_id] = block_state.model_copy(
                    update={"citations": citations}
                )

        self._rellenar_bloques_de_citas(state, updated_blocks)
        return {"blocks": updated_blocks}

    def _rellenar_bloques_de_citas(self, state: WorkspaceState, bloques: dict) -> None:
        """El apartado de fuentes del informe (issue #180).

        Un `CITATION_BLOCK` recoge las citas de los bloques que nombra en `source_block_refs`.
        Lo hacía `CitationBlockHandler`, que **nadie montaba**: el bloque se quedaba sin
        contenido y el ensamblador lo saltaba, así que una plantilla con un apartado de fuentes
        —que `llm_spec_service` ofrece al modelo como tipo disponible— salía sin él y sin
        decirlo.

        Va después del bucle de arriba, y no antes: recoge las citas que ese bucle acaba de
        adjuntar a los bloques de IA. Al revés recogería las de la ejecución anterior.
        """
        if state.spec is None:
            return

        ahora = datetime.now(timezone.utc)
        for contrato in state.spec.blocks:
            if contrato.kind != "CITATION_BLOCK":
                continue
            bloque = bloques.get(contrato.id)
            if bloque is None:
                continue

            citas = [
                cita.model_dump(mode="json")
                for ref_id in contrato.source_block_refs
                if (fuente := bloques.get(ref_id)) is not None and fuente.citations
                for cita in fuente.citations
            ]
            if not citas:
                continue

            bloques[contrato.id] = bloque.model_copy(
                update={
                    "content": {"citations": citas},
                    "status": "extracted",
                    "updated_at": ahora,
                }
            )
