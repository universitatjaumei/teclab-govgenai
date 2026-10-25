"""Re-embedding masivo del corpus ya cargado (RAG.9). Deploy: edge.

Es la herramienta operativa de los prompts que cambian **qué se embebe** o **con qué**:
RAG.7 metió la jerarquía en el texto embebido, RAG.8 el troceado padre-hijo, MOD.2 abrió el
cambio de proveedor. Los tres dejan un corpus cuyos vectores ya no son los que la ingesta
produciría hoy, y eso no da error: da resultados peores.

**Se re-embebe `embedding_text`, nunca `content`.** Desde RAG.7 son textos distintos, y
reconstruir el embebible a partir del contenido daría vectores que la ingesta no generó
jamás. Los chunks anteriores a RAG.9 no lo tienen guardado; no se inventan: se cuentan
aparte y se remiten a `recalculate-corpus`, que sí re-trocea desde el documento.

**Por lotes y sin cargar el corpus en memoria**: se pagina por clave primaria en vez de
`OFFSET`, porque el UPDATE de cada lote cambia las filas bajo los pies del cursor y un
`OFFSET` creciente se saltaría chunks en silencio.

    uv run python -m server.app.modules.agents_hub.ingestion.reembed --chatbot-id <uuid>
    uv run python -m server.app.modules.agents_hub.ingestion.reembed --all --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.operational_models import HubDocumentChunk

logger = logging.getLogger(__name__)

LOTE_POR_DEFECTO = 128


@dataclass(frozen=True)
class ReembedPlan:
    """Lo que haría un re-embedding, antes de hacerlo."""

    chatbot_id: uuid.UUID
    modelo_activo: str
    dimension_activa: int
    total: int
    pendientes: int
    al_dia: int
    sin_texto_embebido: int

    def describe(self) -> str:
        lineas = [
            f"Chatbot {self.chatbot_id} -> {self.modelo_activo} ({self.dimension_activa})",
            f"  {self.total} chunks en total",
            f"  {self.pendientes} a re-embeber",
            f"  {self.al_dia} ya en el modelo activo (se saltan; --force los incluye)",
        ]
        if self.sin_texto_embebido:
            lineas.append(
                f"  {self.sin_texto_embebido} SIN texto embebido guardado: no se pueden "
                "re-embeber con fidelidad. Usa POST /hub/chatbots/<id>/recalculate-corpus, "
                "que re-trocea desde el documento."
            )
        return "\n".join(lineas)


def _es_de_otro_espacio(modelo: str, dimension: int, tarea: str | None = None):
    """PIL.1: el tipo de tarea es parte del espacio, no un adorno del registro.

    `IS DISTINCT FROM` y no `!=` porque la columna admite NULL —el modelo local no
    distingue propósito— y con `!=` un NULL da NULL, que en un WHERE se comporta como
    falso: los chunks sin tipo declarado quedarían fuera del re-embebido justo cuando son
    los que hay que rehacer.
    """
    return or_(
        HubDocumentChunk.embedding_model != modelo,
        HubDocumentChunk.embedding_dim != dimension,
        HubDocumentChunk.embedding_task_type.is_distinct_from(tarea),
    )


async def planificar_reembed(
    session: AsyncSession, chatbot_id: uuid.UUID, embedding_service: Any
) -> ReembedPlan:
    """Cuenta sin tocar nada. Es lo que ejecuta `--dry-run`."""
    modelo = str(embedding_service.model_name)
    dimension = int(embedding_service.dimensions)
    tarea = getattr(embedding_service, "embedding_task_type", None)

    base = select(func.count(HubDocumentChunk.id)).where(
        HubDocumentChunk.chatbot_id == chatbot_id
    )
    total = int((await session.execute(base)).scalar_one() or 0)
    ajenos = int(
        (
            await session.execute(
                base.where(_es_de_otro_espacio(modelo, dimension, tarea))
            )
        ).scalar_one()
        or 0
    )
    sin_texto = int(
        (
            await session.execute(
                base.where(_es_de_otro_espacio(modelo, dimension)).where(
                    HubDocumentChunk.embedding_text.is_(None)
                )
            )
        ).scalar_one()
        or 0
    )

    return ReembedPlan(
        chatbot_id=chatbot_id,
        modelo_activo=modelo,
        dimension_activa=dimension,
        total=total,
        pendientes=ajenos - sin_texto,
        al_dia=total - ajenos,
        sin_texto_embebido=sin_texto,
    )


async def reembeber_chatbot(
    session: AsyncSession,
    chatbot_id: uuid.UUID,
    embedding_service: Any,
    batch_size: int = LOTE_POR_DEFECTO,
    force: bool = False,
) -> int:
    """Re-embebe los chunks del chatbot con el servicio activo. Devuelve cuántos cambió.

    Idempotente: los que ya están en el modelo activo se saltan, salvo `force`, que existe
    para el caso en que cambió el TEXTO sin cambiar el modelo —RAG.7 y RAG.8 alteraron
    `embedding_text` sin tocar BGE-M3, y ahí la procedencia no distingue nada.
    """
    modelo = str(embedding_service.model_name)
    dimension = int(embedding_service.dimensions)
    tarea = getattr(embedding_service, "embedding_task_type", None)

    procesados = 0
    ultimo_id: uuid.UUID | None = None

    while True:
        consulta = (
            select(HubDocumentChunk)
            .where(HubDocumentChunk.chatbot_id == chatbot_id)
            .where(HubDocumentChunk.embedding_text.isnot(None))
            .order_by(HubDocumentChunk.id)
            .limit(batch_size)
        )
        if not force:
            consulta = consulta.where(_es_de_otro_espacio(modelo, dimension, tarea))
        if ultimo_id is not None:
            consulta = consulta.where(HubDocumentChunk.id > ultimo_id)

        lote = list((await session.execute(consulta)).scalars().all())
        if not lote:
            break

        # Los fragmentos sin texto embebible no se seleccionan: `embedding_text` viene relleno.
        vectores = await _embeber(embedding_service, [cast(str, c.embedding_text) for c in lote])
        for chunk, vector in zip(lote, vectores, strict=True):
            chunk.embedding = vector
            chunk.embedding_model = modelo
            chunk.embedding_dim = dimension
            chunk.embedding_task_type = tarea
        await session.flush()

        procesados += len(lote)
        ultimo_id = lote[-1].id
        logger.info("Re-embebidos %s chunks del chatbot %s", procesados, chatbot_id)

    return procesados


async def _embeber(embedding_service: Any, textos: list[str]) -> list[list[float]]:
    """Re-embeber es indexar: mismo propósito y mismo camino que la ingesta (PIL.1)."""
    from server.app.modules.agents_hub.services.embedding_service import (
        embed_para_indexar,
    )

    return await embed_para_indexar(embedding_service, textos)


async def _chatbots_con_corpus(session: AsyncSession) -> list[uuid.UUID]:
    filas = await session.execute(select(HubDocumentChunk.chatbot_id).distinct())
    return [fila for fila in filas.scalars().all()]


async def _main(args: argparse.Namespace) -> None:
    from server.app.modules.agents_hub.database.connection import (
        create_session_factory,
        get_engine,
    )
    from server.app.modules.agents_hub.services.embedding_resolver import (
        resolve_embedding_service,
    )

    async with create_session_factory(get_engine())() as session:
        objetivos = (
            await _chatbots_con_corpus(session)
            if args.all
            else [uuid.UUID(args.chatbot_id)]
        )
        for chatbot_id in objetivos:
            servicio = await resolve_embedding_service(session, chatbot_id)
            plan = await planificar_reembed(session, chatbot_id, servicio)
            print(plan.describe())
            if args.dry_run:
                continue
            procesados = await reembeber_chatbot(
                session,
                chatbot_id,
                servicio,
                batch_size=args.batch_size,
                force=args.force,
            )
            await session.commit()
            print(f"  -> {procesados} chunks re-embebidos")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Re-embebe el corpus con el servicio de embeddings activo."
    )
    objetivo = parser.add_mutually_exclusive_group(required=True)
    objetivo.add_argument("--chatbot-id", help="UUID del chatbot a re-embeber")
    objetivo.add_argument(
        "--all", action="store_true", help="Todos los chatbots con corpus"
    )
    parser.add_argument("--dry-run", action="store_true", help="Solo informa del plan")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embebe también los que ya están en el modelo activo",
    )
    parser.add_argument("--batch-size", type=int, default=LOTE_POR_DEFECTO)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(_main(args))


if __name__ == "__main__":
    main()
