"""Módulo de anonimización para redacción (9R.5.5).

Motor híbrido regex + spaCy NER + anclajes de formulario, migrado desde
client_app/app/modules/privacy/. Reutilizable por:

  - TestDataAnonymizerService (Parte 2 de 9R.5.5): scripts metaprogramados.
  - Fase 13 (NER reversible): hooks pre/post-LLM en DraftingCoreGraph.
"""
from server.app.modules.redaccion.services.anonymization.anonymizer import (
    AnonymizationContext,
    Entity,
)
from server.app.modules.redaccion.services.anonymization.faker_generator import (
    FakerGenerator,
)
from server.app.modules.redaccion.services.anonymization.pii_detector import (
    PiiDetector,
    PiiSpan,
    ColumnInfo,
)
from server.app.modules.redaccion.services.anonymization.policies import (
    AnonymizerPolicy,
    Strategy,
)

__all__ = [
    "AnonymizationContext",
    "AnonymizerPolicy",
    "ColumnInfo",
    "Entity",
    "FakerGenerator",
    "PiiDetector",
    "PiiSpan",
    "Strategy",
]
