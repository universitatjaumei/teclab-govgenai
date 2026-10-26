"""MdAgentSelectorPipeline — evidencia inicial del modo de selección agéntica.

El pipeline entrega un **índice** como evidencia inicial y delega la selección al
`AgenticLoop`, que lee los documentos que decida a través de los tools.

## Por qué el índice es un punto de extensión (enmienda del Bloque VIS, 2026-07-28)

El índice de **documentos** es provisional y no se cementa. Medido en
`INFORME_MATERIES_I_METADADES_AGENTS.md` §6.1: el catálogo de fichas son ~72k tokens y no
cabe en el system prompt; el índice de las 58 submaterias son 2.307 tokens y sí cabe.
**VIS.2 sustituye el proveedor**, no el pipeline ni el grafo — de ahí `IndexProvider`.

Corolario: el índice lleva título y id, **nunca el markdown completo**. La versión anterior
de este fichero devolvía `markdown_content` de todos los documentos del chatbot, que es
exactamente lo que el modo selector viene a evitar: volcar el corpus entero en el prompt.

Deploy: edge
"""
from __future__ import annotations

import logging
import uuid
from collections import Counter
from typing import Protocol

from sqlalchemy import func, select

from server.app.modules.agents_hub.agent.public_graphs.strategies.retrieval_contract import (
    EvidenceItem,
    RetrievalResult,
)
from server.app.modules.agents_hub.services.retrieval.metadata_filter import MetadataFilter

logger = logging.getLogger(__name__)

INDEX_TITLE_MAX = 300


def _dominant_language(items: list[EvidenceItem]) -> str | None:
    langs = [i.language for i in items if i.language]
    if not langs:
        return None
    return Counter(langs).most_common(1)[0][0]


class IndexProvider(Protocol):
    """Construye el índice que se ofrece al selector como evidencia inicial."""

    async def build_index(
        self, chatbot_id: str, deps, query: str = "", language: str | None = None
    ) -> list[EvidenceItem]: ...


class DocumentIndexProvider:
    """Índice por documento: título + id, sin el cuerpo.

    Provisional: VIS.2 lo sustituye por el índice de submaterias.

    Aplica el `MetadataFilter` de VIS.1 con el mismo defecto cerrado que las tres
    estrategias de recuperación. Un índice sin filtrar sería una fuga aunque el modelo
    no llegara a leer el documento: el título ya dice que existe.
    """

    def __init__(self, metadata_filter: MetadataFilter | None = None) -> None:
        self._filter = metadata_filter if metadata_filter is not None else MetadataFilter()

    async def build_index(
        self, chatbot_id: str, deps, query: str = "", language: str | None = None
    ) -> list[EvidenceItem]:
        from dataclasses import replace

        from server.app.modules.agents_hub.database.operational_models import (
            HubDocument,
            HubDocumentChunk,
        )

        cid = uuid.UUID(chatbot_id) if isinstance(chatbot_id, str) else chatbot_id
        # ACT.3: el indice ensena UNA ficha por norma, la de la lengua de la pregunta. Si
        # ensenara las dos, el selector tendria que elegir entre dos entradas identicas y
        # podria leer y citar las dos.
        filtro = replace(self._filter, query_language=language) if language else self._filter
        stmt = (
            select(HubDocument)
            .where(HubDocument.chatbot_id == cid)
            .where(*filtro.document_conditions())
            .order_by(HubDocument.title)
        )
        result = await deps.session.execute(stmt)
        documentos = list(result.scalars().all())

        # HIB.E — la nota de cada entrada es la mejor similitud coseno entre la consulta y los
        # fragmentos de ESE documento.
        #
        # Antes era `1.0` fija, y como el quality gate del CoreGraph toma el maximo de
        # `merged_items` —que en este modo es este indice—, el agentico **contestaba siempre**
        # con cualquier umbral. Su 7 de 7 frente al 6 de 7 del RAG no media recuperacion: media
        # la ausencia de filtro.
        #
        # Contra los fragmentos y no contra el documento entero por dos razones: el documento
        # entero no tiene vector —el agentico lee `markdown_content`— y un articulo que
        # contesta bien dentro de una ley de 279.425 tokens se diluiria en cualquier promedio.
        #
        # Y en la MISMA escala que la rama vectorial, que es lo que permite que un umbral de
        # 0,65 signifique lo mismo en los dos asistentes de Gerencia. Sin eso, la comparacion
        # entre ellos —que es el objeto de toda esta rama— no querria decir nada.
        notas: dict[uuid.UUID, float] = {}
        self.scores_medidos = False
        embedder = getattr(deps, "embedder", None)
        if query and embedder is not None and documentos:
            try:
                vector = await embedder.embed(query)
                distancia = HubDocumentChunk.embedding.cosine_distance(vector)
                q = (
                    select(
                        HubDocumentChunk.document_id,
                        func.min(distancia).label("d"),
                    )
                    .where(
                        HubDocumentChunk.document_id.in_([d.id for d in documentos])
                    )
                    .group_by(HubDocumentChunk.document_id)
                )
                for doc_id, d in (await deps.session.execute(q)).all():
                    notas[doc_id] = 1.0 - float(d)
                self.scores_medidos = True
            except Exception:  # noqa: BLE001
                # Sin embedder o con la consulta caida, el indice sale plano y se DICE. Una
                # nota sin medir indistinguible de una medida es lo que sostuvo durante un
                # informe entero la conclusion de que el agentico iba mejor que el RAG.
                logger.warning("no se pudieron puntuar las entradas del indice", exc_info=False)
                notas = {}
                self.scores_medidos = False

        return [
            EvidenceItem(
                source_id=str(d.id),
                content=f"{(d.title or '(sin título)')[:INDEX_TITLE_MAX]} (id: {d.id})",
                source_url=d.canonical_url,
                title=d.title,
                language=d.language,
                score=notas.get(d.id, 1.0),
                metadata={"index_entry": True, "score_medido": d.id in notas},
            )
            for d in documentos
        ]


class MdAgentSelectorPipeline:
    """Devuelve el índice del proveedor inyectado; la selección la hace el AgenticLoop."""

    def __init__(self, index_provider: IndexProvider | None = None) -> None:
        self._index_provider = (
            index_provider if index_provider is not None else DocumentIndexProvider()
        )

    async def run(
        self,
        query: str,
        chatbot_id: str,
        cfg,  # noqa: ARG002 — la firma la fija el protocolo del pipeline
        deps,
        language: str | None = None,
    ) -> RetrievalResult:
        items = await self._index_provider.build_index(
            chatbot_id, deps, query=query, language=language
        )
        return RetrievalResult(
            items=items,
            debug={
                "pipeline_mode": "MD_AGENT_SELECTOR",
                "index_entries": len(items),
                "index_provider": type(self._index_provider).__name__,
                # Si el indice salio plano hay que poder distinguir «no habia con que medir»
                # de «se midio y salio plano». Sin la marca, la traza de HIB.I no lo dice.
                "index_scores_medidos": getattr(
                    self._index_provider, "scores_medidos", None
                ),
            },
            context_source_language=_dominant_language(items),
        )
