"""Contratos Pydantic de plantilla y versión — 9R.1.1 / 9R.1.2.

ReportTemplateContract y ReportTemplateVersion son inmutables una vez publicados:
las plantillas solo se versionan, nunca se editan in-place.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# Perfiles conocidos — se amplía en 9R.2.1
from typing import Literal as _Literal

ReportProfileId = _Literal[
    "GENERIC_REPORT",
    "ANNUAL_REPORT",
    "DOCTORATE_PROGRAM_REPORT",
    "CONTRACT_REPORT",
    "FREEFORM_MEMO",
]


class AIBlockPolicy(str, Enum):
    ALLOWED = "allowed"
    DISABLED = "disabled"
    REQUIRED_REVIEW = "required_review"


class ReviewPolicy(str, Enum):
    NONE = "none"
    OPTIONAL = "optional"
    REQUIRED = "required"


class ExportPolicy(str, Enum):
    DOCX = "docx"
    ODT = "odt"
    PDF = "pdf"
    MARKDOWN = "markdown"


# ---------------------------------------------------------------------------
# Re-exports de los contratos definidos en 9R.1.2
# (los tests de 9R.1.1 importan desde este módulo)
# ---------------------------------------------------------------------------

from server.app.modules.redaccion.contracts.blocks import (  # noqa: E402
    BlockContract,
    StaticTextBlock,
    UserInputBlock,
    DeterministicDataBlock,
    TableBlock,
    ChartBlock,
    DataTransformBlock,
    DataTransformBlockConfig,
    AIAssistedTextBlock,
    AISummaryBlock,
    AIRewriteBlock,
    CitationBlock,
    ReviewGateBlock,
)
from server.app.modules.redaccion.contracts.inputs import InputContract, InputSlot  # noqa: E402
from server.app.modules.redaccion.contracts.ui import (  # noqa: E402
    ReportUIContract,
    UISection,
    UIFieldDescriptor,
    UIDropzoneDescriptor,
)

__all__ = [
    "ReportProfileId",
    "AIBlockPolicy",
    "ReviewPolicy",
    "ExportPolicy",
    # blocks
    "BlockContract",
    "StaticTextBlock",
    "UserInputBlock",
    "DeterministicDataBlock",
    "TableBlock",
    "ChartBlock",
    "DataTransformBlock",
    "DataTransformBlockConfig",
    "AIAssistedTextBlock",
    "AISummaryBlock",
    "AIRewriteBlock",
    "CitationBlock",
    "ReviewGateBlock",
    # inputs
    "InputContract",
    "InputSlot",
    # ui
    "ReportUIContract",
    "UISection",
    "UIFieldDescriptor",
    "UIDropzoneDescriptor",
    # template
    "SectionContract",
    "ReportTemplateSpec",
    "ReportTemplateVersion",
    "ReportTemplateContract",
]


# ---------------------------------------------------------------------------
# Sección y spec de plantilla
# ---------------------------------------------------------------------------

class SectionContract(BaseModel):
    id: str
    title: str
    order: int
    block_ids: list[str] = []


class ReportTemplateSpec(BaseModel):
    """Spec completa de una versión de plantilla: secciones, bloques, contratos."""

    sections: list[SectionContract]
    blocks: list[Annotated[BlockContract, Field(discriminator="kind")]]
    input_contract: InputContract
    ui_contract: ReportUIContract
    ai_block_policy: AIBlockPolicy
    review_policy: ReviewPolicy
    export_policy: ExportPolicy


# ---------------------------------------------------------------------------
# Versión de plantilla — inmutable una vez persistida
# ---------------------------------------------------------------------------

class ReportTemplateVersion(BaseModel):
    """Una versión de plantilla. Frozen: solo se versiona, nunca se edita."""

    model_config = ConfigDict(frozen=True)

    id: UUID
    template_id: UUID
    version: int
    spec: ReportTemplateSpec
    created_at: datetime
    created_by: UUID


# ---------------------------------------------------------------------------
# Contrato de plantilla
# ---------------------------------------------------------------------------

class ReportTemplateContract(BaseModel):
    """Contrato serializable de una plantilla de informe.

    Las plantillas globales (is_global=True) solo pueden pertenecer a la plataforma.

    **MT.4 — el vocabulario de `owner_kind` es el del modelo**, y `HubReportTemplate` usa
    `organizacion`. Aquí estaba escrito `organization`, en inglés, desde antes de que ese nivel
    existiera de verdad: dos grafías del mismo valor en dos sitios, que no molestaban porque este
    contrato todavía no tiene consumidor —lo tendrá cuando MT.20 exporte plantillas entre
    instalaciones—. Alineado ahora, porque el día que alguien valide una fila real el fallo sería
    un `ValueError` por una letra.
    """

    id: UUID
    name: str
    description: str | None = None
    report_profile: ReportProfileId
    owner_kind: Literal["platform", "organizacion", "superadmin", "user"]
    owner_id: UUID | None = None
    is_global: bool = False
    current_version_id: UUID
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def _global_requires_platform_owner(self) -> ReportTemplateContract:
        if self.is_global and self.owner_kind != "platform":
            raise ValueError(
                "Global templates can only be owned by the platform; "
                f"got owner_kind={self.owner_kind!r}"
            )
        return self
