"""Orquestador de ingestión asincrona."""

import asyncio
import contextlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, cast, Protocol

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.exc import IntegrityError, InvalidRequestError
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.core.lengua_del_corpus import codi_del_corpus
from server.app.modules.agents_hub.services.language_detector import detect_language
from server.app.modules.agents_hub.ingestion.bilingual_bridge import terminos_bilingues
from server.app.modules.agents_hub.ingestion.corpus.reconciler import CorpusReconciler
from server.app.modules.agents_hub.ingestion.corpus.source import MarkdownSubido
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
from server.app.modules.agents_hub.services.modos_de_recuperacion import MODOS_QUE_BUSCAN_POR_FRAGMENTOS

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
        confirmar: bool = True,
    ) -> tuple[HubDocument, int]:
        """Crea/actualiza un HubDocument. Genera chunks SOLO si retrieval_mode == 'RAG'.

        `confirmar=False` deja el commit a quien llama (#285): la subida del panel aplica los
        metadatos del corpus **después**, y si confirmaba aquí un fallo posterior dejaba el
        documento buscable y sin vigencia, `us_assistents` ni `source_kind`.

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
            # Los fragmentos de todos los documentos que se reemplazan, en un solo DELETE (#282).
            viejos = list(old_result.scalars())
            if viejos:
                await self._session.execute(
                    delete(HubDocumentChunk).where(
                        HubDocumentChunk.document_id.in_([d.id for d in viejos])
                    )
                )
            for old_doc in viejos:
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
                with contextlib.suppress(InvalidRequestError):
                    self._session.expunge(doc)
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

        if confirmar:
            await self._session.commit()
        else:
            await self._session.flush()
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
                "No se pudo resolver la config de troceado; se usa la de plataforma",
                exc_info=True,
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
        for ch, embedding in zip(chunks, vectores, strict=True):
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
        for chunk, embedding in zip(chunks, vectores, strict=True):
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
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        """Ejecuta el job de un `.md` subido por el panel, anotando progreso y tiempos por
        etapa (RAG.12).

        EXT.1: lo que hay en el almacén ya lo convirtió el pipeline de curación, así que aquí
        no se convierte nada. #265: entra por el mismo reconciliador que la consola, que es
        quien aplica el contrato —título, `id_publicacio`, vigencia, `us_assistents`— y lo
        empareja con lo que ya hay.

        **Límite conocido**: la fila se actualiza en la misma transacción que la ingesta, así
        que el progreso intermedio no es visible desde fuera hasta que el job cierra. Hacerlo
        visible en vivo exige una transacción autónoma —una segunda sesión—, y comprometerse
        a eso por una barra de progreso no sale a cuenta hoy. El consumidor en vivo es
        `progress_callback`.
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

        error: Exception | None = None
        try:
            if self._storage is None:
                raise RuntimeError("el watcher se construyó sin almacenamiento y este job lo necesita")
            crudo = await self._storage.get(job.source_url)
            texto = crudo.decode("utf-8") if isinstance(crudo, bytes) else crudo
            informe = await CorpusReconciler(
                self._session, self, confirmar_cada_documento=False
            ).reconcile(
                MarkdownSubido(
                    job.original_filename or Path(job.source_url).name,
                    texto,
                    url_por_defecto=job.source_url,
                    canonical_url=job.canonical_url,
                    language=job.language,
                ),
                job.chatbot_id,
                seguimiento=seguimiento,
                anotar_trabajo=False,
            )
            job.status = "completed"
            job.chunks_processed = informe.fragmentos
            # Lo que no se ingirió, y por qué —`us_assistents: no`, una copia que no se pudo
            # hacer—, como **avisos** y no como error (#285): un completado con `error_message`
            # se leía en el panel igual que un fallo.
            job.error_message = None
            job.processing_stats = {
                **seguimiento.resumen(),
                "avisos": list(informe.motivos_omision),
            }
            job.processing_completed_at = datetime.now(timezone.utc)
        except Exception as e:
            logger.error("Job %s falló: %s", job_id, e, exc_info=True)
            error = e

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
    return (cast(CursorResult, resultado).rowcount or 0) == 1


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
    return cast(CursorResult, resultado).rowcount or 0


#: Cada cuánto pasa la limpieza de temporales. Viven 24 h, así que una pasada cada seis horas los
#: borra como mucho un cuarto de día tarde; es la cadencia del barrido de artefactos de funciones.
TEMPORALES_CADA_SEGUNDOS = 6 * 60 * 60


async def una_pasada_de_temporales(session_factory) -> int:
    """Una limpieza de los PDF temporales del chat, con su propia sesión (#254)."""
    async with session_factory() as session:
        borrados = await cleanup_temporary_chunks(session)
    if borrados:
        logger.info("Fragmentos temporales caducados borrados: %d", borrados)
    return borrados


async def bucle_de_temporales(
    session_factory, *, cada_segundos: int = TEMPORALES_CADA_SEGUNDOS
) -> None:
    """Pasa la limpieza de temporales para siempre. Lo lanza el arranque (#254).

    `cleanup_temporary_chunks` existía, con su test, y no la llamaba nadie: los PDF que alguien
    subía como contexto de su consulta se quedaban para siempre. **Un fallo de una pasada no para
    el bucle**: se registra y se espera a la siguiente, como en `bucle_de_caducados`.
    """
    while True:
        try:
            await una_pasada_de_temporales(session_factory)
        except Exception:  # se registra y se reintenta en la siguiente pasada
            logger.exception("La limpieza de fragmentos temporales falló; se reintenta luego")
        await asyncio.sleep(cada_segundos)
