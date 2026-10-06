"""CRUD de prompt templates por chatbot.

Deploy: cloud
Módulo: chatbots — una plantilla cuelga de un chatbot (`chatbot_id` NOT NULL).
"""

import uuid as _uuid
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import require_role, require_scopes
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import (
    assert_chatbot_org_access,
    orgs_del_principal,
)
from server.app.modules.agents_hub.database.config_models import (
    HubChatbot,
    HubPromptTemplate,
)
from server.app.modules.agents_hub.database.connection import get_async_session

router = APIRouter(prefix="/hub/prompt-templates", tags=["hub-prompt-templates"])

_require_admin = require_role("superadmin", "admin")


def _chatbots_visibles(user: UserInfo):
    """Subconsulta con los chatbots cuyas plantillas puede ver este principal.

    SEC.8.1: la plantilla no tiene `organizacion_id`; cuelga del chatbot. Acotar el listado
    exige por tanto pasar por la tabla de chatbots, y hacerlo **en SQL**: filtrar después de
    leer traería a memoria los prompts de sistema de otras administraciones igual.
    """
    return select(HubChatbot.id).where(
        HubChatbot.organizacion_id.in_(orgs_del_principal(user))
    )


class PromptTemplateRead(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    chatbot_id: UUID
    slug: str
    language: str
    template_text: str
    version: int
    default_tier: int | None
    override_tier: int | None


class PromptTemplateCreate(BaseModel):
    chatbot_id: UUID
    slug: str
    language: str
    template_text: str
    default_tier: int | None = None
    override_tier: int | None = None


class PromptTemplateUpdate(BaseModel):
    template_text: str | None = None
    default_tier: int | None = None
    override_tier: int | None = None


@router.get("/", response_model=list[PromptTemplateRead], dependencies=[Depends(require_scopes("chatbots:read"))])
async def list_prompt_templates(
    chatbot_id: UUID | None = None,
    session: AsyncSession = Depends(get_async_session),
    user: UserInfo = Depends(_require_admin),
) -> list[HubPromptTemplate]:
    q = select(HubPromptTemplate).order_by(
        HubPromptTemplate.slug, HubPromptTemplate.language
    )
    if chatbot_id is not None:
        await assert_chatbot_org_access(session, chatbot_id, user)
        q = q.where(HubPromptTemplate.chatbot_id == chatbot_id)
    elif not user.is_superadmin:
        # Sin `chatbot_id` el listado devolvía las plantillas de TODOS los chatbots.
        q = q.where(HubPromptTemplate.chatbot_id.in_(_chatbots_visibles(user)))
    result = await session.execute(q)
    return list(result.scalars().all())


@router.post("/", response_model=PromptTemplateRead, status_code=status.HTTP_201_CREATED)
async def create_prompt_template(
    body: PromptTemplateCreate,
    session: AsyncSession = Depends(get_async_session),
    user: UserInfo = Depends(_require_admin),
) -> HubPromptTemplate:
    await assert_chatbot_org_access(session, body.chatbot_id, user)
    template = HubPromptTemplate(
        id=_uuid.uuid4(),
        chatbot_id=body.chatbot_id,
        slug=body.slug,
        language=body.language,
        template_text=body.template_text,
        version=1,
        default_tier=body.default_tier,
        override_tier=body.override_tier,
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return template


@router.patch("/{template_id}", response_model=PromptTemplateRead, dependencies=[Depends(require_scopes("chatbots:write"))])
async def update_prompt_template(
    template_id: UUID,
    body: PromptTemplateUpdate,
    session: AsyncSession = Depends(get_async_session),
    user: UserInfo = Depends(_require_admin),
) -> HubPromptTemplate:
    result = await session.execute(
        select(HubPromptTemplate).where(HubPromptTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    # El prompt de sistema decide cómo responde el asistente: escribir en el ajeno es
    # controlar el comportamiento del asistente de otra administración.
    await assert_chatbot_org_access(session, template.chatbot_id, user)

    if body.template_text is not None:
        template.template_text = body.template_text
        template.version += 1
    if body.default_tier is not None:
        template.default_tier = body.default_tier
    if body.override_tier is not None:
        template.override_tier = body.override_tier

    await session.commit()
    await session.refresh(template)
    return template


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_prompt_template(
    template_id: UUID,
    session: AsyncSession = Depends(get_async_session),
    user: UserInfo = Depends(_require_admin),
) -> None:
    result = await session.execute(
        select(HubPromptTemplate).where(HubPromptTemplate.id == template_id)
    )
    template = result.scalar_one_or_none()
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    await assert_chatbot_org_access(session, template.chatbot_id, user)
    await session.delete(template)
    await session.commit()
