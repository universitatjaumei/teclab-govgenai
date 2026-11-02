"""La fecha de hoy y el curso académico, para el prompt de cualquier plantilla (#364).

Sin esto el modelo trata como futuros plazos ya pasados y no sabe qué curso es «este»: con los
tres modelos de producción, «¿contarán para el DOCENTIA 2025/2026 unas ponencias pendientes?» se
contestaba «sí, si se validan antes del 31 de julio de 2026» el 2 de noviembre de ese año.

Lo añade el `CoreGraph` y no una plantilla, para que llegue a todas, también a las de terceros
(PLG). Y va **al final** del contexto: la caché implícita de Gemini reutiliza el prefijo, que en el
contexto largo son decenas de miles de tokens de corpus, y una línea que cambia cada día puesta
delante lo invalidaría entero cada mañana.

Deploy: edge
"""
from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

_MESES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def fecha_de_hoy() -> date:
    """La fecha en Madrid, que es la de la institución y no la del contenedor (en UTC)."""
    return datetime.now(ZoneInfo("Europe/Madrid")).date()


def curso_academico(hoy: date) -> str:
    """De septiembre a agosto: el 2 de noviembre de 2026 es el curso 2026-27."""
    inicio = hoy.year if hoy.month >= 9 else hoy.year - 1
    return f"{inicio}-{(inicio + 1) % 100:02d}"


def linea_de_la_fecha(hoy: date) -> str:
    return (
        f"FECHA DE HOY: {hoy.day} de {_MESES[hoy.month - 1]} de {hoy.year} "
        f"(curso académico {curso_academico(hoy)}). Tenla en cuenta para saber si un plazo ya "
        "ha pasado y a qué curso se refiere quien pregunta."
    )
