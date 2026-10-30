"""Contratos Pydantic para hallazgos de calidad de contenido web (9Q.1)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


FindingType = Literal[
    # CUR.2: hay varias versiones **por ano** del mismo recurso. Sustituye a `superseded` para este
    # caso, porque el usuario aporto el dato del dominio que lo tumbaba: el portal publica acuerdos
    # y actas por ano y **todos siguen vigentes**, asi que decir que la de 2017 esta "superada" por
    # la de 2025 es falso. Lo unico cierto es que la serie existe, y eso es informativo: un hallazgo
    # por grupo, con sus URLs y sus fechas, para que una persona decida si sobran las antiguas.
    "version_series",
    "superseded",
    "duplicate",
    "contradiction",
    "empty",
    "thin",
    # #345: una página escasa cuyo texto son enlaces. No es un defecto, es estructura del portal,
    # y mezclada con `thin` llenaba de ruido la cola de las escasas de verdad.
    "navigation",
    # RAS.5: una pagina que ya estaba en el corpus de un asistente ha cambiado en el portal y se
    # ha reingerido. No es un defecto: es el aviso de que lo que el asistente responde sobre esa
    # pagina ha cambiado, para poder revisarlo. Antes el cambio se detectaba y no se propagaba.
    "content_updated",
    # RAS.2: la pagina no se ha podido leer sin renderizar. Es lo unico que el sistema sabe de
    # verdad cuando el contenido lo pinta JavaScript, y sustituye al `empty` critico que
    # afirmaba lo contrario: que la pagina esta vacia. Aviso, no acusacion.
    "needs_javascript",
    "stale",
    "crawl_error",
    "orphan_page",
    # RAG.14: hueco de corpus. A diferencia de los demas, no sale de auditar paginas
    # sino de leer conversaciones que salieron mal.
    "content_gap",
    # SYNC.2: la fecha de revision prevista de un documento ha vencido. Tampoco sale de
    # auditar paginas: sale de que pase el tiempo. El sync detecta lo que cambia en origen,
    # y una norma que nadie toca durante tres anos no emite ninguna senal.
    "revisio_vencuda",
    # DIN.4: la pagina desaparecio del portal y su apartado NO esta en modo automatico, asi que
    # no se ha tocado el corpus. Es una senal para quien cura, no una acusacion contra la
    # pagina: se retira sola cuando la pagina vuelve a aparecer.
    "page_gone",
    # DIN.5: la automatizacion NO metio esta pagina al corpus porque el propio job acababa de
    # decir que no se puede leer. La pagina sigue siendo candidata: resuelto el hallazgo, la
    # pasada siguiente la ingiere sola. El motivo va en `signal` porque quien cura tiene que
    # poder ver POR QUE no entro.
    "auto_ingesta_detenida",
    # DIN.4: las bajas de esta pasada superan el umbral del ambito, asi que no se ha retirado
    # NADA. Protege de la clase de rastreo malo que `truncated` no capta —el portal que responde
    # 200 con una plantilla vacia, la redireccion masiva— y que sin esto vaciaria un corpus con
    # el rastreo en verde.
    "retirada_masiva_detenida",
    # DER.2: la misma norma con contenidos distintos en dos chatbots de la organización.
    # Es la factura de haber descartado compartir el documento (COR): filas separadas
    # conservan que cada asistente elija su modelo de embedding, y a cambio pueden derivar.
    "copia_divergent",
]

FindingSeverity = Literal["info", "warning", "critical"]

FindingStatus = Literal["new", "confirmed", "dismissed", "resolved"]

_VALID_FINDING_TRANSITIONS: dict[str, set[str]] = {
    "new": {"confirmed", "dismissed"},
    "confirmed": {"resolved", "dismissed"},
    "dismissed": {"new"},
    "resolved": set(),
}


def transiciones_permitidas(estado: str) -> set[str]:
    """Los estados a los que puede pasar un hallazgo desde `estado`.

    Una sola regla para la transición que se aplica y para las acciones que se ofrecen.
    """
    return set(_VALID_FINDING_TRANSITIONS.get(estado, set()))


class InvalidFindingTransitionError(ValueError):
    pass


class ContentFinding(BaseModel, frozen=True):
    """Un hallazgo tiene UN sujeto: un sitio web (9Q) o un chatbot (RAG.14).

    El validador no es decoracion: nullable en la columna significa «este hallazgo usa
    el otro sujeto», nunca «sin sujeto». Un hallazgo sin sujeto no se puede revisar.
    """

    id: uuid.UUID
    site_id: uuid.UUID | None = None
    chatbot_id: uuid.UUID | None = None
    finding_type: FindingType
    severity: FindingSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    detected_at: datetime
    status: FindingStatus = "new"

    page_id: uuid.UUID | None = None
    related_page_id: uuid.UUID | None = None
    source_url: str | None = None
    signal: dict[str, Any] = Field(default_factory=dict)

    reviewed_at: datetime | None = None
    reviewed_by: uuid.UUID | None = None
    resolution_note: str | None = None

    @model_validator(mode="after")
    def _exactamente_un_sujeto(self) -> "ContentFinding":
        if (self.site_id is None) == (self.chatbot_id is None):
            raise ValueError(
                "un hallazgo cuelga de un sitio O de un chatbot, nunca de los dos ni "
                "de ninguno: sin sujeto no se puede revisar"
            )
        return self
