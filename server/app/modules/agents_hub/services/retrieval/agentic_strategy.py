"""AgenticRetrievalStrategy -- el LLM elige que documentos leer.

VIS.1: el indice que ve el modelo esta filtrado por MetadataFilter. Listar un documento
que el actor no puede recuperar seria una fuga aunque nunca llegara a leerse: el titulo
ya dice que existe.

VIS.2 (Nivel 1): el indice se pide por SUBMATERIA y devuelve FICHAS, no contenido. Si la
seleccion del modelo no encaja con nada, el indice retrocede en escalones —submateria ->
ambito -> catalogo global— y cada escalon queda anotado en `last_index_level`, que la
evidencia arrastra para poder medir cuantas consultas necesitan ensanchar el tema.

El retroceso ensancha el TEMA, nunca el PERMISO: `nivell_acces`, `us_assistents`,
La regla de lengua (ACT.3) y la exclusion de superseded se aplican en los tres escalones.
"""

import uuid
from dataclasses import replace

from langchain_core.tools import tool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.agent.tools.list_documents import list_documents
from server.app.modules.agents_hub.agent.tools.read_document import read_document
from server.app.modules.agents_hub.agent.tools.search_knowledge import search_knowledge
from server.app.modules.agents_hub.database.operational_models import HubDocument
from server.app.modules.agents_hub.services.retrieval.citations import url_de_cita
from server.app.modules.agents_hub.services.retrieval.metadata_filter import MetadataFilter
from server.app.modules.agents_hub.services.retrieval.types import RetrievalContext
from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
    con_lengua as _con_lengua,
)
from server.app.modules.agents_hub.services.retrieval.vigencia import marca_de_vigencia

# Escalones del indice, de mas estrecho a mas ancho.
INDEX_LEVEL_SUBMATERIES = "submateries"
INDEX_LEVEL_AMBIT = "ambit"
INDEX_LEVEL_GLOBAL = "global"


class AgenticRetrievalStrategy:
    mode = "MD_AGENT_SELECTOR"

    def __init__(
        self,
        session: AsyncSession,
        metadata_filter: MetadataFilter | None = None,
    ):
        self._session = session
        self._filter = metadata_filter if metadata_filter is not None else MetadataFilter()
        self.last_index_level: str | None = None

    async def list_index(
        self,
        chatbot_id: uuid.UUID,
        language: str | None,
        submateries: list[str] | None = None,
    ) -> list[dict]:
        """Fichas de los documentos del tema pedido, con retroceso escalonado."""
        escalones: list[tuple[str, MetadataFilter]] = []
        if submateries:
            escalones.append((
                INDEX_LEVEL_SUBMATERIES,
                replace(self._filter, submateries=tuple(submateries)),
            ))
        if self._filter.ambits:
            escalones.append((
                INDEX_LEVEL_AMBIT,
                replace(self._filter, submateries=()),
            ))
        escalones.append((
            INDEX_LEVEL_GLOBAL,
            replace(self._filter, submateries=(), ambits=()),
        ))

        fichas: list[dict] = []
        for nivel, filtro in escalones:
            self.last_index_level = nivel
            fichas = await self._fichas(chatbot_id, language, filtro)
            if fichas:
                break
        return fichas

    async def _fichas(
        self,
        chatbot_id: uuid.UUID,
        language: str | None,
        filtro: MetadataFilter,
    ) -> list[dict]:
        stmt = select(HubDocument).where(HubDocument.chatbot_id == chatbot_id)
        # ACT.3: el indice ensena UNA ficha por norma, la de la lengua de la pregunta. Antes
        # era un filtro duro por lengua, que dejaba fuera las normas sin traducir.
        stmt = stmt.where(*_con_lengua(filtro, language).document_conditions())
        stmt = stmt.order_by(HubDocument.title)
        res = await self._session.execute(stmt)
        # La ficha lleva de qué va la norma y con qué rango manda; el cuerpo se pide
        # despues con read_document. Devolver markdown aqui es volcar el corpus al prompt,
        # que es exactamente lo que el modo selector viene a evitar.
        return [
            {
                "id": str(d.id),
                "title": d.title,
                "url": url_de_cita(d, None),
                "language": d.language,
                "token_count": d.token_count,
                "resum_router": (d.doc_metadata or {}).get("resum_router"),
                "rang": (d.doc_metadata or {}).get("rang"),
                "submateries": list(d.submateries or []),
            }
            for d in res.scalars().all()
        ]

    async def read(self, document_id: uuid.UUID) -> dict | None:
        """Documento completo por id. **Sin filtro a proposito** (VIS.3).

        Es la puerta por la que se leen las dos cosas que la recuperacion excluye: la
        version en la otra lengua, cuando el usuario pide la cita literal, y una norma
        derogada, cuando la pregunta es justo qué decia antes. Ambas son consultas
        legitimas y ambas exigen el id explicito, que solo se obtiene de un indice ya
        filtrado o de `variant_id`.
        """
        doc = await self._session.get(HubDocument, document_id)
        if not doc:
            return None
        return {
            "title": doc.title,
            # #334 — la URL que cita el vectorial: la página del sitio, no el PDF.
            "url": url_de_cita(doc, None),
            "markdown_content": doc.markdown_content,
            "language": doc.language,
            # Lo que cuesta leerlo entero. El loop lo necesita para no volcar en la
            # conversación una norma que no cabe (la LCSP son 279.425 tokens).
            "token_count": doc.token_count,
            "estat_vigencia": doc.estat_vigencia,
            # `versio_idiomatica_de` declara donde esta la hermana; sin esto, pedir la cita
            # la otra lengua exigiria una busqueda por url, que es adivinar.
            "variant_id": await self._variant_id(doc),
            **marca_de_vigencia(doc),
        }

    async def _variant_id(self, doc: HubDocument) -> str | None:
        """Id de la version en la otra lengua, en cualquiera de los dos sentidos."""
        if doc.versio_idiomatica_de is not None:
            return str(doc.versio_idiomatica_de)
        res = await self._session.execute(
            select(HubDocument.id).where(HubDocument.versio_idiomatica_de == doc.id).limit(1)
        )
        hermana = res.scalars().first()
        return str(hermana) if hermana else None

    async def get_context(
        self,
        query: str,
        chatbot_id: uuid.UUID,
        language: str | None = None,
    ) -> RetrievalContext:
        return RetrievalContext(sources=[], mode=self.mode, total_tokens=0)

    def get_agent_tools(self) -> list:
        """Lo que el modelo puede llamar, ya envuelto como tool de LangChain.

        `tool()` es lo que filtra los argumentos inyectados del esquema; pasar las funciones
        desnudas hacía morir a `bind_tools` con `SchemaError` sobre los Protocol.

        `search_knowledge` está aquí porque la normativa **externa** no cabe: las 22 del
        corpus de Gerencia suman 1.745.337 tokens y la Ley de Contratos sola son 279.425.
        Sin búsqueda por fragmentos, la única forma de consultarla es cargarla entera.
        """
        return [tool(list_documents), tool(read_document), tool(search_knowledge)]
