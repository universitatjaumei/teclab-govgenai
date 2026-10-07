"""Tools MCP de los agentes de unidad (#226).

Envuelven endpoints que ya existen (`docs/ESPECIFICACIONES.md` §5.14):

- `catalogo_de_agentes` → `GET /api/v1/agentes/catalogo`          [scope agentes:consulta]
- `consultar_agente`    → `POST /api/v1/agentes/{id}/consulta`     [scope agentes:consulta]
- `ampliar_consulta`    → `POST /api/v1/agentes/consultas/{id}/ampliacion` [scope agentes:consulta]
- `cargar_indice_de_agente` → `PUT /api/v1/agentes/{id}/indice`, o `POST …/indice/hoja` con una
  hoja del equipo en el servidor local                            [scope agentes:indice]

**Consultar** permite usar un agente desde Claude además de desde Gemini: el agente es
configuración, no código, y sirve a los dos asistentes. Lo que vuelve es el prompt del agente con
los enlaces: quien lo usa lo entrega a su asistente, que abre los documentos con su cuenta.

**La hoja la interpreta el servidor.** Con `ruta_hoja`, el fichero se manda tal cual al mismo
endpoint que usa la pantalla, y las columnas, la vigencia y las fechas se leen en un solo sitio.
Reinterpretarlas aquí sería una segunda fuente de verdad que se separaría de la primera.

**Fuera, a propósito: publicar, versionar o retirar.** Exige la sesión de una persona (#214): un
token no publica nada, y consta quién publica.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Callable

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from api_client import ApiClient

CATALOGO_PATH = "/api/v1/agentes/catalogo"

ClientProvider = Callable[[], ApiClient]


def consulta_path(agente_id: str) -> str:
    return f"/api/v1/agentes/{agente_id}/consulta"


def ampliacion_path(consulta_id: str) -> str:
    return f"/api/v1/agentes/consultas/{consulta_id}/ampliacion"


def indice_path(agente_id: str) -> str:
    return f"/api/v1/agentes/{agente_id}/indice"


async def run_catalogo_core(client: ApiClient) -> Any:
    return await client.get(CATALOGO_PATH)


async def run_consultar_core(
    client: ApiClient,
    agente_id: str,
    consulta: str,
    *,
    datos: dict[str, str] | None = None,
    adjunta: bool = False,
    lengua: str = "es",
) -> dict:
    return await client.post(
        consulta_path(agente_id),
        json={"consulta": consulta, "lengua": lengua, "adjunta": adjunta, "datos": datos or {}},
    )


async def run_ampliar_core(
    client: ApiClient,
    consulta_id: str,
    texto: str,
    *,
    datos: dict[str, str] | None = None,
    lengua: str = "es",
) -> dict:
    return await client.post(
        ampliacion_path(consulta_id), json={"texto": texto, "lengua": lengua, "datos": datos or {}}
    )


async def run_cargar_indice_core(
    client: ApiClient,
    agente_id: str,
    *,
    fichas: list[dict] | None = None,
    ruta_hoja: str | None = None,
    documentos_en_carpeta: int | None = None,
) -> dict:
    """El índice entero, de una de las dos maneras. **Lo que no venga se retira.**"""
    if (fichas is None) == (ruta_hoja is None):
        raise ValueError("Pasa las fichas o la ruta de una hoja, una de las dos.")
    if ruta_hoja is not None and documentos_en_carpeta is not None:
        # La subida de la hoja no lo recibe: descartarlo en silencio sería mentir sobre lo cargado.
        raise ValueError("Con una hoja no se puede indicar `documentos_en_carpeta`: manda las fichas.")
    if ruta_hoja is not None:
        hoja = Path(ruta_hoja).expanduser()
        return await client.post(
            f"{indice_path(agente_id)}/hoja", files={"file": (hoja.name, hoja.read_bytes())}
        )
    cuerpo: dict[str, Any] = {"fichas": fichas}
    if documentos_en_carpeta is not None:
        cuerpo["documentos_en_carpeta"] = documentos_en_carpeta
    return await client.put(indice_path(agente_id), json=cuerpo)


_DATOS = Annotated[
    dict[str, str] | None,
    Field(
        description=(
            "Los datos de la consulta que declara el agente, por su clave (están en "
            "`datos_consulta` del catálogo): p. ej. {\"tipo_de_contrato\": \"Suministros\"}. "
            "Los obligatorios hay que darlos."
        )
    ),
]
_LENGUA = Annotated[
    str,
    Field(description="Lengua de las instrucciones fijas que añade la plataforma: «es», «ca» o «en»."),
]

_HOJA = Annotated[
    str | None,
    Field(
        description=(
            "Sólo en el servidor local: ruta de una hoja CSV o Excel de tu equipo, con las columnas "
            "de la pantalla (url, titulo, resumen y las demás). La interpreta el servidor. "
            "Alternativa a `fichas`. En el servidor remoto no vale: la ruta sería de su disco."
        )
    ),
]

def register_agentes_tools(
    mcp: FastMCP, *, client_provider: ClientProvider, con_ficheros_locales: bool = False
) -> None:
    """Registra las tools. `con_ficheros_locales` sólo en el servidor stdio, que corre en el
    equipo de quien lo usa: en el remoto, una ruta sería del disco del servidor."""

    @mcp.tool()
    async def catalogo_de_agentes() -> dict:
        """Los agentes de unidad que se te ofrecen, con su finalidad y los datos que piden.
        [scope agentes:consulta]

        Va dentro de `agentes` y no como lista suelta: una lista se entrega partida en un bloque
        por agente, y quien la lee tendría que recomponerla."""
        return {"agentes": await run_catalogo_core(client_provider())}

    @mcp.tool()
    async def consultar_agente(
        agente_id: Annotated[str, Field(description="El `id` del agente, del catálogo.")],
        consulta: Annotated[str, Field(description="La pregunta, concreta: es con lo que se eligen los documentos.")],
        datos: _DATOS = None,
        adjunta: Annotated[
            bool,
            Field(description="Si vas a adjuntar un documento al asistente (sólo cuenta si el agente lo permite)."),
        ] = False,
        lengua: _LENGUA = "es",
    ) -> dict:
        """Prepara una consulta a un agente de unidad. [scope agentes:consulta]

        Devuelve `prompt` —el del agente con la pregunta, los datos y los enlaces a los documentos
        elegidos— y `consulta_id`. **Entrega el prompt a tu asistente**, que abre los documentos
        con tu cuenta; la plataforma no ve su contenido. Queda registrado como uso del agente.
        """
        return await run_consultar_core(
            client_provider(), agente_id, consulta, datos=datos, adjunta=adjunta, lengua=lengua
        )

    @mcp.tool()
    async def ampliar_consulta(
        consulta_id: Annotated[str, Field(description="El `consulta_id` de la consulta que se amplía.")],
        texto: Annotated[
            str, Field(description="Qué falta o qué se quiere precisar: se busca con esto, no con la pregunta.")
        ],
        datos: _DATOS = None,
        lengua: _LENGUA = "es",
    ) -> dict:
        """Más documentos para la misma conversación, sin repetir los ya ofrecidos.
        [scope agentes:consulta]

        Devuelve un `prompt` corto —el texto y los enlaces nuevos, sin el del agente— para la
        misma conversación, y un `consulta_id` nuevo. Si `documentos` viene vacío, no quedan más.
        """
        return await run_ampliar_core(client_provider(), consulta_id, texto, datos=datos, lengua=lengua)

    @mcp.tool()
    async def cargar_indice_de_agente(
        agente_id: Annotated[str, Field(description="El `id` del agente.")],
        fichas: Annotated[
            list[dict] | None,
            Field(
                description=(
                    "El índice entero, una ficha por documento: url, titulo, resumen y, si hacen "
                    "falta, vigente, revision_prevista_en (AAAA-MM-DD) y metadatos (columna → valor, "
                    "p. ej. capa o prioritario)."
                )
            ),
        ] = None,
        ruta_hoja: _HOJA = None,
        documentos_en_carpeta: Annotated[
            int | None, Field(description="Cuántos documentos hay en la carpeta, tengan ficha o no.")
        ] = None,
    ) -> dict:
        """Deja el índice de un agente igual que lo que se manda. [scope agentes:indice]

        **Es el estado completo: lo que no venga se retira.** Devuelve cuántas fichas son nuevas,
        actualizadas, sin cambios y retiradas.
        """
        if ruta_hoja is not None and not con_ficheros_locales:
            raise ValueError(
                "El servidor remoto no lee ficheros: manda las `fichas`, o usa el servidor local."
            )
        return await run_cargar_indice_core(
            client_provider(),
            agente_id,
            fichas=fichas,
            ruta_hoja=ruta_hoja,
            documentos_en_carpeta=documentos_en_carpeta,
        )
