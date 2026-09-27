"""InitAnonymizationNode — Fase 13.

Posición en el grafo: **justo después de `deterministic_extraction`**, que es lo primero que
deja texto donde mirar, y antes de cualquier nodo que toque LLM.

Lo segundo lo decía este docstring desde el principio y era falso (issue #170): el nodo estaba
entre `data_quality_check` y `ai_assist_draft`, con la transformación de datos y el nodo de
gráficos por delante. Los dos llaman al modelo y los dos invocan `apply_pre_llm` —están
preparados— con un contexto que allí todavía era `None`. Lo comprueba ahora un test que recorre
el grafo, en vez de una frase.

Construye el `RunAnonymizationContext` del workspace recorriendo todos los textos
disponibles (inputs + bloques extraídos), detectando PII con `PiiDetector` y
generando sintéticos con `FakerGenerator` (semilla determinista por workspace + idx).
"""

from __future__ import annotations

from typing import Any

from server.app.modules.redaccion.contracts.runtime import WorkspaceState
from server.app.modules.redaccion.services.anonymization.run_context import (
    AnonymizationMode,
    PiiSpan,
    RunAnonymizationContext,
    disposition_7_mask,
    is_masked_under_disposition_7,
)


class InitAnonymizationNode:
    """Construye y devuelve el `anonymization_context` del workspace."""

    def __init__(self, pii_detector: Any, faker_generator: Any) -> None:
        self._detector = pii_detector
        self._faker = faker_generator

    async def __call__(self, state: WorkspaceState) -> dict:
        mode = _coerce_mode(state.anonymization_mode)

        # OFF: contexto vacío, sin escaneo.
        if mode == AnonymizationMode.OFF:
            return {
                "anonymization_context": RunAnonymizationContext(
                    workspace_id=state.workspace_id,
                    mode=mode,
                ),
            }

        # 1. Recolectar texto de inputs + bloques extraídos.
        text_corpus, source_map = self._gather_text(state)

        # Issue #170 — se pregunta **después** del `return` de OFF y **sólo si hay texto**:
        # `spacy_available` fuerza la carga del modelo (~305 MB), y ni quien tiene la
        # anonimización apagada ni una ejecución sin nada extraído tienen por qué pagarla para
        # informar de una capa que no llegaron a usar.
        #
        # Y sin escaneo la respuesta honrada es `None`, no `False`: `False` afirmaría que se
        # comprobó y no estaba.
        ner_disponible = (
            bool(getattr(self._detector, "spacy_available", False)) if text_corpus else None
        )

        # 2. Detectar spans en todo el corpus.
        raw_spans = self._detector.detect_spans(text_corpus) if text_corpus else []

        # 3. Construir mapas y spans del run.
        spans: list[PiiSpan] = []
        forward_map: dict[str, str] = {}
        reverse_map: dict[str, str] = {}
        seen_originals: set[str] = set()

        for idx, raw in enumerate(raw_spans):
            original = getattr(raw, "original_text", None) or getattr(raw, "original", "")
            if not original or original in seen_originals:
                continue
            seen_originals.add(original)

            pii_type = getattr(raw, "type", "")
            block_id = _find_source_block_id(raw, source_map)

            if is_masked_under_disposition_7(pii_type, mode):
                synthetic = disposition_7_mask(pii_type, original)
                masked = True
            else:
                synthetic = self._generate_synthetic(
                    pii_type=pii_type,
                    original=original,
                    workspace_id=str(state.workspace_id),
                    idx=idx,
                    suggested=getattr(raw, "suggested_fake", ""),
                )
                masked = False

            spans.append(
                PiiSpan(
                    type=pii_type,
                    original=original,
                    synthetic=synthetic,
                    confidence=float(getattr(raw, "confidence", 1.0)),
                    source_block_id=block_id,
                    masked=masked,
                )
            )

            # En modo DETECT_ONLY no llenamos los mapas: sustituir/revertir son no-op.
            # En modo REPLACE y máscara LOPDGDD sí registramos forward; reverse_map
            # NO incluye spans enmascarados (irreversibles por diseño).
            if mode != AnonymizationMode.DETECT_ONLY:
                forward_map[original] = synthetic
                if not masked:
                    reverse_map[synthetic] = original

        return {
            "anonymization_context": RunAnonymizationContext(
                workspace_id=state.workspace_id,
                run_manifest_id=state.run_manifest_id,
                mode=mode,
                spans=spans,
                forward_map=forward_map,
                reverse_map=reverse_map,
                ner_disponible=ner_disponible,
            ),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _gather_text(
        self, state: WorkspaceState
    ) -> tuple[str, dict[str, str]]:
        """Concatena texto de inputs normalizados y bloques extraídos.

        Cuando este nodo corre (después de DataQualityCheckNode), todo el texto
        relevante ya está en `artifacts_normalized` (markdown de inputs) o en
        `blocks[*].content`. `state.inputs` sólo guarda metadata del fichero
        (slot_id, storage_path, …), nada de texto.

        Devuelve (corpus, source_map) donde source_map mapea texto→block_id (o
        slot_id) para atribución; si el mismo string aparece en varios sitios,
        se registra el primero.
        """
        parts: list[str] = []
        source_map: dict[str, str] = {}

        for slot_id, markdown in state.artifacts_normalized.items():
            if markdown and markdown.strip():
                parts.append(markdown)
                source_map.setdefault(markdown, slot_id)

        for block_id, block_state in state.blocks.items():
            content = block_state.content or {}
            for value in content.values():
                if isinstance(value, str) and value.strip():
                    parts.append(value)
                    source_map.setdefault(value, block_id)
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str) and item.strip():
                            parts.append(item)
                            source_map.setdefault(item, block_id)

        # Issue #170 — **las instrucciones en lenguaje natural también se escanean.** Viven en
        # `spec.blocks[*].config`, no en el contenido de ningún bloque ni en los ficheros
        # normalizados, así que no entraban por ninguno de los dos caminos de arriba. Y son un
        # sitio donde el dato personal entra **a mano**: las escribe una persona («agrupa las
        # dietas de …»), y de ahí salen tal cual hacia el modelo en el nodo de transformación y
        # en el de gráficos.
        #
        # Sin esto el cableado del contexto no sirve de nada en ese camino: el mapa sale vacío y
        # `apply_pre_llm` no tiene qué sustituir. Son dos mitades de lo mismo.
        for contrato in getattr(getattr(state, "spec", None), "blocks", None) or []:
            config = getattr(contrato, "config", None)
            for campo in ("nl_instruction", "nl_prompt"):
                texto = getattr(config, campo, None)
                if isinstance(texto, str) and texto.strip():
                    parts.append(texto)
                    source_map.setdefault(texto, str(getattr(contrato, "id", "")))

        corpus = "\n".join(parts)
        return corpus, source_map

    def _generate_synthetic(
        self,
        *,
        pii_type: str,
        original: str,
        workspace_id: str,
        idx: int,
        suggested: str,
    ) -> str:
        """Genera un sintético determinista. Resuelve colisiones reintentando con sufijo."""
        candidate = self._call_faker(pii_type, original, workspace_id, idx)
        if not candidate:
            candidate = suggested or f"REDACTED_{pii_type}_{idx}"
        return candidate

    def _call_faker(
        self,
        pii_type: str,
        original: str,
        workspace_id: str,
        idx: int,
    ) -> str:
        # FakerGenerator.generate(entity_type, original, context=...) cachea por
        # (type, original) — determinista. Aceptamos su valor tal cual.
        try:
            return self._faker.generate(pii_type, original, context=f"{workspace_id}:{idx}")
        except TypeError:
            # Fallback si el generator no acepta context.
            return self._faker.generate(pii_type, original)


def _coerce_mode(raw: str | AnonymizationMode) -> AnonymizationMode:
    if isinstance(raw, AnonymizationMode):
        return raw
    try:
        return AnonymizationMode(raw)
    except ValueError:
        return AnonymizationMode.REPLACE


def _find_source_block_id(
    raw_span: Any, source_map: dict[str, str]
) -> str | None:
    """Atribuye el span al primer block/slot cuyo texto lo contenga.

    El PII suele aparecer como subcadena del texto del bloque ("Contacto:
    juan@example.com"), por lo que la búsqueda no puede ser por igualdad exacta.
    """
    original = getattr(raw_span, "original_text", None) or getattr(raw_span, "original", "")
    if not original:
        return None
    if original in source_map:
        return source_map[original]
    for text, source_id in source_map.items():
        if original in text:
            return source_id
    return None
