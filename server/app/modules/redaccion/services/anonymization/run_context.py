"""RunAnonymizationContext — Fase 13 (NER reversible en redacción).

Mantiene el mapeo bidireccional original↔sintético durante la ejecución del
DraftingCoreGraph para que ningún PII real llegue al LLM (RGPD) pero el output
final preserve los originales para el usuario.

Reglas duras (ver docs/REDACCION_CONTRACT_FIRST.md §"NER reversible"):
- `substitute()` ordena por longitud descendente para evitar matches parciales
  (p.ej. evita que "Juan García" se rompa por sustituir "Juan" primero).
- `reverse()` SÓLO revierte cadenas exactas en `reverse_map`: si el LLM
  alucina un nombre tipo Faker que no estaba en nuestro mapping, queda tal cual.
- Modo `REPLACE_WITH_DISPOSITION_7` (LOPDGDD) aplica MÁSCARA a DNI/NIE/Passport,
  NO Faker → irreversible para esos tipos; el output final queda enmascarado.
- Los mapas forward/reverse NUNCA se persisten en BD; viven sólo en memoria.

Deploy: edge.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums y constantes
# ---------------------------------------------------------------------------


PiiType = Literal[
    "PERSON",
    "PERSON_NAME",
    "ORG",
    "ORGANIZATION",
    "LOC",
    "ADDRESS",
    "EMAIL",
    "PHONE",
    "DNI",
    "NIE",
    "PASSPORT",
    "IBAN",
    "CREDIT_CARD",
    "POSTAL_CODE",
    "DATE",
    "NSS",
]


class AnonymizationMode(str, Enum):
    """Modo de operación de la anonimización, heredado de la organización (AIS.5).

    - OFF: PII real al LLM (sólo dev/test — viola RGPD en producción).
    - DETECT_ONLY: detecta y audita conteos, pero NO sustituye en el prompt.
    - REPLACE: sustituye con Faker antes del LLM y deshace la sustitución **dentro de la misma
      ejecución** (default).
    - REPLACE_WITH_DISPOSITION_7: como REPLACE pero DNI/NIE/Passport se
      enmascaran (***NNNNX) en lugar de fakerizar → irreversible para esos
      tipos. Conforme a LOPDGDD Disposición Adicional 7ª.

    **Hasta dónde llega la reversión de REPLACE, dicho en vez de dado por hecho.** El mapa
    sintético→real vive **en memoria, durante la ejecución**: eso basta para lo que el flujo
    necesita —el texto vuelve con los nombres reales en el mismo informe que lo pidió— y **no
    permite re-identificar después**. Un informe generado ayer no se puede deshacer: el mapa no
    se guarda en ningún sitio, a propósito. La persistencia cifrada es F2.A.4 (Vault Edge) y
    llegará cuando haya un caso que la necesite; hasta entonces esto no es una carencia sino el
    alcance, y decirlo aquí evita que alguien construya encima de una promesa más ancha.

    El modo lo fija la organización y el informe sólo puede **endurecerlo**: ver
    `anonymization/politica.py`.
    """

    OFF = "off"
    DETECT_ONLY = "detect_only"
    REPLACE = "replace"
    REPLACE_WITH_DISPOSITION_7 = "replace_with_disposition_7"


# Tipos cuyo tratamiento bajo Disposición 7 es máscara irreversible.
_DISPOSITION_7_MASKED_TYPES: frozenset[str] = frozenset({"DNI", "NIE", "PASSPORT"})


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class PiiSpan(BaseModel):
    """Un span detectado y su correspondencia sintética para el run.

    `synthetic == original` cuando el modo no sustituye (OFF / DETECT_ONLY).
    `synthetic` es la máscara cuando aplica Disposición 7 (DNI/NIE/Passport).
    """

    type: str
    original: str
    synthetic: str
    confidence: float = 1.0
    source_block_id: str | None = None
    masked: bool = False  # True ⇔ Disposición 7 aplicada → irreversible


class RunAnonymizationContext(BaseModel):
    workspace_id: UUID
    run_manifest_id: UUID | None = None
    mode: AnonymizationMode
    spans: list[PiiSpan] = Field(default_factory=list)
    forward_map: dict[str, str] = Field(default_factory=dict)
    reverse_map: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    #: Si el NER estuvo disponible en esta ejecución (issue #170).
    #:
    #: **`None` no es `False`.** `None` significa que no se escaneó —modo `off`— y decir `False`
    #: ahí afirmaría haber comprobado algo que no se comprobó. `False` significa que se escaneó
    #: sin modelo lingüístico: los identificadores estructurados sí se cogieron, los nombres
    #: dentro de la prosa no. Sin este dato, esa ejecución produce un resumen tan saludable como
    #: cualquier otra mientras deja pasar exactamente lo que la capa de patrones no ve.
    ner_disponible: bool | None = None

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def substitute(self, text: str) -> str:
        """Sustituye originales por sintéticos en `text`.

        - En modos OFF y DETECT_ONLY devuelve el texto sin cambios.
        - Ordena las claves por longitud descendente para evitar matches parciales.
        - Si el mismo `original` aparece varias veces en `text`, se reemplazan todas.
        """
        if self.mode in (AnonymizationMode.OFF, AnonymizationMode.DETECT_ONLY):
            return text
        if not self.forward_map or not text:
            return text

        for original in sorted(self.forward_map, key=len, reverse=True):
            synth = self.forward_map[original]
            if not original or original == synth:
                continue
            text = text.replace(original, synth)
        return text

    def reverse(self, text: str) -> str:
        """Revierte sintéticos por originales SÓLO para claves exactas en reverse_map.

        - En modo OFF devuelve el texto sin cambios.
        - En modo DETECT_ONLY también — nunca hubo sustitución que revertir.
        - Cadenas máscara (Disposición 7) NO están en `reverse_map` → no se revierten.
        - Ordena por longitud descendente para evitar romper matches anidados.
        """
        if self.mode in (AnonymizationMode.OFF, AnonymizationMode.DETECT_ONLY):
            return text
        if not self.reverse_map or not text:
            return text

        for synthetic in sorted(self.reverse_map, key=len, reverse=True):
            original = self.reverse_map[synthetic]
            if not synthetic or synthetic == original:
                continue
            text = text.replace(synthetic, original)
        return text

    def counts_by_type(self) -> dict[str, int]:
        """Conteo de spans por tipo PII — para `AnonymizationSummary`."""
        counts: dict[str, int] = {}
        for span in self.spans:
            counts[span.type] = counts.get(span.type, 0) + 1
        return counts


class AnonymizationSummary(BaseModel):
    """Resumen sin originales ni sintéticos — para auditoría persistida en el manifest."""

    mode: AnonymizationMode
    counts_by_type: dict[str, int] = Field(default_factory=dict)
    total_spans: int = 0
    #: Si la detección de nombres en texto libre estuvo puesta. Ver el campo homónimo del
    #: contexto: `None` = no se escaneó, `False` = se escaneó sólo con patrones.
    ner_disponible: bool | None = None
    detected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @classmethod
    def from_context(cls, ctx: RunAnonymizationContext) -> "AnonymizationSummary":
        counts = ctx.counts_by_type()
        return cls(
            mode=ctx.mode,
            counts_by_type=counts,
            total_spans=sum(counts.values()),
            ner_disponible=ctx.ner_disponible,
            detected_at=ctx.created_at,
        )


# ---------------------------------------------------------------------------
# Helpers de máscara LOPDGDD (Disposición Adicional 7ª)
# ---------------------------------------------------------------------------


_DNI_RE = re.compile(r"^\s*(\d{8})([A-Za-z])\s*$")
_NIE_RE = re.compile(r"^\s*([XYZxyz])(\d{7})([A-Za-z])\s*$")


def disposition_7_mask(pii_type: str, original: str) -> str:
    """Genera la máscara LOPDGDD para DNI/NIE/Passport.

    Preserva los últimos 4 caracteres alfanuméricos y la letra de control
    cuando aplica; oculta el resto con asteriscos. La transformación NO es
    reversible (el output final del usuario queda enmascarado).
    """
    pii_type = pii_type.upper()
    if pii_type == "DNI":
        m = _DNI_RE.match(original)
        if m:
            digits, letter = m.group(1), m.group(2).upper()
            return f"****{digits[-4:]}{letter}"
    elif pii_type == "NIE":
        m = _NIE_RE.match(original)
        if m:
            prefix, digits, letter = m.group(1).upper(), m.group(2), m.group(3).upper()
            return f"{prefix}***{digits[-4:]}{letter}"
    # Passport (formato variable): conserva últimos 4 caracteres.
    text = original.strip()
    if len(text) <= 4:
        return "*" * len(text)
    return "*" * (len(text) - 4) + text[-4:]


def is_masked_under_disposition_7(pii_type: str, mode: AnonymizationMode) -> bool:
    """Determina si un tipo concreto recibe máscara LOPDGDD bajo el modo activo."""
    return (
        mode == AnonymizationMode.REPLACE_WITH_DISPOSITION_7
        and pii_type.upper() in _DISPOSITION_7_MASKED_TYPES
    )


__all__ = [
    "AnonymizationMode",
    "AnonymizationSummary",
    "PiiSpan",
    "PiiType",
    "RunAnonymizationContext",
    "disposition_7_mask",
    "is_masked_under_disposition_7",
]
