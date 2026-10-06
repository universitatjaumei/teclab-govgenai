"""Endpoints LLM-drafts — 9R.4.3.

Deploy: edge
Expone generación, validación y aprobación de ReportTemplateDraft.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user, get_session, require_module, require_role, require_scopes
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import organizacion_unica_de
from server.app.core.uploads import read_within_limit
from server.app.routers.redaccion._actor import (
    nombre_del_modelo,
    user_to_uuid as _user_to_uuid,
)
from server.app.modules.redaccion.contracts.drafts import (
    ReportTemplateDraft,
    ReportTemplateDraftValidationResult,
)
from server.app.modules.redaccion.database.models import (
    HubReportTemplate,
    HubReportTemplateVersion,
    HubWorkspace,
)
from server.app.modules.redaccion.database.repos import (
    ReportTemplateRepo,
    ReportTemplateVersionRepo,
    WorkspaceRepo,
)
from server.app.modules.agents_hub.services.model_factory import get_model_for_tier
from server.app.modules.redaccion.services.draft_validator import DraftValidator
from server.app.modules.redaccion.services.muestra_de_datos import (
    MuestraDeDatos,
    MuestraIlegibleError,
    resumen_de_la_muestra,
)
from server.app.modules.redaccion.services.llm_spec_service import (
    LLMSpecService,
    PropuestaInvalidaError,
)
from server.app.modules.redaccion.services.spec_builder import spec_desde_borrador

router = APIRouter(prefix="/redaccion/llm-drafts", tags=["redaccion-llm-drafts"],
    # INF.7 — el modulo se exige a nivel de router: asi no se puede olvidar en un
    # endpoint nuevo del mismo fichero, que es como se abrieron los agujeros que SEC.8.1
    # tuvo que cerrar uno a uno.
    dependencies=[Depends(require_module("informes"))],
)

_require_admin = require_role("superadmin", "admin")


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class ProposeRequest(BaseModel):
    prompt_nl: str
    mode: Literal["admin_template", "user_workspace"] = "user_workspace"
    # INF.4 — la estructura del fichero sobre el que va el informe, si quien lo pide la aportó.
    # Se obtiene de `POST /llm-drafts/sample`, que es quien lee el fichero y **anonimiza** los
    # valores: así lo que viaja al modelo ya está anonimizado y, además, la pantalla puede
    # enseñar exactamente qué se va a mandar antes de mandarlo.
    muestra: MuestraDeDatos | None = None


class ApproveAsTemplateRequest(BaseModel):
    draft: ReportTemplateDraft
    name: str
    is_global: bool = False


class ApproveAsTemplateResponse(BaseModel):
    template_id: uuid.UUID
    version_id: uuid.UUID
    name: str
    is_global: bool


class ApproveAsWorkspaceRequest(BaseModel):
    draft: ReportTemplateDraft
    name: str


class ApproveAsWorkspaceResponse(BaseModel):
    workspace_id: uuid.UUID
    template_id: uuid.UUID
    template_version_id: uuid.UUID
    name: str
    status: str


# ---------------------------------------------------------------------------
# LLM service dependency — override in production via app.dependency_overrides
# ---------------------------------------------------------------------------

async def get_llm_spec_service(
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(get_current_user),
) -> LLMSpecService:
    """El servicio de propuesta de plantillas, con el modelo de la cascada (VER.2).

    Era un stub que devolvía 503 siempre, así que la puerta de entrada natural del módulo
    —describir el informe y que la plantilla se proponga sola— estaba cerrada aunque
    `LLMSpecService` llevara escrito y probado desde 9R.

    El 503 se conserva para el caso que de verdad lo merece —no hay modelo configurado— y
    **con el motivo dentro**: es la diferencia entre «esto no está montado» y «esto está
    roto», y sin ella hay que ir al log del servidor para distinguirlas.
    """
    from server.app.modules.agents_hub.services.config_provider import LocalConfigProvider

    try:
        # MT.3 — el modelo de la organización de quien describe el informe.
        modelo = await get_model_for_tier(
            1,
            LocalConfigProvider(session),
            organizacion_id=organizacion_unica_de(current_user),
        )
    except Exception as fallo:  # noqa: BLE001
        raise HTTPException(
            status_code=503,
            detail=f"No hay modelo de redacción disponible: {fallo}",
        ) from fallo

    return LLMSpecService(modelo, nombre_del_modelo(modelo))


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/sample",
    response_model=MuestraDeDatos,
    operation_id="describeSampleFile",
)
async def describe_sample_file(
    file: UploadFile = File(...),
    _user: UserInfo = Depends(get_current_user),
) -> MuestraDeDatos:
    """La estructura de un fichero, con los valores de la muestra **ya anonimizados** (INF.4).

    Deploy: edge

    Existe porque pedirle a un modelo la estructura de un informe sobre un fichero cuyas
    columnas no ha visto es pedirle que adivine, y en las pruebas del 2026-08-20 adivinó mal.
    El legacy sí lo mandaba (`etl_factory`), anonimizado.

    Va aparte de `/propose` en vez de convertirlo en multipart por dos razones: `/propose`
    sigue siendo un contrato JSON para quien ya lo usa, y la pantalla puede **enseñar lo que se
    va a enviar** antes de enviarlo, que en una herramienta cuyos usuarios desconfían de mandar
    datos a un LLM no es un detalle.

    El fichero **no se guarda**: se lee, se resume y se descarta. Pero se lee **con tope**
    (SEC.9.6): que no se persista no impide que un fichero grande agote la memoria del proceso
    mientras se resume, y éste era el único `UploadFile` que quedó fuera de SEC.6 y SEC.8.2.
    """
    contenido = await read_within_limit(file)
    try:
        return resumen_de_la_muestra(contenido, file.filename or "sin-nombre")
    except MuestraIlegibleError as fallo:
        raise HTTPException(status_code=422, detail=str(fallo)) from fallo


@router.post("/propose", response_model=ReportTemplateDraft, operation_id="proposeLlmDraft")
async def propose(
    body: ProposeRequest,
    user: UserInfo = Depends(get_current_user),
    service: LLMSpecService = Depends(get_llm_spec_service),
) -> ReportTemplateDraft:
    """Genera un ReportTemplateDraft a partir de texto natural. Sin persistir."""
    owner_kind: Literal["admin", "user"] = (
        "admin" if user.role in ("superadmin", "admin") else "user"
    )
    try:
        return await service.propose_template(body.prompt_nl, owner_kind, muestra=body.muestra)
    except PropuestaInvalidaError as fallo:
        # 422 y no 500: la propuesta la hizo el modelo, y quien pidió el informe necesita
        # saber que puede reformular, no ver un error del servidor.
        raise HTTPException(
            status_code=422,
            detail=f"La propuesta del modelo no encaja con el contrato de plantilla: {fallo}",
        ) from fallo


@router.post(
    "/validate",
    response_model=ReportTemplateDraftValidationResult,
    operation_id="validateLlmDraft",
    dependencies=[Depends(require_scopes("redaccion:templates:read"))],
)
async def validate_draft(
    draft: ReportTemplateDraft,
    _: UserInfo = Depends(get_current_user),
) -> ReportTemplateDraftValidationResult:
    """Valida y normaliza un draft estructuralmente."""
    return DraftValidator().validate(draft)


@router.post(
    "/approve-as-template",
    response_model=ApproveAsTemplateResponse,
    operation_id="approveAsTemplate",
    dependencies=[Depends(require_scopes("redaccion:templates:write"))],
)
async def approve_as_template(
    body: ApproveAsTemplateRequest,
    user: UserInfo = Depends(_require_admin),
    session: AsyncSession = Depends(get_session),
) -> ApproveAsTemplateResponse:
    """Persiste el draft como plantilla. Admin o superadmin; **lo global, sólo la plataforma**.

    **La condición estaba invertida** (issue #90): era `user.role != "admin"`, y como
    `_require_admin` deja pasar a los dos roles, eso bloqueaba precisamente al
    superadministrador y **dejaba al administrador de organización escribir una fila de nivel
    plataforma** —`owner_kind="platform"`, nueve líneas más abajo— que ven todas las demás
    organizaciones. Un ámbito inferior escribiendo por encima del suyo, saltándose las dos capas
    de `docs/MULTITENENCIA.md`.

    Lo decía este mismo endpoint: global significa plataforma, y la plataforma es el
    superadministrador (`core/auth/models.py`: «gestiona la plataforma global»).

    **Se pregunta por la capacidad y no por la cadena del rol.** `user.role != "admin"` se queda
    corto en cuanto el conjunto de roles crece, y sin avisar; `is_superadmin` dice lo que se
    quiere comprobar.
    """
    if body.is_global and not user.is_superadmin:
        raise HTTPException(
            status_code=403,
            detail="Solo un superadministrador puede crear plantillas de plataforma",
        )

    result = DraftValidator().validate(body.draft)
    if not result.ok:
        raise HTTPException(
            status_code=422,
            detail=[
                {"loc": [e.field], "msg": e.message, "type": "value_error"}
                for e in result.errors
            ],
        )

    normalized = result.normalized_draft
    template_id = uuid.uuid4()
    version_id = uuid.uuid4()
    owner_uuid = _user_to_uuid(user.user_id)

    template = HubReportTemplate(
        id=template_id,
        name=body.name,
        report_profile=normalized.proposed_profile,
        # MT.4 — `is_global` dejó de ser columna: el nivel lo dice `owner_kind`, y «global»
        # significa nivel de plataforma. Antes se guardaban los dos, así que una plantilla
        # podía quedar como `owner_kind='superadmin'` **y** global a la vez, que son dos
        # niveles distintos escritos en la misma fila.
        owner_kind="platform" if body.is_global else user.role,
        owner_id=owner_uuid,
        current_version_id=version_id,
    )
    version = HubReportTemplateVersion(
        id=version_id,
        template_id=template_id,
        version=1,
        # La plantilla se guarda como plantilla, no como borrador: son formas distintas y
        # guardar el borrador dejaba la version inservible (VER.3).
        spec_json=spec_desde_borrador(normalized).model_dump(mode="json"),
        created_by=owner_uuid,
    )

    await ReportTemplateRepo(session).save(template)
    await ReportTemplateVersionRepo(session).save(version)
    await session.commit()

    return ApproveAsTemplateResponse(
        template_id=template_id,
        version_id=version_id,
        name=body.name,
        is_global=body.is_global,
    )


@router.post("/approve-as-workspace", response_model=ApproveAsWorkspaceResponse, operation_id="approveAsWorkspace")
async def approve_as_workspace(
    body: ApproveAsWorkspaceRequest,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ApproveAsWorkspaceResponse:
    """Crea plantilla privada + workspace en estado draft. Cualquier usuario autenticado."""
    result = DraftValidator().validate(body.draft)
    if not result.ok:
        raise HTTPException(
            status_code=422,
            detail=[
                {"loc": [e.field], "msg": e.message, "type": "value_error"}
                for e in result.errors
            ],
        )

    normalized = result.normalized_draft
    template_id = uuid.uuid4()
    version_id = uuid.uuid4()
    workspace_id = uuid.uuid4()
    owner_uuid = _user_to_uuid(user.user_id)

    template = HubReportTemplate(
        id=template_id,
        name=body.name,
        report_profile=normalized.proposed_profile,
        owner_kind="user",
        owner_id=owner_uuid,
        current_version_id=version_id,
    )
    version = HubReportTemplateVersion(
        id=version_id,
        template_id=template_id,
        version=1,
        # La plantilla se guarda como plantilla, no como borrador: son formas distintas y
        # guardar el borrador dejaba la version inservible (VER.3).
        spec_json=spec_desde_borrador(normalized).model_dump(mode="json"),
        created_by=owner_uuid,
    )
    # 9R.10.2: arrancamos en `ingesting` para que la UI sepa que el workspace
    # está listo para subir inputs. Cuando el usuario invoca POST /run el
    # estado pasa a `drafting`.
    workspace = HubWorkspace(
        id=workspace_id,
        template_version_id=version_id,
        owner_id=owner_uuid,
        status="ingesting",
    )

    await ReportTemplateRepo(session).save(template)
    await ReportTemplateVersionRepo(session).save(version)
    await WorkspaceRepo(session).save(workspace)
    await session.commit()

    return ApproveAsWorkspaceResponse(
        workspace_id=workspace_id,
        template_id=template_id,
        template_version_id=version_id,
        name=body.name,
        status="ingesting",
    )
