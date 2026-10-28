"""`DatosDelCliente` sobre la base local. Deploy: edge (#298); vive en `api/` porque abarca el
corpus y la redacción, y un módulo no importa de otro (AIS.3).

Es lo que contesta el edge cuando el cloud pregunta por el corpus de un chatbot o por los datos de
una organización. Hoy viven en la misma base y en el mismo proceso, así que se contesta con la
**sesión de la petición**: la purga queda en la transacción del borrado, como exige PIL.2.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.core.datos_del_cliente import CorpusRetirado
from server.app.core.storage import StorageService
from server.app.modules.agents_hub.database.operational_models import (
    HubAgenteUnidad,
    HubDocument,
    HubLexiconPair,
    HubWebSite,
)
from server.app.modules.agents_hub.services.corpus_purge import (
    borrar_fuentes_del_chatbot,
    purgar_corpus_del_chatbot,
)
from server.app.modules.redaccion.database.models import (
    HubFuncion,
    HubFuncionArtefacto,
    HubReportTemplate,
    HubWorkspace,
)

#: #252 — lo que una organización tiene sin clave foránea y que, mientras exista, impide borrarla.
#: Borrarlo en cascada sería irreversible y alcanzaría ficheros del almacenamiento; para retirar una
#: organización con actividad está desactivarla (decisión del usuario, 2026-10-10). **Fuera, a
#: propósito, la traza**: el registro de actividad y los manifiestos cuentan lo que pasó, como las
#: interacciones, y no impiden nada. Los chatbots tampoco: cascadean y su corpus se purga.
LO_QUE_BLOQUEA_EL_BORRADO = (
    ("sitios", HubWebSite),
    ("informes", HubWorkspace),
    ("plantillas", HubReportTemplate),
    ("funciones", HubFuncion),
    ("artefactos", HubFuncionArtefacto),
    ("agentes", HubAgenteUnidad),
    ("pares_lexicos", HubLexiconPair),
)


class DatosDelClienteLocal:
    def __init__(self, session: AsyncSession, storage: StorageService) -> None:
        self._session = session
        self._storage = storage

    async def tokens_del_corpus(self, chatbot_id: uuid.UUID) -> int:
        fila = await self._session.execute(
            select(func.coalesce(func.sum(HubDocument.token_count), 0)).where(
                HubDocument.chatbot_id == chatbot_id
            )
        )
        return int(fila.scalar_one() or 0)

    async def lo_que_impide_borrar(self, organizacion_id: uuid.UUID) -> dict[str, int]:
        pendiente: dict[str, int] = {}
        for nombre, modelo in LO_QUE_BLOQUEA_EL_BORRADO:
            cuantos = (
                await self._session.execute(
                    select(func.count()).select_from(modelo).where(
                        modelo.organizacion_id == organizacion_id
                    )
                )
            ).scalar_one()
            if cuantos:
                pendiente[nombre] = int(cuantos)
        return pendiente

    async def purgar_corpus(self, chatbot_ids: Sequence[uuid.UUID]) -> CorpusRetirado:
        documentos = fragmentos = trabajos = 0
        for chatbot_id in chatbot_ids:
            retirado = await purgar_corpus_del_chatbot(self._session, chatbot_id)
            documentos += retirado.documentos
            fragmentos += retirado.fragmentos
            trabajos += retirado.trabajos
        return CorpusRetirado(documentos=documentos, fragmentos=fragmentos, trabajos=trabajos)

    async def borrar_fuentes(self, chatbot_ids: Sequence[uuid.UUID]) -> None:
        for chatbot_id in chatbot_ids:
            await borrar_fuentes_del_chatbot(self._storage, chatbot_id)
