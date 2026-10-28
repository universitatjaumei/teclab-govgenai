"""Lo que el panel de ingesta lee y escribe del corpus de un chatbot. Deploy: edge (#274).

Vivía en los handlers de `hub_ingestion_router`. Allí se quedan la autorización, la validación de
la subida y los códigos de estado; aquí, las consultas, los borrados y los `commit`.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select

from server.app.core.storage import StorageService
from server.app.modules.agents_hub.database.config_models import HubChatbot
from server.app.modules.agents_hub.database.operational_models import (
    HubDocument,
    HubDocumentChunk,
    HubIngestionJob,
)


async def chatbot_o_404(session, chatbot_id: uuid.UUID) -> HubChatbot:
    chatbot = await session.get(HubChatbot, chatbot_id)
    if chatbot is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found")
    return chatbot


async def trabajos(session, chatbot_id: uuid.UUID) -> list[HubIngestionJob]:
    return list(
        (
            await session.execute(
                select(HubIngestionJob)
                .where(HubIngestionJob.chatbot_id == chatbot_id)
                .order_by(HubIngestionJob.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


async def documentos(session, chatbot_id: uuid.UUID, language: str | None) -> list[HubDocument]:
    consulta = (
        select(HubDocument)
        .where(HubDocument.chatbot_id == chatbot_id)
        .order_by(HubDocument.created_at.desc())
    )
    if language:
        consulta = consulta.where(HubDocument.language == language)
    return list((await session.execute(consulta)).scalars().all())


async def vigencia_pendiente(session, chatbot_id: uuid.UUID) -> tuple[int, list[HubDocument]]:
    """(total del corpus, los que esperan a que alguien valide su vigencia).

    El criterio sale de `vigencia_no_validada` —la misma función que usa la capa de recuperación
    para decidir si advierte—, traducida a SQL para no traerse el corpus entero a memoria. Si esta
    condición y aquella función divergen, la pantalla dirá que faltan N y el asistente advertirá
    por M sin que nadie lo note.
    """
    from server.app.modules.agents_hub.services.retrieval.vigencia import ESTAT_VIGENT

    total = await session.scalar(
        select(func.count()).select_from(HubDocument).where(HubDocument.chatbot_id == chatbot_id)
    )
    pendientes = (
        await session.execute(
            select(HubDocument)
            .where(HubDocument.chatbot_id == chatbot_id)
            .where(
                HubDocument.vigencia_validada_el.is_(None)
                | HubDocument.estat_vigencia.is_distinct_from(ESTAT_VIGENT)
            )
            # Lo que ya tenía fecha de revisión y se pasó va primero: es lo único de la cola con
            # un plazo que alguien fijó. El resto ordena por título para que la lista sea estable
            # entre recargas y se pueda ir tachando.
            .order_by(
                HubDocument.data_revisio_prevista.asc().nullslast(),
                HubDocument.title.asc(),
            )
        )
    ).scalars().all()
    return int(total or 0), list(pendientes)


async def documento_del_chatbot(
    session, chatbot_id: uuid.UUID, document_id: uuid.UUID
) -> HubDocument:
    documento = await session.get(HubDocument, document_id)
    if not documento or documento.chatbot_id != chatbot_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento no encontrado.")
    return documento


async def validar_vigencia(session, documento: HubDocument, validada_por: str) -> HubDocument:
    """Sella la vigencia. **No se valida lo que el estado dice que no está vigente**: 409.

    Un documento derogado está en la cola por su `estat_vigencia`, no por falta de sello, así que
    ponerle la fecha no lo sacaría de ella: el botón parecería roto.

    En `vigencia_validada_per` y **nunca en `revisat_per`**: ese otro campo viene del frontmatter
    del corpus y es la revisión humana del contenido, obligatoria para la normativa. El correo y no
    el identificador interno, porque esta columna la lee una persona.
    """
    from server.app.modules.agents_hub.services.retrieval.vigencia import ESTAT_VIGENT

    if documento.estat_vigencia != ESTAT_VIGENT:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"El documento está marcado como «{documento.estat_vigencia}», así que validar su "
                "vigencia no lo sacaría de la cola. Lo que procede es retirarlo del corpus o "
                "corregir su estado."
            ),
        )
    documento.vigencia_validada_el = datetime.now(timezone.utc)
    documento.vigencia_validada_per = validada_por
    await session.commit()
    return documento


async def copias_en_otros_chatbots(
    session, documento: HubDocument, organizacion_id: uuid.UUID
) -> list[HubDocument]:
    """Copias de la misma norma en los demás chatbots de la organización (DER.2).

    **Se busca por `canonical_url`, no por `content_hash`.** Si una copia ha derivado, su hash es
    distinto y buscar por hash no la encontraría — justo el caso en el que más importa avisar.
    """
    hermanos = list(
        (
            await session.execute(
                select(HubChatbot.id).where(HubChatbot.organizacion_id == organizacion_id)
            )
        )
        .scalars()
        .all()
    )
    return [
        copia
        for copia in (
            await session.execute(
                select(HubDocument)
                .where(HubDocument.canonical_url == documento.canonical_url)
                .where(HubDocument.chatbot_id.in_(hermanos))
            )
        ).scalars().all()
        if copia.chatbot_id != documento.chatbot_id
    ]


async def borrar_documentos(session, documentos_a_borrar: list[HubDocument]) -> None:
    """Cada documento con sus fragmentos, en una transacción."""
    for documento in documentos_a_borrar:
        await session.execute(
            sa_delete(HubDocumentChunk).where(HubDocumentChunk.document_id == documento.id)
        )
        await session.delete(documento)
    await session.commit()


async def trabajos_del_chatbot(session, chatbot_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(HubIngestionJob)
            .where(HubIngestionJob.chatbot_id == chatbot_id)
        )
        or 0
    )


async def encolar(session, trabajo: HubIngestionJob) -> HubIngestionJob:
    session.add(trabajo)
    await session.commit()
    await session.refresh(trabajo)
    return trabajo


async def trabajo_del_chatbot(
    session, chatbot_id: uuid.UUID, job_id: uuid.UUID
) -> HubIngestionJob:
    trabajo = await session.get(HubIngestionJob, job_id)
    if not trabajo or trabajo.chatbot_id != chatbot_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job no encontrado.")
    return trabajo


async def _borrar_fuente(storage: StorageService, trabajo: HubIngestionJob) -> None:
    """El fichero subido, sólo si es una clave de almacenamiento y no una URL."""
    if not trabajo.source_url.startswith(("http://", "https://")):
        try:
            await storage.delete(trabajo.source_url)
        except FileNotFoundError:
            pass


async def borrar_trabajo(session, trabajo: HubIngestionJob, storage: StorageService) -> int:
    """El trabajo, los documentos que dejó y sus fragmentos. Devuelve cuántos documentos."""
    canonica = trabajo.canonical_url or trabajo.source_url
    documentos_del_trabajo = (
        await session.execute(
            select(HubDocument).where(
                HubDocument.chatbot_id == trabajo.chatbot_id,
                HubDocument.canonical_url == canonica,
            )
        )
    ).scalars().all()
    for documento in documentos_del_trabajo:
        await session.execute(
            sa_delete(HubDocumentChunk).where(HubDocumentChunk.document_id == documento.id)
        )
        await session.delete(documento)
    await _borrar_fuente(storage, trabajo)
    await session.delete(trabajo)
    await session.commit()
    return len(documentos_del_trabajo)


async def vaciar(session, chatbot_id: uuid.UUID, storage: StorageService) -> tuple[int, int]:
    """Todos los documentos, fragmentos y trabajos del chatbot. (documentos, trabajos)."""
    await session.execute(sa_delete(HubDocumentChunk).where(HubDocumentChunk.chatbot_id == chatbot_id))

    documentos_del_chatbot = (
        await session.execute(select(HubDocument).where(HubDocument.chatbot_id == chatbot_id))
    ).scalars().all()
    for documento in documentos_del_chatbot:
        await session.delete(documento)

    trabajos_del_chatbot_ = (
        await session.execute(select(HubIngestionJob).where(HubIngestionJob.chatbot_id == chatbot_id))
    ).scalars().all()
    for trabajo in trabajos_del_chatbot_:
        await _borrar_fuente(storage, trabajo)
        await session.delete(trabajo)

    await session.commit()
    return len(documentos_del_chatbot), len(trabajos_del_chatbot_)
