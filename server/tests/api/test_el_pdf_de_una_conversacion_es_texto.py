"""Lo que alguien escribe en el chat sale en el PDF como texto, no como marcado de ReportLab.

`_render_pdf` metía cada línea en un `Paragraph`, que interpreta un marcado propio: `<img src=…>`
lee un fichero local del servidor y lo incrusta, y una etiqueta mal cerrada hace que la
exportación entera falle con un 500. El texto de las conversaciones lo escribe quien pregunta, así
que se escapa antes; la negrita que pone la propia exportación se añade después.
"""
from __future__ import annotations

import io
import uuid

import pdfplumber

from server.app.api.v1.hub_tasks import _render_pdf


def _texto(pdf: bytes) -> str:
    with pdfplumber.open(io.BytesIO(pdf)) as documento:
        return "\n".join(pagina.extract_text() or "" for pagina in documento.pages)


def test_should_not_interpret_markup_written_in_the_chat():
    markdown = (
        "# Conversación exportada\n\n"
        '**Usuario**: <img src="/etc/hostname" width="50" height="50"/> y <b>sin cerrar\n\n'
        "**Asistente**:\n\nUna respuesta con <font color='red'>marcado</font>.\n"
    )

    pdf = _render_pdf(markdown, uuid.uuid4())

    texto = _texto(pdf)
    assert "<img" in texto, texto
    assert "<b>sin cerrar" in texto, texto


def test_should_keep_the_bold_the_export_itself_adds():
    pdf = _render_pdf("**Usuario**: hola\n", uuid.uuid4())

    assert "Usuario" in _texto(pdf)
    assert "**" not in _texto(pdf)
