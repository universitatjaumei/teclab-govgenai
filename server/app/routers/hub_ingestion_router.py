"""Router de administración (Hub) para la ingestión de documentos.

Deploy: edge — maneja documentos, trabajos de ingesta y fragmentos del corpus, que son datos del cliente (#273).
Módulo: chatbots — la ingesta alimenta el corpus de un chatbot.

Aquí la autorización, la validación de la subida y los códigos de estado; lo que lee y escribe la
base, en `modules/agents_hub/services/ingesta_del_panel.py` (#274).
"""

import uuid
from datetime import date, datetime
from typing import Any, Literal

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel, ConfigDict, Field, computed_field
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user, require_role
from server.app.core.auth import UserInfo
from server.app.core.auth.tenancy import assert_chatbot_org_access, organizacion_unica_de
from server.app.core.storage import FsspecStorageService, get_storage_service
from server.app.core.uploads import (
    UploadKind,
    assert_within_document_quota,
    validate_upload,
)
from server.app.api.deps import get_session
from server.app.modules.agents_hub.database.operational_models import HubIngestionJob
from server.app.modules.agents_hub.services import ingesta_del_panel as ingesta
from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
from server.app.modules.agents_hub.services.embedding_resolver import (
    resolve_embedding_service,
)


class AnalyzeHtmlRequest(BaseModel):
    html: str
    url_hint: str = ""


# ── Contrato de respuesta (CAL.2) ──────────────────────────────────────────────
# Estos endpoints nacieron devolviendo dicts sueltos. FastAPI documenta eso como un
# objeto vacío, Orval lo genera como `Promise<unknown>` y el frontend acababa
# redeclarando la forma del dato a mano en `shared/api/ingestion.ts`. Declarar el
# `response_model` es lo que hace que el tipo del panel venga del contrato.
#
# `status` va como `str` y no como `Literal`: es un campo de presentación, la tabla de
# jobs ya tiene rama por defecto, y un valor inesperado en una fila debe pintarse "en
# cola", no tumbar el listado entero con un 500 de validación de respuesta.


#: Un trabajo en estos estados no se puede borrar: lo está procesando el watcher.
ESTADOS_EN_CURSO = ("pending", "running")


class IngestionJob(BaseModel):
    """Trabajo de ingesta tal y como lo pinta la tabla técnica del panel."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    chatbot_id: uuid.UUID
    source_url: str
    original_filename: str | None = None
    canonical_url: str | None = None
    language: str | None = None
    status: str
    chunks_processed: int
    error_message: str | None = None
    # Progreso y estadísticas por etapa (RAG.12). Van en el contrato porque el panel
    # los pinta: sin ellos, un job trabajando y un job colgado se ven igual.
    progress_current: int = 0
    progress_total: int | None = None
    progress_message: str = ""
    processing_stats: dict[str, Any] = Field(default_factory=dict)
    processing_started_at: datetime | None = None
    processing_completed_at: datetime | None = None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def avisos(self) -> list[str]:
        """Lo que un trabajo completado no ingirió, y por qué (#285).

        Va aparte de `error_message`, que es sólo de los fallidos: con las notas ahí, un
        completado con una omisión deliberada —`us_assistents: no`— se leía como un fallo.
        """
        return [str(a) for a in (self.processing_stats or {}).get("avisos", [])]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def acciones_permitidas(self) -> list[Literal["borrar"]]:
        """«borrar» si no está en curso: la misma regla con la que `delete_ingestion_job` da 409."""
        return [] if self.status in ESTADOS_EN_CURSO else ["borrar"]


class IngestionJobsOut(BaseModel):
    jobs: list[IngestionJob]


class HubDocumentOut(BaseModel):
    """Documento citable, en la forma resumida que lista la tabla del corpus."""

    id: uuid.UUID
    chatbot_id: uuid.UUID
    title: str
    canonical_url: str
    language: str
    source_kind: str
    token_count: int
    created_at: datetime | None = None
    updated_at: datetime | None = None


class HubDocumentDetailOut(HubDocumentOut):
    """El mismo documento con su markdown, que es lo que alimenta el preview."""

    markdown_content: str


class HubDocumentsOut(BaseModel):
    documents: list[HubDocumentOut]


class DocumentVigenciaOut(BaseModel):
    """Documento en la cola de validación de vigencia (A7)."""

    id: uuid.UUID
    title: str
    language: str
    canonical_url: str
    id_publicacio: str | None = None
    estat_vigencia: str | None = None
    vigencia_validada_el: datetime | None = None
    vigencia_validada_per: str | None = None
    data_revisio_prevista: date | None = None
    revisat_per: str | None = None
    # Por qué está en la cola. Se calcula aquí y no en el cliente porque es la misma regla
    # que decide el aviso del asistente: duplicarla en React es garantizar que un día digan
    # cosas distintas.
    motiu: str


class VigenciaPendentOut(BaseModel):
    total: int
    pendents: int
    documents: list[DocumentVigenciaOut]


class MessageOut(BaseModel):
    message: str


class CopiasDocumentoOut(BaseModel):
    """Dónde más vive esta norma, para avisar antes de borrar (DER.2)."""

    copias_en_otros_chatbots: int = 0
    chatbots_afectados: list[str] = []


class DeleteDocumentOut(BaseModel):
    """Resultado de borrar un documento, con lo que ha quedado sin borrar (DER.2).

    `copias_en_otros_chatbots` no es información decorativa: es la diferencia entre «he
    quitado esta norma del asistente» y «he retirado esta norma del corpus», que quien pulsa
    el botón necesita saber **después** de pulsarlo aunque no lo supiera antes.
    """

    message: str
    copias_en_otros_chatbots: int = 0
    chatbots_afectados: list[str] = []
    documentos_eliminados: int = 1


class UploadDocumentOut(BaseModel):
    job: IngestionJob
    message: str


class DeleteIngestionJobOut(BaseModel):
    message: str
    documents_deleted: int


class ClearCollectionOut(BaseModel):
    message: str
    documents_deleted: int
    jobs_deleted: int


class AnalyzeHtmlOut(BaseModel):
    proposed_selectors: dict[str, str | None]
    confidence: float
    sample_extraction: dict[str, str]


router = APIRouter(prefix="/hub/ingestion", tags=["hub-ingestion"])

# Escribir en el corpus —subir, sustituir, borrar, vaciar— y pedir al modelo que analice un HTML
# es administración. Pertenecer a la organización basta para leer, no para esto: una cuenta
# institucional se aprovisiona como `user` al entrar por primera vez.
_ESCRIBE_EN_EL_CORPUS = require_role("superadmin", "admin")


async def _get_llm_service(
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(get_current_user),
):
    """MT.3 — el analizador de HTML resuelve el modelo para la organización de quien pide.

    No hay chatbot todavía: esto se usa **antes** de configurar la ingesta, para proponer
    selectores mirando una página. Así que la organización sale del actor, y con `None`
    —varias organizaciones o superadministrador— cae al nivel de plataforma, que es el
    comportamiento de siempre.
    """
    from server.app.modules.agents_hub.services.config_provider import LocalConfigProvider
    from server.app.modules.agents_hub.services.model_factory import get_model_for_tier
    from server.app.modules.agents_hub.services.html_analyzer_service import LangChainLLMAdapter

    provider = LocalConfigProvider(session)
    model = await get_model_for_tier(
        1, provider, organizacion_id=organizacion_unica_de(current_user)
    )
    return LangChainLLMAdapter(model)


def get_html_analyzer_service(llm_service=Depends(_get_llm_service)) -> Any:
    """El analizador de HTML, con el modelo de la petición (#274)."""
    from server.app.modules.agents_hub.services.html_analyzer_service import (
        HtmlAnalyzerService,
    )

    return HtmlAnalyzerService(llm_service=llm_service)


@router.post("/analyze-html", status_code=status.HTTP_200_OK, response_model=AnalyzeHtmlOut)
async def analyze_html(
    body: AnalyzeHtmlRequest,
    current_user: UserInfo = Depends(_ESCRIBE_EN_EL_CORPUS),  # noqa: ARG001 — autoriza: se pide por su efecto
    service=Depends(get_html_analyzer_service),
):
    """Propone selectores CSS para el contenido principal de un HTML institucional."""
    from server.app.modules.agents_hub.services.html_analyzer_service import EmptyHtmlError

    try:
        result = await service.analyze(html=body.html, url_hint=body.url_hint)
    except EmptyHtmlError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El HTML no puede estar vacío.",
        ) from exc
    return {
        "proposed_selectors": result.proposed_selectors,
        "confidence": result.confidence,
        "sample_extraction": result.sample_extraction,
    }



async def _chatbot_autorizado(session, chatbot_id, principal):
    """Lee el chatbot y comprueba la organización (SEC.2).

    Aquí vivía un `# TODO: Validar que el usuario tiene acceso al chatbot`. Mientras estuvo
    sin cerrar, cualquier administrador podía leer los trabajos de ingesta —y por tanto las
    URL y los nombres de fichero del corpus— de cualquier organización.
    """
    return await assert_chatbot_org_access(session, chatbot_id, principal)


@router.get("/{chatbot_id}/jobs", response_model=IngestionJobsOut)
async def get_ingestion_jobs(
    chatbot_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(get_current_user),
):
    """Obtiene los trabajos de ingestión de un chatbot."""
    await _chatbot_autorizado(session, chatbot_id, current_user)
    return {"jobs": await ingesta.trabajos(session, chatbot_id)}


@router.get("/{chatbot_id}/documents", response_model=HubDocumentsOut)
async def list_documents(
    chatbot_id: uuid.UUID,
    language: str | None = Query(None, description="Filtrar por idioma (es, ca, en…)"),
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(get_current_user),
):
    """Lista los documentos ingestados de un chatbot (unidades citables).

    Acepta ?language=es para filtrar por idioma.
    """
    await _chatbot_autorizado(session, chatbot_id, current_user)
    docs = await ingesta.documentos(session, chatbot_id, language)
    return {
        "documents": [
            {
                "id": str(d.id),
                "chatbot_id": str(d.chatbot_id),
                "title": d.title,
                "canonical_url": d.canonical_url,
                "language": d.language,
                "source_kind": d.source_kind,
                "token_count": d.token_count,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "updated_at": d.updated_at.isoformat() if d.updated_at else None,
            }
            for d in docs
        ]
    }


@router.get("/{chatbot_id}/vigencia", response_model=VigenciaPendentOut)
async def list_pending_vigencia(
    chatbot_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(get_current_user),
):
    """Documentos cuya vigencia nadie ha validado, que son los que provocan el aviso (A7).

    El criterio sale de `vigencia_no_validada` —la misma función que usa la capa de
    recuperación para decidir si advierte—, traducida a SQL para no traerse el corpus entero
    a memoria. Si esta condición y aquella función divergen, la pantalla dirá que faltan N y
    el asistente advertirá por M sin que nadie lo note.

    Deploy: edge.
    """
    from server.app.modules.agents_hub.services.retrieval.vigencia import ESTAT_VIGENT

    await _chatbot_autorizado(session, chatbot_id, current_user)
    total, docs = await ingesta.vigencia_pendiente(session, chatbot_id)

    return VigenciaPendentOut(
        total=total or 0,
        pendents=len(docs),
        documents=[
            DocumentVigenciaOut(
                id=d.id,
                title=d.title,
                language=d.language,
                canonical_url=d.canonical_url,
                id_publicacio=d.id_publicacio,
                estat_vigencia=d.estat_vigencia,
                vigencia_validada_el=d.vigencia_validada_el,
                vigencia_validada_per=d.vigencia_validada_per,
                data_revisio_prevista=d.data_revisio_prevista,
                revisat_per=d.revisat_per,
                # El estado manda sobre la falta de validación: un documento derogado que
                # además nadie validó pide retirarlo, no revisarlo, y meterlo en el montón
                # de «sólo hay que mirarlo» es donde se queda sin hacer.
                motiu=(
                    "estat_no_vigent"
                    if d.estat_vigencia != ESTAT_VIGENT
                    else "sense_validar"
                ),
            )
            for d in docs
        ],
    )


@router.post(
    "/{chatbot_id}/vigencia/{document_id}/validar",
    response_model=DocumentVigenciaOut,
)
async def validar_vigencia(
    chatbot_id: uuid.UUID,
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(require_role("superadmin", "admin")),
):
    """Deja constancia de que una persona ha comprobado la vigencia de un documento (REV.6).

    La cola existía y **no se podía tachar**: `vigencia_validada_el` y `revisat_per` sólo se
    leían —no había en todo el servidor un sitio que los escribiera—, así que el aviso que el
    asistente emite al citar un documento sin validar se repetía indefinidamente y el número de
    pendientes no bajaba nunca.

    **No se valida lo que el estado dice que no está vigente.** Un documento derogado está en la
    cola por su `estat_vigencia`, no por falta de sello, así que ponerle la fecha no lo sacaría
    de ella: el botón parecería roto. Y lo que pide no es revisarlo, es retirarlo o corregir el
    estado. De ahí el 409 en vez de un sellado que no serviría de nada.

    **Reservado a administración**, como las escrituras de este router: esto no es una lectura,
    es un acto editorial que queda firmado con un nombre en `revisat_per`.

    Deploy: edge.
    """
    await _chatbot_autorizado(session, chatbot_id, current_user)
    doc = await ingesta.documento_del_chatbot(session, chatbot_id, document_id)
    # El 409 de un documento no vigente y por qué se firma en `vigencia_validada_per`, en
    # `ingesta.validar_vigencia`.
    doc = await ingesta.validar_vigencia(session, doc, current_user.email)

    return DocumentVigenciaOut(
        id=doc.id,
        title=doc.title,
        language=doc.language,
        canonical_url=doc.canonical_url,
        id_publicacio=doc.id_publicacio,
        estat_vigencia=doc.estat_vigencia,
        vigencia_validada_el=doc.vigencia_validada_el,
        vigencia_validada_per=doc.vigencia_validada_per,
        data_revisio_prevista=doc.data_revisio_prevista,
        revisat_per=doc.revisat_per,
        motiu="sense_validar",
    )


@router.get("/{chatbot_id}/documents/{document_id}", response_model=HubDocumentDetailOut)
async def get_document(
    chatbot_id: uuid.UUID,
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(get_current_user),
):
    """Devuelve un documento con su contenido markdown (para preview en la UI)."""
    await _chatbot_autorizado(session, chatbot_id, current_user)
    doc = await ingesta.documento_del_chatbot(session, chatbot_id, document_id)
    return {
        "id": str(doc.id),
        "chatbot_id": str(doc.chatbot_id),
        "title": doc.title,
        "canonical_url": doc.canonical_url,
        "language": doc.language,
        "source_kind": doc.source_kind,
        "token_count": doc.token_count,
        "markdown_content": doc.markdown_content,
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }


@router.get(
    "/{chatbot_id}/documents/{document_id}/copias",
    status_code=status.HTTP_200_OK,
    response_model=CopiasDocumentoOut,
)
async def get_document_copies(
    chatbot_id: uuid.UUID,
    document_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(get_current_user),
):
    """En qué otros chatbots de la organización vive esta norma (DER.2).

    Existe para que el aviso salga **antes** de confirmar el borrado. Decirlo después
    convierte la información en un lamento: quien la lee ya ha borrado.
    """
    chatbot = await _chatbot_autorizado(session, chatbot_id, current_user)
    doc = await ingesta.documento_del_chatbot(session, chatbot_id, document_id)
    copias = await ingesta.copias_en_otros_chatbots(session, doc, chatbot.organizacion_id)
    return {
        "copias_en_otros_chatbots": len(copias),
        "chatbots_afectados": [str(c.chatbot_id) for c in copias],
    }


@router.delete(
    "/{chatbot_id}/documents/{document_id}",
    status_code=status.HTTP_200_OK,
    response_model=DeleteDocumentOut,
)
async def delete_document(
    chatbot_id: uuid.UUID,
    document_id: uuid.UUID,
    en_todos_los_chatbots: bool = Query(
        False,
        description=(
            "Borra también la copia de esta norma en los demás chatbots de la "
            "organización. Por defecto solo se borra la de este chatbot"
        ),
    ),
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(_ESCRIBE_EN_EL_CORPUS),
):
    """Elimina un documento ingestado y todos sus chunks.

    DER.2: con el documento duplicado por chatbot, «borrar la norma» es ambiguo — puede
    significar quitarla de este asistente o retirarla del corpus de la organización. La
    respuesta dice en cuántos asistentes más está, para que quien borra sepa lo que **no** ha
    hecho; y el borrado en cascada hay que pedirlo, porque hacerlo por defecto sobre corpus
    normativo es cómo se pierde una norma sin que nadie lo haya pedido.
    """
    chatbot = await _chatbot_autorizado(session, chatbot_id, current_user)
    doc = await ingesta.documento_del_chatbot(session, chatbot_id, document_id)
    copias = await ingesta.copias_en_otros_chatbots(session, doc, chatbot.organizacion_id)

    a_borrar = [doc, *copias] if en_todos_los_chatbots else [doc]
    await ingesta.borrar_documentos(session, a_borrar)

    if en_todos_los_chatbots:
        mensaje = f"Documento eliminado en {len(a_borrar)} chatbot(s)."
    elif copias:
        mensaje = (
            f"Documento eliminado en este chatbot. Sigue en {len(copias)} chatbot(s) mas "
            "de la organizacion: para retirarlo del corpus entero, repite con "
            "en_todos_los_chatbots=true."
        )
    else:
        mensaje = "Documento eliminado."

    return {
        "message": mensaje,
        "copias_en_otros_chatbots": len(copias),
        "chatbots_afectados": [str(c.chatbot_id) for c in copias],
        "documentos_eliminados": len(a_borrar),
    }


async def _assert_cumple_el_contrato(
    content: bytes,
    filename: str | None,
    *,
    url_por_defecto: str,
    canonical_url: str | None,
    language: str | None,
) -> None:
    """El `.md` tiene que ser una entrada válida de corpus, no un Markdown cualquiera.

    **Se valida lo que se va a ingerir** (#285): la misma `MarkdownSubido` que leerá el trabajo,
    con la URL y el idioma del formulario. Antes se repetía aquí, a mano, lo que hace
    `source._entrada` y sin esos dos campos, así que un idioma que el contrato rechaza pasaba la
    puerta y fallaba después, en el trabajo, donde ya no hay nadie delante.

    Se reportan **todos** los campos que fallan, no el primero: quien prepara un documento
    necesita la lista completa para corregirla de una pasada.
    """
    from pydantic import ValidationError

    from server.app.modules.agents_hub.ingestion.corpus.faq import FaqFormatoInvalido
    from server.app.modules.agents_hub.ingestion.corpus.source import MarkdownSubido

    try:
        texto = content.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="El fichero no es texto UTF-8.",
        ) from None

    try:
        await MarkdownSubido(
            filename or "documento.md",
            texto,
            url_por_defecto=url_por_defecto,
            canonical_url=canonical_url,
            language=language,
        ).list_entries()
    except FaqFormatoInvalido as mal_formada:
        # FAQ.1: si se declara FAQ, tiene que tener forma de FAQ. El fallo es mudo al trocear:
        # una FAQ en negritas se ingiere sin protestar y responde peor a partir de entonces.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "FAQ_FORMAT_INVALID", "message": str(mal_formada)},
        ) from mal_formada
    except ValidationError as exc:
        problemas = [
            {
                "campo": ".".join(str(p) for p in e["loc"]) or "(documento)",
                "problema": e["msg"],
            }
            for e in exc.errors()
        ]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "CORPUS_CONTRACT_VIOLATION",
                "message": (
                    "El front-matter no cumple el contrato del corpus. Regenera el "
                    "documento con el pipeline de curación y vuelve a subirlo."
                ),
                "problemas": problemas,
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "CORPUS_CONTRACT_VIOLATION", "message": str(exc)},
        ) from exc


@router.post(
    "/upload", status_code=status.HTTP_202_ACCEPTED, response_model=UploadDocumentOut
)
async def upload_document(
    background_tasks: BackgroundTasks,
    chatbot_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    canonical_url: str | None = Form(None),
    language: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(_ESCRIBE_EN_EL_CORPUS),
    storage: FsspecStorageService = Depends(get_storage_service),
):
    """Sube al corpus un `.md` conforme al contrato y lanza su ingestión en background.

    EXT.1: aquí entraba un PDF y se convertía con Docling **dentro de la petición**. Lo que
    salía no tiene front-matter, ni anclas de artículo, ni estado de vigencia: contenido que
    el asistente no puede citar como norma, entrando por la misma puerta que el corpus
    curado y quedando indistinguible de él.

    La conversión vive fuera, en el pipeline de curación —que además es donde está el OCR, con
    `origen_del_text` para declarar lo transcrito automáticamente—. Aquí solo entra su salida.
    Ver `docs/DECISION_EXTRACCION_Y_DESPLIEGUE.md`.
    """
    await _chatbot_autorizado(session, chatbot_id, current_user)

    # El 415 se da aquí y no en `validate_upload` para poder decir A DÓNDE ir. `UploadKind.
    # TEXT` admite además `.txt`, que para el corpus no vale: lo que se ingiere es la salida
    # del conversor, y esa es Markdown.
    nombre = (file.filename or "").lower()
    if not nombre.endswith((".md", ".markdown")):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail={
                "code": "CORPUS_ACCEPTS_MARKDOWN_ONLY",
                "message": (
                    "Al corpus solo entra Markdown (.md) conforme al contrato. Un PDF u otro "
                    "original se convierte antes en el pipeline de curación —que es donde "
                    "está el OCR y donde la conversión se revisa—, y se sube su salida."
                ),
            },
        )

    # Validación compartida (SEC.6): extensión + contenido + corte por tamaño durante la
    # lectura. `TEXT` y no `PDF`: el corpus se alimenta de Markdown.
    validado = await validate_upload(file, kind=UploadKind.TEXT)
    content = validado.read()
    validado.close()

    # Generar el UUID explícitamente para poder construir la storage key antes del commit
    # (mapped_column default= es un default SQL, no Python; job.id sería None hasta el flush).
    # Va antes de validar porque la clave es la URL por defecto de lo que se ingiere.
    job_id = uuid.uuid4()
    storage_key = f"ingestion/{chatbot_id}/{job_id}.md"

    # El contrato se comprueba AQUÍ, con la persona delante y sabiendo qué subió. Validarlo
    # al procesar en background significaría enterarse por un job fallido.
    await _assert_cumple_el_contrato(
        content,
        file.filename,
        url_por_defecto=storage_key,
        canonical_url=canonical_url or None,
        language=language,
    )

    assert_within_document_quota(await ingesta.trabajos_del_chatbot(session, chatbot_id))

    await storage.put(storage_key, content)

    job = HubIngestionJob(
        id=job_id,
        chatbot_id=chatbot_id,
        source_url=storage_key,
        original_filename=file.filename,
        canonical_url=canonical_url or None,
        status="pending",
        language=language,
    )

    job = await ingesta.encolar(session, job)

    # Lanzar tarea en background — el PDF queda en storage (no se borra)
    async def process_job(job_id: uuid.UUID) -> None:
        async for bg_session in get_session():
            watcher = IngestionWatcher(
                session=bg_session,
                # `bg_session` y no `session`: la sesión de la petición ya está cerrada
                # cuando corre la tarea de fondo —`BackgroundTasks` se ejecuta después de
                # enviar la respuesta—, así que resolver el servicio con ella es usar algo
                # que el ciclo de vida de FastAPI ya dio por terminado.
                embedding_service=await resolve_embedding_service(bg_session, chatbot_id),
                storage=get_storage_service(),
            )
            await watcher.run_job(job_id)

    background_tasks.add_task(process_job, job.id)

    return {"job": job, "message": "Documento subido y encolado."}


@router.delete(
    "/{chatbot_id}/jobs/{job_id}",
    status_code=status.HTTP_200_OK,
    response_model=DeleteIngestionJobOut,
)
async def delete_ingestion_job(
    chatbot_id: uuid.UUID,
    job_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(_ESCRIBE_EN_EL_CORPUS),
    storage: FsspecStorageService = Depends(get_storage_service),
):
    """Elimina un job de ingestión y todos sus chunks asociados."""
    await _chatbot_autorizado(session, chatbot_id, current_user)
    job = await ingesta.trabajo_del_chatbot(session, chatbot_id, job_id)

    if job.status in ESTADOS_EN_CURSO:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No se puede eliminar un job en curso.",
        )

    documentos_borrados = await ingesta.borrar_trabajo(session, job, storage)

    return {"message": "Documento eliminado.", "documents_deleted": documentos_borrados}


@router.delete(
    "/{chatbot_id}/chunks",
    status_code=status.HTTP_200_OK,
    response_model=ClearCollectionOut,
)
async def clear_chatbot_collection(
    chatbot_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(_ESCRIBE_EN_EL_CORPUS),
    storage: FsspecStorageService = Depends(get_storage_service),
):
    """Elimina todos los documentos, chunks y jobs de un chatbot."""
    await _chatbot_autorizado(session, chatbot_id, current_user)
    docs_deleted, jobs_deleted = await ingesta.vaciar(session, chatbot_id, storage)

    return {
        "message": "Colección vaciada correctamente.",
        "documents_deleted": docs_deleted,
        "jobs_deleted": jobs_deleted,
    }
