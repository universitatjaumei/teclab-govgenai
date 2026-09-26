"""Huecos de corpus detectados desde señales de fallo (RAG.14). Deploy: edge.

La señal ya existe y no cuesta nada recogerla: RAG.2 persiste `fallback_reason` cada vez que
el chatbot no encuentra con qué responder, y el feedback bajo lleva ahí desde 9Q. Lo que
faltaba era leerlas juntas.

**Una pregunta sin respuesta es ruido; veinte preguntas parecidas sin respuesta son un
documento que falta**, y eso sí es accionable: alguien puede ir a buscar esa norma y
cargarla. Ese salto —de anécdota a tarea— es todo lo que hace este módulo.

Tres decisiones que lo sostienen:

- **El hallazgo es del chatbot, no de un sitio web.** El resto de hallazgos de 9Q nacieron
  de auditar páginas; este nace de conversaciones, y forzarlo a colgar de un sitio sería
  inventarle un sitio a una pregunta.
- **La agrupación es por centroide, no por texto.** «quant cobro de dieta» e «import de la
  dieta per dia» son el mismo hueco; comparar cadenas los contaría como dos y la cola de
  revisión se llenaría del mismo problema escrito de veinte maneras.
- **Umbral de tamaño mínimo.** Dos preguntas parecidas son casualidad. Sin umbral, la cola
  se llena de ruido y deja de mirarse, que es la forma habitual de matar una cola de
  revisión.

El clustering es **aglomerativo por umbral de coseno**, no k-means: no se sabe cuántos
huecos hay —es justo lo que se busca— y k-means exige decidirlo de antemano. `_cosine` es una
copia local, no un import cruzado hacia el módulo de curación (que tiene el mismo cálculo en
su detector semántico): la frontera de CUR.1 prohíbe que este lado importe del otro, y cinco
líneas de aritmética no justifican una dependencia cruzada.
"""
from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.operational_models import (
    HubContentFinding,
    HubInteraction,
)

# Feedback igual o por debajo de esto cuenta como señal. Sobre 5, un 2 ya es «no me sirve».
UMBRAL_FEEDBACK = 2
VENTANA_DIAS = 30
MIN_TAMANO_CLUSTER = 3
# Por encima de esto, dos consultas son el mismo hueco. Deliberadamente alto: mezclar dos
# huecos en uno hace ilegible el hallazgo, y partir uno en dos solo lo hace repetitivo.
UMBRAL_SIMILITUD = 0.80
MAX_QUERIES_REPRESENTATIVAS = 5
MAX_TOP_TERMS = 8

_PALABRA = re.compile(r"\w{4,}", re.UNICODE)
# Palabras que aparecen en cualquier pregunta y no distinguen un hueco de otro.
_VACIAS = {
    "para", "como", "cual", "cuales", "cuanto", "cuanta", "donde", "quien", "sobre",
    "quant", "quin", "quina", "quines", "quan", "quantes", "aquest", "aquesta",
    "puedo", "puede", "tengo", "tiene", "hacer", "esta", "este", "pero", "cuando",
}


class EmbeddingService(Protocol):
    async def embed(self, text: str) -> list[float]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


@dataclass(frozen=True)
class SenalDeFallo:
    """Una interacción que salió mal, con por qué se sabe que salió mal."""

    query: str
    motivo: str
    cuando: datetime


@dataclass(frozen=True)
class GapFinding:
    """Espejo mínimo de `ContentFinding`, el contrato del módulo de curación, para el hueco
    de un chatbot: este módulo no puede importar del otro lado de la frontera (CUR.1). `site_id`
    y `page_id` se conservan siempre a `None` —un hueco no cuelga de ningún sitio ni de ninguna
    página, sólo de un chatbot— porque los tests de 9Q ya comprueban esa invariante contra el
    propio hallazgo; el validador de «exactamente un sujeto» de `ContentFinding` no hace falta,
    eso sí: la tabla sólo admite un hueco de chatbot por esta vía.
    """

    id: uuid.UUID
    chatbot_id: uuid.UUID
    finding_type: str
    severity: str
    confidence: float
    detected_at: datetime
    signal: dict[str, Any] = field(default_factory=dict)
    site_id: uuid.UUID | None = None
    page_id: uuid.UUID | None = None


async def recoger_senales(
    session: AsyncSession,
    chatbot_id: uuid.UUID,
    dias: int = VENTANA_DIAS,
    umbral_feedback: int = UMBRAL_FEEDBACK,
) -> list[SenalDeFallo]:
    """Interacciones del chatbot que delatan que no se supo responder.

    Dos fuentes con la misma consecuencia: el usuario dijo que no valía, o el propio grafo
    reconoció que no tenía con qué responder. La segunda es gratis y no depende de que
    nadie pulse nada, que es lo que la hace útil de verdad.
    """
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    # recorrido-acotado: interacciones de un chatbot en una ventana de dias, y solo las que
    # fallaron. Son 74 filas en toda la tabla hoy. Si `hub_interactions` llega a crecer de
    # verdad, esto se pagina antes que ninguna otra cosa: es analitica sobre el historico
    # entero de una ventana (issue #159).
    filas = await session.execute(
        select(HubInteraction)
        .where(HubInteraction.chatbot_id == chatbot_id)
        .where(HubInteraction.created_at >= desde)
        .where(
            or_(
                HubInteraction.feedback_score <= umbral_feedback,
                HubInteraction.fallback_reason.in_(("quality_gate", "citation")),
            )
        )
        .order_by(HubInteraction.created_at)
    )
    return [
        SenalDeFallo(
            query=fila.user_message,
            motivo=fila.fallback_reason or "low_feedback",
            cuando=fila.created_at,
        )
        for fila in filas.scalars().all()
    ]


def _agrupar(
    senales: list[SenalDeFallo], vectores: list[list[float]], umbral: float
) -> list[list[int]]:
    """Aglomerativo por umbral: cada señal entra en el primer grupo que la acepta.

    Se compara contra el CENTROIDE del grupo y no contra su primer miembro, para que el
    resultado no dependa del orden de llegada más de lo inevitable.
    """
    grupos: list[list[int]] = []
    centroides: list[list[float]] = []

    for indice, vector in enumerate(vectores):
        destino = None
        for numero, centroide in enumerate(centroides):
            if _cosine(vector, centroide) >= umbral:
                destino = numero
                break

        if destino is None:
            grupos.append([indice])
            centroides.append(list(vector))
            continue

        grupos[destino].append(indice)
        n = len(grupos[destino])
        centroides[destino] = [
            (c * (n - 1) + v) / n for c, v in zip(centroides[destino], vector)
        ]

    return grupos


def _terminos_top(consultas: list[str]) -> list[str]:
    contador: Counter[str] = Counter()
    for consulta in consultas:
        for palabra in _PALABRA.findall(consulta.lower()):
            if palabra not in _VACIAS:
                contador[palabra] += 1
    return [palabra for palabra, _ in contador.most_common(MAX_TOP_TERMS)]


def _severidad(recuento: int) -> str:
    """Cuánta gente se ha quedado sin respuesta por lo mismo."""
    if recuento >= 20:
        return "critical"
    if recuento >= 8:
        return "warning"
    return "info"


@dataclass(frozen=True)
class HuecoDetectado:
    """Un cluster que ya merece hallazgo, con su centroide para poder deduplicar."""

    finding: GapFinding
    centroide: list[float]


async def detectar_huecos(
    session: AsyncSession,
    chatbot_id: uuid.UUID,
    embedding_service: EmbeddingService,
    dias: int = VENTANA_DIAS,
    min_cluster_size: int = MIN_TAMANO_CLUSTER,
    umbral_similitud: float = UMBRAL_SIMILITUD,
) -> list[GapFinding]:
    """Los huecos del chatbot, sin escribir nada. Es lo que se puede mirar antes de guardar."""
    return [h.finding for h in await _detectar(
        session, chatbot_id, embedding_service, dias, min_cluster_size, umbral_similitud
    )]


async def _detectar(
    session: AsyncSession,
    chatbot_id: uuid.UUID,
    embedding_service: EmbeddingService,
    dias: int,
    min_cluster_size: int,
    umbral_similitud: float,
) -> list[HuecoDetectado]:
    senales = await recoger_senales(session, chatbot_id, dias=dias)
    if len(senales) < min_cluster_size:
        return []

    vectores = [await embedding_service.embed(s.query) for s in senales]
    ahora = datetime.now(timezone.utc)
    huecos: list[HuecoDetectado] = []

    for grupo in _agrupar(senales, vectores, umbral_similitud):
        if len(grupo) < min_cluster_size:
            continue

        delgrupo = [senales[i] for i in grupo]
        consultas = [s.query for s in delgrupo]
        momentos = sorted(s.cuando for s in delgrupo)
        dimension = len(vectores[grupo[0]])
        centroide = [
            sum(vectores[i][d] for i in grupo) / len(grupo) for d in range(dimension)
        ]

        huecos.append(HuecoDetectado(
            finding=GapFinding(
                id=uuid.uuid4(),
                chatbot_id=chatbot_id,
                finding_type="content_gap",
                severity=_severidad(len(grupo)),  # type: ignore[arg-type]
                # No es la confianza de un modelo: es cuánto respalda el volumen a que esto
                # sea un hueco real y no tres personas con mala suerte.
                confidence=min(1.0, len(grupo) / 10),
                detected_at=ahora,
                signal={
                    "queries": consultas[:MAX_QUERIES_REPRESENTATIVAS],
                    "count": len(grupo),
                    "first_seen": momentos[0].isoformat(),
                    "last_seen": momentos[-1].isoformat(),
                    "top_terms": _terminos_top(consultas),
                    "reasons": sorted({s.motivo for s in delgrupo}),
                    "centroid": centroide,
                },
            ),
            centroide=centroide,
        ))

    return huecos


async def analizar_huecos(
    session: AsyncSession,
    chatbot_id: uuid.UUID,
    embedding_service: EmbeddingService,
    dias: int = VENTANA_DIAS,
    min_cluster_size: int = MIN_TAMANO_CLUSTER,
    umbral_similitud: float = UMBRAL_SIMILITUD,
) -> int:
    """Detecta y persiste. Devuelve cuántos huecos hay vivos tras el análisis.

    **Deduplica por centroide contra los hallazgos abiertos**, no por identidad de texto: el
    detector se ejecuta periódicamente sobre una ventana móvil, así que sin esto cada
    ejecución añadiría una fila del mismo problema y la cola sería inservible en una semana.
    Un hallazgo ya revisado —`resolved` o `dismissed`— no bloquea uno nuevo: si el hueco
    reaparece después de darlo por cerrado, eso es información, no ruido.
    """
    huecos = await _detectar(
        session, chatbot_id, embedding_service, dias, min_cluster_size, umbral_similitud
    )
    if not huecos:
        return 0

    abiertos = list((await session.execute(
        select(HubContentFinding)
        .where(HubContentFinding.chatbot_id == chatbot_id)
        .where(HubContentFinding.finding_type == "content_gap")
        .where(HubContentFinding.status.in_(("new", "confirmed")))
    )).scalars().all())

    for hueco in huecos:
        existente = _mismo_hueco(abiertos, hueco.centroide, umbral_similitud)
        if existente is None:
            session.add(HubContentFinding(
                id=hueco.finding.id,
                site_id=None,
                chatbot_id=chatbot_id,
                finding_type=hueco.finding.finding_type,
                severity=hueco.finding.severity,
                confidence=hueco.finding.confidence,
                signal_json=hueco.finding.signal,
                status="new",
                detected_at=hueco.finding.detected_at,
            ))
            continue

        existente.signal_json = hueco.finding.signal
        existente.severity = hueco.finding.severity
        existente.confidence = hueco.finding.confidence
        existente.detected_at = hueco.finding.detected_at

    await session.flush()
    return len(huecos)


def _mismo_hueco(
    abiertos: list[HubContentFinding], centroide: list[float], umbral: float
) -> HubContentFinding | None:
    for hallazgo in abiertos:
        guardado = (hallazgo.signal_json or {}).get("centroid")
        if guardado and _cosine(list(guardado), centroide) >= umbral:
            return hallazgo
    return None


def render_huecos(huecos: list[GapFinding]) -> str:
    """Informe legible para la consola del comando."""
    if not huecos:
        return "  sin huecos por encima del umbral"
    lineas = []
    for hueco in huecos:
        s: dict[str, Any] = hueco.signal
        lineas.append(
            f"  [{hueco.severity}] {s['count']} consultas sin respuesta "
            f"({s['first_seen'][:10]} .. {s['last_seen'][:10]})"
        )
        lineas.append(f"      terminos: {', '.join(s['top_terms'])}")
        for consulta in s["queries"]:
            lineas.append(f"      - {consulta}")
    return "\n".join(lineas)
