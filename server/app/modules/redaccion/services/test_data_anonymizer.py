"""TestDataAnonymizerService — envoltura del módulo de anonimización para
el workflow de propuesta de scripts (9R.5.5, Parte 2).

Opera siempre sobre StorageRef. Para PDFs, anonimiza sobre markdown extraído
por Docling (opción 1 confirmada en el prompt 9R.5.5): no se regenera el PDF.
"""
from __future__ import annotations

import uuid
from pydantic import BaseModel, Field

from server.app.core.storage import StorageService
from server.app.modules.redaccion.pipelines.contracts import StorageRef
from server.app.modules.redaccion.services.anonymization.anonymizer import (
    AnonymizationContext,
)
from server.app.modules.redaccion.services.anonymization.faker_generator import (
    FakerGenerator,
)
from server.app.modules.redaccion.services.anonymization.pii_detector import (
    ColumnInfo,
    FakerProvider,
    PiiDetector,
    PiiSpan,
)
from server.app.modules.redaccion.services.anonymization.service import (
    _read_dataframe,
    _suffix_from_key,
    _write_dataframe,
)


# ---------------------------------------------------------------------------
# Contratos públicos
# ---------------------------------------------------------------------------

class ColumnSubstitution(BaseModel):
    """Configuración de sustitución por columna que envía el cliente."""

    column_name: str
    faker_provider: FakerProvider = "keep"


class SpanOverride(BaseModel):
    """Override del usuario sobre un PiiSpan detectado en el PDF."""

    start: int
    end: int
    suggested_fake: str | None = None
    accept: bool = True  # False → no sustituir esta ocurrencia


class AnonymizedTabularResult(BaseModel):
    synthetic_ref: StorageRef
    anonymization_map: dict[str, str] = Field(default_factory=dict)
    columns_applied: list[str] = Field(default_factory=list)


class AnonymizedPdfResult(BaseModel):
    synthetic_ref: StorageRef
    anonymization_map: dict[str, str] = Field(default_factory=dict)
    spans_applied: int = 0


# ---------------------------------------------------------------------------
# Mapeo provider → tipo PII para FakerGenerator
# ---------------------------------------------------------------------------

_PROVIDER_TO_PII: dict[FakerProvider, str] = {
    "name": "PERSON_NAME",
    "first_name": "PERSON_NAME",
    "last_name": "PERSON_NAME",
    "email": "EMAIL",
    "phone": "PHONE",
    "iban": "IBAN",
    "dni": "DNI",
    "nie": "NIE",
    "address": "ADDRESS",
    "city": "CITY",
    "company": "ORGANIZATION",
    "date": "DATE",
    "integer": "POSTAL_CODE",
}


_PROVIDER_CONTEXT: dict[FakerProvider, str] = {
    "first_name": "nombre",
    "last_name": "apellido",
    "name": "fullname",
}


class TestDataAnonymizerService:
    """Operaciones de anonimización de test data para el workflow de scripts."""

    def __init__(self, storage: StorageService) -> None:
        self._storage = storage

    # ------------------------------------------------------------------
    # Tabular
    # ------------------------------------------------------------------

    async def describe_columns(self, file_ref: StorageRef) -> list[ColumnInfo]:
        """Carga el archivo tabular y devuelve descripciones de columnas."""
        data = await self._storage.get(file_ref.key)
        suffix = _suffix_from_key(file_ref.key)
        df = _read_dataframe(data, suffix)
        return PiiDetector().scan_dataframe(df)

    async def anonymize_tabular(
        self,
        file_ref: StorageRef,
        substitutions: list[ColumnSubstitution],
        output_bucket: str | None = None,
    ) -> AnonymizedTabularResult:
        """Aplica sustituciones por columna fila a fila.

        #255 — **una columna que no llega en `substitutions` se trata con lo que el propio servidor
        propone al describirla**. Antes se dejaba como estaba, y el asistente no mandaba ninguna:
        el «sintético» era una copia del original marcada como anonimizada. Lo que el cliente
        manda manda, y `keep` es como se dice que una columna no es dato personal.
        """
        data = await self._storage.get(file_ref.key)
        suffix = _suffix_from_key(file_ref.key)
        df = _read_dataframe(data, suffix)

        indicadas = {sub.column_name for sub in substitutions}
        propuestas = [
            ColumnSubstitution(column_name=str(col.name), faker_provider=col.inferred_faker_provider)
            for col in PiiDetector().scan_dataframe(df)
            if str(col.name) not in indicadas
        ]

        fakes = FakerGenerator()
        applied: list[str] = []
        for sub in [*substitutions, *propuestas]:
            if sub.column_name not in df.columns:
                continue
            if sub.faker_provider == "keep":
                continue
            pii_type = _PROVIDER_TO_PII.get(sub.faker_provider)
            if pii_type is None:
                continue
            ctx_hint = _PROVIDER_CONTEXT.get(sub.faker_provider, sub.column_name)
            df[sub.column_name] = df[sub.column_name].astype(str).apply(
                lambda v, t=pii_type, c=ctx_hint: fakes.generate(t, v, context=c)
            )
            applied.append(sub.column_name)

        out_bytes = _write_dataframe(df, suffix)
        out_key = f"test-data/{uuid.uuid4()}.{suffix or 'bin'}"
        await self._storage.put(out_key, out_bytes)
        return AnonymizedTabularResult(
            synthetic_ref=StorageRef(
                bucket=output_bucket or file_ref.bucket, key=out_key
            ),
            anonymization_map=dict(fakes.fake_to_real),
            columns_applied=applied,
        )

    # ------------------------------------------------------------------
    # PDF: markdown sintético (sin regenerar PDF)
    # ------------------------------------------------------------------

    async def preview_pdf_spans(self, file_ref: StorageRef) -> list[PiiSpan]:
        """Devuelve los spans PII detectados sobre el markdown del PDF."""
        markdown = await self._extract_pdf_markdown(file_ref)
        return PiiDetector().detect_spans(markdown)

    async def anonymize_pdf_to_text(
        self,
        file_ref: StorageRef,
        span_overrides: list[SpanOverride] | None = None,
        output_bucket: str | None = None,
    ) -> AnonymizedPdfResult:
        """Extrae markdown del PDF, anonimiza el texto y persiste `.md` sintético.

        `span_overrides` permite al usuario rechazar un span (accept=False) o
        sustituir el `suggested_fake` por uno propio. El resto se genera con
        el comportamiento por defecto del motor.
        """
        markdown = await self._extract_pdf_markdown(file_ref)
        overrides = {
            (s.start, s.end): s for s in (span_overrides or [])
        }

        ctx = AnonymizationContext()
        # Mismo flujo que ctx.anonymize() pero permitiendo override por span.
        anchor_entities, anchor_meta = ctx._detect_with_anchors(markdown)
        ctx._detected_anchors.extend(anchor_meta)
        regex_ner = ctx._detect_with_regex(markdown) + ctx._detect_with_ner(markdown)
        non_overlap = ctx._remove_overlapping(anchor_entities, regex_ner)
        entities = anchor_entities + non_overlap
        entities.sort(key=lambda e: e.start, reverse=True)

        result_text = markdown
        spans_applied = 0
        for entity in entities:
            ov = overrides.get((entity.start, entity.end))
            if ov is not None and not ov.accept:
                continue
            if ov is not None and ov.suggested_fake:
                fake = ov.suggested_fake
                # Registrar manualmente en mapa para deanonimización futura
                ctx.fakes.fake_to_real[fake] = entity.text
                ctx.fakes.real_to_fake[entity.text] = fake
            else:
                fake = ctx.fakes.generate(entity.type, entity.text, context=entity.context)
            result_text = result_text[: entity.start] + fake + result_text[entity.end :]
            spans_applied += 1

        out_key = f"test-data/{uuid.uuid4()}.md"
        await self._storage.put(out_key, result_text.encode("utf-8"))
        return AnonymizedPdfResult(
            synthetic_ref=StorageRef(
                bucket=output_bucket or file_ref.bucket, key=out_key
            ),
            anonymization_map=dict(ctx.fake_to_real),
            spans_applied=spans_applied,
        )

    # ------------------------------------------------------------------
    # Internals: extracción del texto del PDF
    # ------------------------------------------------------------------

    async def _extract_pdf_markdown(self, file_ref: StorageRef) -> str:
        """Texto del PDF para buscarle PII (EXT.2: pdfplumber, no Docling).

        Docling ya se usaba aquí **sin OCR**, así que el alcance no cambia: PDFs con capa de
        texto. Lo que se va son sus modelos y el fichero temporal que hacía falta porque
        Docling lee desde una ruta — pdfplumber acepta los bytes directamente.

        Devuelve `""` si no hay capa de texto en vez de levantar: esto es una **previsualización**
        de qué datos personales se detectan, y quien la pide ve la lista vacía y entiende que
        ahí no había nada que leer. Rechazar sería más ruidoso de lo que el caso pide.
        """
        from server.app.core.pdf_text import extraer_paginas, hay_capa_de_texto

        data = await self._storage.get(file_ref.key)
        paginas = extraer_paginas(data)
        if not hay_capa_de_texto(paginas):
            return ""
        return "\n\n".join(p.strip() for p in paginas if p.strip()).strip()
