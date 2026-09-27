"""AnonymizationContext — motor híbrido regex + spaCy NER + anclajes (9R.5.5).

Migrado de client_app/app/modules/privacy/anonymizer.py con las siguientes
adaptaciones:

- FakerGenerator extraído a `faker_generator.py` (separación de responsabilidades).
- EncryptionService eliminado: el determinismo se obtiene por instancia
  (mismo input → mismo fake), **y no por persistencia cifrada, que es una decisión
  tomada y no un pendiente**. Aquí ponía `TODO post-MVP`, y eso contradecía lo que
  ya estaba escrito dos ficheros más allá: `run_context.py` lleva como regla dura
  que «los mapas forward/reverse NUNCA se persisten en BD; viven sólo en memoria»,
  y `service.py` guarda el motivo —decisión del 2026-08-24: el piloto no trata
  datos de ciudadanos y la anonimización es configurable, así que no hay bóveda
  cifrada antes del piloto— junto con el nombre del trabajo que la traerá el día
  que haga falta: **F2.A.4 (Vault Edge)**.

  La consecuencia práctica, que es lo que importa al usar esto: **la reversión vale
  dentro de una ejecución y no después**. Un reinicio se lleva el mapa, y eso es lo
  buscado, no una limitación que alguien vaya a arreglar sin decirlo. Si algún día
  la correspondencia tiene que sobrevivir a un reinicio, eso es F2.A.4 y se decide
  allí, con quien la vaya a consumir delante.
- Sin acoplamiento a enterprise_audit_service: la auditoría se delega al
  llamador (workspace_audit_events para flujos de redacción).
- Mantenido el fallback explícito sin spaCy (degrada a regex con warning).
- Mantenida la Disposición Adicional Séptima LOPDGDD para documentos de
  identidad (`anonymize_document_id(mode='AEPD')`).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from server.app.modules.redaccion.services.anonymization.faker_generator import (
    FakerGenerator,
)

logger = logging.getLogger(__name__)


def _try_load_spacy_model(model: str = "es_core_news_md") -> Any:
    """Carga perezosa del modelo spaCy. Devuelve None y emite warning si falla."""
    try:
        import spacy  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "[Anonymizer] spaCy no instalado — degradando a regex + anclajes."
        )
        return None
    try:
        return spacy.load(model)
    except (OSError, IOError) as exc:
        logger.warning(
            "[Anonymizer] modelo spaCy '%s' no disponible (%s). "
            "Degradando a regex + anclajes.",
            model,
            exc,
        )
        return None


_NLP_CACHE: dict[str, Any] = {}


def _get_nlp(model: str) -> Any:
    if model not in _NLP_CACHE:
        _NLP_CACHE[model] = _try_load_spacy_model(model)
    return _NLP_CACHE[model]


#: Tipos que la politica por defecto sustituye en texto libre.
#:
#: Estaba escrita dentro de `AnonymizationContext.anonymize()`. REG.3 la saca a constante porque
#: el endpoint publico necesita la misma lista para informar de que aplico: con una copia, las dos
#: politicas por defecto divergirian en cuanto alguien anada un tipo, y en silencio —el endpoint
#: devolveria un texto sustituido y un informe que no lo describe.
TIPOS_ANONIMIZADOS_POR_DEFECTO: tuple[str, ...] = (
    "PERSON_NAME",
    "EMAIL",
    "DNI",
    "NIE",
    "PHONE",
    "PASSPORT",
)


@dataclass
class Entity:
    """Entidad detectada en un texto."""

    text: str
    type: str
    start: int
    end: int
    context: str = ""  # campo de formulario (firstname/lastname/fullname) si aplica


@dataclass
class AnonymizationAuditEvent:
    """Evento estructurado de auditoría emitido tras anonymize_text/dataframe."""

    operation: str  # "anonymize_text" | "anonymize_dataframe"
    pii_types: dict[str, int] = field(default_factory=dict)
    new_entities: int = 0
    spacy_available: bool = True
    source_description: str = ""


class AnonymizationContext:
    """Motor de anonimización híbrido: regex + spaCy NER + anclajes de formulario.

    El método `anonymize()` es el entry-point principal para texto libre.
    `anonymize_dataframe()` procesa estructuras tabulares columna a columna.

    No persiste estado entre instancias: para deanonimización dentro del
    mismo job, mantén la misma instancia o serializa `fake_to_real` por
    el llamador.
    """

    PATTERNS: dict[str, str] = {
        "DNI": r"\b\d{1,2}(?:[\.\s]?\d{3}){2}[\-\s]?[A-Z]\b|\b\d{8}[\-\s]?[A-Z]\b",
        "EMAIL": r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
        "IBAN": r"\bES\d{22}\b",
        "PHONE": r"\b[6-9]\d{8}\b",
        "NIE": r"\b[XYZ]\d{7}[A-Z]\b",
        "CREDIT_CARD": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
        "NSS": r"\b\d{2}[/-]?\d{8}[/-]?\d{2}\b",
        "DATE": r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
        "POSTAL_CODE": r"\b\d{5}\b",
    }

    _COMMON_WORDS_EXCLUSION: frozenset[str] = frozenset({
        "duración", "duracion", "título", "titulo", "nombre", "apellido", "apellidos",
        "cargo", "puesto", "dirección", "direccion", "provincia", "municipio",
        "entidad", "departamento", "centro", "facultad", "universidad",
        "proyecto", "resumen", "palabras", "clave", "área", "area", "tipo",
        "código", "codigo", "referencia", "administrativa", "forma",
        "ejecución", "ejecucion", "individual", "información", "informacion",
        "datos", "contacto", "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
        "años", "meses", "días", "semanas", "horas",
        "ministerio", "ciencia", "innovación", "innovacion", "universidades",
        "proyectos", "generación", "generacion", "conocimiento",
        "investigación", "investigacion", "temática", "tematica",
        "secundaria", "principal", "subárea", "subarea", "modalidad",
        "orientada", "carácter", "caracter", "multidisciplinar", "interdisciplinar",
    })

    ANCHOR_PATTERNS: dict[str, str] = {
        "ANCHOR_FIRSTNAME": (
            r"(?i)(Nombre|Nom|First\s*Name|Nombre\s*de\s*pila)"
            r"\s*[:=]?\s*"
            r"([A-ZÁÉÍÓÚÑÀÈÌÒÙÇ][a-záéíóúñàèìòùç]+(?:\s+[A-ZÁÉÍÓÚÑÀÈÌÒÙÇ][a-záéíóúñàèìòùç]+)?)"
        ),
        "ANCHOR_LASTNAME": (
            r"(?i)(Apellidos?|Cognoms?|Surname|Last\s*Name|Primer\s*Apellido|Segundo\s*Apellido)"
            r"\s*[:=]?\s*"
            r"([A-ZÁÉÍÓÚÑÀÈÌÒÙÇ][a-záéíóúñàèìòùç]+(?:\s+[A-ZÁÉÍÓÚÑÀÈÌÒÙÇ][a-záéíóúñàèìòùç]+)?)"
        ),
        "ANCHOR_FULLNAME": (
            r"(?i)(Representante\s*Legal|Contacto|Titular|Solicitante|Interesado|Firmante)"
            r"\s*[:=]?\s*"
            r"([A-ZÁÉÍÓÚÑÀÈÌÒÙÇ][a-záéíóúñàèìòùç]+(?:\s+[A-ZÁÉÍÓÚÑÀÈÌÒÙÇ][a-záéíóúñàèìòùç]+){1,4})"
        ),
    }

    def __init__(
        self,
        locale: str = "es_ES",
        spacy_model: str = "es_core_news_md",
        faker_seed: int | None = None,
    ) -> None:
        self._spacy_model = spacy_model
        # **El modelo se carga en el primer texto que pase por el NER, no aquí** (issue #170).
        # Son ~305 MB de RSS medidos, y desde que el grafo de redacción construye un detector en
        # cada ejecución, cargarlos en el constructor se los cobraría también a quien tiene la
        # anonimización en `off` — que es una decisión legítima de su organización. El resultado
        # se cachea por proceso en `_NLP_CACHE`, así que sigue siendo coste de arranque y no
        # latencia por informe.
        self._nlp_valor: Any = None
        self._nlp_resuelto = False
        self.fakes = FakerGenerator(locale=locale, seed=faker_seed)
        self._detected_anchors: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Compatibilidad con el legacy: exponer los mapas a través del contexto
    # ------------------------------------------------------------------

    @property
    def fake_to_real(self) -> dict[str, str]:
        return self.fakes.fake_to_real

    @property
    def real_to_fake(self) -> dict[str, str]:
        return self.fakes.real_to_fake

    @property
    def stats(self) -> dict[str, int]:
        return self.fakes.stats

    @property
    def _nlp(self) -> Any:
        if not self._nlp_resuelto:
            self._nlp_valor = _get_nlp(self._spacy_model)
            self._nlp_resuelto = True
        return self._nlp_valor

    @_nlp.setter
    def _nlp(self, valor: Any) -> None:
        """Escribible a propósito: un test fuerza `None` para comprobar la degradación."""
        self._nlp_valor = valor
        self._nlp_resuelto = True

    @property
    def spacy_available(self) -> bool:
        """Fuerza la carga: preguntar si está disponible es pedir que se compruebe."""
        return self._nlp is not None

    # ------------------------------------------------------------------
    # Detección
    # ------------------------------------------------------------------

    def _detect_with_regex(self, text: str) -> list[Entity]:
        entities: list[Entity] = []
        for typ, pattern in self.PATTERNS.items():
            for match in re.finditer(pattern, text):
                entities.append(
                    Entity(text=match.group(0), type=typ, start=match.start(), end=match.end())
                )
        return entities

    def _is_likely_person_name(self, text: str) -> bool:
        if not text or len(text.strip()) < 2:
            return False
        text_clean = text.strip()
        text_lower = text_clean.lower()
        if text_lower in self._COMMON_WORDS_EXCLUSION:
            return False
        words = text_clean.split()
        if len(words) == 1:
            if not text_clean[0].isupper() or len(text_clean) < 3:
                return False
        has_proper_capitalization = any(w[0].isupper() for w in words if w)
        if not has_proper_capitalization:
            return False
        non_common = [w for w in words if w.lower() not in self._COMMON_WORDS_EXCLUSION]
        if not non_common:
            return False
        alpha_chars = sum(1 for c in text_clean if c.isalpha())
        if alpha_chars < len(text_clean) * 0.5:
            return False
        return True

    def _detect_with_ner(self, text: str) -> list[Entity]:
        if not self._nlp:
            return []
        doc = self._nlp(text)
        entities: list[Entity] = []
        for ent in doc.ents:
            if ent.label_ == "PER" and self._is_likely_person_name(ent.text):
                entities.append(
                    Entity(
                        text=ent.text,
                        type="PERSON_NAME",
                        start=ent.start_char,
                        end=ent.end_char,
                    )
                )
            elif ent.label_ == "LOC":
                entities.append(
                    Entity(
                        text=ent.text,
                        type="ADDRESS",
                        start=ent.start_char,
                        end=ent.end_char,
                    )
                )
            elif ent.label_ == "ORG":
                entities.append(
                    Entity(
                        text=ent.text,
                        type="ORGANIZATION",
                        start=ent.start_char,
                        end=ent.end_char,
                    )
                )
        return entities

    def _detect_with_anchors(
        self, text: str
    ) -> tuple[list[Entity], list[dict[str, Any]]]:
        entities: list[Entity] = []
        anchor_metadata: list[dict[str, Any]] = []
        for anchor_type, pattern in self.ANCHOR_PATTERNS.items():
            for match in re.finditer(pattern, text):
                label = match.group(1).strip()
                captured_value = match.group(2).strip()
                if not captured_value or len(captured_value) < 2:
                    continue
                if not self._is_likely_person_name(captured_value):
                    continue
                if anchor_type == "ANCHOR_FIRSTNAME":
                    context, field_type = "nombre", "firstname"
                elif anchor_type == "ANCHOR_LASTNAME":
                    context, field_type = "apellido", "lastname"
                else:
                    context, field_type = "fullname", "fullname"
                start_off, end_off = match.start(2), match.end(2)
                entities.append(
                    Entity(
                        text=captured_value,
                        type="PERSON_NAME",
                        start=start_off,
                        end=end_off,
                        context=context,
                    )
                )
                anchor_metadata.append(
                    {
                        "label": label,
                        "label_normalized": label.lower().replace(" ", "_"),
                        "field_type": field_type,
                        "value_start": start_off,
                        "value_end": end_off,
                        "full_match_start": match.start(),
                        "full_match_end": match.end(),
                    }
                )
        return entities, anchor_metadata

    @staticmethod
    def _remove_overlapping(
        priority: list[Entity], secondary: list[Entity]
    ) -> list[Entity]:
        result: list[Entity] = []
        for sec in secondary:
            overlaps = any(
                not (sec.end <= pri.start or sec.start >= pri.end) for pri in priority
            )
            if not overlaps:
                result.append(sec)
        return result

    # ------------------------------------------------------------------
    # Masking helpers
    # ------------------------------------------------------------------

    def _mask_generic(self, entity_type: str, value: str) -> str:
        if not value:
            return value
        s = str(value)
        length = len(s)

        if entity_type == "EMAIL":
            parts = s.split("@")
            if len(parts) != 2:
                return "*" * length
            user, domain = parts
            u_shown = user[:1] + "*" * (len(user) - 1) if len(user) > 1 else user
            d_parts = domain.split(".")
            if len(d_parts) >= 2:
                d_shown = d_parts[0][:1] + "*" * (len(d_parts[0]) - 1) + "." + d_parts[-1]
            else:
                d_shown = "*" * len(domain)
            return f"{u_shown}@{d_shown}"

        if entity_type == "PHONE":
            return s[:2] + "*" * (length - 2) if length > 3 else "*" * length

        if entity_type in ("PERSON_NAME", "ORGANIZATION", "ADDRESS"):
            return " ".join(
                (w[0] + "*" * (len(w) - 1)) if len(w) > 1 else w for w in s.split()
            )

        if entity_type in ("IBAN", "CREDIT_CARD"):
            return "*" * (length - 4) + s[-4:] if length > 4 else "*" * length

        return "*" * length

    def anonymize_document_id(self, value: str, mode: str = "MASK") -> str:
        """Anonimiza DNI/NIE/Pasaporte.

        Modos:
        - MASK: enmascarado completo con asteriscos.
        - AEPD: Disposición Adicional Séptima LOPDGDD — muestra solo dígitos
          centrales según el tipo de documento detectado.
        """
        if not value:
            return value

        if mode == "MASK":
            return "*" * len(value) if len(value) > 4 else "*********"

        if mode != "AEPD":
            return value

        s = value
        length = len(s)
        is_nie = bool(re.match(r"^[A-Z]\d{7}[A-Z]$", s))
        is_passport = bool(re.match(r"^[A-Z]{3}\d{6}$", s))
        digit_indices = [i for i, c in enumerate(s) if c.isdigit()]
        to_show: set[int] = set()

        if is_passport and len(digit_indices) >= 6:
            to_show.update(digit_indices[2:6])
            return "".join(c if i in to_show else "*" for i, c in enumerate(s))

        if is_nie and len(digit_indices) >= 7:
            to_show.update(digit_indices[3:7])
            return "".join(c if i in to_show else "*" for i, c in enumerate(s))

        if len(digit_indices) >= 7:
            to_show.update(digit_indices[3:7])
            return "".join(c if i in to_show else "*" for i, c in enumerate(s))

        # < 7 dígitos → mostrar últimos 4 caracteres
        if length <= 4:
            return s
        return "*" * (length - 4) + s[-4:]

    def anonymize_name(self, value: str, mode: str = "MASK") -> str:
        if not value:
            return value
        if mode == "MASK":
            return self._mask_generic("PERSON_NAME", value)
        if mode == "INITIALS":
            parts = [p.strip()[0] + "." for p in value.split() if p.strip()]
            return " ".join(parts)
        return self._mask_generic("PERSON_NAME", value)

    # ------------------------------------------------------------------
    # API pública: texto libre
    # ------------------------------------------------------------------

    def anonymize(
        self, data: Any, allowed_types: list[str] | None = None
    ) -> Any:
        """Anonimiza texto libre, dicts y listas recursivamente.

        Por defecto preserva nombres, emails, DNI, NIE, teléfonos y pasaportes.
        """
        if allowed_types is None:
            allowed_types = list(TIPOS_ANONIMIZADOS_POR_DEFECTO)

        if isinstance(data, dict):
            return {k: self.anonymize(v, allowed_types) for k, v in data.items()}
        if isinstance(data, list):
            return [self.anonymize(item, allowed_types) for item in data]
        if not isinstance(data, str):
            return data

        text = data
        anchor_entities, anchor_meta = self._detect_with_anchors(text)
        self._detected_anchors.extend(anchor_meta)

        regex_ner = self._detect_with_regex(text) + self._detect_with_ner(text)
        non_overlap = self._remove_overlapping(anchor_entities, regex_ner)
        entities = anchor_entities + non_overlap
        entities = [e for e in entities if e.type in allowed_types]
        entities.sort(key=lambda e: e.start, reverse=True)

        result = text
        for entity in entities:
            fake = self.fakes.generate(entity.type, entity.text, context=entity.context)
            result = result[: entity.start] + fake + result[entity.end :]
        return result

    def deanonymize(self, data: Any) -> Any:
        if isinstance(data, str):
            result = data
            for fake, real in self.fakes.fake_to_real.items():
                result = result.replace(fake, real)
            return result
        if isinstance(data, dict):
            return {k: self.deanonymize(v) for k, v in data.items()}
        if isinstance(data, list):
            return [self.deanonymize(item) for item in data]
        return data

    # ------------------------------------------------------------------
    # API pública: tablas
    # ------------------------------------------------------------------

    def anonymize_dataframe(
        self, df: pd.DataFrame, columns_config: dict[str, dict[str, Any]]
    ) -> pd.DataFrame:
        """Aplica la configuración por columna sobre el DataFrame.

        `columns_config[col]` = `{"type": <PII>, "mode": <MASK|AEPD|FAKER|INITIALS>}`.
        """
        result_df = df.copy()
        for col, config in columns_config.items():
            if col not in result_df.columns:
                continue
            entity_type = config.get("type", "UNKNOWN")
            mode = config.get("mode", "FAKER")

            if entity_type in ("DNI", "NIE", "PASSPORT", "ID"):
                if mode in ("MASK", "AEPD"):
                    result_df[col] = result_df[col].astype(str).apply(
                        lambda x, m=mode: self.anonymize_document_id(x, mode=m)
                    )
                else:
                    result_df[col] = result_df[col].astype(str).apply(
                        lambda x, t=entity_type, c=col: self.fakes.generate(t, x, context=c)
                    )
            elif mode == "MASK":
                result_df[col] = result_df[col].astype(str).apply(
                    lambda x, t=entity_type: self._mask_generic(t, x)
                )
            elif entity_type in ("PERSON_NAME", "PERSON"):
                if mode == "INITIALS":
                    result_df[col] = result_df[col].astype(str).apply(
                        lambda x: self.anonymize_name(x, mode="INITIALS")
                    )
                else:
                    result_df[col] = result_df[col].astype(str).apply(
                        lambda x, c=col: self.fakes.generate("PERSON_NAME", x, context=c)
                    )
            elif entity_type in ("EMAIL", "PHONE", "IBAN"):
                result_df[col] = result_df[col].astype(str).apply(
                    lambda x, t=entity_type, c=col: self.fakes.generate(t, x, context=c)
                )
            elif entity_type in self.PATTERNS or entity_type in ("ADDRESS", "ORGANIZATION"):
                result_df[col] = result_df[col].astype(str).apply(
                    lambda x, t=entity_type, c=col: self.fakes.generate(t, x, context=c)
                )
            else:
                result_df[col] = result_df[col].astype(str).apply(self.anonymize)
        return result_df

    # ------------------------------------------------------------------
    # Heurística de cabecera + análisis de DataFrame
    # ------------------------------------------------------------------

    _HEADER_HEURISTICS: dict[str, list[str]] = {
        "PERSON_NAME": [
            "nombre", "name", "nom", "cognom", "apellido", "firstname", "lastname",
            "fullname", "cliente", "empleado", "usuario",
        ],
        "EMAIL": ["email", "correo", "mail", "e-mail"],
        "PHONE": ["telefono", "phone", "movil", "celular", "tel"],
        "DNI": ["dni", "nif", "documento", "identificacion", "id_card"],
        "NIE": ["nie"],
        "IBAN": ["iban", "cuenta", "banco", "ccc"],
        "ADDRESS": [
            "direccion", "domicilio", "calle", "address", "ciudad", "poblacion",
            "cp", "postal",
        ],
        "CREDIT_CARD": ["tarjeta", "card", "cc_num"],
    }

    def _analyze_header(self, col_name: str) -> str | None:
        name_lower = col_name.lower().strip()
        for pii_type, keywords in self._HEADER_HEURISTICS.items():
            if any(k in name_lower for k in keywords):
                return pii_type
        return None

    def analyze_fields(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        sample_size = min(len(df), 10)
        sample_df = df.head(sample_size)

        for col in df.columns:
            findings: list[str] = []
            header_type = self._analyze_header(str(col))
            if header_type:
                findings.extend([header_type] * 3)
            for value in sample_df[col].dropna().astype(str):
                entities = self._detect_with_regex(value) + self._detect_with_ner(value)
                findings.extend(ent.type for ent in entities)

            detected_type = "NONE"
            confidence = 0.0
            if findings:
                counts: dict[str, int] = {}
                for f_typ in findings:
                    counts[f_typ] = counts.get(f_typ, 0) + 1
                best = max(counts, key=counts.get)  # type: ignore[arg-type]
                type_map = {
                    "EMAIL": "EMAIL",
                    "PERSON_NAME": "PERSON",
                    "DNI": "ID",
                    "NIE": "ID",
                    "PASSPORT": "ID",
                    "PHONE": "ID",
                    "IBAN": "ID",
                    "CREDIT_CARD": "ID",
                }
                detected_type = type_map.get(best, "NONE")
                total = sample_size + (3 if header_type else 0)
                confidence = counts[best] / total if total else 0.0

            strategy = "none"
            if detected_type in ("EMAIL", "ID"):
                strategy = "masking"
            elif detected_type == "PERSON":
                strategy = "synthetic"

            results.append(
                {
                    "field": col,
                    "type": detected_type,
                    "is_sensitive": detected_type != "NONE",
                    "confidence": min(confidence, 1.0),
                    "recommended_strategy": strategy,
                }
            )
        return results

    # ------------------------------------------------------------------
    # Anchors API (contexto para LLM)
    # ------------------------------------------------------------------

    def get_detected_anchors(self) -> list[dict[str, Any]]:
        return list(self._detected_anchors)

    def clear_detected_anchors(self) -> None:
        self._detected_anchors.clear()

    def get_form_structure_hint(self) -> str | None:
        if not self._detected_anchors:
            return None
        firstname: list[str] = []
        lastname: list[str] = []
        fullname: list[str] = []
        for anchor in self._detected_anchors:
            label = anchor.get("label", "")
            field_type = anchor.get("field_type", "")
            if field_type == "firstname":
                firstname.append(label)
            elif field_type == "lastname":
                lastname.append(label)
            elif field_type == "fullname":
                fullname.append(label)

        lines = ["ESTRUCTURA DEL FORMULARIO DETECTADA:"]
        for lbl in dict.fromkeys(firstname):
            lines.append(f"  - Etiqueta '{lbl}:' contiene NOMBRE DE PILA")
        for lbl in dict.fromkeys(lastname):
            lines.append(f"  - Etiqueta '{lbl}:' contiene APELLIDOS")
        for lbl in dict.fromkeys(fullname):
            lines.append(f"  - Etiqueta '{lbl}:' contiene NOMBRE COMPLETO")
        if firstname and lastname:
            lines.extend(
                [
                    "",
                    "IMPORTANTE: El formulario tiene NOMBRE y APELLIDOS en campos SEPARADOS.",
                    "Si el usuario solicita 'Nombre y Apellidos' o 'Nombre completo' como",
                    "campo único, DEBES:",
                    "  1. Extraer el valor de la etiqueta de nombre (ej: 'Nombre:')",
                    "  2. Extraer el valor de la etiqueta de apellidos (ej: 'Apellidos:')",
                    "  3. Concatenar ambos valores con un espacio: '{nombre} {apellidos}'",
                ]
            )
        return "\n".join(lines)
