"""Orquestador de ingestión asincrona."""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.core.lengua_del_corpus import codi_del_corpus
from server.app.modules.agents_hub.services.language_detector import detect_language
from server.app.modules.agents_hub.ingestion.bilingual_bridge import terminos_bilingues
from server.app.modules.agents_hub.ingestion.corpus.frontmatter import parse_frontmatter
from server.app.modules.agents_hub.database.operational_models import (
    HubDocument,
    HubDocumentChunk,
    HubIngestionJob,
)
from server.app.modules.agents_hub.ingestion.chunker import MarkdownChunker
from server.app.modules.agents_hub.ingestion.hasher import hash_content
from server.app.modules.agents_hub.ingestion.job_progress import (
    ProgressCallback,
    SeguimientoDeJob,
)
from server.app.modules.agents_hub.ingestion.markdown_utils import (
    estimate_tokens,
    extract_title_from_markdown,
)

logger = logging.getLogger(__name__)


class EmbeddingService(Protocol):
    model_name: str
    dimensions: int

    async def embed(self, text: str) -> list[float]: ...


def _procedencia(embedding_service: Any) -> tuple[str, int, str | None]:
    """Modelo, dimension y tipo de tarea del servicio, o error explicito (RAG.9 + PIL.1).

    Antes esto era un `getattr(..., None)` y escribia NULL cuando el servicio no lo
    declaraba, que es exactamente el vector anonimo que la columna vino a impedir. Ahora
    la columna es NOT NULL, asi que sin esto el sintoma seria un NotNullViolation de
    Postgres en mitad de una ingesta, sin decir cual de los dos datos falta ni de quien.

    El tipo de tarea SI admite None, y no es una excepcion a la regla anterior: el modelo
    local no distingue documento de consulta, y declararlo asi es informacion, no un hueco.
    """
    modelo = getattr(embedding_service, "model_name", None)
    dimension = getattr(embedding_service, "dimensions", None)
    if not modelo or not dimension:
        raise ValueError(
            f"El servicio de embeddings {type(embedding_service).__name__} no declara "
            "`model_name` y `dimensions`, y sin ellos el vector queda sin procedencia: "
            "cambiar de modelo dejaria de ser detectable."
        )
    tarea = getattr(embedding_service, "embedding_task_type", None)
    return str(modelo), int(dimension), (str(tarea) if tarea else None)


class StorageService(Protocol):
    async def get(self, key: str) -> bytes: ...


class ChatbotConfigProvider(Protocol):
    async def get_retrieval_mode(self, chatbot_id: uuid.UUID) -> str: ...


#: ACT.8 — modos de recuperacion que CONSULTAN el indice vectorial, y por tanto necesitan que
#: sus documentos esten troceados y embebidos.
#:
#: Aqui ponia `== "RAG"`, y la premisa —«los otros dos modos no embeben nada»— estaba escrita
#: igual en tres sitios. Fue una decision, pero es ANTERIOR a que el agentico tuviera busqueda
#: por fragmentos: `MD_AGENT_SELECTOR` expone `search_knowledge`, que embebe la consulta y llama
#: a `hybrid_search`, y el bloque HIB reparo sus 14.198 fragmentos dejando escrito que «no son
#: peso muerto». Al actualizar el corpus el 28-08-2026 sus 6 documentos nuevos entraron sin un
#: solo fragmento, y el informe decia `ingeridos=6` sin mentir: el documento si entro.
#:
#: Y habia un defecto latente peor que el hueco: la rama que no trocea BORRA los fragmentos que
#: hubiera, asi que reingerir un documento del agentico se los llevaba. Se habria ido vaciando
#: pasada a pasada sin que nada avisara.
#:
#: `MD_LONG_CONTEXT` no esta, y es correcto: inyecta documentos enteros y no consulta el indice
#: nunca, asi que alli los fragmentos si son peso muerto y borrarlos es lo que toca.
#:
#: Se declara UNA vez y la importan los tres consumidores. Que estuviera repetida es por lo que
#: envejecio sin que nadie la revisara.
MODOS_QUE_BUSCAN_POR_FRAGMENTOS = ("RAG", "MD_AGENT_SELECTOR")


class IngestionWatcher:
    """Orquesta la ingestión de documentos.

    Crea/actualiza HubDocument como unidad citable canonica.
    Genera chunks solo cuando retrieval_mode == 'RAG'.
    """

    def __init__(
        self,
        session: AsyncSession,
        embedding_service: EmbeddingService,
        storage: StorageService | None = None,
        chatbot_provider: ChatbotConfigProvider | None = None,
    ):
        self._session = session
        self._embedding = embedding_service
        self._storage = storage
        self._chatbot_provider = chatbot_provider
        # RAG.8: el chunker por defecto es el de plataforma. `_chunker_para` lo sustituye
        # por el resuelto en la cascada cuando hay chatbot; se conserva este para los
        # caminos que no lo tienen (subidas temporales) y para no romper a quien lo use.
        self.chunker = MarkdownChunker()
        # Keep legacy attribute for backward compatibility
        self.session = session
        self.embedding_service = embedding_service

    async def process_source(
        self,
        source_url: str,
        chatbot_id: uuid.UUID,
        language: str | None = None,
        citation_url: str | None = None,
        prefetched_content: str | None = None,
        title: str | None = None,
        crawled_page_id: uuid.UUID | None = None,
        seguimiento: SeguimientoDeJob | None = None,
    ) -> tuple[HubDocument, int]:
        """Crea/actualiza un HubDocument. Genera chunks SOLO si retrieval_mode == 'RAG'.

        Returns:
            (HubDocument, chunks_created_count) — idempotente por content_hash.
        """
        seg = seguimiento or SeguimientoDeJob()

        # EXT.1: al corpus entra Markdown ya convertido, nunca un original que haya que
        # interpretar aquí. Los cuatro llamantes —reconciliador, curación, publicación de
        # páginas y la subida del panel— pasan el cuerpo; que esto sea una condición y no
        # un `if` es lo que impide que mañana alguien reabra la vía de conversión en
        # caliente sin darse cuenta de lo que reabre.
        if prefetched_content is None:
            raise ValueError(
                "process_source exige el contenido ya convertido: al corpus solo entra "
                "Markdown del pipeline de curación (EXT.1). Para extraer texto de un "
                "documento aportado como contexto, usa el extractor de contexto."
            )
        content = prefetched_content
        seg.total_chars = len(content)

        # El `language=` que llega aqui es una entrada externa: sale del job o del
        # `language:` del front-matter del `.md`, asi que puede venir escrito `ca`. Se
        # normaliza antes de guardarlo; `detect_language` ya devuelve el codigo del corpus.
        language = codi_del_corpus(language)
        if language is None:
            language = detect_language(content)
        content_hash = hash_content(content)
        canonical = citation_url or source_url
        doc_title = title or extract_title_from_markdown(content) or canonical
        token_count = estimate_tokens(content)

        # Idempotencia: mismo chatbot + mismo hash → actualizar sin rechunkear
        existing = await self._session.execute(
            select(HubDocument).where(
                HubDocument.chatbot_id == chatbot_id,
                HubDocument.content_hash == content_hash,
            ).limit(1)
        )
        doc = existing.scalar_one_or_none()
        if doc:
            doc.canonical_url = canonical
            doc.title = doc_title
            doc.updated_at = datetime.now(timezone.utc)
            if crawled_page_id is not None:
                doc.crawled_page_id = crawled_page_id
        else:
            # Si ya existia un documento con esta URL e idioma → reemplazar.
            # Idiomas distintos de la misma URL coexisten sin borrarse mutuamente.
            old_result = await self._session.execute(
                select(HubDocument).where(
                    HubDocument.chatbot_id == chatbot_id,
                    HubDocument.canonical_url == canonical,
                    HubDocument.language == language,
                )
            )
            for old_doc in old_result.scalars():
                await self._session.execute(
                    delete(HubDocumentChunk).where(
                        HubDocumentChunk.document_id == old_doc.id
                    )
                )
                await self._session.delete(old_doc)

            source_kind = (
                "crawler"
                if source_url.startswith(("http://", "https://"))
                else "upload"
            )
            doc = HubDocument(
                chatbot_id=chatbot_id,
                title=doc_title,
                canonical_url=canonical,
                markdown_content=content,
                content_hash=content_hash,
                language=language,
                source_kind=source_kind,
                token_count=token_count,
                crawled_page_id=crawled_page_id,
            )
            try:
                # Savepoint: si falla por clave duplicada solo se revierte el savepoint,
                # no la transacción exterior (que mantiene el job válido).
                #
                # **El `add` va DENTRO.** Estaba fuera, y con eso el objeto entraba en la
                # transacción exterior: al fallar el flush, la sesión quedaba marcada para
                # deshacer y el `SELECT` de aquí abajo —el que busca el documento que ya
                # existe— moría con `PendingRollbackError`. El trabajo terminaba en «falló»
                # con una traza de SQLAlchemy, en vez de reutilizar el documento.
                #
                # Sólo se veía con **dos trabajos a la vez**, que es el caso que este bloque
                # dice cubrir: en secuencial el savepoint ya absorbía el choque. Reproducido
                # en `test_subida_duplicada.py::TestDosTrabajosALaVez`.
                async with self._session.begin_nested():
                    self._session.add(doc)
                    await self._session.flush()
            except IntegrityError:
                # Dos jobs concurrentes procesaron el mismo contenido: usar el existente.
                # Tras el rollback del savepoint, doc puede estar ya desvinculado.
                try:
                    self._session.expunge(doc)
                except Exception:
                    pass
                existing_dup = await self._session.execute(
                    select(HubDocument).where(
                        HubDocument.chatbot_id == chatbot_id,
                        HubDocument.content_hash == content_hash,
                    ).limit(1)
                )
                doc = existing_dup.scalar_one()
                return doc, 0

        # ACT.8 — la pregunta no es el MODO, es si el asistente busca por fragmentos.
        retrieval_mode = (
            await self._chatbot_provider.get_retrieval_mode(chatbot_id)
            if self._chatbot_provider
            else "RAG"
        )
        n_chunks = 0
        if retrieval_mode in MODOS_QUE_BUSCAN_POR_FRAGMENTOS:
            n_chunks = await self._regenerate_chunks_for_document(doc, seguimiento=seg)
        else:
            # Limpiar chunks previos si el modo cambió a uno que de verdad no los usa.
            await self._session.execute(
                delete(HubDocumentChunk).where(HubDocumentChunk.document_id == doc.id)
            )

        await self._session.commit()
        return doc, n_chunks

    async def _chunker_para(self, chatbot_id: uuid.UUID) -> MarkdownChunker:
        """Chunker con los parámetros resueltos en la cascada (RAG.8).

        Antes se instanciaba con los defaults del código, así que la configuración por
        chatbot no existía: el admin podía cambiar `chunk_size` en la API y no pasaba nada.
        Si la cascada no responde —chatbot inexistente, o llamada fuera de contexto—, se
        usa el chunker de plataforma en vez de reventar la ingesta por un dato de tuning.
        """
        from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
            get_effective_public_graph_config,
        )

        try:
            cfg = await get_effective_public_graph_config(chatbot_id, self._session)
            return MarkdownChunker(
                chunk_size=int(cfg.chunk_size),
                chunk_overlap=int(cfg.chunk_overlap),
                strategy=str(cfg.chunking_strategy),
                # HIB.L — si no llega hasta aquí, el techo es decorativo: es el mismo defecto
                # que este método arregló para `chunk_size`.
                parent_max_tokens=int(getattr(cfg, "parent_max_tokens", 8000) or 8000),
            )
        except Exception:  # pragma: no cover - la ingesta no cae por la config de troceado
            logger.warning(
                "No se pudo resolver la config de troceado; se usa la de plataforma"
            )
            return self.chunker

    def _anotar_progreso(
        self, job: HubIngestionJob, callback: ProgressCallback | None
    ) -> ProgressCallback:
        """Escribe el progreso en la fila y, si hay, se lo pasa a quien mira.

        Sin `commit`: el `flush` implícito de la sesión basta para que el valor viaje con la
        transacción de la ingesta. Comprometerse a un commit por etapa expondría un
        documento sin sus fragmentos a cualquier lector concurrente.
        """
        def _anotar(actual: int, total: int | None, mensaje: str) -> None:
            job.progress_current = actual
            job.progress_total = total
            job.progress_message = mensaje[:255]
            if callback is not None:
                callback(actual, total, mensaje)

        return _anotar

    async def _embed_en_lote(self, textos: list[str]) -> list[list[float]]:
        """Embebe una lista PARA INDEXAR, usando el lote del servicio si lo expone.

        La logica vive en `embed_para_indexar` (PIL.1) porque el re-embebido necesita
        exactamente la misma: dos copias de esta decision es como se acaba con medio corpus
        embebido con un proposito y medio con otro.
        """
        from server.app.modules.agents_hub.services.embedding_service import (
            embed_para_indexar,
        )

        return await embed_para_indexar(self._embedding, textos)

    async def _regenerate_chunks_for_document(
        self, doc: HubDocument, seguimiento: SeguimientoDeJob | None = None
    ) -> int:
        """Borra los chunks del documento y los regenera. Devuelve el numero creado."""
        seg = seguimiento or SeguimientoDeJob()
        await self._session.execute(
            delete(HubDocumentChunk).where(HubDocumentChunk.document_id == doc.id)
        )
        chunker = await self._chunker_para(doc.chatbot_id)
        async with seg.etapa("chunk"):
            chunks = chunker.split(
                doc.markdown_content,
                metadata={
                    "document_id": str(doc.id),
                    "source_url": doc.canonical_url,
                    # FAQ.2: la autoridad del texto viaja con el fragmento. Sin esto, al
                    # recuperar una respuesta de FAQ nadie sabe ya que no era una norma.
                    # Es metadato del chunk, no texto embebido: reclasificar sigue siendo
                    # un UPDATE y no obliga a re-embeber.
                    "content_class": doc.content_class,
                },
                # RAG.7: el título encabeza el texto que se embebe, no el que se almacena.
                document_title=doc.title,
            )
        # A partir de aquí sí se sabe cuántos pasos quedan; antes, `progress_total` es None
        # a propósito, porque un 0 se leería como «no hay nada que hacer».
        seg.total = len(chunks)
        seg.n_chunks = len(chunks)
        terminos = terminos_bilingues(doc)
        # MOD.1: la procedencia se graba CON el vector. Sin ella, cambiar de modelo es una
        # avería silenciosa; con ella, `assert_embedding_space_matches` puede detectarla.
        modelo, dimension, tarea = _procedencia(self._embedding)
        # RAG.7: se embebe `embedding_text` —jerarquía + contenido—, no el contenido crudo.
        # Y por LOTES cuando el servicio lo soporta: el watcher iba chunk a chunk, o sea una
        # llamada por fragmento, que con un proveedor por API es una ida y vuelta de red por
        # cada uno. `embed` suelto se conserva para los servicios que no expongan lote.
        seg.embedding_model = modelo
        async with seg.etapa("embed", f"{len(chunks)} fragmentos en 1 lote"):
            vectores = await self._embed_en_lote([ch.embedding_text for ch in chunks])
        seg.n_batches += 1

        async with seg.etapa("persist", actual=len(chunks)):
            self._persistir_chunks(
                doc, chunks, vectores, terminos, modelo, dimension, tarea
            )
        return len(chunks)

    def _persistir_chunks(
        self, doc: HubDocument, chunks, vectores, terminos, modelo, dimension, tarea=None
    ) -> None:
        for ch, embedding in zip(chunks, vectores):
            self._session.add(HubDocumentChunk(
                chatbot_id=doc.chatbot_id,
                document_id=doc.id,
                content=ch.content,
                source_url=doc.canonical_url,
                content_hash=hash_content(ch.content),
                embedding=embedding,
                chunk_metadata={**ch.metadata, "document_id": str(doc.id)},
                language=doc.language,
                bilingual_terms=terminos,
                embedding_model=modelo,
                embedding_dim=dimension,
                embedding_task_type=tarea,
                # RAG.9: se guarda el texto que se embebio, no solo el que se muestra. Es lo
                # que permite que un re-embed produzca el mismo vector que produjo la ingesta.
                embedding_text=ch.embedding_text,
                parent_content=ch.parent_content or None,
            ))

    async def process_user_upload(
        self,
        source_url: str,
        chatbot_id: uuid.UUID,
        owner_id: uuid.UUID,
        progress_callback: ProgressCallback | None = None,
    ) -> list[HubDocumentChunk]:
        """Procesa un documento subido por un usuario (siempre re-procesa, marca como temporal).

        EXT.2: la extracción es `pdfplumber` y no Docling. Aquí sí vale: la persona tiene el
        documento delante y ve en la respuesta si salió regular. Un PDF escaneado levanta
        `PdfSinCapaDeTexto`, que el endpoint traduce a un 422 con un mensaje que se entiende
        — ingerir un documento vacío en silencio es la avería que nadie ve.
        """
        from server.app.core.pdf_text import extraer_texto_de_pdf

        seg = SeguimientoDeJob(progress_callback)

        def _process() -> str:
            return extraer_texto_de_pdf(source_url)

        async with seg.etapa("extract", "pdfplumber"):
            content = await asyncio.to_thread(_process)
        language = detect_language(content)
        async with seg.etapa("chunk"):
            chunks = self.chunker.split(content, metadata={"source_url": source_url})
        seg.total = len(chunks)
        created_chunks = []

        # RAG.9: los adjuntos caen en la MISMA tabla y se buscan junto al corpus, asi que
        # tienen que embeberse igual —`embedding_text`, no `content`— y declarar su
        # procedencia. Hacian ninguna de las dos cosas: mientras la columna fue opcional el
        # hueco era invisible, y el vector de un adjunto salia de un texto distinto del que
        # habria salido si el mismo documento hubiera entrado por la ingesta normal.
        modelo, dimension, tarea = _procedencia(self._embedding)
        async with seg.etapa("embed", f"{len(chunks)} fragmentos en 1 lote"):
            vectores = await self._embed_en_lote([ch.embedding_text for ch in chunks])

        seg.avisar("persist", actual=len(chunks))
        for chunk, embedding in zip(chunks, vectores):
            db_chunk = HubDocumentChunk(
                chatbot_id=chatbot_id,
                content=chunk.content,
                source_url=source_url,
                content_hash=hash_content(chunk.content),
                embedding=embedding,
                chunk_metadata=chunk.metadata,
                language=language,
                embedding_model=modelo,
                embedding_dim=dimension,
                embedding_task_type=tarea,
                embedding_text=chunk.embedding_text,
                is_temporary=True,
                owner_id=owner_id,
            )
            self._session.add(db_chunk)
            created_chunks.append(db_chunk)

        await self._session.commit()
        return created_chunks

    async def run_job(
        self,
        job_id: uuid.UUID,
        prefetched_content: str | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Ejecuta un job de ingestión, anotando progreso y tiempos por etapa (RAG.12).

        **Límite conocido**: la fila se actualiza en la misma transacción que la ingesta, así
        que el progreso intermedio no es visible desde fuera hasta que el job cierra. Hacerlo
        visible en vivo exige una transacción autónoma —una segunda sesión—, y comprometerse
        a eso por una barra de progreso no sale a cuenta hoy. El consumidor en vivo es
        `progress_callback`, que es por donde informa la carga masiva por consola.
        """
        # Issue #159 — el candado va ANTES de nada, y decide en una sola operación.
        if not await tomar_job(self._session, job_id):
            logger.info(
                "El job %s ya estaba en curso o terminado: no se procesa otra vez.", job_id
            )
            return

        job = await self._session.get(HubIngestionJob, job_id)
        if not job:
            return

        seguimiento = SeguimientoDeJob(self._anotar_progreso(job, progress_callback))

        tmp_path: str | None = None
        error: Exception | None = None
        try:
            fuente = job.source_url
            citation_url = job.canonical_url
            cuerpo = prefetched_content

            if self._storage and not job.source_url.startswith(("http://", "https://")):
                # EXT.1: lo que hay en el almacén es el `.md` que subió el panel, ya
                # convertido por el pipeline de curación. Se lee como texto y se pasa como
                # contenido: por aquí ya no se convierte nada, así que no hay fichero
                # temporal que escribir ni conversor al que llamar.
                crudo = await self._storage.get(job.source_url)
                cuerpo = crudo.decode("utf-8") if isinstance(crudo, bytes) else crudo
                if not citation_url:
                    citation_url = job.source_url  # storage key como identificador canónico

            # El CLI de curación (`corpus/source.py`) separa front-matter y cuerpo con
            # `parse_frontmatter` antes de ingerir; esta vía leía el fichero entero y lo
            # pasaba tal cual, así que el bloque YAML se troceaba y se embebía como si fuera
            # contenido (CLAUDE.md §5) y el `language:` declarado nunca llegaba a leerse. Es
            # no-op si no hay front-matter: `parse_frontmatter` devuelve `({}, texto)`. Solo
            # se toca si hay `cuerpo`: `None` sigue cayendo en el `ValueError` explícito de
            # `process_source` en vez de convertirse en una cadena vacía silenciosa.
            metadatos_frontmatter: dict = {}
            if cuerpo is not None:
                metadatos_frontmatter, cuerpo = parse_frontmatter(cuerpo)
            idioma_efectivo = job.language or metadatos_frontmatter.get("language")

            filename_hint = Path(job.original_filename).stem if job.original_filename else None
            doc, n_chunks = await self.process_source(
                fuente,
                job.chatbot_id,
                citation_url=citation_url,
                prefetched_content=cuerpo,
                language=idioma_efectivo,
                title=filename_hint,
                seguimiento=seguimiento,
            )
            job.status = "completed"
            job.chunks_processed = n_chunks
            job.processing_stats = seguimiento.resumen()
            job.processing_completed_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.error("Job %s falló: %s", job_id, e, exc_info=True)
            error = e
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

        if error is not None:
            try:
                await self._session.rollback()
                job = await self._session.get(HubIngestionJob, job_id)
                if job:
                    job.status = "failed"
                    job.error_message = str(error)
                    # Lo medido hasta el fallo vive en memoria, así que el rollback de
                    # arriba no se lo llevó. Es justo cuando más falta hace: dice por dónde
                    # iba y cuál fue la etapa que reventó.
                    job.processing_stats = seguimiento.resumen()
                    job.processing_completed_at = datetime.now(timezone.utc)
                    await self._session.commit()
            except Exception as save_err:
                logger.error("No se pudo guardar el estado 'failed' del job %s: %s", job_id, save_err, exc_info=True)
        else:
            await self._session.commit()


#: Desde qué estados se puede empezar a procesar un job. `failed` entra a propósito: si no, un
#: fallo transitorio dejaría el documento fuera del corpus para siempre y la única salida sería
#: volver a subirlo.
ESTADOS_QUE_SE_PUEDEN_TOMAR = ("pending", "failed")


async def tomar_job(session: AsyncSession, job_id: uuid.UUID) -> bool:
    """Marca el job como `running` y dice si **este** llamante se lo ha quedado (issue #159).

    **Decide en una sola operación de base de datos, y ésa es toda la gracia.** Comprobar el
    estado y escribirlo después deja una ventana entre la lectura y la escritura; dos tareas de
    `BackgroundTasks` corren en el mismo bucle de eventos y ceden el control en cada `await`, así
    que en esa ventana cabe una tarea entera. El `UPDATE ... WHERE status IN (...)` lo resuelve el
    servidor: quien obtiene `rowcount == 1` se lo queda y el otro se va.

    **Qué evita.** `run_job` no miraba el estado: ponía `running` y procesaba. Dos invocaciones
    sobre el mismo `job_id` ingerían el documento **dos veces**, y unos fragmentos duplicados en
    el corpus no se notan y no se deshacen solos — es peor que una consulta lenta, que al menos
    se ve.

    **Y un job atascado en `running` no queda bloqueado para siempre por un cronómetro**: el
    estado lo decide quien reintente, poniéndolo en `failed`, y no una regla de caducidad que
    habría que acertar.
    """
    resultado = await session.execute(
        update(HubIngestionJob)
        .where(
            HubIngestionJob.id == job_id,
            HubIngestionJob.status.in_(ESTADOS_QUE_SE_PUEDEN_TOMAR),
        )
        .values(status="running", processing_started_at=datetime.now(timezone.utc))
    )
    await session.commit()
    return (resultado.rowcount or 0) == 1


async def cleanup_temporary_chunks(session: AsyncSession, ttl_hours: int = 24) -> int:
    """Elimina los fragmentos temporales que han superado su tiempo de vida.

    **Se borra en SQL, y el filtro entero va en el `WHERE` (issue #159).** La versión anterior
    traía **todos** los fragmentos temporales de `hub_document_chunks` —163.762 filas en el corpus
    de hoy— como objetos ORM, y comparaba la fecha **en Python**. Tres cosas mal a la vez: el
    recorrido no tenía límite, cada objeto arrastra su vector de 3.072 dimensiones, y la
    condición que de verdad reducía el conjunto se evaluaba después de haberlo traído entero.

    Es la misma forma que dejó la VM 50 minutos sin responder el 2026-09-24, en una función que
    además **borra**: un fallo aquí no se queda en una consulta lenta.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ttl_hours)
    resultado = await session.execute(
        delete(HubDocumentChunk).where(
            HubDocumentChunk.is_temporary,
            HubDocumentChunk.created_at < cutoff,
        )
    )
    await session.commit()
    return resultado.rowcount or 0
