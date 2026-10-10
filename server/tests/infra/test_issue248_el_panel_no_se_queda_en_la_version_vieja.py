"""#248 — después de un despliegue, el panel no se queda en la versión anterior.

Le pasó al usuario el 2026-10-08: tras desplegar la edición de módulos en Personas, el botón
«Editar» no salió hasta forzar la recarga con Ctrl+F5. Un recargar normal no bastaba porque nginx
servía `index.html` **sin `Cache-Control`**, y sin cabecera el navegador lo guarda con su propia
heurística y no pregunta: el HTML viejo seguía pidiendo los ficheros viejos.

La regla que lo arregla es la estándar de un bundle con hash en el nombre:

* `index.html` con `no-cache` —se guarda, pero se revalida siempre—, porque es lo único que dice
  qué versión toca;
* `assets/` con `immutable` y un año, porque su nombre lleva el hash del contenido: si cambia el
  contenido cambia el nombre, y cachearlo para siempre es correcto.

La otra mitad —la pestaña que ya estaba abierta antes del despliegue— la cubre el aviso del panel
(`frontend/src/shared/version/`), y su test vive con él.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
NGINX = RAIZ / "frontend" / "nginx.conf"


def _bloque(texto: str, cabecera: str) -> str:
    """El cuerpo de un `location` concreto, sin los comentarios."""
    sin_comentarios = "\n".join(linea.split("#", 1)[0] for linea in texto.splitlines())
    m = re.search(re.escape(cabecera) + r"\s*\{([^}]*)\}", sin_comentarios)
    assert m, f"nginx.conf no tiene `{cabecera}`"
    return m.group(1)


def test_index_html_se_revalida_siempre() -> None:
    bloque = _bloque(NGINX.read_text(encoding="utf-8"), "location /panel/")
    assert re.search(r'add_header\s+Cache-Control\s+"?no-cache"?', bloque), (
        "Sin `Cache-Control: no-cache` en `/panel/`, el navegador guarda `index.html` con su "
        "heurística y un recargar normal sigue en la versión anterior al despliegue."
    )


def test_los_ficheros_con_hash_se_guardan_para_siempre() -> None:
    bloque = _bloque(NGINX.read_text(encoding="utf-8"), "location /panel/assets/")
    assert re.search(r"add_header\s+Cache-Control\s+\"[^\"]*immutable", bloque)
    # Un fichero con hash que no existe es un 404, no el `index.html`: servir HTML donde se
    # pidió un módulo JavaScript da un error de MIME que no dice nada a quien lo ve.
    assert re.search(r"try_files\s+\$uri\s+=404", bloque)
