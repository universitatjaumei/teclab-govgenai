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
        with open(transcripcion, encoding="utf-8") as f:
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
    try:
        entrada = json.load(sys.stdin)
    except ValueError:
        _anotar("no se pudo leer la entrada del hook: no se registra")
        return 0

    carpeta = Path(entrada.get("cwd") or os.getcwd())
    try:
        declaracion = _declaracion_del_proyecto(carpeta)
    except ValueError as fallo:
        _anotar(f"{FICHERO_DEL_PROYECTO} no es JSON válido en {carpeta}: {fallo}; no se registra")
        return 0
    if not declaracion or not declaracion.get("finalidad"):
        _anotar(f"sin {FICHERO_DEL_PROYECTO} con «finalidad» en {carpeta} ni encima: no se registra")
        return 0

    token = os.environ.get("GOVGENAI_PAT_ACTIVIDAD", "").strip()
    if not token:
        _anotar("falta GOVGENAI_PAT_ACTIVIDAD (un token con actividad:write): no se registra")
        return 0

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
    return 0


if __name__ == "__main__":
    sys.exit(main())
