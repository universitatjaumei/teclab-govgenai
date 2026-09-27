"""Tests de preservación de citas y persistencia del manifest — Fase 13.

Cubre los grupos "Citas" y "Persistencia" del prompt 13.1.

Citas: CitationAndTraceabilityNode (9R.6.3) construye citas a partir de
`block_contract.depends_on`, leyendo `source_block.content` directamente —
NUNCA del output del LLM. Por tanto las citas siempre contienen originales
mientras el bloque fuente sea determinista (DeterministicExtractionNode no
pasa por el LLM). Estos tests confirman ese invariante bajo modo REPLACE.

Persistencia: AnonymizationSummary expone sólo metadata; forward_map y
reverse_map del context NO se serializan al manifest.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from server.app.modules.redaccion.contracts.manifest import DraftingRunManifest
from server.app.modules.redaccion.contracts.runtime import (
    BlockState,
    WorkspaceState,
)
from server.app.modules.redaccion.graph.nodes.citation_traceability import (
    CitationAndTraceabilityNode,
)
from server.app.modules.redaccion.services.anonymization.run_context import (
    AnonymizationMode,
    AnonymizationSummary,
    PiiSpan,
    RunAnonymizationContext,
)


def _make_block(
    block_id: str,
    *,
    content: dict | None = None,
    status: str = "extracted",
    kind: str = "DETERMINISTIC_DATA",
) -> BlockState:
    return BlockState(
        block_id=block_id,
        kind=kind,
        status=status,  # type: ignore[arg-type]
        content=content,
        last_updated_by="system",
        updated_at=datetime.now(timezone.utc),
    )


def _spec_with_dependent_ai_block(
    ai_block_id: str, source_block_id: str
) -> object:
    """Spec mínima: un bloque IA que depende de un bloque determinista por field_path='free_text'."""
    ref = SimpleNamespace(
        block_id=source_block_id,
        projection="summary",  # usa source.content.get("free_text") como excerpt
        field_path=None,
    )
    ai_contract = SimpleNamespace(
        id=ai_block_id,
        kind="AI_ASSISTED_TEXT",
        depends_on=[ref],
    )
    source_contract = SimpleNamespace(
        id=source_block_id,
        kind="DETERMINISTIC_DATA",
        depends_on=[],
    )
    return SimpleNamespace(blocks=[source_contract, ai_contract])


# ──────────────────────────────────────────────────────────────────
# Tests de preservación de citas
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_citations_preserve_original_pii_after_reversal() -> None:
    """Una cita generada sobre 'Juan García' aparece en el output final como 'Juan García'.

    Razón: las citas se construyen desde `source_block.content`, que es
    determinista (DeterministicExtractionNode) y nunca pasa por el LLM. El
    sintético 'Carlos Pérez' que circula por el LLM no toca el path de citas.
    """
    state = WorkspaceState(
        workspace_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        report_profile="GENERIC_REPORT",
        inputs={},
        blocks={
            "data_block": _make_block(
                "data_block",
                content={"free_text": "Firma: Juan García el 2026-05-18."},
                status="extracted",
            ),
            "ai_block": _make_block(
                "ai_block",
                content={
                    "text": "Análisis: el firmante es Juan García.",
                    "model_used": "gpt-4o",
                    "prompt_version": "v1",
                },
                status="ai_generated",
                kind="AI_ASSISTED_TEXT",
            ),
        },
        status="drafting",
        warnings=[],
        anonymization_context=RunAnonymizationContext(
            workspace_id=uuid.uuid4(),
            mode=AnonymizationMode.REPLACE,
            spans=[
                PiiSpan(type="PERSON", original="Juan García", synthetic="Carlos Pérez"),
            ],
            forward_map={"Juan García": "Carlos Pérez"},
            reverse_map={"Carlos Pérez": "Juan García"},
        ),
    )
    state.spec = _spec_with_dependent_ai_block("ai_block", "data_block")

    out = await CitationAndTraceabilityNode()(state)
    ai_block = out["blocks"]["ai_block"]

    assert ai_block.citations is not None and len(ai_block.citations) == 1
    excerpt = ai_block.citations[0].excerpt or ""
    assert "Juan García" in excerpt
    assert "Carlos Pérez" not in excerpt


@pytest.mark.asyncio
async def test_citations_keep_source_document_metadata() -> None:
    """`Citation.source_document` y la página son metadata, no PII — estables tras anonimización."""
    state = WorkspaceState(
        workspace_id=uuid.uuid4(),
        template_version_id=uuid.uuid4(),
        report_profile="GENERIC_REPORT",
        inputs={},
        blocks={
            "data_block": _make_block(
                "data_block",
                content={
                    "free_text": "Datos del expediente firmado por Juan García.",
                    "page": 3,
                },
                status="extracted",
            ),
            "ai_block": _make_block(
                "ai_block",
                content={"text": "Resumen del expediente."},
                status="ai_generated",
                kind="AI_ASSISTED_TEXT",
            ),
        },
        status="drafting",
        warnings=[],
        anonymization_context=RunAnonymizationContext(
            workspace_id=uuid.uuid4(),
            mode=AnonymizationMode.REPLACE,
            spans=[],
            forward_map={"Juan García": "Carlos Pérez"},
            reverse_map={"Carlos Pérez": "Juan García"},
        ),
    )
    state.spec = _spec_with_dependent_ai_block("ai_block", "data_block")

    out = await CitationAndTraceabilityNode()(state)
    citations = out["blocks"]["ai_block"].citations
    assert citations and len(citations) == 1
    assert citations[0].source_document == "data_block"
    # page se extrae si el contenido lo expone — confirmamos que no se anonimiza.
    assert citations[0].page in (3, None)


# ──────────────────────────────────────────────────────────────────
# Tests de persistencia segura
# ──────────────────────────────────────────────────────────────────


def test_run_manifest_records_summary_without_originals() -> None:
    """El manifest expone counts_by_type + total_spans + mode + detected_at; nunca originales ni sintéticos."""
    workspace_id = uuid.uuid4()
    ctx = RunAnonymizationContext(
        workspace_id=workspace_id,
        mode=AnonymizationMode.REPLACE,
        spans=[
            PiiSpan(type="PERSON", original="Juan García", synthetic="Carlos Pérez"),
            PiiSpan(type="EMAIL", original="ana@x.com", synthetic="f@y.com"),
            PiiSpan(type="PERSON", original="Luis Ruiz", synthetic="Pedro Sanz"),
        ],
        forward_map={"Juan García": "Carlos Pérez", "ana@x.com": "f@y.com", "Luis Ruiz": "Pedro Sanz"},
        reverse_map={"Carlos Pérez": "Juan García", "f@y.com": "ana@x.com", "Pedro Sanz": "Luis Ruiz"},
    )

    manifest = DraftingRunManifest(
        id=uuid.uuid4(),
        workspace_id=workspace_id,
        template_version_id=uuid.uuid4(),
        report_profile="GENERIC_REPORT",
        status_at_close="exported",
        anonymization_summary=AnonymizationSummary.from_context(ctx),
    )

    summary = manifest.anonymization_summary
    assert summary is not None
    assert summary.total_spans == 3
    assert summary.counts_by_type == {"PERSON": 2, "EMAIL": 1}
    # Serialización completa del manifest no debe contener originales ni sintéticos.
    blob = json.dumps(manifest.model_dump(mode="json"), default=str)
    for forbidden in ("Juan García", "Carlos Pérez", "ana@x.com", "f@y.com", "Luis Ruiz", "Pedro Sanz"):
        assert forbidden not in blob, f"{forbidden!r} no debe persistirse en el manifest"


def test_anonymization_context_never_persists_forward_or_reverse_map_to_db() -> None:
    """Garantía estructural: AnonymizationSummary NO tiene campos forward_map/reverse_map/spans/originales.

    Si alguien añadiera esos campos al summary, este test rompería y obligaría a
    revisar el contrato — son los únicos campos que NUNCA deben salir de memoria.
    """
    summary_fields = set(AnonymizationSummary.model_fields.keys())
    forbidden = {"forward_map", "reverse_map", "spans", "originals"}
    leaked = summary_fields & forbidden
    assert not leaked, f"AnonymizationSummary expone campos prohibidos: {leaked}"

    # Y por simetría confirmamos los campos esperados (no nos quedamos cortos).
    #
    # `ner_disponible` entra con la issue #170 y esta lista es justo la revisión que el test
    # existe para forzar: es un booleano sobre **la instalación**, no sobre el documento —dice si
    # había modelo lingüístico cuando se escaneó—, así que no puede llevar nada de nadie.
    expected = {"mode", "counts_by_type", "total_spans", "detected_at", "ner_disponible"}
    assert summary_fields == expected
