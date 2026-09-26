"""Endpoint de exportación de tareas como documento descargable.

GET /api/v1/hub/tasks/export/{run_id}[?fmt=markdown|pdf]
  Devuelve la interacción identificada por run_id como fichero
  Markdown o PDF. Solo el dueño de la tarea (o un admin) puede descargar.


Deploy: edge
"""

import io
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.app.api.deps import get_current_user
from server.app.core.auth import UserInfo
from server.app.core.auth.tenancy import assert_chatbot_org_access
from server.app.modules.agents_hub.database.connection import get_async_session
from server.app.modules.agents_hub.database.operational_models import HubInteraction

router = APIRouter(prefix="/hub/tasks", tags=["hub-tasks"])


@router.get("/export/{run_id}")
async def export_task(
    run_id: uuid.UUID,
    fmt: str = "markdown",
    user: UserInfo = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> Response:
    """Exporta el resultado de una tarea como documento descargable.

    Args:
        run_id: Identificador de la interacción (generado durante el chat).
        fmt: Formato de salida — "markdown" (por defecto) o "pdf".
        user: Usuario autenticado.
        session: Sesión de base de datos.

    Returns:
        Fichero Markdown o PDF con el contenido de la interacción.

    Raises:
        404: Si el run_id no existe.
        403: Si el usuario no es el dueño ni admin.
    """
    # `run_id` identifica una ejecución, así que esto devuelve una fila o ninguna. El `limit(1)`
    # no cambia el resultado: lo hace explícito, y de paso esta consulta deja de parecerse a un
    # recorrido de `hub_interactions` sin acotar (issue #159).
    result = await session.execute(
        select(HubInteraction).where(HubInteraction.run_id == run_id).limit(1)
    )
    interaction = result.scalar_one_or_none()
    if interaction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {run_id} not found",
        )

    # SEC.8.1: «eres el dueño o eres admin» no bastaba. Un admin es admin *de una
    # organización*, y la conversación exportada es un dato personal de un ciudadano que
    # habló con OTRA administración. Quien no es el dueño tiene que pertenecer, además, a
    # la organización del chatbot.
    if interaction.user_id != user.user_id:
        if user.role not in ("superadmin", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
            )
        await assert_chatbot_org_access(session, interaction.chatbot_id, user)

    markdown_text = _render_markdown(interaction)

    if fmt == "pdf":
        pdf_bytes = _render_pdf(markdown_text, run_id)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="task_{run_id}.pdf"'
            },
        )

    return Response(
        content=markdown_text.encode("utf-8"),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="task_{run_id}.md"'},
    )


def _render_markdown(interaction: HubInteraction) -> str:
    """Genera el Markdown de la conversación."""
    return (
        "# Conversación exportada\n\n"
        f"**ID de sesión**: {interaction.run_id}\n\n"
        "---\n\n"
        f"**Usuario**: {interaction.user_message}\n\n"
        f"**Asistente**:\n\n{interaction.assistant_message}\n"
    )


def _render_pdf(markdown_text: str, run_id: uuid.UUID) -> bytes:
    """Convierte el Markdown a PDF usando ReportLab."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        leftMargin=2.5 * cm,
        rightMargin=2.5 * cm,
    )
    styles = getSampleStyleSheet()
    story = []

    for line in markdown_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            story.append(Spacer(1, 0.3 * cm))
        elif stripped.startswith("# "):
            story.append(Paragraph(stripped[2:], styles["Title"]))
        elif stripped.startswith("## "):
            story.append(Paragraph(stripped[3:], styles["Heading2"]))
        elif stripped.startswith("---"):
            story.append(Spacer(1, 0.5 * cm))
        else:
            # Convertir **texto** en negrita para ReportLab
            formatted = stripped.replace("**", "<b>", 1).replace("**", "</b>", 1)
            story.append(Paragraph(formatted, styles["Normal"]))

    doc.build(story)
    return buffer.getvalue()
