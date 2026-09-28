"""Contratos de runtime del DraftingCoreGraph — 9R.1.3 / 9R.6.6.

WorkspaceState es el estado que fluye por el grafo durante una ejecución.
BlockState tiene una máquina de estados explícita; las transiciones inválidas
levantan InvalidBlockTransitionError.
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    pass

from server.app.modules.redaccion.contracts.template import (
    ReportProfileId,
    ReportTemplateSpec,
)

# ---------------------------------------------------------------------------
# Estados
# ---------------------------------------------------------------------------

BlockStatus = Literal[
    "draft",
    "missing_input",
    "extracted",
    "ai_generated",
    "needs_review",
    "approved",
    "rejected",
    "locked",
    "failed",
]

FailureKind = Literal[
    "extraction_failed",
    "ai_failed",
    "script_failed",
    "validation_failed",
]

WorkspaceStatus = Literal[
    "draft",
    "ingesting",
    "extracting",
    "drafting",
    "in_review",
    "assembled",
    "exported",
    "error",
]

# Transiciones válidas por estado origen
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "draft":         {"missing_input", "extracted", "ai_generated", "failed"},
    "missing_input": {"extracted", "failed"},
    "extracted":     {"ai_generated", "needs_review", "failed"},
    "ai_generated":  {"needs_review", "failed"},
    "needs_review":  {"approved", "rejected"},
    "rejected":      {"ai_generated", "draft"},
    "approved":      {"locked"},
    "locked":        set(),
    "failed":        {"draft", "extracted", "ai_generated", "rejected"},
}


# ---------------------------------------------------------------------------
# Excepciones
# ---------------------------------------------------------------------------

class InvalidBlockTransitionError(Exception):
    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(
            f"Invalid block transition: {from_status!r} → {to_status!r}"
        )
        self.from_status = from_status
        self.to_status = to_status


class WorkspaceBlockedByFailedBlocksError(Exception):
    """Raised by FinalAssemblerNode when a required block has status=failed."""

    def __init__(self, failed_block_ids: list[str]) -> None:
        super().__init__(
            f"Workspace blocked: required blocks failed — {failed_block_ids}"
        )
        self.failed_block_ids = failed_block_ids


# ---------------------------------------------------------------------------
# Tipos de apoyo
# ---------------------------------------------------------------------------

class Citation(BaseModel):
    source_document: str
    page: int | None = None
    cell_ref: str | None = None
    excerpt: str | None = None


class ApprovalRecord(BaseModel):
    approved_by: UUID
    approved_at: datetime
    note: str | None = None


class InputArtifact(BaseModel):
    slot_id: str
    filename: str
    storage_path: str
    size_bytes: int
    uploaded_at: datetime


class ExtractionWarning(BaseModel):
    block_id: str | None = None
    message: str
    kind: str  # "missing_data" | "low_confidence" | "type_mismatch" | …


# ---------------------------------------------------------------------------
# BlockState
# ---------------------------------------------------------------------------

class BlockState(BaseModel):
    block_id: str
    kind: str
    status: BlockStatus
    content: dict | None = None
    original_ai_content: dict | None = None
    citations: list[Citation] | None = None
    last_updated_by: Literal["system", "user", "ai"]
    updated_at: datetime
    approval: ApprovalRecord | None = None
    failure_kind: FailureKind | None = None
    last_error_message: str | None = None
    retry_attempts: int = 0

    def validate_transition(self, new_status: BlockStatus) -> None:
        allowed = _VALID_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise InvalidBlockTransitionError(self.status, new_status)


# ---------------------------------------------------------------------------
# WorkspaceState
# ---------------------------------------------------------------------------

class WorkspaceState(BaseModel):
    workspace_id: UUID
    template_version_id: UUID
    report_profile: ReportProfileId
    inputs: dict[str, InputArtifact]
    blocks: dict[str, BlockState]
    block_outputs: dict[str, dict] = {}
    status: WorkspaceStatus
    warnings: list[ExtractionWarning]
    run_manifest_id: UUID | None = None
    spec: ReportTemplateSpec | None = None
    artifacts_normalized: dict[str, str] = Field(default_factory=dict)
    user_edits: dict[str, dict] = Field(default_factory=dict)
    final_document: str | None = None
    final_document_hash: str | None = None
    #: Lo que una persona escribió en los campos de los bloques `USER_INPUT` (issue #86).
    #: Va aparte de `inputs`, que son ficheros: mezclarlos haría que un texto apareciera en la
    #: pantalla como un fichero subido y en el registro como una entrada corrupta.
    manual_inputs: dict[str, str] = Field(default_factory=dict)
    regenerate_blocks: set[str] = Field(default_factory=set)
    skip_blocks: set[str] = Field(default_factory=set)
    # Fase 13 — NER reversible. `anonymization_mode` se carga del workspace en
    # load_template; `anonymization_context` lo establece InitAnonymizationNode.
    # Tipado vía TYPE_CHECKING para evitar ciclo contracts↔services.
    anonymization_mode: str = "replace"
    anonymization_context: Any = None
