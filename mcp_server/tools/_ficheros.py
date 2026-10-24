"""Lo que una herramienta del servidor stdio puede leer del equipo de quien la usa (#270).

Dos herramientas suben al catálogo de la organización un fichero cuya ruta les da el agente.
Sin mirar qué es, una errata —`~/.ssh/id_rsa` en vez del cuaderno— lo subía entero. Se
comprueban la extensión y el tamaño **antes de leer**, con los mismos límites que el servidor.
"""
from __future__ import annotations

from pathlib import Path


def fichero_local(ruta: str, *, extensiones: tuple[str, ...], maximo_bytes: int) -> Path:
    """La ruta, comprobada: existe, su extensión es una de las admitidas y no pasa del tope."""
    fichero = Path(ruta).expanduser()
    if fichero.suffix.lower() not in extensiones:
        raise ValueError(
            f"«{fichero.name}» no es un fichero que se pueda subir aquí: sólo "
            f"{', '.join(extensiones)}."
        )
    tamano = fichero.stat().st_size
    if tamano > maximo_bytes:
        raise ValueError(
            f"«{fichero.name}» pesa {tamano / 1024 / 1024:.1f} MB y el tope es "
            f"{maximo_bytes // 1024 // 1024} MB."
        )
    return fichero
