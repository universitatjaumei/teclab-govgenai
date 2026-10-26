"""VectorRetrievalStrategy -- envuelve HybridRetriever y agrupa por documento."""

import logging
import uuid
from collections import defaultdict
from dataclasses import replace
from time import perf_counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.modules.agents_hub.database.operational_models import HubDocument
from server.app.modules.agents_hub.services.reranker import pool_size
from server.app.modules.agents_hub.services.retrieval.citations import (
    url_de_cita,
    with_anchor,
)
from server.app.modules.agents_hub.services.retrieval.metadata_filter import MetadataFilter
from server.app.modules.agents_hub.services.retrieval.types import RetrievalContext, Source
from server.app.modules.agents_hub.services.retrieval.metadata_filter import (
    con_lengua as _con_lengua,
)
from server.app.modules.agents_hub.services.retrieval.vigencia import (
    hidratar_avisos_de_vigencia,
    marca_de_vigencia,
)
from server.app.modules.agents_hub.services.retriever import RRF_K, HybridRetriever

logger = logging.getLogger(__name__)

# Techo teorico de la fusion RRF (retriever.py): un fragmento que sale primero en las dos
# ramas suma vector_weight/(k+1) + (1-vector_weight)/(k+1) = 1/(k+1). Sin reranker, el
# quality gate del CoreGraph compara `EvidenceItem.score` contra `quality_threshold` en
# escala [0,1] (ver los mocks de score=0.9 en test_core_graph.py) -- sin dividir por este
# techo, ni la mejor coincidencia posible (~0.016) se acerca al umbral por defecto (0.6), y
# el gate cae a fallback siempre, por buena que sea la recuperacion real.
RRF_MAX_SCORE = 1.0 / (RRF_K + 1)


def documento_del_fragmento(fragmento: Any) -> uuid.UUID | None:
    """De que documento es este fragmento: la COLUMNA primero, el metadato como repliegue.

    **El fallo que esto hace imposible.** El `document_id` vive en dos sitios: la columna, que
    la base sostiene con una clave ajena, y `chunk_metadata`, que es una copia denormalizada
    escrita al trocear. La agrupacion leia el metadato, y el 2026-08-28 se encontro que el
    asistente agentico de Gerencia tenia **14.198 de sus 14.208 fragmentos** con ese metadato
    apuntando a documentos del chatbot **RAG**: los fragmentos eran suyos —la columna
    `chatbot_id` estaba bien y la busqueda los filtraba— pero al agrupar se cargaban las filas
    del hermano y **la cita salia con su titulo**, sin ningun error.

    Cuando dos copias del mismo dato pueden discrepar, se lee la que no se puede corromper sin
    que la base se queje.

    El metadato se conserva como repliegue por los fragmentos legados, creados cuando la columna
    no existia. Ese es el motivo por el que la agrupacion lo miraba: era el unico que habia, y
    siguio mirandolo despues.
    """
    columna = getattr(fragmento, "document_id", None)
    if columna:
        return columna if isinstance(columna, uuid.UUID) else uuid.UUID(str(columna))
    crudo = (getattr(fragmento, "metadata", None) or {}).get("document_id")
    if not crudo:
        return None
    try:
        return uuid.UUID(str(crudo))
    except (ValueError, AttributeError, TypeError):
        # Un metadato ilegible no puede agrupar: mejor un documento sin identificar —que la
        # estrategia ya sabe tratar— que una excepcion en el camino de la respuesta.
        return None


class VectorRetrievalStrategy:
    mode = "RAG"

    def __init__(
        self,
        session: AsyncSession,
        embedding_service,
        top_k: int = 8,
        metadata_filter: MetadataFilter | None = None,
        min_score: float = 0.0,
        reranker: Any = None,
        candidate_k: int | None = None,
        inject_whole_document: bool = False,
    ):
        self._session = session
        self._embedding = embedding_service
        self._retriever = HybridRetriever(session)
        self._top_k = top_k
        self._filter = metadata_filter if metadata_filter is not None else MetadataFilter()
        self._min_score = min_score
        # RAG.6a: None = sin reranking. Lo inyecta el pipeline solo si cfg.reranker_enabled,
        # así que la estrategia no tiene que conocer el flag.
        self._reranker = reranker
        # HIB.J: cuántos FRAGMENTOS se le piden al híbrido, frente a `top_k`, que son los
        # DOCUMENTOS que acaban llegando al modelo. Antes el pool valía
        # `pool_size(top_k) if reranker else top_k`, así que apagar el reranker lo encogía
        # de 30 a 3 —dos cambios en una línea—. Medido sobre el lote: 19 de 25 consultas
        # recibieron menos documentos que `top_k`, y 6 uno solo.
        self._candidate_k = candidate_k if candidate_k is not None else pool_size(top_k)
        # HIB.T: qué texto se le entrega al modelo por cada documento elegido — el artículo
        # (el padre del fragmento) o la norma ENTERA.
        #
        # No es una estrategia aparte a propósito. El experimento de granularidad midió que
        # cinco normas enteras seleccionadas por este mismo top-k eran la única celda que ganaba
        # a Gemini de forma significativa (7 a 0, p=0,016), pero se midió con una llamada directa
        # al modelo y por eso salió con **0 enlaces de 25**: sin contrato de citas, sin ancla y
        # sin aviso de vigencia. Un mando aquí las hereda las cuatro; una estrategia nueva las
        # habría vuelto a dejar fuera.
        #
        # Y el modo `MD_LONG_CONTEXT` que ya existía no sirve para esto: selecciona por fecha de
        # creación hasta llenar el presupuesto e **ignora la consulta**.
        self.inject_whole_document = bool(inject_whole_document)

    def _texto_de_evidencia(self, best: Any, doc: Any) -> str:
        """El texto que se le entrega al modelo por este documento.

        Con `inject_whole_document` la evidencia es la norma completa; sin él, el artículo —que
        es lo que RAG.8 (small-to-big) buscaba: se encuentra con el hijo, más específico, y se
        responde con la sección entera, que trae el contexto que al hijo le falta.

        Los repliegues no son defensivos, son los tres casos reales: un fragmento temporal o de
        legado **no tiene documento**, un documento puede no tener `markdown_content`, y un
        fragmento sin padre existe desde que HIB.L puso techo. Sin ellos el `excerpt` saldría
        vacío y la respuesta se quedaría sin fundamento **sin dar ningún error**, que es el modo
        de fallo que este bloque lleva cazando.
        """
        if self.inject_whole_document and doc is not None:
            entero = getattr(doc, "markdown_content", None)
            if entero:
                return entero
        return best.parent_content or best.content

    async def get_context(
        self,
        query: str,
        chatbot_id: uuid.UUID,
        language: str | None = None,
    ) -> RetrievalContext:
        query_embedding = await self._embedding.embed(query)
        # HIB.J: el pool ya no depende de si hay reranker. Se pide siempre `candidate_k`
        # fragmentos, RRF los ordena, y el reranker —si está— los reordena. La razón de
        # RAG.6a sigue valiendo (pedirle `top_k` a un reranker es pedirle que reordene lo ya
        # elegido) y ahora vale también sin él: con troceado fino, `top_k` fragmentos pueden
        # ser un solo documento.
        candidatos = self._candidate_k
        results = await self._retriever.hybrid_search(
            query=query,
            query_embedding=query_embedding,
            chatbot_id=chatbot_id,
            top_k=candidatos,
            language=None,
            # El filtro incluye la exclusión de páginas superseded (9Q.6), el nivel de acceso
            # del actor (VIS.1) y, desde ACT.3, la regla de lengua: una sola versión por norma,
            # la de quien pregunta. El defecto es cerrado.
            #
            # `language=None` a propósito: el parámetro del retriever es un filtro DURO sobre la
            # lengua del fragmento y con él desaparecerían las 195 normas que sólo existen en
            # valenciano. Lo que hace falta es la regla de la hermana, y va en el filtro.
            metadata_filter=_con_lengua(self._filter, language),
            min_score=self._min_score,
        )
        if not results:
            return RetrievalContext(sources=[], mode=self.mode, total_tokens=0)

        if self._reranker is not None:
            results = await self._aplicar_reranker(query, results)

        # HIB.U: se agrupa por la COLUMNA `document_id`, con el metadato solo como repliegue
        # para los fragmentos legados. Ver `documento_del_fragmento`.
        by_doc: dict[uuid.UUID | None, list] = defaultdict(list)
        for r in results:
            by_doc[documento_del_fragmento(r)].append(r)

        # Bulk-load documents
        doc_ids = [d for d in by_doc.keys() if d is not None]
        docs_map: dict[uuid.UUID, HubDocument] = {}
        if doc_ids:
            stmt = select(HubDocument).where(HubDocument.id.in_(doc_ids))
            res = await self._session.execute(stmt)
            docs_map = {d.id: d for d in res.scalars().all()}

        sources: list[Source] = []
        total_tokens = 0
        for doc_id, chunks in by_doc.items():
            best = max(chunks, key=lambda c: c.score)
            doc = docs_map.get(doc_id) if doc_id else None
            title = doc.title if doc else best.source_url.rsplit("/", 1)[-1]
            base_url = doc.canonical_url if doc else best.source_url
            # La cita apunta al artículo del que sale la evidencia, no al documento
            # entero: el ancla viene del chunk mejor puntuado (ING.0.4).
            #
            # PUB.3: si hay sitio publicado, la cita va a su página —que tiene anclas— en vez
            # de al PDF, que se abre por la primera hoja. Sin sitio configurado, lo de antes.
            url = url_de_cita(doc, best.metadata) if doc else with_anchor(base_url, best.metadata)
            # RAG.8 (small-to-big): si el fragmento tiene padre, la evidencia es el padre.
            # Se busca con el hijo —vector más específico, se encuentra mejor— y se responde
            # con la sección entera, que trae el contexto que al hijo le falta.
            #
            # La deduplicación de hijos del mismo padre sale gratis de agrupar por documento,
            # que ya se hacía: es un superconjunto. Y se mantiene así a propósito, porque
            # emitir una entrada por padre duplicaría documentos en el `sources` del evento
            # SSE `done`, contrato que RAG.2 fijó por snapshot.
            excerpt = self._texto_de_evidencia(best, doc)
            # PIL.3: el aviso de que este artículo está DESPLAZADO por una norma posterior.
            #
            # El corpus lo escribe dentro del texto del artículo, pero un artículo se parte
            # en 3-6 fragmentos y la nota cae físicamente en uno: 83 de 86 unidades
            # desplazadas tienen trozos sin ella. Se hidrata aquí, desde `desplacat_per` del
            # documento, que lo declara POR ANCLA — así no depende de dónde cayó el texto.
            #
            # Va delante del contenido y es texto de la evidencia, no una instrucción al
            # modelo: CRITERIS §1.4 pide resolver antes del modelo lo que se pueda resolver.
            excerpt = hidratar_avisos_de_vigencia(excerpt, doc, best.metadata)
            # HIB.J — la nota que llega al quality gate es una MAGNITUD DE RELEVANCIA, no
            # una posición.
            #
            # Con reranker sigue siendo la del reranker, que ya está en [0,1]. Sin él era
            # la fusión RRF normalizada por su techo teórico, y eso resultó ser una
            # **constante igual a `vector_weight`**: medido, 0,7 en las 25 consultas del
            # lote. El techo teórico (rango 1 en las dos ramas) exige que el mismo fragmento
            # salga por vector y por léxico, y con troceado fino no ocurre; el ganador es
            # siempre el rango 1 vectorial, que aporta `vector_weight · 1/(k+1)`.
            #
            # Una puerta que lee una constante no es una puerta: con umbral ≤ 0,7 pasaba
            # todo y con umbral > 0,7 no pasaba nada. Se sustituye por la similitud coseno
            # del mejor fragmento del documento, que es lo que `Source.score` dice ser
            # («relevancia [0, 1]») y lo que el contrato de `hybrid_search` ya pedía para
            # este consumidor. Efecto colateral bienvenido: con y sin reranker el umbral
            # pasa a significar lo mismo, y desaparece la asimetría que HIB.A tuvo que
            # declarar como trampa.
            #
            # Sin ninguna relevancia —fragmentos sólo de la rama léxica— la nota es 0,0 y
            # decide la puerta: heredar una constante que la deja pasar es el defecto que
            # este prompt quita.
            if self._reranker is not None:
                score = best.score
            else:
                relevancias = [
                    c.relevance for c in chunks if c.relevance is not None
                ]
                score = max(relevancias) if relevancias else 0.0
            sources.append(Source(
                document_id=doc.id if doc else uuid.uuid4(),
                title=title,
                url=url or "",
                excerpt=excerpt,
                score=score,
                metadata={
                    "chunks_matched": len(chunks),
                    "ancora": best.metadata.get("ancora"),
                    "ruta": best.metadata.get("ruta"),
                    # VIS.3: sin documento no hay dato de vigencia que consultar (chunk
                    # temporal o legado), y en ese caso no se advierte de lo que no se sabe.
                    **(marca_de_vigencia(doc) if doc else {}),
                },
            ))
            total_tokens += len(excerpt) // 4

        # HIB.J — el orden lo decide la RECUPERACIÓN (fusión RRF, o el reranker si está), y
        # ya viene dado: `by_doc` se llena recorriendo `results` ordenados, así que la
        # inserción sigue al mejor rango de cada documento. Antes se reordenaba aquí por
        # `score`, que era equivalente mientras el score fuera la fusión; ahora el score es
        # la relevancia coseno y reordenar por ella desharía parte de la contribución
        # léxica que la fusión aporta —y que la ablación de HIB.A mostró que vale—.
        #
        # `top_k` se aplica AQUÍ y en documentos, que es lo que el mando dice ser. El recorte
        # va después de agrupar: cortar el pool antes es lo que hacía que pedir 3 fragmentos
        # devolviera un solo documento.
        sources = sources[: self._top_k]
        total_tokens = sum(len(s.excerpt) // 4 for s in sources)
        return RetrievalContext(sources=sources, mode=self.mode, total_tokens=total_tokens)

    async def _aplicar_reranker(self, query: str, results: list) -> list:
        """Reordena el pool y **sustituye** el score de fusión por el del reranker.

        La sustitución no es un detalle: el packer de RAG.5 corta por score y el quality
        gate del CoreGraph promedia. Si conviviesen la escala del RRF (~1/60) y la del
        reranker ([0,1]), esos dos controles decidirían sobre números incomparables.

        La duración se registra porque es el dato con el que se decide si el reranker sale a
        cuenta: añade una llamada de red por consulta y nadie ha medido todavía cuánto pesa.
        """
        inicio = perf_counter()
        # HIB.J: se le piden TODOS los candidatos reordenados, no `top_k`. Ahora `top_k`
        # cuenta documentos y el recorte se hace tras agrupar; truncar aquí a `top_k`
        # fragmentos dejaría menos documentos de los pedidos, que es el mismo defecto que
        # este prompt corrige en el pool.
        clasificados = await self._reranker.rerank(
            query, [r.content for r in results], len(results)
        )
        transcurrido_ms = (perf_counter() - inicio) * 1000

        reordenados = []
        for clasificado in clasificados:
            original = results[clasificado.index]
            reordenados.append(replace(original, score=clasificado.score))

        logger.info(
            "rerank: %d candidatos -> %d resultados en %.0f ms",
            len(results),
            len(reordenados),
            transcurrido_ms,
        )
        return reordenados

    def get_agent_tools(self) -> list:
        return []
