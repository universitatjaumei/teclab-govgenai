"""Retirada del corpus de un chatbot (PIL.2). Deploy: edge.

`hub_documents.chatbot_id` **no tiene clave ajena**, y no es un descuido: la cayó el split
entre `HubConfigBase` (configuración, se sincroniza cloud→edge) y `HubOperationalBase` (datos
del cliente, viven sólo en el edge), y la frontera de CLAUDE.md pide que no vuelva. Postgres,
por tanto, no puede cascadear de un chatbot a su corpus.

Lo que sí cascadea es `hub_document_chunks → hub_documents` (`fk_chunk_document_id`, ING.0.2),
así que basta con borrar los documentos: los fragmentos —y con ellos los embeddings, que es
lo que ocupa— se van detrás.

**Y sus trabajos de ingesta** (#253): `hub_ingestion_jobs.chatbot_id` tampoco tiene clave ajena. Las
filas se van aquí, en la transacción; sus `.md` fuente, que viven en `ingestion/{chatbot}/`, los borra
`borrar_fuentes_del_chatbot` **después** del commit, porque el almacenamiento no es transaccional.

**Qué NO se borra: las interacciones.** Son el registro de lo que el asistente contestó, no
su corpus, y desde REV.1 son además material de revisión. Borrar un chatbot no reescribe la
historia de lo que dijo.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.core.storage import StorageService
from server.app.modules.agents_hub.database.config_models import HubChatbot
from server.app.modules.agents_hub.database.operational_models import (
    HubDocument,
    HubDocumentChunk,
    HubIngestionJob,
)


@dataclass(frozen=True)
class CorpusRetirado:
    """Lo que se llevó por delante, para poder decirlo en voz alta."""

    documentos: int
    fragmentos: int
    trabajos: int = 0


async def purgar_corpus_del_chatbot(
    session: AsyncSession, chatbot_id: uuid.UUID
) -> CorpusRetirado:
    """Retira documentos y fragmentos del chatbot. **No hace commit.**

    El commit es de quien llama, y eso es deliberado: la purga y el borrado del chatbot
    tienen que ser la misma transacción. Media limpieza —el chatbot borrado y su corpus
    dentro, o al revés— es peor que ninguna, porque deja de haber forma de encontrar lo que
    quedó suelto.
    """
    documentos = int(
        (
            await session.execute(
                select(func.count(HubDocument.id)).where(
                    HubDocument.chatbot_id == chatbot_id
                )
            )
        ).scalar_one()
        or 0
    )
    fragmentos = int(
        (
            await session.execute(
                select(func.count(HubDocumentChunk.id)).where(
                    HubDocumentChunk.chatbot_id == chatbot_id
                )
            )
        ).scalar_one()
        or 0
    )

    # Los fragmentos se borran explícitamente ADEMÁS de por la cascada: los adjuntos
    # temporales de una consulta (`is_temporary`) cuelgan del chatbot sin documento, así que
    # la cascada por sí sola los dejaría atrás.
    await session.execute(
        delete(HubDocumentChunk).where(HubDocumentChunk.chatbot_id == chatbot_id)
    )
    await session.execute(delete(HubDocument).where(HubDocument.chatbot_id == chatbot_id))
    trabajos = (
        await session.execute(
            delete(HubIngestionJob).where(HubIngestionJob.chatbot_id == chatbot_id)
        )
    ).rowcount or 0

    return CorpusRetirado(documentos=documentos, fragmentos=fragmentos, trabajos=trabajos)


_log = logging.getLogger(__name__)


async def borrar_fuentes_del_chatbot(storage: StorageService, chatbot_id: uuid.UUID) -> None:
    """Los `.md` que guardaron sus trabajos de ingesta (#253). **Después del commit** del borrado.

    #258 — si el almacenamiento falla, el chatbot ya está borrado: se registra y no se lanza, porque
    un 500 diría que no se hizo algo que sí se hizo. Lo que quede lo recoge
    `barrer_fuentes_huerfanas`.
    """
    try:
        await storage.delete_prefix(f"ingestion/{chatbot_id}/")
    except Exception:  # noqa: BLE001 — se registra; el barrido lo recoge
        _log.warning(
            "No se pudo borrar las fuentes de ingesta del chatbot %s; lo recogerá el barrido",
            chatbot_id,
            exc_info=True,
        )


async def barrer_fuentes_huerfanas(session: AsyncSession, storage: StorageService) -> int:
    """Borra `ingestion/{chatbot}/` de los chatbots que ya no existen (#258). Devuelve cuántos.

    Es lo que dejó un borrado de fuentes que falló después del commit. Lo que no es un uuid no lo
    toca: no sabe de quién es.
    """
    candidatos: dict[uuid.UUID, str] = {}
    for nombre in await storage.listar("ingestion/"):
        try:
            candidatos[uuid.UUID(nombre)] = nombre
        except ValueError:
            continue
    if not candidatos:
        return 0
    vivos = set(
        (
            await session.execute(select(HubChatbot.id).where(HubChatbot.id.in_(list(candidatos))))
        ).scalars()
    )
    huerfanos = [nombre for chatbot_id, nombre in candidatos.items() if chatbot_id not in vivos]
    for nombre in huerfanos:
        await storage.delete_prefix(f"ingestion/{nombre}/")
    if huerfanos:
        _log.info("Fuentes de ingesta huérfanas borradas: %d chatbots", len(huerfanos))
    return len(huerfanos)
