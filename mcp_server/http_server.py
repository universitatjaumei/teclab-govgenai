"""Servidor MCP remoto: streamable HTTP con el token de cada cliente (REG.4).

Es la «opción B» que el análisis previo dejó anotada en 2026-06-06 sin caso de uso (procedencia en `docs/MCP_SERVER.md` §8); el bloque REG lo
trajo. El servidor stdio de `server.py` **no cambia**: sigue siendo mono-usuario y sigue leyendo
`GOVGENAI_PAT` del entorno, que ahí es lo correcto —un proceso, una persona, un token—.

**Lo que cambia aquí es de dónde sale la credencial.** Un servicio remoto atiende a varios
clientes a la vez. Si el operador plantara un PAT en su entorno, todos actuarían con él: mismos
permisos, misma organización y mismo rastro en el registro de actividad. La trazabilidad que el
bloque REG existe para dar se perdería justo en la superficie que más la necesita. Así que el
token es el `Authorization: Bearer` de cada petición MCP entrante, y viaja de ahí al `ApiClient`
de esa llamada y de nadie más.

Y si no viene, la tool falla con un mensaje que dice qué falta. Llamar a la API sin credencial
sólo conseguiría que el 401 del servidor llegara disfrazado de avería nuestra.

**Dos decisiones del transporte:**

*Sin sesión* (`stateless_http`). No hay nada que guardar entre peticiones: cada llamada trae su
propia credencial. A cambio, el proxy inverso puede repartir sin afinidad y un reinicio del
servicio no deja clientes con una sesión que ya no existe.

*Respuestas JSON* en vez de SSE. Las tools que monta este servidor son petición y respuesta, sin
progreso ni elicitación que haya que ir emitiendo; y un flujo SSE a través de un proxy inverso
funciona sólo si alguien se acordó de desactivar el buffering, que es una avería silenciosa
esperando su momento.

**Cuáles son, no cuántas**: las que registren las llamadas a `register_*_tools` de más abajo.
Este docstring daba una cantidad fija que se quedó corta, y era el sitio que más engañaba
porque estaba en el código: ni leyéndolo se salía del error (issue #89).

**El paquete sigue sin importar `server/app`** (regla de MCP.1, con test): es un cliente HTTP más,
como el frontend, y eso es lo que le permite desplegarse como el proceso pequeño que es.

Arranque local (desde `mcp_server/`):

    GOVGENAI_API_BASE_URL=http://localhost:8000 \\
    GOVGENAI_MCP_ALLOWED_HOSTS=localhost:8080 \\
        uv run uvicorn http_server:app --factory --port 8080
"""
from __future__ import annotations

import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Mapping

# Permite ejecutar por ruta resolviendo los imports hermanos sin instalar el paquete.
_PKG_DIR = str(Path(__file__).resolve().parent)
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from api_client import ApiClient
from config import HttpConfig, load_http_config
from tools.actividad import register_actividad_tools
from tools.agentes import register_agentes_tools
from tools.verificaciones import register_verificaciones_tools

_TIMEOUT = 30.0


class PatAusenteError(RuntimeError):
    """La petición MCP no trae un PAT utilizable.

    Es error del cliente, y el mensaje lo dice para que se pueda arreglar sin leer nuestro código.
    """


def pat_de_las_cabeceras(cabeceras: Mapping[str, str]) -> str:
    """Extrae el PAT de `Authorization`, o explica qué falta.

    Se exige el esquema `Bearer` explícitamente en vez de aceptar cualquier cosa: un cliente mal
    configurado que mande `Basic` recibe aquí un mensaje útil, y no un 401 del servidor que le
    haría buscar el problema en su token.
    """
    bruto = (cabeceras.get("authorization") or "").strip()
    if not bruto:
        raise PatAusenteError(
            "Falta el PAT. Este servidor MCP no tiene token propio: cada cliente presenta el "
            "suyo en la cabecera `Authorization: Bearer pat_...` al conectarse."
        )

    esquema, _, valor = bruto.partition(" ")
    if esquema.lower() != "bearer" or not valor.strip():
        raise PatAusenteError(
            f"El PAT se presenta como `Authorization: Bearer pat_...`; llegó el esquema "
            f"`{esquema}`."
        )
    return valor.strip()


def _construye(
    config: HttpConfig | None = None,
) -> tuple[FastMCP, httpx.AsyncClient]:
    """El servidor y su pool de conexiones, para que quien lo monte decida cuándo cerrarlo.

    **El pool NO se cierra en el ciclo de vida de FastMCP**, y esto costó encontrarlo (VAS.4).
    Con `stateless_http` ese ciclo corre **por petición**, así que un `aclose()` en su `finally`
    cerraba el pool compartido en cuanto acababa la primera llamada: el servidor remoto servía
    **una sola llamada por proceso** y la segunda moría con «Cannot send a request, as the client
    has been closed».

    Lo destapó una sesión MCP real, no la suite: el test de dos clientes concurrentes pasaba
    —sus peticiones empiezan antes de que el ciclo de la primera termine, así que las dos
    encuentran el pool abierto— y lo que fallaba era lo secuencial, que es lo normal. Ahora hay
    un test que hace dos llamadas seguidas.
    """
    cfg = config or load_http_config()

    # El pool se comparte entre clientes con tokens distintos porque la cabecera se pone por
    # petición (ver `ApiClient._request`); lo que se comparte son conexiones, no identidades.
    pool = httpx.AsyncClient(base_url=cfg.api_base_url.rstrip("/"), timeout=_TIMEOUT)

    mcp = FastMCP(
        "govgenai-remoto",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            allowed_hosts=list(cfg.allowed_hosts),
            allowed_origins=list(cfg.allowed_origins),
        ),
    )

    def client_provider() -> ApiClient:
        """Un `ApiClient` con el token de **esta** petición.

        Se lee del contexto en cada llamada y no se guarda en ninguna variable de módulo: con dos
        clientes en vuelo a la vez, un token guardado se mezclaría con el del otro. Hay un test
        que lo comprueba con dos peticiones concurrentes.
        """
        peticion = mcp.get_context().request_context.request
        if peticion is None:  # pragma: no cover - sólo si se monta sobre otro transporte
            raise PatAusenteError(
                "Esta tool necesita el PAT de la petición HTTP entrante y aquí no hay ninguna."
            )
        return ApiClient(cfg.api_base_url, pat_de_las_cabeceras(peticion.headers), client=pool)

    register_actividad_tools(mcp, client_provider=client_provider)
    register_verificaciones_tools(mcp, client_provider=client_provider)
    register_agentes_tools(mcp, client_provider=client_provider)
    return mcp, pool


def build_http_server(config: HttpConfig | None = None) -> FastMCP:
    """El servidor MCP remoto con sus tools. Para inspeccionarlo y para los tests.

    Quien lo use así se queda sin cerrar el pool, que en un proceso corto lo reclama el sistema
    al salir. La aplicación de verdad la construye `build_http_app`, que sí lo cierra.
    """
    mcp, _pool = _construye(config)
    return mcp


def build_http_app(config: HttpConfig | None = None) -> Starlette:
    """La aplicación ASGI, para servirla con uvicorn detrás del proxy inverso."""
    mcp, pool = _construye(config)
    app = mcp.streamable_http_app()

    # El cierre va en el ciclo de vida de la APLICACIÓN y no en el de FastMCP, que con
    # `stateless_http` corre por petición. Se envuelve el que trae el SDK en vez de sustituirlo:
    # ahí dentro vive el gestor de sesiones, y quitarlo dejaría el transporte sin arrancar.
    #
    # No se usa `add_event_handler("shutdown", …)`, que esta versión de Starlette ya no tiene.
    original = app.router.lifespan_context

    @asynccontextmanager
    async def _con_cierre_del_pool(aplicacion):
        async with original(aplicacion):
            try:
                yield
            finally:
                await pool.aclose()

    app.router.lifespan_context = _con_cierre_del_pool
    return app


def app() -> Starlette:  # pragma: no cover - punto de entrada de uvicorn --factory
    return build_http_app()
