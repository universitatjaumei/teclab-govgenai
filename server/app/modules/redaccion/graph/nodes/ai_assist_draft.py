"""AIAssistDraftNode — genera texto IA para bloques AI_ASSISTED_TEXT / AI_SUMMARY / AI_REWRITE (9R.6.3/9R.6.6/9R.5.9)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Protocol

from server.app.modules.redaccion.contracts.runtime import ExtractionWarning, WorkspaceState
from server.app.modules.redaccion.services.anonymization.hooks import (
    apply_post_llm,
    apply_pre_llm,
)
from server.app.modules.redaccion.services.block_executor import (
    BlockExecutor,
    propagate_dependency_failures,
)

_AI_BLOCK_KINDS = frozenset({"AI_ASSISTED_TEXT", "AI_SUMMARY", "AI_REWRITE"})
_SKIP_STATUSES = frozenset({"approved", "locked"})
_MARKDOWN_LIMIT = 30_000


class LLMService(Protocol):
    model_name: str

    async def generate(self, prompt: str, context: str) -> str: ...


def _block_text(content: dict) -> str:
    """Extrae el texto más rico disponible del contenido de un bloque.

    Preferencia (9R.5.9): document.markdown > free_text > repr(content).
    Si el documento es complex_tables, añade un volcado JSON de las tablas.
    """
    doc = content.get("document")
    if isinstance(doc, dict) and doc.get("markdown"):
        text = doc["markdown"][:_MARKDOWN_LIMIT]
        if doc.get("extraction_strategy") == "complex_tables":
            pages = doc.get("pages") or []
            tables = [tbl for p in pages for tbl in (p.get("tables") or [])]
            if tables:
                text += f"\n\ntables_json:\n{json.dumps(tables, ensure_ascii=False)[:10_000]}"
        return text
    if content.get("free_text"):
        return str(content["free_text"])
    return str(content)


_VALIDADOS = ("extracted", "approved")


class SinDatosParaValorar(ValueError):
    """El apartado declara de qué tabla habla y esa tabla no ha producido datos.

    Se trata como fallo del bloque, no como contexto vacío: una valoración redactada sin sus
    datos parece fundamentada y no lo está, que es peor que un apartado que falta.
    """


def _build_context(blocks: dict) -> str:
    """Todos los bloques validados. Es el alcance de las plantillas que no declaran anclaje."""
    parts = []
    for bid, bstate in sorted(blocks.items()):
        if bstate.status in _VALIDADOS and bstate.content:
            parts.append(f"[{bid}]\n{_block_text(bstate.content)}")
    return "\n\n".join(parts)


def _contexto_anclado(blocks: dict, refs: list[str]) -> str:
    """Solo las tablas que el apartado declara, **en el orden en que las declara**.

    SEG.1 — el orden es de la plantilla y no alfabético: quien redacta la plantilla sabe si la
    tabla de matrícula va antes que la de tasas, y esa secuencia es parte de lo que se valora.
    """
    parts = []
    for ref in refs:
        bstate = blocks.get(ref)
        if bstate is None or bstate.status not in _VALIDADOS or not bstate.content:
            raise SinDatosParaValorar(
                f"el apartado se apoya en «{ref}», que no ha producido datos"
            )
        parts.append(f"[{ref}]\n{_block_text(bstate.content)}")
    return "\n\n".join(parts)


class _TrazaQueNoTraza:
    """Lo mínimo que `BlockExecutor` pide cuando el nodo se construye sin tracing.

    Existe para que construir el nodo a secas —los tests y cualquier uso fuera del grafo— no
    obligue a pasar un servicio de observabilidad. El grafo sí le pasa el suyo.
    """

    class _Span:
        def add_event(self, *_args: Any, **_kwargs: Any) -> None: ...
        def end(self, *_args: Any, **_kwargs: Any) -> None: ...

    def node_span(self, *_args: Any, **_kwargs: Any) -> "_TrazaQueNoTraza._Span":
        return self._Span()


class AIAssistDraftNode:
    """Invoca el LLM para generar borradores de bloques IA usando solo datos validados como contexto.

    En caso de fallo por bloque: marca status=failed y continúa con el resto.

    **Delega el reintento en `BlockExecutor`** (issue #153). Aquél declaraba en mayúsculas ser
    «la ÚNICA superficie con política de retry» y no lo importaba nadie, así que un *timeout* del
    modelo —transitorio por definición— dejaba el apartado caído para siempre, y la columna
    `retry_attempts` que la pantalla pinta desde la #98 valía 0 en todas las filas porque nadie
    la escribía.

    Y **propaga los fallos por dependencia** antes de redactar nada: si el bloque del que un
    apartado declara depender ha fallado, ese apartado no se genera. Es la misma regla que ya
    aplicaba el camino anclado de SEG.1, con las mismas palabras —«una valoración redactada sin
    sus datos parece fundamentada y no lo está»—, sólo que `depends_on` es otro campo y por ahí
    no la comprobaba nadie.
    """

    def __init__(
        self,
        llm_service: Any,
        tracing: Any = None,
        retry_delay_seconds: float = 2.0,
    ) -> None:
        self._llm = llm_service
        # El tracing es el del grafo cuando lo hay; `BlockExecutor` sólo le pide spans.
        self._executor = BlockExecutor(
            tracing or _TrazaQueNoTraza(), retry_delay_seconds=retry_delay_seconds
        )

    async def __call__(self, state: WorkspaceState) -> dict:
        if state.spec is None:
            return {}

        anon_ctx = state.anonymization_context
        # El contexto de todo el informe se calcula una vez y sirve a los apartados **sin**
        # anclaje. Los anclados se construyen uno a uno más abajo: es la razón de ser de SEG.1.
        contexto_completo = apply_pre_llm(_build_context(state.blocks), anon_ctx)
        updated_blocks = dict(state.blocks)
        new_warnings = list(state.warnings)
        now = datetime.now(timezone.utc)

        for block_contract in state.spec.blocks:
            if block_contract.kind not in _AI_BLOCK_KINDS:
                continue

            block_id = block_contract.id
            if block_id not in updated_blocks:
                continue

            # Se recalcula en cada vuelta y no una sola vez al entrar: un apartado de IA que
            # falla aquí es la dependencia del siguiente, y la cascada tiene que verlo **en este
            # mismo paso**. Es idempotente y barata.
            updated_blocks = propagate_dependency_failures(state.spec, updated_blocks)

            block_state = updated_blocks[block_id]
            if block_state.status in _SKIP_STATUSES:
                continue
            if block_state.status == "failed":
                # Lo marcó la propagación: su dependencia no produjo datos. No se llama al
                # modelo, que es el punto — redactarlo produciría un texto con aspecto de
                # fundamentado sobre lo que quedara en el contexto.
                new_warnings.append(ExtractionWarning(
                    block_id=block_id,
                    message=block_state.last_error_message or "dependency_failed",
                    kind="dependency_failed",
                ))
                continue

            refs = list(getattr(block_contract, "data_block_refs", []) or [])

            async def _redactar(contrato, _state, _refs=refs):
                if _refs:
                    contexto = apply_pre_llm(
                        _contexto_anclado(updated_blocks, _refs), anon_ctx
                    )
                else:
                    contexto = contexto_completo

                raw_text = await self._llm.generate(
                    prompt=contrato.ai_prompt_template_id,
                    context=contexto,
                )
                # POST-HOOK (Fase 13): revertimos sintético → original en el output.
                return apply_post_llm(raw_text, anon_ctx)

            resultado = await self._executor.execute(
                _redactar, block_contract, state, failure_kind="ai_failed"
            )

            if resultado.status == "failed":
                new_warnings.append(ExtractionWarning(
                    block_id=block_id, message=resultado.last_error or "", kind="ai_error",
                ))
                updated_blocks[block_id] = block_state.model_copy(update={
                    "status": "failed",
                    "failure_kind": resultado.failure_kind or "ai_failed",
                    "last_error_message": (resultado.last_error or "")[:500],
                    "retry_attempts": resultado.retry_attempts,
                    "last_updated_by": "system",
                    "updated_at": now,
                })
                continue

            updated_blocks[block_id] = block_state.model_copy(update={
                "retry_attempts": resultado.retry_attempts,
                "content": {
                    "text": resultado.output,
                    "model_used": self._llm.model_name,
                    "prompt_version": block_contract.ai_prompt_template_id,
                    # De dónde salió lo que el modelo leyó. Va en el estado porque el estado es
                    # el registro (P6), y de aquí lo recoge el manifiesto.
                    "context_scope": "anchored" if refs else "full",
                    "context_block_ids": refs,
                },
                "status": "ai_generated",
                "last_updated_by": "ai",
                "updated_at": now,
            })

        return {"blocks": updated_blocks, "warnings": new_warnings}
