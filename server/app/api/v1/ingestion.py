"""Endpoint de ingestión de documentos de usuario.

Deploy: edge
"""

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user
from server.app.core.auth import UserInfo
from server.app.core.auth.tenancy import assert_chatbot_org_access
from server.app.core.pdf_text import PdfSinCapaDeTexto
from server.app.core.uploads import UploadKind, validate_upload
from server.app.api.deps import get_session
from server.app.modules.agents_hub.ingestion.watcher import IngestionWatcher
from server.app.modules.agents_hub.services.embedding_resolver import (
    resolve_embedding_service,
)

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/user-upload", status_code=status.HTTP_201_CREATED)
async def user_upload(
    chatbot_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
    current_user: UserInfo = Depends(get_current_user),
) -> dict:
    """Procesa un PDF subido por el usuario y lo vectoriza como contexto temporal.

    Los chunks creados son visibles únicamente para el usuario que los subió.
    """
    # SEC.8.1: el `chatbot_id` venía del formulario y no se comprobaba, así que se podían
    # inyectar documentos —y gastar el servicio de embeddings— contra el chatbot de
    # cualquier organización. Los chunks quedan acotados al usuario, pero el trabajo y el
    # coste los pagaba el dueño del chatbot.
    await assert_chatbot_org_access(session, chatbot_id, current_user)

    # Validación compartida (SEC.6): extensión + magic bytes + corte por tamaño
    # durante la lectura. No se mira content_type: lo fija el cliente.
    validado = await validate_upload(file, kind=UploadKind.PDF)

    import shutil
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        shutil.copyfileobj(validado, tmp)
        tmp_path = tmp.name
    validado.close()

    try:
        watcher = IngestionWatcher(
            session=session,
            embedding_service=await resolve_embedding_service(session, chatbot_id),
        )
        try:
            chunks = await watcher.process_user_upload(
                source_url=tmp_path,
                chatbot_id=chatbot_id,
                owner_id=uuid.UUID(current_user.user_id),
            )
        except PdfSinCapaDeTexto as escaneado:
            # EXT.2: sin OCR, un escaneado no da texto. Se rechaza diciéndolo, en vez de
            # ingerir un documento vacío que luego nadie relaciona con esta subida: el
            # usuario preguntaría y el asistente no encontraría nada, sin ningún error
            # a la vista.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "PDF_WITHOUT_TEXT_LAYER", "message": str(escaneado)},
            ) from escaneado
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return {"chunks_created": len(chunks)}
