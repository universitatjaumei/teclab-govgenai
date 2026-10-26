"""Cabeceras de seguridad y superficie mínima (SEC.7, M5). Deploy: shared.

Dos cosas pequeñas que se notan el día de una auditoría y el día de un incidente.

**La documentación interactiva se apaga en producción.** `/docs` y `/openapi.json` publican
el mapa entero de la API —rutas de administración incluidas— a quien pase por ahí. En
desarrollo es la herramienta más útil que hay; en producción es un índice para quien busca
por dónde entrar. No es que oculte una vulnerabilidad: es que no hay razón para servirlo.

**Las cabeceras son las cuatro de siempre**, y cada una tapa algo concreto:

- `X-Content-Type-Options: nosniff` — que el navegador no adivine el tipo de un fichero
  subido y acabe ejecutando como script algo que se guardó como texto.
- `X-Frame-Options: DENY` + `frame-ancestors 'none'` — que una respuesta de la API no se
  enmarque. **Esto no protege el panel**: este middleware sólo envuelve lo que sirve FastAPI, y
  el documento del panel lo sirve el nginx de la imagen del frontend, que pone sus propias
  cabeceras (`frontend/nginx.conf`, desde el 2026-10-22; antes no ponía ninguna).
- `Referrer-Policy: strict-origin-when-cross-origin` — que un enlace saliente no se lleve la
  ruta completa, que en un panel de administración lleva identificadores dentro.
- `Strict-Transport-Security` **solo en producción**: enviarlo en desarrollo obligaría al
  navegador a exigir HTTPS en `localhost` durante meses, y el desarrollador que se lo coma
  no tiene forma evidente de deshacerlo.
"""
from __future__ import annotations

from typing import TypedDict

from starlette.middleware.base import BaseHTTPMiddleware

PRODUCCION = "production"

# CSP mínima para un panel que sirve su propio JS y habla con su propio origen. No incluye
# `script-src` estricto con nonce: el frontend es una SPA compilada por Vite y afinar eso sin
# poder probarlo en el navegador sería romper la aplicación a ciegas.
CSP_PANEL = "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"


def cabeceras_de_seguridad(entorno: str) -> dict[str, str]:
    cabeceras = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        "Referrer-Policy": "strict-origin-when-cross-origin",
        "Content-Security-Policy": CSP_PANEL,
    }
    if entorno == PRODUCCION:
        cabeceras["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return cabeceras


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Añade las cabeceras a toda respuesta, incluidas las de error.

    En el middleware y no en cada endpoint por lo de siempre: el endpoint que se escriba
    mañana las lleva sin que nadie se acuerde.
    """

    def __init__(self, app, entorno: str) -> None:
        super().__init__(app)
        self.cabeceras = cabeceras_de_seguridad(entorno)

    async def dispatch(self, request, call_next):
        respuesta = await call_next(request)
        for nombre, valor in self.cabeceras.items():
            # `setdefault`: si un endpoint ya puso la suya —el widget con su propia
            # `frame-ancestors`, cuando llegue— gana la del endpoint, que sabe más.
            respuesta.headers.setdefault(nombre, valor)
        return respuesta


class UrlsDeDocumentacion(TypedDict):
    docs_url: str | None
    redoc_url: str | None
    openapi_url: str | None


def urls_de_documentacion(entorno: str) -> UrlsDeDocumentacion:
    """Los tres argumentos de `FastAPI(...)` que apagan la documentación en producción."""
    if entorno == PRODUCCION:
        return {"docs_url": None, "redoc_url": None, "openapi_url": None}
    return {"docs_url": "/docs", "redoc_url": "/redoc", "openapi_url": "/openapi.json"}
