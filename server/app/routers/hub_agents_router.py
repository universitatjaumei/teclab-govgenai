"""Router para operaciones de agentes sobre workspaces: exportación DOCX/ODT.

Deploy: edge
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user, get_session
from server.app.core.auth.models import UserInfo
from server.app.core.auth.tenancy import assert_chatbot_org_access
from server.app.core.storage import StorageService, get_storage_service
from server.app.modules.agents_hub.database.operational_models import HubInteraction
from server.app.modules.agents_hub.services.export_service import ExportService

router = APIRouter(prefix="/hub/agents", tags=["hub-agents"])


def get_export_service(
    storage: StorageService = Depends(get_storage_service),
) -> ExportService:
    """La exportación a DOCX/ODT, sobre el almacenamiento configurado (#274)."""
    return ExportService(storage=storage)


class ExportRequest(BaseModel):
    format: Literal["docx", "odt"] = "docx"


class ExportOut(BaseModel):
    download_url: str
    file_path: str
    size_bytes: int


@router.post(
    "/workspaces/{workspace_id}/export",
    response_model=ExportOut,
    operation_id="exportAgentWorkspace",
    status_code=status.HTTP_200_OK,
)
async def export_agent_workspace(
    workspace_id: str,
    body: ExportRequest,
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_session),
    service: ExportService = Depends(get_export_service),
) -> ExportOut:
    """Exporta el final_document de un workspace de agentes a DOCX u ODT.

    Requiere que el workspace tenga un final_document generado por el grafo LangGraph.
    Deploy: edge
    """
    # SEC.9.6 — antes esta consulta era `where(user_id == user.user_id).limit(1)`: **ignoraba el
    # `workspace_id` de la ruta** y devolvía una interacción cualquiera del usuario, presentada
    # como el workspace pedido. No era sólo un fallo de autorización: el DOCX exportado no era
    # el documento que se había pedido, y nada lo delataba.
    result = await session.execute(
        select(HubInteraction).where(
            HubInteraction.id == workspace_id,
            HubInteraction.user_id == user.user_id,
        )
    )
    interaction = result.scalar_one_or_none()
    if interaction is not None:
        # `hub_interactions` se acota por su chatbot (docs/MULTITENENCIA.md), así que la
        # propiedad no basta: la organización manda.
        await assert_chatbot_org_access(session, interaction.chatbot_id, user)

    if interaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No workspace found: {workspace_id}",
        )

    final_document = interaction.assistant_message or ""

    class _SimpleManifest:
        retrieved_chunks = []

    export_result = await service.export(
        workspace_id=workspace_id,
        final_document=final_document,
        run_manifest=_SimpleManifest(),
        format=body.format,
        theme=None,
    )

    return ExportOut(
        download_url=export_result.download_url,
        file_path=export_result.file_path,
        size_bytes=export_result.size_bytes,
    )
