"""Consumo y cuota del actor efectivo (SEC.4). Deploy: edge.

Sin este endpoint, un 429 es indistinguible de una avería: la persona ve que el asistente ha
dejado de responder y no tiene forma de saber si se le acabó la cuota, cuánto le queda ni
cuándo se renueva. Contestarlo es la diferencia entre un límite y un fallo.

Devuelve **lo del actor efectivo**, no lo del dueño del PAT: cuando la petición llega por un
cliente de confianza, quien quiere saber cuánto le queda es la persona que pregunta.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user
from server.app.core.auth.delegated_actor import resolve_effective_actor
from server.app.core.auth.models import UserInfo
from server.app.core.quotas import consumo_de, limites_aplicables
from server.app.modules.agents_hub.database.config_models import HubChatbot, HubOrganizacion
from server.app.api.deps import get_session

router = APIRouter(prefix="/hub/usage", tags=["hub-usage"])


class CuotaOut(BaseModel):
    subject: str
    window: str
    limit: int
    used: int
    remaining: int


class UsoOut(BaseModel):
    actor: str
    delegated: bool
    quotas: list[CuotaOut]


@router.get("/me", response_model=UsoOut)
async def get_my_usage(
    request: Request,
    chatbot_id: uuid.UUID,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
) -> UsoOut:
    """Cuotas que le aplican al actor en este chatbot, y cuánto lleva gastado.

    Pide `chatbot_id` porque **no existe una cuota del usuario a secas**: los límites salen
    de la cascada del chatbot y su organización, así que la misma persona tiene distintos
    márgenes según con quién hable.
    """
    chatbot = await session.get(HubChatbot, chatbot_id)
    if chatbot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Chatbot not found"
        )

    actor = resolve_effective_actor(request, user)
    # La frontera de acceso, aquí también: si no puede hablar con el chatbot, tampoco puede
    # enterarse de cómo están configuradas sus cuotas.
    from server.app.core.auth.chatbot_access import assert_chatbot_access

    assert_chatbot_access(actor, chatbot, via="session")

    organizacion = await session.get(HubOrganizacion, chatbot.organizacion_id)

    cuotas = []
    for limite in limites_aplicables(actor, chatbot, organizacion):
        usados = await consumo_de(
            session, limite.subject_type, limite.subject_id, limite.ventana
        )
        cuotas.append(
            CuotaOut(
                subject=limite.subject_type,
                window=limite.ventana,
                limit=limite.limite,
                used=usados,
                remaining=max(0, limite.limite - usados),
            )
        )

    return UsoOut(actor=actor.subject_id, delegated=actor.delegated, quotas=cuotas)
