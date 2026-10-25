"""Caducidad activa del corpus (SYNC.2). Deploy: edge.

**El sync solo detecta lo que cambia en origen.** Una norma que nadie toca durante tres años
no genera ninguna señal, y sin embargo es exactamente el riesgo nº1 del informe: 312 de 314
fichas dicen «vigent?». Este detector convierte el paso del tiempo en una señal, que es la
única forma de que algo deje de envejecer en silencio.

Es el más simple de los tres detectores que llenan la cola de revisión, y a propósito: lee
una fecha y la compara con hoy. No hay embeddings, ni LLM, ni heurística —de ahí que la
confianza sea 1,0: no está estimando nada—. Lo que aporta no es inteligencia, es que la
pregunta se haga alguna vez.

Tres decisiones, las mismas que en RAG.14 y por los mismos motivos:

- **El hallazgo cuelga del chatbot**, no de un sitio web: nace del corpus, no de auditar
  páginas, y forzarle un sitio sería inventárselo.
- **Deduplica contra los hallazgos abiertos.** El detector se ejecuta periódicamente; sin
  esto, cada pasada añadiría una fila del mismo documento y la cola sería inservible en una
  semana, que es la forma habitual de matar una cola de revisión.
- **Un hallazgo ya cerrado no bloquea uno nuevo.** Si la fecha sigue vencida después de
  darlo por resuelto, hay que volver a decirlo; lo contrario convierte `resolved` en un
  silenciador permanente sobre un documento que nadie ha revisado.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.operational_models import (
    HubContentFinding,
    HubDocument,
)

TIPO = "revisio_vencuda"
ESTADOS_ABIERTOS = ("new", "confirmed")
# A partir de aquí el retraso deja de ser un despiste y pasa a ser un problema de vigencia.
DIAS_CRITICO = 180


@dataclass(frozen=True)
class Caducado:
    """Un documento cuya revisión ha vencido, con lo que hace falta para juzgarlo."""

    document_id: uuid.UUID
    id_publicacio: str | None
    title: str | None
    source_url: str | None
    data_revisio_prevista: date
    darrera_actualitzacio: datetime | None
    dies_de_retard: int

    @property
    def severity(self) -> str:
        return "critical" if self.dies_de_retard >= DIAS_CRITICO else "warning"

    def senal(self) -> dict:
        return {
            "document_id": str(self.document_id),
            "id_publicacio": self.id_publicacio,
            "title": self.title,
            "data_revisio_prevista": self.data_revisio_prevista.isoformat(),
            "darrera_actualitzacio": (
                self.darrera_actualitzacio.isoformat()
                if self.darrera_actualitzacio
                else None
            ),
            "dies_de_retard": self.dies_de_retard,
        }


async def detectar_caducados(
    session: AsyncSession, chatbot_id: uuid.UUID, hoy: date | None = None
) -> list[Caducado]:
    """Documentos del chatbot con la revisión vencida, más vencidos primero.

    `hoy` se inyecta para poder probar el borde sin esperar a que pase el tiempo.
    """
    hoy = hoy or date.today()

    filas = (
        await session.execute(
            select(HubDocument)
            .where(HubDocument.chatbot_id == chatbot_id)
            .where(HubDocument.data_revisio_prevista.is_not(None))
            .where(HubDocument.data_revisio_prevista < hoy)
            # Lo que no se indexa no caduca: avisar de un documento que el asistente no
            # va a leer nunca es llenar la cola de trabajo que no sirve para nada.
            .where(HubDocument.us_assistents != "no")
        )
    ).scalars().all()

    caducados = [
        Caducado(
            document_id=doc.id,
            id_publicacio=doc.id_publicacio,
            title=doc.title,
            source_url=doc.canonical_url,
            data_revisio_prevista=prevista,
            darrera_actualitzacio=doc.last_seen_at or doc.created_at,
            dies_de_retard=(hoy - prevista).days,
        )
        for doc in filas
        # La consulta ya excluye los nulos; esto sólo se lo dice al comprobador de tipos.
        if (prevista := doc.data_revisio_prevista) is not None
    ]
    return sorted(caducados, key=lambda c: c.dies_de_retard, reverse=True)


async def analizar_caducidad(
    session: AsyncSession, chatbot_id: uuid.UUID, hoy: date | None = None
) -> int:
    """Detecta y persiste. Devuelve cuántos documentos tienen la revisión vencida.

    Un documento que ya tiene un hallazgo abierto **se actualiza en vez de duplicarse**: los
    días de retraso crecen cada día que pasa, y quien mira la cola quiere el número de hoy,
    no una fila nueva por cada ejecución.
    """
    caducados = await detectar_caducados(session, chatbot_id, hoy)
    if not caducados:
        return 0

    abiertos = {
        (f.signal_json or {}).get("document_id"): f
        for f in (
            await session.execute(
                select(HubContentFinding)
                .where(HubContentFinding.chatbot_id == chatbot_id)
                .where(HubContentFinding.finding_type == TIPO)
                .where(HubContentFinding.status.in_(ESTADOS_ABIERTOS))
            )
        ).scalars().all()
    }

    ahora = datetime.now(timezone.utc)
    for caducado in caducados:
        existente = abiertos.get(str(caducado.document_id))
        if existente is None:
            session.add(
                HubContentFinding(
                    site_id=None,
                    chatbot_id=chatbot_id,
                    finding_type=TIPO,
                    severity=caducado.severity,
                    # No hay estimación: la fecha ha vencido o no ha vencido.
                    confidence=1.0,
                    source_url=caducado.source_url,
                    signal_json=caducado.senal(),
                    status="new",
                    detected_at=ahora,
                )
            )
            continue

        existente.severity = caducado.severity
        existente.signal_json = caducado.senal()
        existente.detected_at = ahora

    await session.flush()
    return len(caducados)


async def listar_caducados(
    session: AsyncSession, chatbot_id: uuid.UUID, status: str | None = None
) -> list[HubContentFinding]:
    """Cola de revisión de las caducidades de un chatbot, las más urgentes primero."""
    consulta = (
        select(HubContentFinding)
        .where(HubContentFinding.chatbot_id == chatbot_id)
        .where(HubContentFinding.finding_type == TIPO)
        .order_by(HubContentFinding.detected_at.desc())
    )
    if status:
        consulta = consulta.where(HubContentFinding.status == status)
    return list((await session.execute(consulta)).scalars().all())


def render_caducados(caducados: list[Caducado]) -> str:
    """Salida de consola de la CLI."""
    if not caducados:
        return "No hay documentos con la revision vencida."
    lineas = [f"{len(caducados)} documento(s) con la revision vencida:"]
    for c in caducados:
        lineas.append(
            f"  [{c.severity:>8}] {c.id_publicacio or c.source_url}: prevista "
            f"{c.data_revisio_prevista.isoformat()}, {c.dies_de_retard} dias de retard"
        )
    return "\n".join(lineas)
