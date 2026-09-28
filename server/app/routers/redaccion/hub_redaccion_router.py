"""Endpoints hub/redaccion — 9R.4.4 / 9R.7.2.

Deploy: edge
Template update notice, migración de workspaces, lectura de workspace/blocks/warnings.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import (
    get_current_user,
    get_session,
    require_role,
    require_scopes,
)
from server.app.api.deps import require_module
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import (
    orgs_del_principal,
    organizacion_unica_de,
    puede_acceder,
)
from server.app.routers.redaccion._actor import es_propietario, user_to_uuid
from server.app.modules.redaccion.contracts.template import ReportTemplateSpec
from server.app.modules.redaccion.contracts.ui import ReportUIContract
from server.app.modules.redaccion.database.models import (
    HubReportTemplate,
    HubReportTemplateVersion,
    HubWorkspace,
    HubWorkspaceBlock,
)
from server.app.modules.redaccion.database.repos import (
    ReportTemplateRepo,
    ReportTemplateVersionRepo,
    WorkspaceBlockRepo,
    WorkspaceRepo,
)
from server.app.modules.redaccion.services.campos_manuales import (
    con_los_campos_de_los_bloques,
)
from server.app.modules.redaccion.services.block_actions import (
    _DESTINO_DE_LA_ACCION,
    acciones_permitidas,
)
from server.app.modules.redaccion.services.estructura_del_informe import (
    bloques_sin_seccion,
    dependencias_imposibles,
)
from server.app.modules.redaccion.services.template_migration_service import (
    CompatibilityConflictError,
    NewVersionNotice,
    TemplateMigrationService,
    WorkspaceNotFoundError,
    WorkspaceOwnershipError,
)

router = APIRouter(prefix="/hub/redaccion", tags=["hub-redaccion"],
    # INF.7 — el modulo se exige a nivel de router: asi no se puede olvidar en un
    # endpoint nuevo del mismo fichero, que es como se abrieron los agujeros que SEC.8.1
    # tuvo que cerrar uno a uno.
    dependencies=[Depends(require_module("informes"))],
)

# ---------------------------------------------------------------------------
# DTOs — workspace / blocks / warnings (9R.7.2)
# ---------------------------------------------------------------------------

class BlockStateOut(BaseModel):
    block_id: str
    kind: str
    status: str
    content: dict | None = None
    failure_kind: str | None = None
    last_error_message: str | None = None
    retry_attempts: int = 0
    updated_at: datetime
    # INF.2 — lo que se puede hacer con este bloque, decidido en el servidor. El cliente itera
    # esta lista y no compara `status` con literales: comparándolos, un bloque de IA que falla
    # no era ni «pendiente» ni «aprobado» para la pantalla, así que bloqueaba el informe sin
    # ofrecer salida. Regla maestra nº2. Detalle en `services/block_actions.py`.
    acciones_permitidas: list[str] = []


def _estado_del_bloque(block: Any) -> BlockStateOut:
    """El DTO de un bloque, en un solo sitio.

    Se construía campo a campo en dos endpoints. Añadir `acciones_permitidas` a mano en los dos
    es justo cómo empiezan a divergir: uno lo trae y el otro no, y la pantalla se comporta
    distinto según de qué petición venga.
    """
    return BlockStateOut(
        block_id=block.block_id,
        kind=block.kind,
        status=block.status,
        content=block.content_json,
        failure_kind=block.failure_kind,
        last_error_message=block.last_error_message,
        retry_attempts=block.retry_attempts,
        updated_at=block.updated_at,
        acciones_permitidas=acciones_permitidas(kind=block.kind, status=block.status),
    )


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    template_version_id: uuid.UUID
    status: str
    blocks: list[BlockStateOut]
    created_at: datetime
    updated_at: datetime
    # INF.1 — qué slots tienen ya su fichero. Sin esto la pantalla no puede distinguir «falta el
    # dato de partida» de «ya se subió en la ejecución anterior», así que el camino único
    # obligaría a resubir el mismo fichero cada vez que se reejecuta un informe. Van solo los
    # `slot_id`, no las rutas: la pantalla necesita saber qué está satisfecho, no dónde vive.
    uploaded_slots: list[str] = []
    # Issue #86 — lo que ya se escribió en los campos manuales, para que la pantalla lo vuelva a
    # pintar. Sin esto, reejecutar un informe manda el formulario vacío y **borra** lo que había:
    # el endpoint de campos es un `PUT`, que es lo que permite vaciar uno a propósito.
    manual_inputs: dict[str, str] = {}


class BlockPatchRequest(BaseModel):
    action: Literal["approve", "reject", "regenerate"]
    note: str | None = None


class ExtractionWarningOut(BaseModel):
    block_id: str | None = None
    message: str
    kind: str
    severity: str = "warning"


_KIND_TO_SEVERITY: dict[str, str] = {
    "type_mismatch": "error",
    "validation_failed": "error",
    "low_confidence": "warning",
    "missing_data": "warning",
}

# INF.2 — el mapa de acción a estado vive en `block_actions`, con la máquina de estados.
# Estaba duplicado aquí y **discrepaba**: `regenerate` llevaba a `extracted` en este endpoint y
# a `ai_generated` en el validado de `workspaces_router`, así que el estado resultante dependía
# de por qué puerta se entrase.

# ---------------------------------------------------------------------------
# DTOs — templates / workspaces (9R.7.3)
# ---------------------------------------------------------------------------

#: MT.4 — el escalón de en medio de la escalera usuario → organización → plataforma.
OWNER_ORGANIZACION = "organizacion"


class TemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    report_profile: str
    owner_kind: str
    is_global: bool
    # MT.4 — de qué organización es, cuando lo es. Va en el contrato porque la pantalla tiene
    # que poder decir de quién es cada plantilla; deducirlo del `owner_kind` en el React sería
    # inventarlo.
    organizacion_id: uuid.UUID | None = None
    #: MT.4.2 — de dónde salió esta copia, si salió de alguna.
    derivado_de: uuid.UUID | None = None
    version_de_origen: int | None = None
    current_version_id: uuid.UUID | None = None
    created_at: datetime
    #: GUI.1 — retirada. La pantalla necesita distinguir «no está» de «está retirada».
    archived: bool = False


class TemplateCreateIn(BaseModel):
    name: str
    description: str | None = None
    report_profile: str = "GENERIC_REPORT"
    owner_kind: str = "platform"
    spec_json: dict = Field(default_factory=dict)


class TemplatePatchIn(BaseModel):
    """Lo que se puede cambiar de una plantilla **sin publicar una versión**.

    GUI.2 — el nombre y la descripción son de la plantilla; el contenido es de la versión, y las
    versiones son append-only. Renombrar no puede tocar los informes ya hechos.
    """

    name: str | None = Field(default=None, min_length=1)
    description: str | None = None

    @field_validator("name")
    @classmethod
    def _nombre_con_algo_dentro(cls, valor: str | None) -> str | None:
        """Un nombre en blanco deja una fila que nadie puede identificar en la lista."""
        if valor is None:
            return None
        limpio = valor.strip()
        if not limpio:
            raise ValueError("el nombre no puede estar en blanco")
        return limpio


class WorkspaceCreateIn(BaseModel):
    template_version_id: uuid.UUID


class WorkspaceCreatedOut(BaseModel):
    workspace_id: uuid.UUID


# ---------------------------------------------------------------------------
# DTOs — migrate (9R.4.4)
# ---------------------------------------------------------------------------

class MigrateRequest(BaseModel):
    target_version_id: uuid.UUID


class MigrateResponse(BaseModel):
    new_workspace_id: uuid.UUID


@router.get(
    "/templates",
    response_model=list[TemplateOut],
    operation_id="listTemplates",
)
async def list_templates(
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    include_archived: bool = False,
) -> list[TemplateOut]:
    """Lista plantillas globales + propias del usuario.

    GUI.1 — las archivadas quedan fuera por defecto. Esa es la razón de ser del archivado:
    quitarlas de la vista sin quitarlas de los informes que las usaron.
    """
    # MT.4 — tres niveles, y el de plataforma **se sigue viendo desde todas las
    # organizaciones**: es lo que permite que la Diputación comparta una plantilla, y en esta
    # base son 20 de 23 filas. Quitarlo al añadir el escalón de en medio habría sido cambiar
    # el comportamiento sin que nadie lo pidiera.
    visibles = [
        HubReportTemplate.is_global.is_(True),
        HubReportTemplate.owner_id == user_to_uuid(user.user_id),
    ]
    mias = orgs_del_principal(user)
    if mias:
        visibles.append(HubReportTemplate.organizacion_id.in_(mias))
    condiciones = [or_(*visibles)]
    if not include_archived:
        condiciones.append(HubReportTemplate.archived_at.is_(None))
    result = await session.execute(select(HubReportTemplate).where(and_(*condiciones)))
    return [_template_out(t) for t in result.scalars().all()]


def _template_out(t: HubReportTemplate) -> TemplateOut:
    return TemplateOut(
        id=t.id,
        name=t.name,
        description=t.description,
        report_profile=t.report_profile,
        owner_kind=t.owner_kind,
        is_global=t.is_global,
        organizacion_id=t.organizacion_id,
        derivado_de=t.derivado_de,
        version_de_origen=t.version_de_origen,
        current_version_id=t.current_version_id,
        created_at=t.created_at,
        archived=t.archived_at is not None,
    )


async def _plantilla_o_404(session: AsyncSession, template_id: uuid.UUID) -> HubReportTemplate:
    plantilla = await session.get(HubReportTemplate, template_id)
    if plantilla is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return plantilla


def _exigir_admin(user: UserInfo) -> None:
    if user.role not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Only admin can manage templates")


def _exigir_poder_sobre(user: UserInfo, plantilla: HubReportTemplate) -> None:
    """Quién puede tocar **esta** plantilla, y no sólo «quién es administrador».

    Encontrado el 2026-08-24 al valorar la reutilización de plantillas entre municipios, y
    comprobado con tres tests: `_exigir_admin` sólo miraba el rol, y después
    `_plantilla_o_404` traía la plantilla **por id, sin comprobar de quién es**. O sea que
    cualquier administrador podía renombrar la plantilla de plataforma, **archivarla** —lo que
    la saca de la lista de todos y bloquea crear informes nuevos con ella (409
    `TEMPLATE_ARCHIVED`)— o renombrar la plantilla personal de otra persona.

    Con una sola organización no se nota. En el modelo Diputación→municipios significa que el
    administrador de un ayuntamiento retira la plantilla compartida de todos los demás.

    Es un agujero de hoy y no una función pendiente, así que se cierra ahora aunque el arreglo
    **completo** necesite la dimensión que MT.4 añade:

    - Una plantilla de plataforma la gestiona **sólo el superadministrador**: es de todos, y
      «de todos» no puede querer decir «de cualquiera».
    - Una plantilla de una persona, su dueño (o el superadministrador).
    - Un administrador **sin** relación con la plantilla, 403. Hoy no hay contra qué
      comprobarlo: las plantillas no tienen `organizacion_id` hasta MT.4, y hasta entonces
      «administrador» sólo significa «administrador de algún sitio». Cuando lo tengan, aquí
      entra el administrador de la organización dueña.
    """
    if user.role == "superadmin":
        return
    # MT.4 — lo que el arreglo del 2026-08-24 no pudo comprobar porque no había columna: un
    # administrador gestiona lo de **su** organización. Va antes que la comprobación del nivel
    # de plataforma porque una plantilla de organización no es de plataforma, y después que el
    # superadministrador porque ése no está acotado por diseño.
    if (
        plantilla.owner_kind == OWNER_ORGANIZACION
        and user.role == "admin"
        and puede_acceder(user, plantilla.organizacion_id)
    ):
        return
    if plantilla.is_global or plantilla.owner_kind in ("platform", "superadmin"):
        raise HTTPException(
            status_code=403,
            detail={
                "code": "PLANTILLA_DE_PLATAFORMA",
                "message": (
                    "Esta plantilla es de la plataforma y la comparten todas las "
                    "organizaciones: sólo un superadministrador puede cambiarla o retirarla. "
                    "Bifúrcala si necesitas una versión propia de tu organización."
                ),
            },
        )
    if plantilla.owner_id is not None and plantilla.owner_id == user_to_uuid(user.user_id):
        return
    raise HTTPException(
        status_code=403,
        detail={
            "code": "PLANTILLA_AJENA",
            "message": "Esta plantilla no es tuya.",
        },
    )


@router.patch(
    "/templates/{template_id}",
    response_model=TemplateOut,
    operation_id="patchTemplate",
)
async def patch_template(
    template_id: uuid.UUID,
    body: TemplatePatchIn,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TemplateOut:
    """Renombra una plantilla o cambia su descripción (GUI.2).

    No publica versión: el contenido de una plantilla vive en sus versiones, que son
    append-only, y renombrar no puede alterar un informe ya generado.
    """
    _exigir_admin(user)
    plantilla = await _plantilla_o_404(session, template_id)
    _exigir_poder_sobre(user, plantilla)

    if body.name is not None:
        plantilla.name = body.name
    if body.description is not None:
        plantilla.description = body.description
    await session.commit()

    # Los valores se leen tras un refresh explícito: `expire_on_commit` dejaría los atributos
    # expirados y leerlos aquí dispararía una recarga síncrona sobre asyncpg (MissingGreenlet,
    # el fallo de MAN.2 en el alta de plantillas).
    await session.refresh(plantilla)
    return _template_out(plantilla)


@router.delete(
    "/templates/{template_id}",
    status_code=204,
    operation_id="archiveTemplate",
)
async def archive_template(
    template_id: uuid.UUID,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """Retira una plantilla de las listas **sin borrarla** (GUI.1).

    Decisión del usuario, y es la correcta: un informe firmado no puede quedarse sin la
    plantilla con la que se hizo. Archivar es idempotente — quien pulsa dos veces no merece un
    error.
    """
    _exigir_admin(user)
    plantilla = await _plantilla_o_404(session, template_id)
    _exigir_poder_sobre(user, plantilla)
    if plantilla.archived_at is None:
        plantilla.archived_at = datetime.now(UTC)
        await session.commit()
    return Response(status_code=204)


@router.post(
    "/templates/{template_id}/fork",
    response_model=TemplateOut,
    status_code=201,
    operation_id="forkTemplate",
)
async def fork_template(
    template_id: uuid.UUID,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TemplateOut:
    """Copia una plantilla heredada al nivel de la organización de quien pide (MT.4).

    **Sin esto, «heredado» significaría «mírala y no la toques».** El arreglo del 2026-08-24
    dejó las plantillas de plataforma a mano sólo del superadministrador, y eso es correcto para
    *modificarlas* —son de todos— pero deja a un municipio sin forma de adaptar la de su
    Diputación. Adaptar es otra operación, y necesita su propia salida.

    **Copia, no mueve**: el original queda intacto para los demás. Y **se lleva la versión
    vigente**, porque una bifurcación sin contenido es una plantilla vacía con el nombre de otra
    — se abriría sin nada dentro y el fallo aparecería en el piloto, no aquí.

    Anota la procedencia (`derivado_de`, `version_de_origen`), que es lo que permite decir
    después «la Diputación ha publicado una v4 y tú te quedaste en la v3».
    """
    _exigir_admin(user)
    original = await _plantilla_o_404(session, template_id)

    destino = organizacion_unica_de(user)
    if destino is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SIN_ORGANIZACION_DESTINO",
                "message": (
                    "Bifurcar una plantilla la copia al nivel de una organización, y no hay "
                    "ninguna a la que copiarla: tu cuenta no pertenece a una sola. Elige la "
                    "organización antes de bifurcar."
                ),
            },
        )

    version = None
    if original.current_version_id is not None:
        version = await ReportTemplateVersionRepo(session).get(original.current_version_id)

    copia = HubReportTemplate(
        name=original.name,
        description=original.description,
        report_profile=original.report_profile,
        owner_kind=OWNER_ORGANIZACION,
        owner_id=user_to_uuid(user.user_id),
        organizacion_id=destino,
        derivado_de=original.id,
        version_de_origen=version.version if version is not None else None,
    )
    repo = ReportTemplateRepo(session)
    copia = await repo.save(copia)

    nueva_version_id = None
    if version is not None:
        nueva = await ReportTemplateVersionRepo(session).save(
            HubReportTemplateVersion(
                template_id=copia.id,
                version=1,
                spec_json=version.spec_json,
                created_by=user_to_uuid(user.user_id),
            )
        )
        # Capturado antes del commit: `expire_on_commit` lo dejaría expirado y leerlo después
        # es un `MissingGreenlet` (el fallo que VER.4 encontró cinco veces en este módulo).
        nueva_version_id = nueva.id
        await repo.update_status(copia.id, nueva_version_id)

    await session.commit()
    await session.refresh(copia)
    return _template_out(copia)


@router.post(
    "/templates/{template_id}/restore",
    response_model=TemplateOut,
    operation_id="restoreTemplate",
)
async def restore_template(
    template_id: uuid.UUID,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TemplateOut:
    """Devuelve a las listas una plantilla archivada por error."""
    _exigir_admin(user)
    plantilla = await _plantilla_o_404(session, template_id)
    _exigir_poder_sobre(user, plantilla)
    plantilla.archived_at = None
    await session.commit()
    await session.refresh(plantilla)
    return _template_out(plantilla)


@router.post(
    "/templates",
    response_model=TemplateOut,
    status_code=201,
    operation_id="createTemplate",
)
async def create_template(
    body: TemplateCreateIn,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> TemplateOut:
    """Crea plantilla + versión 1. Solo admin/superadmin."""
    if user.role not in ("superadmin", "admin"):
        raise HTTPException(status_code=403, detail="Only admin can create templates")

    template = HubReportTemplate(
        name=body.name,
        description=body.description,
        report_profile=body.report_profile,
        owner_kind=body.owner_kind,
        owner_id=user_to_uuid(user.user_id),
        # MT.4 — `organizacion_id` sólo cuando el nivel es de organización, que es lo que exige
        # el CHECK. En los demás niveles nulo: una de plataforma no es de ninguna, y una
        # personal se identifica por su dueño.
        organizacion_id=(
            organizacion_unica_de(user) if body.owner_kind == OWNER_ORGANIZACION else None
        ),
    )
    template_repo = ReportTemplateRepo(session)
    template = await template_repo.save(template)

    version = HubReportTemplateVersion(
        template_id=template.id,
        version=1,
        spec_json=body.spec_json,
        created_by=user_to_uuid(user.user_id),
    )
    version_repo = ReportTemplateVersionRepo(session)
    version = await version_repo.save(version)
    version_id = version.id  # antes del commit: expire_on_commit lo dejaría expirado

    await template_repo.update_status(template.id, version_id)
    await session.commit()
    await session.refresh(template)

    return TemplateOut(
        id=template.id,
        name=template.name,
        description=template.description,
        report_profile=template.report_profile,
        owner_kind=template.owner_kind,
        is_global=template.is_global,
        organizacion_id=template.organizacion_id,
        current_version_id=version_id,
        created_at=template.created_at,
    )


@router.post(
    "/workspaces",
    response_model=WorkspaceCreatedOut,
    status_code=201,
    operation_id="createWorkspace",
)
async def create_workspace_endpoint(
    body: WorkspaceCreateIn,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceCreatedOut:
    """Crea workspace en estado draft para una versión de plantilla."""
    version = await ReportTemplateVersionRepo(session).get(body.template_version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Template version not found")

    # GUI.1 — retirada es retirada: una plantilla archivada sirve para consultar lo que se hizo
    # con ella, no para empezar algo nuevo. Sin esto, archivar sólo la escondería de la lista y
    # cualquier enlace guardado seguiría creando informes con ella.
    plantilla = await session.get(HubReportTemplate, version.template_id)
    if plantilla is not None and plantilla.archived_at is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "TEMPLATE_ARCHIVED",
                "message": (
                    f"La plantilla «{plantilla.name}» está retirada: no se pueden crear "
                    "informes nuevos con ella. Recupérala si la necesitas."
                ),
            },
        )

    workspace = HubWorkspace(
        template_version_id=body.template_version_id,
        owner_id=user_to_uuid(user.user_id),
        status="draft",
    )
    workspace = await WorkspaceRepo(session).save(workspace)
    await session.commit()
    await session.refresh(workspace)

    return WorkspaceCreatedOut(workspace_id=workspace.id)


@router.get(
    "/template-versions/{version_id}/ui-contract",
    response_model=ReportUIContract,
)
async def get_template_ui_contract(
    version_id: uuid.UUID,
    _user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> ReportUIContract:
    """Devuelve el ReportUIContract de una versión de plantilla.

    INF.1 — `required` de cada dropzone se **deriva del `input_contract` al servir**, no se
    confía al valor guardado. Las versiones son inmutables y las que ya existen se guardaron
    antes de que el campo existiera, así que leerlas tal cual daría `required=False` para un
    slot obligatorio y la pantalla volvería a dejar lanzar el informe sin datos. La fuente de
    verdad de qué es obligatorio es `input_contract.required_slots`; el campo del dropzone es
    la proyección que consume el cliente.
    """
    version = await ReportTemplateVersionRepo(session).get(version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Template version not found")
    spec = ReportTemplateSpec.model_validate(version.spec_json)

    obligatorios = {s.slot_id for s in spec.input_contract.required_slots}
    # Issue #86 — los campos de los bloques `USER_INPUT` se derivan aquí por lo mismo que el
    # `required` de arriba: las versiones son inmutables y la plantilla que tiene el problema ya
    # está sembrada, así que un arreglo que dependa de volver a sembrar no le llega.
    base = con_los_campos_de_los_bloques(spec)
    return base.model_copy(
        update={
            "dropzones": [
                dz.model_copy(update={"required": dz.slot_id in obligatorios})
                for dz in base.dropzones
            ]
        }
    )


@router.get(
    "/workspaces/{workspace_id}",
    response_model=WorkspaceOut,
    operation_id="getWorkspaceById",
)
async def get_workspace_by_id(
    workspace_id: uuid.UUID,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> WorkspaceOut:
    """Devuelve el workspace con todos sus bloques."""
    workspace = await WorkspaceRepo(session).get(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    # SEC.8.1: el usuario llegaba declarado y sin usar, así que cualquiera con el UUID leía
    # los bloques del expediente ajeno.
    if not es_propietario(user.user_id, workspace.owner_id):
        raise HTTPException(status_code=403, detail="Not the workspace owner")
    blocks = await WorkspaceBlockRepo(session).list(workspace_id)
    return WorkspaceOut(
        id=workspace.id,
        template_version_id=workspace.template_version_id,
        status=workspace.status,
        blocks=[
            _estado_del_bloque(b)
            for b in blocks
        ],
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
        uploaded_slots=sorted(workspace.inputs_json or {}),
        manual_inputs={
            str(k): str(v) for k, v in (workspace.manual_inputs_json or {}).items()
        },
    )


@router.patch(
    "/workspaces/{workspace_id}/blocks/{block_id}",
    response_model=BlockStateOut,
    operation_id="patchWorkspaceBlock",
)
async def patch_workspace_block(
    workspace_id: uuid.UUID,
    block_id: str,
    body: BlockPatchRequest,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> BlockStateOut:
    """Aprueba, rechaza o solicita regeneración de un bloque."""
    workspace = await WorkspaceRepo(session).get(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    # Aprobar un bloque es una decisión con firma: sin esta comprobación la tomaba
    # cualquiera sobre el expediente de otro.
    if not es_propietario(user.user_id, workspace.owner_id):
        raise HTTPException(status_code=403, detail="Not the workspace owner")
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

    # INF.2 — se hace cumplir **la misma lista que se anuncia**. Este endpoint escribía el
    # estado a pelo, sin consultar la máquina de estados: pedir «regenerar» sobre un bloque
    # pendiente de revisión lo movía a `extracted` en silencio, una transición que la tabla no
    # permite. Con la comprobación aquí, `acciones_permitidas` deja de ser decorativo — lo que
    # la pantalla no ofrece, el servidor no acepta.
    permitidas = acciones_permitidas(kind=block.kind, status=block.status)
    if body.action not in permitidas:
        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    f"No se puede {body.action!r} un bloque en estado {block.status!r}"
                ),
                "acciones_permitidas": permitidas,
            },
        )

    block.status = _DESTINO_DE_LA_ACCION[body.action]
    await session.commit()
    await session.refresh(block)
    return _estado_del_bloque(block)


@router.get(
    "/workspaces/{workspace_id}/warnings",
    response_model=list[ExtractionWarningOut],
    operation_id="getWorkspaceWarnings",
)
async def get_workspace_warnings(
    workspace_id: uuid.UUID,
    _user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> list[ExtractionWarningOut]:
    """Lista de avisos de extracción del workspace."""
    workspace = await WorkspaceRepo(session).get(workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return [
        ExtractionWarningOut(
            block_id=w.get("block_id"),
            message=w.get("message", ""),
            kind=w.get("kind", ""),
            severity=_KIND_TO_SEVERITY.get(w.get("kind", ""), "warning"),
        )
        for w in (workspace.warnings_json or [])
    ]


@router.get(
    "/workspaces/{workspace_id}/template-update-notice",
    response_model=NewVersionNotice,
    responses={204: {"description": "Workspace already at latest version"}},
)
async def template_update_notice(
    workspace_id: uuid.UUID,
    _user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> NewVersionNotice | Response:
    """Devuelve aviso de nueva versión disponible, o 204 si ya está alineado."""
    service = TemplateMigrationService(session)
    try:
        notice = await service.detect_new_version(workspace_id)
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found")

    if notice is None:
        return Response(status_code=204)
    return notice


@router.post(
    "/workspaces/{workspace_id}/migrate",
    response_model=MigrateResponse,
    status_code=201,
)
async def migrate_workspace(
    workspace_id: uuid.UUID,
    body: MigrateRequest,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> MigrateResponse:
    """Crea workspace nuevo contra target_version_id, archiva el antiguo."""
    service = TemplateMigrationService(session)
    try:
        new_workspace = await service.migrate_workspace(
            workspace_id,
            body.target_version_id,
            user_to_uuid(user.user_id),
        )
    except WorkspaceNotFoundError:
        raise HTTPException(status_code=404, detail="Workspace not found")
    except WorkspaceOwnershipError:
        raise HTTPException(
            status_code=403,
            detail="Only the workspace owner can trigger migration",
        )
    except CompatibilityConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={"compatibility_errors": exc.compatibility_errors},
        )

    return MigrateResponse(new_workspace_id=new_workspace.id)


# ---------------------------------------------------------------------------
# DTOs — autoría de plantillas vía MCP (MCP.2)
# ---------------------------------------------------------------------------

class TemplateVersionOut(BaseModel):
    id: uuid.UUID
    template_id: uuid.UUID
    version: int
    spec: dict


class PublishVersionIn(BaseModel):
    spec_json: dict


class PublishVersionOut(BaseModel):
    template_id: uuid.UUID
    version: int
    version_id: uuid.UUID | None = None
    published: bool


# ---------------------------------------------------------------------------
# Endpoints — autoría de plantillas vía MCP (MCP.2)
# ---------------------------------------------------------------------------

@router.get("/template-schema", operation_id="getTemplateSchema")
async def get_template_schema(
    _user: UserInfo = Depends(require_scopes("redaccion:templates:read")),
) -> dict:
    """JSON Schema de ReportTemplateSpec.

    Alimenta el resource ``govgenai://redaccion/template-schema`` del servidor MCP:
    Claude redacta los drafts de plantilla directamente contra este contrato.
    """
    return ReportTemplateSpec.model_json_schema()


@router.get(
    "/template-versions/{version_id}",
    response_model=TemplateVersionOut,
    operation_id="getTemplateVersion",
)
async def get_template_version(
    version_id: uuid.UUID,
    user: UserInfo = Depends(require_scopes("redaccion:templates:read")),
    session: AsyncSession = Depends(get_session),
) -> TemplateVersionOut:
    """Devuelve la spec completa de una versión de plantilla."""
    version = await ReportTemplateVersionRepo(session).get(version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Template version not found")
    # SEC.8.1: el listado de plantillas ya filtra por `owner_id`, pero esta lectura por
    # id no lo hacía, así que la `spec` completa de una plantilla privada ajena se servía
    # a cualquiera con el UUID de la versión.
    plantilla = await session.get(HubReportTemplate, version.template_id)
    if plantilla is None or not es_propietario(user.user_id, plantilla.owner_id):
        raise HTTPException(status_code=404, detail="Template version not found")
    return TemplateVersionOut(
        id=version.id,
        template_id=version.template_id,
        version=version.version,
        spec=version.spec_json,
    )


@router.post(
    "/templates/{template_id}/versions",
    response_model=PublishVersionOut,
    status_code=201,
    operation_id="publishTemplateVersion",
)
async def publish_template_version(
    template_id: uuid.UUID,
    body: PublishVersionIn,
    dry_run: bool = False,
    user: UserInfo = Depends(require_role("superadmin", "admin")),
    _scope: UserInfo = Depends(require_scopes("redaccion:templates:write")),
    session: AsyncSession = Depends(get_session),
) -> PublishVersionOut:
    """Publica una nueva versión de plantilla (append-only).

    Nunca muta una versión existente: añade la siguiente. ``dry_run=True`` valida
    la spec contra ``ReportTemplateSpec`` y calcula la versión resultante SIN
    persistir.
    """
    template = await ReportTemplateRepo(session).get(template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")

    try:
        spec = ReportTemplateSpec.model_validate(body.spec_json)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=json.loads(exc.json()))

    # SEG.5 — un bloque que ninguna sección enumera no se pinta. Se rechaza aquí porque es el
    # único momento en que avisar sirve de algo: después, el informe sale con las secciones
    # vacías y sin nada que lo explique.
    huerfanos = bloques_sin_seccion(spec.sections, spec.blocks)
    if huerfanos:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Estos bloques no están en ninguna sección y no aparecerían en el informe: "
                f"{', '.join(huerfanos)}. Añádelos al `block_ids` de la sección "
                f"correspondiente."
            ),
        )

    # Issue #153 — una dependencia hacia adelante o un ciclo no rompen nada al ejecutar, y ése
    # es el problema: el apartado dependiente se redacta igual, apoyado en un bloque que todavía
    # no produjo nada. Se rechaza aquí por la misma razón que lo de arriba — después ya es tarde,
    # y validarlo al leer rompería las plantillas que ya están guardadas.
    imposibles = dependencias_imposibles(spec.blocks)
    if imposibles:
        raise HTTPException(
            status_code=422,
            detail=(
                "Esta plantilla declara dependencias que no se pueden cumplir: "
                + "; ".join(imposibles)
                + ". Coloca cada bloque después de aquellos de los que depende."
            ),
        )

    version_repo = ReportTemplateVersionRepo(session)
    existing = await version_repo.list(template_id)
    next_version = (existing[-1].version + 1) if existing else 1

    if dry_run:
        return PublishVersionOut(
            template_id=template_id, version=next_version, published=False
        )

    new_version_id = uuid.uuid4()
    new_version = HubReportTemplateVersion(
        id=new_version_id,
        template_id=template_id,
        version=next_version,
        spec_json=body.spec_json,
        created_by=user_to_uuid(user.user_id),
    )
    await version_repo.save(new_version)
    await ReportTemplateRepo(session).update_status(template_id, new_version_id)
    await session.commit()

    return PublishVersionOut(
        template_id=template_id,
        version=next_version,
        version_id=new_version_id,
        published=True,
    )
