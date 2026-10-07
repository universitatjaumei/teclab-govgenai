#!/usr/bin/env python3
"""Hook `SessionEnd` de Claude Code: anota la sesión en el registro de actividad IA (#230).

El registro por MCP es declarativo: Claude sólo anota un uso si alguien se lo pide, y un registro
de cumplimiento que depende de la memoria de cada uno se queda vacío. Este guion lo hace solo, una
vez por sesión, al cerrarla.

**Sólo metadatos, nunca la conversación.** Lee la transcripción únicamente para saber qué modelo
se usó; lo que se manda es cuándo, quién (un identificador opaco), la herramienta, la finalidad,
el modelo y las categorías de datos. El contrato del servidor rechaza cualquier campo de contenido.

**La finalidad y las categorías las declara el proyecto**, en `.claude/govgenai.json` (se busca
desde la carpeta de trabajo hacia arriba):

    {"finalidad": "Desarrollo de la plataforma", "categorias_datos": ["sin_datos_personales"],
     "agente": "opcional"}

Sin ese fichero no se registra, y se dice: una finalidad inventada aquí sería un dato del registro
que nadie declaró.

**Del entorno de la persona, nunca del repositorio:**
- `GOVGENAI_PAT_ACTIVIDAD`: un token con sólo `actividad:write`;
- `GOVGENAI_URL`: la plataforma, por omisión `https://normativa.uji.es`;
- `GOVGENAI_ACTOR`: el identificador de quien lo usa; si no está, uno opaco y estable derivado
  del usuario y el equipo, nunca el correo.

**Si algo falla, la sesión no se rompe**: el guion sale siempre con 0. Pero queda escrito, en
`~/.claude/govgenai-actividad.log` y en la salida de error, porque un registro que falla en
silencio es peor que no registrar: nadie lo echa en falta hasta la auditoría.

Sólo biblioteca estándar: se ejecuta con el Python que haya, sin instalar nada.
"""
from __future__ import annotations

import getpass
import hashlib
import json
import os
import platform
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERRAMIENTA = "claude-code"
URL_POR_OMISION = "https://normativa.uji.es"
FICHERO_DEL_PROYECTO = Path(".claude") / "govgenai.json"


def _registro_local() -> Path:
    return Path.home() / ".claude" / "govgenai-actividad.log"


def _anotar(mensaje: str) -> None:
    """Al registro local y a la salida de error. Nunca lleva el token."""
    linea = f"{datetime.now(timezone.utc).isoformat()} {mensaje}"
    print(linea, file=sys.stderr)
    try:
        destino = _registro_local()
        destino.parent.mkdir(parents=True, exist_ok=True)
        with destino.open("a", encoding="utf-8") as f:
            f.write(linea + "\n")
    except OSError:
        pass


def _declaracion_del_proyecto(desde: Path) -> dict | None:
    for carpeta in [desde, *desde.parents]:
        fichero = carpeta / FICHERO_DEL_PROYECTO
        if fichero.is_file():
            return json.loads(fichero.read_text(encoding="utf-8"))
    return None


def _modelo(transcripcion: str | None) -> str | None:
    """El último modelo que aparece en la transcripción. **Sólo eso**: el texto no se lee."""
    if not transcripcion:
        return None
    modelo = None
    try:
        # `errors="replace"`: una línea con bytes inválidos se salta, no tumba el registro.
        with open(transcripcion, encoding="utf-8", errors="replace") as f:
            for linea in f:
                try:
                    entrada = json.loads(linea)
                except ValueError:
                    continue
                mensaje = entrada.get("message") if isinstance(entrada, dict) else None
                if isinstance(mensaje, dict) and mensaje.get("model"):
                    modelo = mensaje["model"]
    except OSError:
        return None
    return modelo


def _actor() -> str:
    declarado = os.environ.get("GOVGENAI_ACTOR", "").strip()
    if declarado:
        return declarado
    huella = hashlib.sha256(f"{getpass.getuser()}@{platform.node()}".encode("utf-8")).hexdigest()
    return f"claude-code-{huella[:16]}"


def construir_evento(entrada: dict, declaracion: dict) -> dict:
    evento = {
        "ocurrido_en": datetime.now(timezone.utc).isoformat(),
        "actor": _actor(),
        "herramienta": HERRAMIENTA,
        "finalidad": declaracion["finalidad"],
        "categorias_datos": list(declaracion.get("categorias_datos") or []),
    }
    modelo = _modelo(entrada.get("transcript_path"))
    if modelo:
        evento["modelo_usado"] = modelo
    if declaracion.get("agente"):
        evento["agente"] = declaracion["agente"]
    return evento


def main() -> int:
    """Siempre 0: un fallo no imprevisto tampoco rompe la sesión, pero queda escrito."""
    try:
        _registrar()
    except Exception as fallo:  # noqa: BLE001 — la promesa es no romper la sesión y decirlo
        _anotar(f"fallo inesperado, no se registra: {type(fallo).__name__}: {fallo}")
    return 0


def _leer_entrada():
    """La entrada viene en UTF-8; en Windows, `sys.stdin` la leería con la página de códigos.

    Leyendo los bytes, una ruta con acentos llega entera y un BOM —el de PowerShell 5.1— se ignora.
    """
    tuberia = getattr(sys.stdin, "buffer", None)
    texto = tuberia.read().decode("utf-8-sig") if tuberia is not None else sys.stdin.read()
    return json.loads(texto)


def _registrar() -> None:
    try:
        entrada = _leer_entrada()
    except ValueError:
        entrada = None
    if not isinstance(entrada, dict):
        _anotar("no se pudo leer la entrada del hook: no se registra")
        return

    carpeta = Path(entrada.get("cwd") or os.getcwd())
    try:
        declaracion = _declaracion_del_proyecto(carpeta)
    except ValueError as fallo:
        _anotar(f"{FICHERO_DEL_PROYECTO} no es JSON válido en {carpeta}: {fallo}; no se registra")
        return
    if declaracion is not None and not isinstance(declaracion, dict):
        _anotar(f"{FICHERO_DEL_PROYECTO} tiene que ser un objeto JSON en {carpeta}: no se registra")
        return
    if not declaracion or not declaracion.get("finalidad"):
        _anotar(f"sin {FICHERO_DEL_PROYECTO} con «finalidad» en {carpeta} ni encima: no se registra")
        return
    categorias = declaracion.get("categorias_datos", [])
    if not isinstance(categorias, list) or not all(isinstance(c, str) for c in categorias):
        # Una cadena suelta acabaría troceada en letras: sería un dato que nadie declaró.
        _anotar(f"«categorias_datos» de {FICHERO_DEL_PROYECTO} tiene que ser una lista de códigos: no se registra")
        return

    token = os.environ.get("GOVGENAI_PAT_ACTIVIDAD", "").strip()
    if not token:
        _anotar("falta GOVGENAI_PAT_ACTIVIDAD (un token con actividad:write): no se registra")
        return

    url = os.environ.get("GOVGENAI_URL", URL_POR_OMISION).rstrip("/") + "/api/v1/actividad"
    evento = construir_evento(entrada, declaracion)
    peticion = urllib.request.Request(
        url,
        data=json.dumps(evento).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=10):
            pass
    except urllib.error.HTTPError as fallo:
        cuerpo = fallo.read().decode("utf-8", "replace")[:300]
        _anotar(f"el registro respondió {fallo.code} a la sesión {entrada.get('session_id')}: {cuerpo}")
    except (urllib.error.URLError, OSError) as fallo:
        _anotar(f"no se pudo hablar con {url}: {fallo}")


if __name__ == "__main__":
    sys.exit(main())
