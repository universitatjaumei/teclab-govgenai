"""Block transition endpoints — 9R.8.1.

Deploy: edge
Approve, reject, regenerate, edit blocks and resume workspace from review gate.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user, get_session, require_module
from server.app.core.auth.models import UserInfo
from server.app.core.storage import StorageService, get_storage_service
from server.app.core.uploads import read_within_limit, sanitizar_nombre
from server.app.routers.redaccion._actor import es_propietario, nombre_del_modelo
from server.app.modules.redaccion.contracts.runtime import BlockState, InvalidBlockTransitionError
from server.app.modules.redaccion.database.models import (
    HubWorkspace,
    HubWorkspaceAuditEvent,
    HubWorkspaceBlock,
)
from server.app.modules.redaccion.services.block_state_machine import (
    BlockStateMachine,
    BlockTransitionEvent,
)
from server.app.modules.redaccion.services.workspace_run_service import (
    InputsNotReadyError,
    WorkspaceRunService,
)
from server.app.modules.redaccion.contracts.preview import PreviewPayload
from server.app.modules.redaccion.services.preview_builder import (
    PendingBlocksError,
    PreviewBuilderService,
)
from server.app.modules.redaccion.database.repos import (
    RunManifestRepo,
    ReportTemplateVersionRepo,
    WorkspaceBlockRepo,
    WorkspaceRepo,
)

router = APIRouter(
    prefix="/redaccion/workspaces",
    tags=["redaccion-workspaces"],
    # SEC.9.6 — era el único router de `redaccion/` sin la guarda de módulo de INF.7. La
    # propiedad del informe sí se comprobaba (`es_propietario`), así que el impacto era
    # saltarse la frontera de módulos, no ver informes ajenos; pero un router que se salta la
    # frontera hace que la frontera dependa de qué fichero toques.
    dependencies=[Depends(require_module("informes"))],
)

_sm = BlockStateMachine()


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------

class BlockTransitionOut(BaseModel):
    block_id: str
    kind: str
    status: str
    content: dict | None = None
    updated_at: datetime


class EditBlockRequest(BaseModel):
    content: dict


class ResumeOut(BaseModel):
    workspace_id: uuid.UUID
    status: str


class InputUploadOut(BaseModel):
    slot_id: str
    filename: str
    storage_path: str
    size_bytes: int
    uploaded_at: datetime


class RunStartedOut(BaseModel):
    run_id: uuid.UUID
    workspace_id: uuid.UUID
    status: str  # queued | running | completed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _block_to_state(block: HubWorkspaceBlock) -> BlockState:
    return BlockState(
        block_id=block.block_id,
        kind=block.kind,
        status=block.status,  # type: ignore[arg-type]
        content=block.content_json,
        last_updated_by="user",
        updated_at=block.updated_at,
        failure_kind=block.failure_kind,  # type: ignore[arg-type]
        last_error_message=block.last_error_message,
        retry_attempts=block.retry_attempts,
    )


def _block_out(block: HubWorkspaceBlock) -> BlockTransitionOut:
    return BlockTransitionOut(
        block_id=block.block_id,
        kind=block.kind,
        status=block.status,
        content=block.content_json,
        updated_at=block.updated_at,
    )


async def _get_workspace(
    workspace_id: uuid.UUID,
    user: UserInfo,
    session: AsyncSession,
) -> HubWorkspace:
    workspace = await session.get(HubWorkspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not es_propietario(user.user_id, workspace.owner_id):
        raise HTTPException(status_code=403, detail="Not the workspace owner")
    return workspace


async def _get_block(
    workspace_id: uuid.UUID,
    block_id: str,
    session: AsyncSession,
) -> HubWorkspaceBlock:
    stmt = select(HubWorkspaceBlock).where(
        and_(
            HubWorkspaceBlock.workspace_id == workspace_id,
            HubWorkspaceBlock.block_id == block_id,
        )
    )
    result = await session.execute(stmt)
    block = result.scalar_one_or_none()
    if block is None:
        raise HTTPException(status_code=404, detail="Block not found")
    return block


async def _apply_transition(
    workspace_id: uuid.UUID,
    block_id: str,
    event: BlockTransitionEvent,
    user: UserInfo,
    session: AsyncSession,
) -> BlockTransitionOut:
    workspace = await _get_workspace(workspace_id, user, session)
    block = await _get_block(workspace_id, block_id, session)

    block_state = _block_to_state(block)
    try:
        new_state, audit = _sm.transition(block_state, event, actor=user.user_id)
    except InvalidBlockTransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    block.status = new_state.status
    block.updated_at = new_state.updated_at

    audit_event = HubWorkspaceAuditEvent(
        workspace_id=workspace.id,
        block_id=block.block_id,
        event=audit.event,
        from_status=audit.from_status,
        to_status=audit.to_status,
        actor=audit.actor,
    )
    session.add(audit_event)
    await session.commit()
    # `expire_on_commit` acaba de expirar los atributos del bloque, y construir la respuesta
    # leyéndolos dispara una recarga perezosa síncrona que revienta con `MissingGreenlet`.
    # Rompía las cuatro transiciones —aprobar, rechazar, regenerar y editar—, es decir, la
    # revisión entera. Tercera aparición del mismo patrón en este módulo.
    await session.refresh(block)

    return _block_out(block)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.patch(
    "/{workspace_id}/blocks/{block_id}/approve",
    response_model=BlockTransitionOut,
    operation_id="approveBlock",
)
async def approve_block(
    workspace_id: uuid.UUID,
    block_id: str,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BlockTransitionOut:
    """Aprueba un bloque en estado needs_review."""
    return await _apply_transition(workspace_id, block_id, BlockTransitionEvent.APPROVE, user, session)


@router.patch(
    "/{workspace_id}/blocks/{block_id}/reject",
    response_model=BlockTransitionOut,
    operation_id="rejectBlock",
)
async def reject_block(
    workspace_id: uuid.UUID,
    block_id: str,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BlockTransitionOut:
    """Rechaza un bloque en estado needs_review."""
    return await _apply_transition(workspace_id, block_id, BlockTransitionEvent.REJECT, user, session)


@router.patch(
    "/{workspace_id}/blocks/{block_id}/regenerate",
    response_model=BlockTransitionOut,
    operation_id="regenerateBlock",
)
async def regenerate_block(
    workspace_id: uuid.UUID,
    block_id: str,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BlockTransitionOut:
    """Solicita regeneración IA de un bloque rechazado (solo ese bloque)."""
    return await _apply_transition(workspace_id, block_id, BlockTransitionEvent.REGENERATE, user, session)


@router.patch(
    "/{workspace_id}/blocks/{block_id}/edit",
    response_model=BlockTransitionOut,
    operation_id="editBlock",
)
async def edit_block(
    workspace_id: uuid.UUID,
    block_id: str,
    body: EditBlockRequest,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BlockTransitionOut:
    """Sobreescribe el contenido de un bloque; registra el original en auditoría.

    SEG.4 — el evento de auditoría es el registro autoritativo, pero **ninguna superficie lo
    expone**, así que sin lo de abajo quien edita no puede consultar lo que la IA había
    propuesto ni volver atrás. Lo que se conserva en el contenido es una copia para la pantalla:

    - `original_ai_text`: lo que escribió **la IA**, no la edición anterior. Se fija la primera
      vez y no se vuelve a tocar.
    - `edited_by` / `edited_at`: sin autoría, una edición es un cambio anónimo y no la
      supervisión efectiva que exige P3.
    - La procedencia del modelo (`model_used`, `prompt_version`, alcance del contexto) sobrevive
      a la edición: es la evidencia de cómo se redactó, y se perdería al sobreescribir el
      contenido con lo que manda el cliente.

    El estado **no se toca**: editar no aprueba.
    """
    await _get_workspace(workspace_id, user, session)
    block = await _get_block(workspace_id, block_id, session)

    original_content = block.content_json or {}

    audit_event = HubWorkspaceAuditEvent(
        workspace_id=workspace_id,
        block_id=block.block_id,
        event="edit",
        from_status=block.status,
        to_status=block.status,
        actor=user.user_id,
        metadata_json={"original_content": original_content},
    )
    session.add(audit_event)

    ahora = datetime.now(timezone.utc)
    procedencia = {
        clave: original_content[clave]
        for clave in ("model_used", "prompt_version", "context_scope", "context_block_ids")
        if clave in original_content
    }
    original_de_la_ia = original_content.get("original_ai_text") or original_content.get("text")

    block.content_json = {
        **procedencia,
        **body.content,
        **({"original_ai_text": original_de_la_ia} if original_de_la_ia else {}),
        "edited_by": user.email,
        "edited_at": ahora.isoformat(),
    }
    block.updated_at = ahora

    await session.commit()
    # Mismo motivo que en `_apply_transition`: sin refrescar, leer los atributos del bloque
    # para la respuesta dispara una recarga síncrona y da 500.
    await session.refresh(block)
    return _block_out(block)


@router.post(
    "/{workspace_id}/resume",
    response_model=ResumeOut,
    operation_id="resumeWorkspace",
)
async def resume_workspace(
    workspace_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ResumeOut:
    """Reanuda el grafo de redacción desde la review gate.

    Cambiaba el estado a `drafting` y **no reanudaba nada** —el mismo hueco que tenía `/run`
    antes de VER.1—, así que aprobar los bloques y pulsar continuar dejaba el informe sin
    ensamblar y el workspace colgado.
    """
    workspace = await _get_workspace(workspace_id, user, session)

    if workspace.status != "in_review":
        raise HTTPException(
            status_code=422,
            detail=f"Workspace must be in 'in_review' state to resume, got '{workspace.status}'",
        )

    workspace.status = "drafting"

    audit_event = HubWorkspaceAuditEvent(
        workspace_id=workspace_id,
        block_id=None,
        event="resume",
        from_status="in_review",
        to_status="drafting",
        actor=user.user_id,
    )
    session.add(audit_event)
    await session.commit()

    background_tasks.add_task(generar_borrador_en_segundo_plano, workspace_id)

    return ResumeOut(workspace_id=workspace_id, status="drafting")


# ---------------------------------------------------------------------------
# 9R.10.2 — Upload de inputs y arranque de ejecución
# ---------------------------------------------------------------------------

@router.post(
    "/{workspace_id}/inputs/{slot_id}",
    response_model=InputUploadOut,
    status_code=status.HTTP_201_CREATED,
    operation_id="uploadWorkspaceInput",
)
async def upload_workspace_input(
    workspace_id: uuid.UUID,
    slot_id: str,
    file: UploadFile = File(...),
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_service),
) -> InputUploadOut:
    """Sube un archivo a un slot de inputs del workspace.

    El archivo se persiste en StorageService con clave
    `redaccion/{workspace_id}/inputs/{slot_id}/{filename}` y se registra una
    entrada en `HubWorkspace.inputs_json[slot_id]`. Si el slot ya tenía un
    archivo, se sobreescribe (los archivos previos quedan en storage como
    huérfanos hasta la limpieza periódica).
    """
    workspace = await _get_workspace(workspace_id, user, session)

    # SEC.8.2: el `filename` viene del cliente y se interpolaba en la clave tal cual, así
    # que un `../` escribía fuera del bucket; y `file.read()` sin tope se traga en memoria
    # lo que le manden.
    content = await read_within_limit(file)
    filename = sanitizar_nombre(file.filename) if file.filename else f"{slot_id}.bin"
    storage_path = f"redaccion/{workspace_id}/inputs/{slot_id}/{filename}"
    await storage.put(storage_path, content)

    uploaded_at = datetime.now(timezone.utc)
    entry = {
        "slot_id": slot_id,
        "filename": filename,
        "storage_path": storage_path,
        "size_bytes": len(content),
        "uploaded_at": uploaded_at.isoformat(),
    }

    # Diccionario **nuevo**, no el mismo mutado: SQLAlchemy detecta cambios por identidad
    # del atributo, así que mutar el JSONB en sitio y reasignar el mismo objeto no marca la
    # columna como sucia y **no emite UPDATE**. El endpoint devolvía 200 con la ruta del
    # fichero y `inputs_json` se quedaba vacío para siempre; visto en VER.4 cuando la
    # extracción no encontraba el Excel que se acababa de subir.
    previos = workspace.inputs_json if isinstance(workspace.inputs_json, dict) else {}
    workspace.inputs_json = {**previos, slot_id: entry}

    audit_event = HubWorkspaceAuditEvent(
        workspace_id=workspace_id,
        block_id=None,
        event="input_uploaded",
        from_status=workspace.status,
        to_status=workspace.status,
        actor=user.user_id,
        metadata_json={"slot_id": slot_id, "filename": filename, "size_bytes": len(content)},
    )
    session.add(audit_event)
    await session.commit()

    return InputUploadOut(
        slot_id=slot_id,
        filename=filename,
        storage_path=storage_path,
        size_bytes=len(content),
        uploaded_at=uploaded_at,
    )


class ManualInputsIn(BaseModel):
    """Lo que se escribió en los campos de los bloques `USER_INPUT` (issue #86)."""

    fields: dict[str, str]


class ManualInputsOut(BaseModel):
    fields: dict[str, str]


@router.put(
    "/{workspace_id}/fields",
    response_model=ManualInputsOut,
    operation_id="setWorkspaceFields",
)
async def set_workspace_fields(
    workspace_id: uuid.UUID,
    body: ManualInputsIn,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ManualInputsOut:
    """Guarda los valores de los campos manuales del informe (issue #86).

    Los bloques `USER_INPUT` estaban en el contrato de la plantilla y **no había dónde
    escribirlos ni dónde guardarlos**: la sección salía vacía en el informe del doctorado y
    nadie podía hacer nada. Este endpoint es el sitio donde se guardan.

    **Van a su propia columna y no a `inputs_json`**, que es la de los ficheros: `uploaded_slots`
    devuelve las claves de aquélla como ficheros ya subidos —así que un texto aparecería en la
    pantalla como un fichero— y el runner valida cada entrada como `InputArtifact`, con lo que
    además lo registraría como entrada corrupta.

    **Sustituye el conjunto entero**, no fusiona: un campo que se vacía tiene que quedar vacío,
    y fusionar dejaría el valor anterior vivo sin que nadie lo viera. Es un `PUT` por eso.

    Diccionario **nuevo** al asignar, por lo mismo que en la subida de ficheros: mutar el JSONB
    en sitio no marca la columna como sucia y el `UPDATE` no se emite.
    """
    workspace = await _get_workspace(workspace_id, user, session)

    valores = {str(k): str(v) for k, v in body.fields.items() if v is not None and str(v) != ""}
    workspace.manual_inputs_json = valores

    session.add(
        HubWorkspaceAuditEvent(
            workspace_id=workspace_id,
            block_id=None,
            event="fields_saved",
            from_status=workspace.status,
            to_status=workspace.status,
            actor=user.user_id,
            # Los nombres de los campos sí; lo escrito no, que puede ser dato personal y el
            # registro de auditoría no es sitio para guardarlo.
            metadata_json={"slot_ids": sorted(valores)},
        )
    )
    await session.commit()

    return ManualInputsOut(fields=valores)


@router.post(
    "/{workspace_id}/run",
    response_model=RunStartedOut,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="runWorkspace",
)
async def run_workspace(
    workspace_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> RunStartedOut:
    """Encola la ejecución del DraftingCoreGraph para el workspace.

    Transiciona `workspace.status` de `draft|ingesting` a `drafting` y **dispara el grafo en
    segundo plano** (VER.1). Hasta aquí solo hacía lo primero: devolvía un `run_id` que no
    identificaba nada y el informe no se generaba nunca, lo que desde el panel es
    indistinguible de un informe que tarda.
    """
    workspace = await _get_workspace(workspace_id, user, session)
    # El estado se lee **antes**: `start_run` hace `commit()`, que con `expire_on_commit`
    # expira los atributos de todos los objetos de la sesión, y leerlo después dispara una
    # recarga perezosa síncrona que revienta con `MissingGreenlet`. Es el mismo patrón que
    # tumbó `create_template` y ocho endpoints de `scripts_router` el 2026-08-14; aquí
    # convertía el 202 en un 500 y la generación no llegaba a encolarse nunca.
    estado_previo = workspace.status

    svc = WorkspaceRunService(session=session)
    try:
        # session.get ya está hecho por _get_workspace; start_run lo repite a
        # través del repo. En MVP es aceptable: el coste de un get adicional
        # es despreciable frente a la simplicidad del wire-up.
        #
        # INF.1 — `validate=True`. Iba apagado, así que un informe sin sus datos se encolaba,
        # respondía 202 y fallaba dentro del grafo: el usuario veía «Datos pendientes» y tres
        # warnings que solo aparecen volviendo atrás con el navegador. La guarda existía y
        # nadie la usaba.
        result = await svc.start_run(workspace_id, validate=True)
    except InputsNotReadyError as exc:
        # El detalle va **estructurado**: la pantalla tiene que poder señalar el campo que
        # falta, y para eso necesita el `slot_id`, no una frase que contenga el slot_id.
        raise HTTPException(
            status_code=422,
            detail={"missing_slots": exc.missing, "message": str(exc)},
        ) from exc

    audit_event = HubWorkspaceAuditEvent(
        workspace_id=workspace_id,
        block_id=None,
        event="run_started",
        from_status=estado_previo,
        to_status="drafting",
        actor=user.user_id,
        metadata_json={"run_id": str(result.run_id)},
    )
    session.add(audit_event)
    await session.commit()

    background_tasks.add_task(generar_borrador_en_segundo_plano, workspace_id)

    return RunStartedOut(
        run_id=result.run_id,
        workspace_id=workspace_id,
        status=result.status,
    )


async def generar_borrador_en_segundo_plano(workspace_id: uuid.UUID) -> None:
    """Ejecuta el grafo con **su propia sesión y su propio modelo**.

    La sesión de la petición ya está cerrada cuando corre esto —`BackgroundTasks` se ejecuta
    después de enviar la respuesta—, así que reutilizarla es usar algo que el ciclo de vida de
    FastAPI dio por terminado. Mismo patrón que la ingesta de documentos.

    Si el modelo no se puede construir, el fallo acaba en el workspace como cualquier otro:
    `ejecutar_borrador` no lanza, deja `status='error'` con el motivo. Un asistente sin modelo
    configurado tiene que decirlo en la pantalla, no en el log del servidor.
    """
    import logging

    from server.app.modules.redaccion.services.drafting_runner import (
        ejecutar_borrador,
        marcar_error,
    )

    # Nada de lo que pase aquí puede propagar: la respuesta ya se envió y una excepción en
    # una tarea de fondo no llega a ninguna parte salvo al log —o, con `TestClient`, al
    # resultado de una petición que no tiene nada que ver—.
    try:
        async for bg_session in get_session():
            try:
                # MT.3 — `None` es «nivel plataforma», y aquí es lo único honesto **por ahora**:
                # esto corre en una tarea de fondo, cuando la sesión de la petición ya se cerró,
                # y el workspace no tiene organización hasta MT.4. Va escrito y no omitido
                # porque el parámetro es obligatorio: así este sitio declara que no lo sabe, en
                # vez de resolver plataforma sin que nadie se entere.
                redactor = await _redactor_de_bloques(
                    bg_session, organizacion_id=None
                )
            except Exception as fallo:  # noqa: BLE001
                await marcar_error(workspace_id, bg_session, f"modelo no disponible: {fallo}")
                return
            await ejecutar_borrador(workspace_id, bg_session, llm_service=redactor)
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception(
            "No se pudo generar el borrador del workspace %s", workspace_id
        )


async def _redactor_de_bloques(session: AsyncSession, *, organizacion_id: Any = None):
    """Modelo de la cascada, adaptado al protocolo que espera el nodo de redacción.

    **AIS.2 — aquí se resuelven también las instrucciones.** Es el único sitio del camino de
    redacción donde hay sesión y organización a la vez, y por eso los dos prompts de SEG.2 se
    resuelven aquí y se entregan ya hechos: `generate()` corre dentro de un nodo del grafo y no
    debería tocar la base de datos. Sin esto el catálogo de actividades sería decorativo para
    estos dos —el override existiría en la tabla y no llegaría nunca al modelo—.
    """
    from server.app.modules.agents_hub.services.config_provider import LocalConfigProvider
    from server.app.modules.agents_hub.services.model_factory import get_model_for_tier
    from server.app.modules.redaccion.services.actividades_llm import (
        ActividadLLM,
        resolver_actividad,
    )
    from server.app.modules.redaccion.services.redactor_de_bloques import (
        PROMPT_RESUMEN_DE_RESULTADOS,
        PROMPT_VALORACION_DE_TENDENCIA,
        RedactorDeBloques,
    )

    proveedor = LocalConfigProvider(session)
    modelo = await get_model_for_tier(1, proveedor, organizacion_id=organizacion_id)

    # La clave del `dict` es el **identificador de plantilla** que viaja en el `spec` y en el
    # manifiesto, no la clave de la actividad: son dos vocabularios y el nodo habla el primero.
    por_plantilla = {
        PROMPT_VALORACION_DE_TENDENCIA: ActividadLLM.VALORACION_DE_TENDENCIA,
        PROMPT_RESUMEN_DE_RESULTADOS: ActividadLLM.RESUMEN_DE_RESULTADOS,
    }
    instrucciones = {}
    for plantilla_id, actividad in por_plantilla.items():
        resuelta = await resolver_actividad(
            actividad, proveedor, organizacion_id=organizacion_id
        )
        instrucciones[plantilla_id] = resuelta.template_text

    return RedactorDeBloques(
        modelo, nombre_del_modelo(modelo), instrucciones=instrucciones
    )


# ---------------------------------------------------------------------------
# 1C.3 — Vista previa imprimible
# ---------------------------------------------------------------------------

@router.get(
    "/{workspace_id}/preview",
    response_model=PreviewPayload,
    operation_id="getWorkspacePreview",
    responses={
        409: {"description": "Blocks pending review"},
        404: {"description": "Workspace not found"},
    },
)
async def get_workspace_preview(
    workspace_id: uuid.UUID,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_service),
) -> PreviewPayload:
    """Devuelve el PreviewPayload para vista previa e impresión.

    Deploy: edge
    Retorna 409 si hay bloques en estado distinto a approved/locked.
    """
    await _get_workspace(workspace_id, user, session)

    builder = _constructor_de_vista_previa(session, storage)
    try:
        return await builder.build_payload(workspace_id)
    except PendingBlocksError as exc:
        raise HTTPException(
            status_code=409,
            detail={"pending_block_ids": exc.pending_block_ids},
        ) from exc


def _constructor_de_vista_previa(session: AsyncSession, storage: Any):
    return PreviewBuilderService(
        workspace_repo=WorkspaceRepo(session),
        block_repo=WorkspaceBlockRepo(session),
        template_version_repo=ReportTemplateVersionRepo(session),
        manifest_repo=RunManifestRepo(session),
        # PRO.5 — la imagen de los gráficos vive en el almacén, no en la base de datos.
        storage_service=storage,
    )


_TIPO_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@router.get(
    "/{workspace_id}/export",
    operation_id="exportWorkspace",
    responses={
        200: {"content": {_TIPO_DOCX: {}}, "description": "El informe en DOCX"},
        409: {"description": "Blocks pending review"},
        404: {"description": "Workspace not found"},
    },
)
async def export_workspace(
    workspace_id: uuid.UUID,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    storage: StorageService = Depends(get_storage_service),
) -> Response:
    """Descarga el informe como DOCX.

    Deploy: edge

    PRO.5 — `ExportService` existía con sus tests desde 1C.3 y **ninguna ruta lo servía**, así
    que el informe no se podía exportar: la prueba manual del bloque VER —«abrir la exportación
    en Word y en Adobe»— no tenía de dónde descargar nada.

    Se sirve el DOCX y no un PDF a propósito: convertir a PDF necesita LibreOffice en la
    máquina, y VER.7 ya enseñó lo que pasa cuando se promete un PDF y se entrega un DOCX
    disfrazado.
    """
    await _get_workspace(workspace_id, user, session)

    from server.app.modules.redaccion.services.export_service import ExportService

    builder = _constructor_de_vista_previa(session, storage)
    try:
        contenido = await ExportService(builder=builder).export(workspace_id, format="docx")
    except PendingBlocksError as exc:
        raise HTTPException(
            status_code=409,
            detail={"pending_block_ids": exc.pending_block_ids},
        ) from exc

    return Response(
        content=contenido,
        media_type=_TIPO_DOCX,
        headers={
            "Content-Disposition": f'attachment; filename="informe_{workspace_id}.docx"'
        },
    )
