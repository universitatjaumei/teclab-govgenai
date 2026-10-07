"""Tools MCP del catálogo de funciones para un agente de código (#236).

- `registrar_cuaderno`    → `POST /api/v1/funciones/externas`   [scope funciones:register]
- `catalogo_de_funciones` → `GET /api/v1/funciones`             [scope funciones:register o funciones:execute]

**Lo que resuelve es de registro, no de ejecución** (AUT.3): el agente que acaba de escribir un
cuaderno lo registra, y la institución sabe qué circula, de qué versión y quién responde. **La
plataforma no lo ejecuta**: el código sigue corriendo donde corría. Su auditoría es informativa —
llega a la revisión posterior y no bloquea— porque un programa que corre fuera usa red y disco
legítimamente.

Lo que se registra así consta como **escrito por IA** (`autoria: "ia"`): es lo que hace este
camino, y la revisión posterior quiere saberlo.

Cuando el cuaderno corre, su última celda manda su huella al registro de actividad con
`funcion_sha256`, y eso enlaza las dos cosas: el catálogo dice qué existe y el registro, cuándo
corrió (`docs/REGISTRO_ACTIVIDAD_IA.md` §4.2.bis).
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Callable

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from api_client import ApiClient

EXTERNAS_PATH = "/api/v1/funciones/externas"
CATALOGO_PATH = "/api/v1/funciones"

ClientProvider = Callable[[], ApiClient]


async def run_registrar_cuaderno_core(
    client: ApiClient,
    declaracion: dict[str, Any],
    *,
    contenido: str | None = None,
    ruta: str | None = None,
    funcion_id: str | None = None,
) -> dict:
    """El fichero entero —su hash es la versión— y la declaración responsable."""
    if (contenido is None) == (ruta is None):
        raise ValueError("Pasa el contenido del cuaderno o su ruta, una de las dos.")
    fichero = contenido if ruta is None else Path(ruta).expanduser().read_text(encoding="utf-8")
    cuerpo: dict[str, Any] = {**declaracion, "fichero": fichero, "autoria": "ia"}
    if funcion_id is not None:
        cuerpo["funcion_id"] = funcion_id
    return await client.post(EXTERNAS_PATH, json=cuerpo)


async def run_catalogo_de_funciones_core(client: ApiClient) -> Any:
    return await client.get(CATALOGO_PATH)


_RUTA = Annotated[
    str,
    Field(
        description=(
            "Sólo en el servidor local: ruta del cuaderno (.ipynb) o del script (.py) en tu equipo. "
            "Alternativa a `contenido`. En el servidor remoto no vale: sería una ruta de su disco."
        )
    ),
]


def register_funciones_tools(
    mcp: FastMCP, *, client_provider: ClientProvider, con_ficheros_locales: bool = False
) -> None:
    """Registra las tools. `con_ficheros_locales` sólo en el servidor stdio, que corre en el
    equipo de quien lo usa."""

    @mcp.tool()
    async def registrar_cuaderno(
        nombre: Annotated[str, Field(description="Cómo se llama en el catálogo.")],
        finalidad: Annotated[str, Field(description="Para qué sirve, en una frase: es la declaración responsable.")],
        categorias_datos: Annotated[
            list[str],
            Field(
                description=(
                    "Categorías de datos personales que trata, con los códigos de "
                    "`GET /api/v1/actividad/categorias`; `sin_datos_personales` si no trata ninguno."
                )
            ),
        ],
        entorno_ejecucion: Annotated[
            str, Field(description="Dónde corre: «un cuaderno en Colab», «el equipo de quien lo usa»…")
        ],
        # `str` y no `str | None`, a propósito: con una unión, FastMCP convierte en objeto un texto
        # que parece JSON antes de validarlo, y un .ipynb es JSON. Vacío significa «no viene».
        contenido: Annotated[
            str, Field(description="El fichero entero, .ipynb o .py. Su hash es la versión.")
        ] = "",
        ruta: _RUTA = "",
        funcion_id: Annotated[
            str | None, Field(description="Para registrar una versión nueva de una función externa que ya existe.")
        ] = None,
    ) -> dict:
        """Registra en el catálogo un cuaderno o script que corre fuera. [scope funciones:register]

        La plataforma **no lo ejecuta**: lo registra, lo audita de forma informativa y lo pone en
        la cola de revisión posterior. Consta como escrito por IA. Antes, mira con
        `catalogo_de_funciones` si ya existe: entonces es una versión nueva (`funcion_id`).
        """
        if ruta and not con_ficheros_locales:
            raise ValueError("El servidor remoto no lee ficheros: manda el `contenido`, o usa el servidor local.")
        declaracion = {
            "nombre": nombre,
            "finalidad": finalidad,
            "categorias_datos": categorias_datos,
            "entorno_ejecucion": entorno_ejecucion,
        }
        return await run_registrar_cuaderno_core(
            client_provider(), declaracion, contenido=contenido or None, ruta=ruta or None, funcion_id=funcion_id
        )

    @mcp.tool()
    async def catalogo_de_funciones() -> dict:
        """Las funciones del catálogo que ves: las de tu organización y las publicadas.
        [scope funciones:register o funciones:execute]

        Va dentro de `funciones`: una lista suelta llega partida en un bloque por elemento."""
        return {"funciones": await run_catalogo_de_funciones_core(client_provider())}
