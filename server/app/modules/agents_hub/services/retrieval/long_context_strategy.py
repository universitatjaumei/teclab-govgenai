"""LongContextRetrievalStrategy -- empaqueta el corpus accesible en el contexto del LLM.

VIS.1: «el corpus» dejo de significar «todos los documentos del chatbot». La estrategia
aplica el MetadataFilter igual que el retriever vectorial; sin filtro explicito rige el
defecto cerrado (publico, canonico, sin superseded, sin us_assistents='no').
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.config_models import HubChatbot
from server.app.modules.agents_hub.database.operational_models import HubDocument
from server.app.modules.agents_hub.services.retrieval.citations import url_de_cita
from server.app.modules.agents_hub.services.retrieval.metadata_filter import MetadataFilter
from server.app.modules.agents_hub.services.retrieval.types import RetrievalContext, Source
from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
    con_lengua as _con_lengua,
)
from server.app.modules.agents_hub.services.retrieval.vigencia import marca_de_vigencia


LONG_CONTEXT_TOKEN_LIMIT = 128_000
PROMPT_CACHE_BLOCK_MIN_TOKENS = 32_000


class LongContextRetrievalStrategy:
    mode = "MD_LONG_CONTEXT"

    def __init__(
        self,
        session: AsyncSession,
        token_limit: int = LONG_CONTEXT_TOKEN_LIMIT,
        metadata_filter: MetadataFilter | None = None,
    ):
        self._session = session
        self._token_limit = token_limit
        self._filter = metadata_filter if metadata_filter is not None else MetadataFilter()

    async def get_context(
        self,
        query: str,
        chatbot_id: uuid.UUID,
        language: str | None = None,
    ) -> RetrievalContext:
        chatbot = await self._session.get(HubChatbot, chatbot_id)
        use_prompt_caching = bool(getattr(chatbot, "use_prompt_caching", False))
        cache_ttl = int(getattr(chatbot, "cache_ttl", 3600) or 3600)

        stmt = select(HubDocument).where(HubDocument.chatbot_id == chatbot_id)
        # ACT.3: la lengua entra por la REGLA de la hermana, no como filtro duro. Un
        # `language == 'es'` haria desaparecer las 195 normas que solo existen en valenciano,
        # que es la trampa documentada en `graph_factory.py`.
        stmt = stmt.where(*_con_lengua(self._filter, language).document_conditions())
        stmt = stmt.order_by(HubDocument.created_at)
        result = await self._session.execute(stmt)
        documents = list(result.scalars().all())

        # VIS.2: recortar por presupuesto en vez de lanzar. La version anterior lanzaba
        # ValueError cuando el corpus pasaba del limite, y en produccion eso no es un aviso
        # sino una caida: el usuario recibe un error en vez de una respuesta parcial y
        # honesta. Se conserva el orden de creacion, que es el que el chatbot declara.
        cabidos: list = []
        acumulado = 0
        for d in documents:
            coste = int(d.token_count or 0)
            if cabidos and acumulado + coste > self._token_limit:
                continue
            if not cabidos and coste > self._token_limit:
                # Ni el primero cabe: se inyecta igualmente, porque un contexto vacio no
                # produce ninguna respuesta y uno recortado sí. Queda marcado como truncado.
                cabidos.append(d)
                acumulado += coste
                break
            cabidos.append(d)
            acumulado += coste

        descartados = len(documents) - len(cabidos)
        total = acumulado

        sources = []
        for d in cabidos:
            is_cache_block = use_prompt_caching and int(d.token_count or 0) > PROMPT_CACHE_BLOCK_MIN_TOKENS
            excerpt = d.markdown_content
            if is_cache_block:
                excerpt = f"[CACHE_BLOCK ttl={cache_ttl}s]\n{excerpt}"

            sources.append(
                Source(
                    document_id=d.id,
                    title=d.title,
                    # #334 — la misma URL que cita el vectorial: la página del sitio, no el
                    # PDF, y nada si `canonical_url` es el nombre de un fichero.
                    url=url_de_cita(d, None) or "",
                    excerpt=excerpt,
                    score=1.0,
                    metadata={
                        "language": d.language,
                        "cacheable": True,
                        "cache_block": is_cache_block,
                        "cache_ttl": cache_ttl if is_cache_block else None,
                        **marca_de_vigencia(d),
                    },
                )
            )
        return RetrievalContext(
            sources=sources,
            mode=self.mode,
            total_tokens=total,
            truncated=descartados > 0,
            discarded_documents=descartados,
        )

    def get_agent_tools(self) -> list:
        return []
