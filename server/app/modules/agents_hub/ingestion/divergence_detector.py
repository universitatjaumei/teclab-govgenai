"""Deriva entre copias de la misma norma (DER.2). Deploy: edge.

Se descartó compartir el documento entre chatbots (bloque COR): la misma norma en dos
asistentes son dos filas, y eso conserva algo que se quiere —que cada asistente elija su
modelo de embedding, que es el conmutador que la guarda de RAG.9 existe para hacer seguro—.

Lo que esa duplicación cuesta es **la deriva**: alguien recarga un asistente y no el otro, y
las dos copias quedan con contenidos distintos sin que nada avise. Este detector es lo que
paga esa factura.

**La clave de identidad es `canonical_url`, no `content_hash`**, y es la decisión que hace
que esto funcione. Hash igual significa contenido idéntico; dos copias que han derivado
tienen hashes **distintos**, así que agrupar por hash encontraría exactamente lo contrario de
lo que se busca.

**Se detecta de forma continua y no al actualizar.** Un aviso en el momento de la
actualización solo protege del descuido que ya se sospecha; esto encuentra la deriva aunque
se produjera hace tres meses por un camino que nadie previó — un borrado a mano, una carga
parcial, una restauración de copia de seguridad.

Tres decisiones heredadas de `staleness_detector`, por los mismos motivos: el hallazgo cuelga
del chatbot, deduplica contra los hallazgos abiertos, y uno ya cerrado no bloquea uno nuevo.

**Vive en `agents_hub` y no en `curation`**, por el mismo criterio que dejó ahí a
`gap_detector` (CUR.1): su sujeto es un chatbot y su señal nace del corpus del asistente, no
de auditar páginas web. Es algo que el asistente **emite** hacia la curación, y la única
comunicación autorizada entre las dos mitades es la tabla `hub_content_findings`. Escribirlo
primero en `curation/` fue un error que cazó `test_frontera_curacion.py`.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.operational_models import (
    HubContentFinding,
    HubDocument,
)

TIPO = "copia_divergent"
ESTADOS_ABIERTOS = ("new", "confirmed")


@dataclass(frozen=True)
class CopiaDeDocumento:
    """Una copia de una norma en un chatbot concreto."""

    document_id: uuid.UUID
    chatbot_id: uuid.UUID
    canonical_url: str
    content_hash: str
    updated_at: datetime | None
    title: str | None
    id_publicacio: str | None
    estat_vigencia: str | None


@dataclass(frozen=True)
class Divergencia:
    """Un chatbot cuya copia de una norma no coincide con la de los demás."""

    chatbot_id: uuid.UUID
    canonical_url: str
    title: str | None
    id_publicacio: str | None
    document_id: uuid.UUID
    content_hash: str
    hash_vigent: str | None
    actualitzat: datetime | None
    actualitzat_vigent: datetime | None
    chatbots_afectats: tuple[uuid.UUID, ...]
    indeterminat: bool
    vigencia_en_disputa: bool

    @property
    def severity(self) -> str:
        """Crítico cuando las copias no se ponen de acuerdo sobre si la norma está en vigor.

        No es que una respuesta esté desactualizada: es que dos asistentes de la misma casa
        contestan lo contrario sobre si una norma sigue vigente. En un asistente normativo no
        hay nada peor que eso.
        """
        return "critical" if self.vigencia_en_disputa else "warning"

    def senal(self) -> dict:
        return {
            "canonical_url": self.canonical_url,
            "title": self.title,
            "id_publicacio": self.id_publicacio,
            "document_id": str(self.document_id),
            "content_hash": self.content_hash,
            "hash_vigent": self.hash_vigent,
            "actualitzat": self.actualitzat.isoformat() if self.actualitzat else None,
            "actualitzat_vigent": (
                self.actualitzat_vigent.isoformat() if self.actualitzat_vigent else None
            ),
            "chatbots_afectats": [str(c) for c in self.chatbots_afectats],
            "indeterminat": self.indeterminat,
            "vigencia_en_disputa": self.vigencia_en_disputa,
        }


def agrupar_divergencias(copias: list[CopiaDeDocumento]) -> list[Divergencia]:
    """Copias de la misma norma que no coinciden, con quién tiene que recargar.

    Función pura sobre las filas, separada de la consulta a propósito: lo que decide si un
    aviso es correcto —quién está atrasado, cuándo no se puede saber, cuándo es grave— se
    prueba sin base de datos.
    """
    # ACT.6 — LA IDENTIDAD DE UNA VERSION ES `id_publicacio`, NO LA URL.
    #
    # Agrupar por `canonical_url` daba 17 falsos positivos sobre el corpus real: hay 5 parejas
    # bilingues que COMPARTEN URL —la misma norma publicada en una sola direccion: una pagina de
    # preguntas frecuentes, un PDF del DOGV con las dos lenguas dentro—. El grupo salia con dos
    # hashes distintos, claro, porque son dos textos, y el detector mandaba recargar asistentes
    # que estaban al dia. Es la misma confusion que ACT.3 le quito a VIS.3: compartir URL no es
    # ser el mismo documento.
    #
    # La URL sigue siendo la clave cuando no hay identificador, que es el caso del corpus
    # rastreado por el modulo de curacion.
    por_norma: dict[str, list[CopiaDeDocumento]] = defaultdict(list)
    for copia in copias:
        por_norma[copia.id_publicacio or copia.canonical_url].append(copia)

    divergencias: list[Divergencia] = []
    for grupo in por_norma.values():
        if len({c.content_hash for c in grupo}) < 2:
            continue

        afectados = tuple(sorted((c.chatbot_id for c in grupo), key=str))
        vigencia_en_disputa = len({c.estat_vigencia for c in grupo}) > 1

        fechas = [c.updated_at for c in grupo if c.updated_at is not None]
        mas_reciente = max(fechas) if fechas else None
        # Sin fecha que las distinga no se puede afirmar cuál manda, y elegir una al azar
        # sería peor que callar: el aviso llevaría implícita una afirmación falsa.
        indeterminado = mas_reciente is None or all(
            c.updated_at == mas_reciente for c in grupo
        )

        if indeterminado:
            atrasadas, vigente = grupo, None
        else:
            vigente = next(c for c in grupo if c.updated_at == mas_reciente)
            atrasadas = [c for c in grupo if c.content_hash != vigente.content_hash]

        for copia in atrasadas:
            divergencias.append(
                Divergencia(
                    chatbot_id=copia.chatbot_id,
                    # La URL de la copia, no la clave del grupo: con `id_publicacio`
                    # como clave, la del grupo ya no es una URL.
                    canonical_url=copia.canonical_url,
                    title=copia.title,
                    id_publicacio=copia.id_publicacio,
                    document_id=copia.document_id,
                    content_hash=copia.content_hash,
                    hash_vigent=vigente.content_hash if vigente else None,
                    actualitzat=copia.updated_at,
                    actualitzat_vigent=vigente.updated_at if vigente else None,
                    chatbots_afectats=afectados,
                    indeterminat=indeterminado,
                    vigencia_en_disputa=vigencia_en_disputa,
                )
            )

    return divergencias


async def detectar_divergencias(
    session: AsyncSession, chatbot_ids: list[uuid.UUID]
) -> list[Divergencia]:
    """Deriva entre las copias que tienen estos chatbots.

    Recibe los identificadores y no una organización a propósito: `HubDocument` es
    operacional (edge) y `HubChatbot` es configuración (cloud), así que quien llama resuelve
    la organización y aquí no se cruzan las dos bases (CLAUDE.md).
    """
    if len(chatbot_ids) < 2:
        return []

    filas = (
        await session.execute(
            select(
                HubDocument.id,
                HubDocument.chatbot_id,
                HubDocument.canonical_url,
                HubDocument.content_hash,
                HubDocument.updated_at,
                HubDocument.title,
                HubDocument.id_publicacio,
                HubDocument.estat_vigencia,
            ).where(HubDocument.chatbot_id.in_(chatbot_ids))
        )
    ).all()

    return agrupar_divergencias([CopiaDeDocumento(*fila) for fila in filas])


async def analizar_divergencias(
    session: AsyncSession, chatbot_ids: list[uuid.UUID]
) -> int:
    """Detecta y persiste. Devuelve cuántas copias están fuera de sincronía.

    Un hallazgo abierto sobre la misma norma y el mismo chatbot **se actualiza en vez de
    duplicarse**: el detector corre periódicamente y sin esto la cola sería inservible en una
    semana, que es la forma habitual de matar una cola de revisión.
    """
    divergencias = await detectar_divergencias(session, chatbot_ids)
    if not divergencias:
        return 0

    abiertos = {
        (f.chatbot_id, (f.signal_json or {}).get("canonical_url")): f
        for f in (
            await session.execute(
                select(HubContentFinding)
                .where(HubContentFinding.chatbot_id.in_(chatbot_ids))
                .where(HubContentFinding.finding_type == TIPO)
                .where(HubContentFinding.status.in_(ESTADOS_ABIERTOS))
            )
        ).scalars().all()
    }

    ahora = datetime.now(timezone.utc)
    for divergencia in divergencias:
        existente = abiertos.get((divergencia.chatbot_id, divergencia.canonical_url))
        if existente is None:
            session.add(
                HubContentFinding(
                    site_id=None,
                    chatbot_id=divergencia.chatbot_id,
                    finding_type=TIPO,
                    severity=divergencia.severity,
                    # No hay estimación: los hashes coinciden o no coinciden.
                    confidence=1.0,
                    source_url=divergencia.canonical_url,
                    signal_json=divergencia.senal(),
                    status="new",
                    detected_at=ahora,
                )
            )
            continue

        existente.severity = divergencia.severity
        existente.signal_json = divergencia.senal()
        existente.detected_at = ahora

    await session.flush()
    return len(divergencias)


def render_divergencias(divergencias: list[Divergencia]) -> str:
    """Salida de consola, para la CLI de carga."""
    if not divergencias:
        return "No hay copias divergentes."

    lineas = [f"{len(divergencias)} copia(s) fuera de sincronia:"]
    for d in divergencias:
        motivo = (
            "no se puede determinar cual es la vigente"
            if d.indeterminat
            else f"la vigente es {(d.hash_vigent or '')[:8]}"
        )
        aviso = " [VIGENCIA EN DISPUTA]" if d.vigencia_en_disputa else ""
        lineas.append(
            f"  [{d.severity:>8}] {d.chatbot_id}: {d.id_publicacio or d.canonical_url} "
            f"-- {motivo}{aviso}"
        )
    return "\n".join(lineas)
