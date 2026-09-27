"""Endpoints de auditoría NER y configuración por workspace — Fase 13.2.

Deploy: edge

Dos endpoints:
- GET  /{workspace_id}/anonymization-summary  → AnonymizationSummaryResponse
- PATCH /{workspace_id}/anonymization-mode    → AnonymizationModeResponse

**Hubo un tercero y se retiró (issue #169).** `POST /re-analyze` devolvía **202 Accepted** con
`status: "queued"` y prometía en su docstring «dispara `InitAnonymizationNode`; el análisis se
encola en background». Lo que hacía era escribir un evento de auditoría y volver: ni
`BackgroundTasks`, ni cola, ni nodo — y nadie consumía el evento que dejaba.

Afirmar haber hecho algo es peor que no hacer nada: quien pulsaba el botón recibía «aceptado,
encolado», la pantalla no daba error, y el análisis no existía.

**La finalidad que el botón sí cumplía se conserva**, porque era otra: ver el resultado de una
anonimización ya aplicada, o el de la iteración anterior. Eso lo sirve el `GET` de aquí arriba
—desde la issue #98 cada ejecución escribe su resumen en el manifiesto—, así que el botón pasó a
refrescar esa vista y no hubo que implementar ninguna cola para anunciarla.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user, get_session, require_module
from server.app.core.auth.models import UserInfo
from server.app.routers.redaccion._actor import es_propietario
from server.app.modules.redaccion.database.models import (
    HubRunManifest,
    HubWorkspace,
    HubWorkspaceAuditEvent,
)
from server.app.modules.redaccion.services.anonymization.politica import (
    modo_efectivo,
    motivo_de_no_relajar,
)
from server.app.modules.redaccion.services.anonymization.run_context import (
    AnonymizationMode,
    AnonymizationSummary,
)

router = APIRouter(prefix="/redaccion/workspaces", tags=["redaccion-anonymization"],
    # INF.7 — el modulo se exige a nivel de router: asi no se puede olvidar en un
    # endpoint nuevo del mismo fichero, que es como se abrieron los agujeros que SEC.8.1
    # tuvo que cerrar uno a uno.
    dependencies=[Depends(require_module("informes"))],
)

_LOCKED_STATUSES = frozenset({"drafting", "in_review", "assembled", "exported"})


# ---------------------------------------------------------------------------
# DTOs
# ---------------------------------------------------------------------------


class AnonymizationSummaryResponse(BaseModel):
    """Resumen de la última ejecución + modo activo en el workspace."""

    mode: AnonymizationMode
    counts_by_type: dict[str, int]
    total_spans: int
    last_run_at: datetime
    current_workspace_mode: AnonymizationMode


class AnonymizationModeUpdate(BaseModel):
    mode: AnonymizationMode


class AnonymizationModeResponse(BaseModel):
    workspace_id: uuid.UUID
    mode: AnonymizationMode
    updated_at: datetime
    #: AIS.5 — por qué el modo aplicado no es el pedido, o `None` si sí lo es. Va en el contrato
    #: porque la regla la impone el servidor y el frontend no puede deducirla: sin esto, pedir
    #: `off` y seguir viendo `replace` se lee como una pantalla rota.
    motivo: str | None = None




# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_workspace_checked(
    workspace_id: uuid.UUID,
    user: UserInfo,
    session: AsyncSession,
) -> HubWorkspace:
    """Carga el workspace y verifica que quien pregunta es su dueño.

    SEC.8.1: antes bastaba con ser admin *de cualquier organización*. Los workspaces de
    redacción son por usuario y contienen datos personales del expediente —lo que este
    router expone es precisamente el resumen de PII detectada y el modo de anonimización—,
    así que un bypass por rol convertía a cualquier admin en lector del expediente ajeno.
    El resumen NER no se comparte por jerarquía: se comparte con quien lo generó.
    """
    workspace = await session.get(HubWorkspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Workspace not found")
    if not es_propietario(user.user_id, workspace.owner_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    return workspace


async def _modo_de_la_organizacion(
    workspace: HubWorkspace, session: AsyncSession
) -> AnonymizationMode | None:
    """El suelo que fija la organización del informe, o **`None` si no ha fijado ninguno** (AIS.5).

    Devuelve `None` y no el valor del código a propósito, y es la distinción que sostiene el
    prompt: `MODO_POR_DEFECTO` es un **valor por omisión**, no un mínimo. Si esta función
    resolviera «sin política» como `replace`, ese valor pasaría a ser un suelo y nadie podría
    elegir `off` en una instalación recién montada — la anonimización sería obligatoria con otro
    nombre, que es lo contrario de lo que se decidió.

    Se resuelve con una consulta y no navegando por una relación: `HubWorkspace` es operacional
    y `HubOrganizacion` es de configuración, y la frontera edge/cloud prohíbe `relationship()`
    entre las dos bases (`AGENTS.md` §Frontera Edge-Cloud).
    """
    from server.app.modules.agents_hub.database.config_models import HubOrganizacion

    if workspace.organizacion_id is None:
        return None

    organizacion = await session.get(HubOrganizacion, workspace.organizacion_id)
    declarado = getattr(organizacion, "anonymization_mode", None)
    return AnonymizationMode(declarado) if declarado else None


async def _get_last_manifest(
    workspace_id: uuid.UUID,
    session: AsyncSession,
) -> HubRunManifest | None:
    """Devuelve el último HubRunManifest para el workspace, o None si no existe."""
    stmt = (
        select(HubRunManifest)
        .where(HubRunManifest.workspace_id == workspace_id)
        .order_by(HubRunManifest.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{workspace_id}/anonymization-summary",
    response_model=AnonymizationSummaryResponse,
    operation_id="getAnonymizationSummary",
)
async def get_anonymization_summary(
    workspace_id: uuid.UUID,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AnonymizationSummaryResponse:
    """Devuelve el resumen NER del último run (sin originales ni sintéticos).

    - 200: resumen disponible.
    - 404: no hay run ejecutado todavía para este workspace.
    - 403: usuario no es owner.

    **El «ni admin/superadmin» que decía esta línea llevaba obsoleto desde SEC.8.1** y no era
    inocuo: describía un bypass por rol que ya no existe, y el panel del frontend lo creyó —hacía
    `if (!isAdmin) return null`, o sea enseñaba la pantalla exactamente a quien el servidor
    responde 403 y se la escondía a quien sí puede verla—. Ver la issue #98.
    """
    workspace = await _get_workspace_checked(workspace_id, user, session)
    manifest_orm = await _get_last_manifest(workspace_id, session)

    if manifest_orm is None:
        raise HTTPException(
            status_code=404,
            detail="No run has been executed for this workspace yet",
        )

    # Extrae el summary del payload del manifest.
    payload = manifest_orm.payload_json or {}
    raw_summary = payload.get("anonymization_summary")
    if raw_summary is None:
        raise HTTPException(
            status_code=404,
            detail="No anonymization summary found for the last run",
        )

    summary = AnonymizationSummary.model_validate(raw_summary)
    return AnonymizationSummaryResponse(
        mode=summary.mode,
        counts_by_type=summary.counts_by_type,
        total_spans=summary.total_spans,
        last_run_at=manifest_orm.created_at,
        current_workspace_mode=AnonymizationMode(workspace.anonymization_mode),
    )


@router.patch(
    "/{workspace_id}/anonymization-mode",
    response_model=AnonymizationModeResponse,
    operation_id="patchAnonymizationMode",
)
async def patch_anonymization_mode(
    workspace_id: uuid.UUID,
    body: AnonymizationModeUpdate,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> AnonymizationModeResponse:
    """Cambia el modo de anonimización del workspace.

    **El informe endurece, no relaja** (AIS.5). El suelo lo pone la organización, porque el modo
    depende del contrato con el proveedor y del tipo de datos, y ninguna de las dos cosas es una
    decisión de quien redacta un informe concreto. Pedir un modo menos protector no es un error
    del cliente —la pantalla ofrece los cuatro— así que **no es un 4xx**: se aplica el suelo y se
    devuelve el motivo, que es lo que evita que alguien crea que la pantalla no funciona.

    - 200: modo actualizado (o mantenido, con `motivo` explicando por qué).
    - 422: workspace en ejecución (drafting/in_review/assembled/exported).
    - 403: usuario no es owner.
    """
    workspace = await _get_workspace_checked(workspace_id, user, session)

    if workspace.status in _LOCKED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="MODE_LOCKED_DURING_EXECUTION",
        )

    heredado = await _modo_de_la_organizacion(workspace, session)
    efectivo = modo_efectivo(heredado=heredado, pedido=body.mode)
    motivo = motivo_de_no_relajar(heredado=heredado, pedido=body.mode)

    old_mode = workspace.anonymization_mode
    workspace.anonymization_mode = efectivo.value
    updated_at = datetime.now(timezone.utc)

    audit_event = HubWorkspaceAuditEvent(
        workspace_id=workspace_id,
        block_id=None,
        event="anonymization_mode_changed",
        from_status=old_mode,
        to_status=efectivo.value,
        actor=user.user_id,
        # Se registra lo PEDIDO además de lo aplicado: si sólo constara el resultado, una
        # auditoría no podría distinguir «eligió replace» de «pidió off y el suelo lo subió».
        metadata_json={
            "old_mode": old_mode,
            "new_mode": efectivo.value,
            "modo_pedido": body.mode.value,
            # `None` cuando la organización no ha fijado política: es un dato distinto de
            # «fijó replace», y la auditoría tiene que poder distinguirlos.
            "modo_heredado": heredado.value if heredado else None,
        },
    )
    session.add(audit_event)
    await session.commit()

    return AnonymizationModeResponse(
        workspace_id=workspace_id,
        mode=efectivo,
        updated_at=updated_at,
        motivo=motivo,
    )


