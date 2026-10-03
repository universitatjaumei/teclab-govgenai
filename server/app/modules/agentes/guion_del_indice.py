"""El guion de Apps Script que mantiene el índice de un agente, tal como lo sirve la plataforma (#174).

Deploy: edge.

**Es uno, no uno por unidad**: recorrer una carpeta, saltarse lo que no cambió y pedir el resumen
es igual para todas, y cambian los parámetros. Si cada unidad escribiera el suyo habría media
docena de guiones parecidos, ninguno auditado. Por eso vive aquí, versionado, y la plataforma lo
entrega con su huella: quien lo instala puede comprobar que es éste.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_CARPETA = Path(__file__).parent / "guion"


@dataclass(frozen=True)
class GuionDelIndice:
    version: str
    sha256: str
    codigo: str
    manifiesto: str


@lru_cache(maxsize=1)
def guion_del_indice() -> GuionDelIndice:
    """El guion y su manifiesto. Se leen una vez: van dentro de la imagen y no cambian sin desplegar."""
    bruto = (_CARPETA / "indice_desde_drive.gs").read_bytes()
    codigo = bruto.decode("utf-8")
    encontrada = re.search(r"const VERSION_DEL_GUION = '([^']+)';", codigo)
    if encontrada is None:
        raise RuntimeError("el guion no declara VERSION_DEL_GUION")
    return GuionDelIndice(
        version=encontrada.group(1),
        sha256=hashlib.sha256(bruto).hexdigest(),
        codigo=codigo,
        manifiesto=(_CARPETA / "appsscript.json").read_text(encoding="utf-8"),
    )
