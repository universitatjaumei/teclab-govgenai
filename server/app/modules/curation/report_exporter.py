"""Exportación del WebQualityReport a DOCX y PDF (9Q.8).

Deploy: edge.

Reutiliza el patrón python-docx de ExportService. Para PDF, se intenta
conversión con LibreOffice; si no está disponible, se devuelve el DOCX
con un aviso en los headers (degradación documentada).
"""
from __future__ import annotations

import asyncio
import io
import shutil
from typing import Any

from server.app.modules.curation.report_contracts import WebQualityReport

#: Cómo se llama el ejecutable de LibreOffice según el sistema. En Linux suele ser `libreoffice`
#: (con `soffice` como alias) y en Windows sólo existe `soffice`.
_EJECUTABLES_DE_LIBREOFFICE = ("soffice", "libreoffice")


def se_puede_convertir_a_pdf() -> bool:
    """Si esta máquina puede producir un PDF de verdad (CUR.8).

    Del usuario, tras descargar el informe: «al darle a descargar al pdf descarga un word. No es
    mucho problema. Podría descargarse solo word pero **o se quita el botón o se permite que la
    descarga sea en pdf**». Un botón que promete PDF y entrega DOCX es una promesa incumplida
    aunque el fichero salga bien etiquetado —eso lo arregló VER.7 y era lo mínimo, no la solución—.
    Así que el botón se ofrece **sólo cuando se puede cumplir**, y quien lo sabe es el servidor.

    Se comprueba con `which` y no intentando la conversión: preguntar cuesta microsegundos y
    convertir cuesta segundos.
    """
    return any(shutil.which(nombre) for nombre in _EJECUTABLES_DE_LIBREOFFICE)


class WebQualityReportExporter:
    """Exporta un WebQualityReport a bytes DOCX o PDF."""

    def __init__(self, storage: Any = None) -> None:
        self._storage = storage

    async def to_docx(self, report: WebQualityReport) -> bytes:
        """Genera un DOCX estructurado con los hallazgos del informe."""
        from docx import Document

        doc = Document()

        # Cabecera
        doc.add_heading(f"Informe de Auditoría Web — {report.site_name}", level=1)
        doc.add_paragraph(
            f"Fecha de generación: {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}"
        )
        doc.add_paragraph(f"Sitio ID: {report.site_id}")
        doc.add_paragraph("")

        # Resumen
        doc.add_heading("Resumen de hallazgos", level=2)
        if report.totals_by_type:
            for ft, count in sorted(report.totals_by_type.items()):
                doc.add_paragraph(f"• {ft}: {count}", style="List Bullet")
        else:
            doc.add_paragraph("No se encontraron hallazgos activos.")

        # Secciones por tipo
        for section in report.sections:
            doc.add_heading(f"{section.finding_type.upper()} ({len(section.findings)})", level=2)
            doc.add_paragraph(f"Recomendación: {section.recommendation}")

            for fv in section.findings:
                para = doc.add_paragraph(style="List Bullet")
                para.add_run(f"[{fv.severity.upper()}] ").bold = True
                para.add_run(fv.page_url or "—")
                if fv.related_page_url:
                    para.add_run(f" → {fv.related_page_url}")
                if fv.explanation:
                    doc.add_paragraph(f"    {fv.explanation}")

        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue()

    async def to_pdf(self, report: WebQualityReport) -> bytes:
        """Intenta convertir el DOCX a PDF vía LibreOffice.

        Si LibreOffice no está disponible, devuelve el DOCX como fallback
        (el caller debe inspeccionar el Content-Type de la respuesta).
        """
        import subprocess
        import tempfile
        import os

        docx_bytes = await self.to_docx(report)
        ejecutable = next(
            (nombre for nombre in _EJECUTABLES_DE_LIBREOFFICE if shutil.which(nombre)), None
        )
        if ejecutable is None:
            return docx_bytes

        def _convertir() -> bytes | None:
            """La conversión, entera y síncrona, para poder mandarla a un hilo.

            Va dentro de la función y no fuera porque el fichero temporal, la escritura y la
            lectura pertenecen al mismo bloque: sacar sólo el `subprocess.run` dejaría las dos
            operaciones de disco bloqueando el bucle igual, y son las que tardan con un informe
            grande.
            """
            with tempfile.TemporaryDirectory() as tmpdir:
                docx_path = os.path.join(tmpdir, "report.docx")
                pdf_path = os.path.join(tmpdir, "report.pdf")

                with open(docx_path, "wb") as fh:
                    fh.write(docx_bytes)

                result = subprocess.run(
                    [
                        ejecutable,
                        "--headless",
                        "--convert-to", "pdf",
                        "--outdir", tmpdir,
                        docx_path,
                    ],
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
                if result.returncode == 0 and os.path.exists(pdf_path):
                    with open(pdf_path, "rb") as fh:
                        return fh.read()
            return None

        try:
            # AIS.8 — en un hilo. Esto es `async def` y llamaba a LibreOffice de forma síncrona,
            # así que **bloqueaba el bucle de eventos hasta 30 segundos**: mientras un informe se
            # convertía, el servidor entero dejaba de atender peticiones. No es un detalle de
            # estilo, es la regla de asincronía total de AGENTS.md, y aquí el coste era medible.
            pdf = await asyncio.to_thread(_convertir)
            if pdf is not None:
                return pdf
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

        # Fallback: devuelve DOCX (degradación documentada — el router añade el header)
        return docx_bytes
