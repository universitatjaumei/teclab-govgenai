"""
Deploy: cloud
Módulo: plataforma — los PAT son credenciales de máquina de la plataforma, y su pantalla vive
en `/plataforma/tokens` (PLAT.2). A nivel de router: aquí no hay ningún endpoint público.

Gestión de Personal Access Tokens (AUTH.3): emisión, listado y revocación. Solo
admin/partner pueden emitir PAT; el token plano se devuelve una única vez.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from server.app.api.deps import get_current_user, get_session, require_module
from server.app.core.auth.models import UserInfo
from server.app.core.auth.pat.scopes import UnknownScopeError, allowed_scopes_for
from server.app.core.auth.pat.service import (
    PatForbiddenError,
    PatInvalidError,
    PatOrganizacionDesconocidaError,
    PatService,
)
from server.app.modules.agents_hub.database.config_models import HubOrganizacion

router = APIRouter(
    prefix="/auth/pats",
    tags=["auth-pat"],
    dependencies=[Depends(require_module("plataforma"))],
)


class PatCreateRequest(BaseModel):
    name: str
    scopes: list[str]
    expires_at: datetime | None = None
    # MT.5, #230: acota el token a una organización. Lo necesita lo que se acota por ella —el
    # registro de actividad— cuando lo emite un superadmin, que las ve todas.
    organizacion_id: uuid.UUID | None = None


class PatCreatedResponse(BaseModel):
    id: uuid.UUID
    token: str  # texto plano — único momento en que se devuelve
    token_prefix: str
    name: str
    scopes: list[str]
    expires_at: datetime | None = None
    organizacion_id: uuid.UUID | None = None


class PatView(BaseModel):
    id: uuid.UUID
    name: str
    token_prefix: str
    scopes: list[str]
    created_at: datetime
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    organizacion_id: uuid.UUID | None = None


@router.post(
    "",
    response_model=PatCreatedResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createPat",
)
async def create_pat(
    body: PatCreateRequest,
    user: UserInfo = Depends(get_current_user),
    session=Depends(get_session),
) -> PatCreatedResponse:
    try:
        pat, token = await PatService(session).create(
            owner=user,
            name=body.name,
            scopes=body.scopes,
            expires_at=body.expires_at,
            organizacion_id=body.organizacion_id,
        )
    except UnknownScopeError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "UNKNOWN_SCOPE", "reason": str(exc)},
        )
    except PatForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PAT_FORBIDDEN", "reason": str(exc)},
        )
    except PatOrganizacionDesconocidaError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "ORGANIZACION_DESCONOCIDA", "reason": str(exc)},
        )
    return PatCreatedResponse(
        id=pat.id,
        token=token,
        token_prefix=pat.token_prefix,
        name=pat.name,
        scopes=list(pat.scopes),
        expires_at=pat.expires_at,
        organizacion_id=pat.organizacion_id,
    )


class PatOrganizacion(BaseModel):
    id: uuid.UUID
    nombre: str


class PatOpciones(BaseModel):
    """Lo que puede elegir quien emite un token: lo dice el servidor, no la pantalla (#230)."""

    scopes: list[str]
    organizaciones: list[PatOrganizacion]


@router.get("/opciones", response_model=PatOpciones, operation_id="getPatOpciones")
async def pat_opciones(
    user: UserInfo = Depends(get_current_user),
    session=Depends(get_session),
) -> PatOpciones:
    consulta = select(HubOrganizacion.id, HubOrganizacion.name).order_by(HubOrganizacion.name)
    if not user.is_superadmin:
        consulta = consulta.where(
            HubOrganizacion.id.in_([uuid.UUID(o) for o in user.organizacion_ids])
        )
    filas = (await session.execute(consulta)).all()
    return PatOpciones(
        scopes=sorted(allowed_scopes_for(user.role)),
        organizaciones=[PatOrganizacion(id=i, nombre=n) for i, n in filas],
    )


@router.get("", response_model=list[PatView], operation_id="listPats")
async def list_pats(
    user: UserInfo = Depends(get_current_user),
    session=Depends(get_session),
) -> list[PatView]:
    pats = await PatService(session).list_for(user)
    return [
        PatView(
            id=p.id,
            name=p.name,
            token_prefix=p.token_prefix,
            scopes=list(p.scopes),
            created_at=p.created_at,
            expires_at=p.expires_at,
            last_used_at=p.last_used_at,
            revoked_at=p.revoked_at,
            organizacion_id=p.organizacion_id,
        )
        for p in pats
    ]


@router.delete("/{pat_id}", status_code=status.HTTP_204_NO_CONTENT, operation_id="revokePat")
async def revoke_pat(
    pat_id: uuid.UUID,
    user: UserInfo = Depends(get_current_user),
    session=Depends(get_session),
) -> Response:
    try:
        await PatService(session).revoke(user, pat_id)
    except PatInvalidError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Access token not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
