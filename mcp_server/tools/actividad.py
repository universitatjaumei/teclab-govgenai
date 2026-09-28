"""Tools MCP de registro de actividad y anonimización (REG.4).

Tres tools, y las tres envuelven endpoints `Deploy: edge` de la API:

- `registrar_actividad` → `POST /api/v1/actividad` (REG.2). Es el camino para que un agente que
  trabaja *fuera* de la plataforma —un asistente de escritorio, un agente de código— quede en el
  registro de usos de IA de su organización.
- `detectar_pii` → `POST /api/v1/anonimizacion/spans` (REG.3).
- `anonimizar_texto` → `POST /api/v1/anonimizacion/replace` (REG.3).

**Sin puerta de confirmación en `registrar_actividad`.** `update_chatbot` tiene una porque muta un
chatbot en producción in-place y un error ahí lo nota quien esté usando el asistente. Registrar
actividad es añadir metadatos: no muta nada, y una tool que un agente va a llamar de forma
rutinaria dejaría de llamarse si cada vez pidiera permiso — con lo que el registro quedaría vacío,
que es peor que cualquier entrada de más.

**Los errores no se silencian.** `ApiClient` ya traduce 401/403/422 a excepciones legibles con el
cuerpo del servidor en `detail`; el SDK MCP las reporta al cliente. Un `except` aquí convertiría
«te falta el scope `actividad:write`» en «no se pudo registrar», que es justo el mensaje que no
deja arreglar nada.
"""
from __future__ import annotations

from typing import Annotated, Any, Callable

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from api_client import ApiClient

ACTIVIDAD_PATH = "/api/v1/actividad"
SPANS_PATH = "/api/v1/anonimizacion/spans"
REPLACE_PATH = "/api/v1/anonimizacion/replace"

ClientProvider = Callable[[], ApiClient]


async def run_registrar_actividad_core(
    client: ApiClient, evento: dict[str, Any]
) -> dict:
    """Envía el evento tal cual: el contrato lo valida el servidor.

    No se rellena ni se completa nada aquí. Un valor por defecto puesto en el cliente MCP sería
    un dato del registro que no declaró quien lo usó, y el registro dejaría de decir la verdad.

    **Y la validación tampoco se duplica.** Los tipos de la firma son los que viajan en JSON; que
    la marca de tiempo lleve zona o que el hash tenga 64 dígitos lo comprueba el servidor, que es
    donde vive la regla. Validar aquí sólo movería el sitio donde falla, y con peor mensaje.
    """
    return await client.post(ACTIVIDAD_PATH, json=evento)


async def run_detectar_pii_core(client: ApiClient, text: str) -> dict:
    return await client.post(SPANS_PATH, json={"text": text})


async def run_anonimizar_texto_core(client: ApiClient, text: str) -> dict:
    return await client.post(REPLACE_PATH, json={"text": text})


def register_actividad_tools(mcp: FastMCP, *, client_provider: ClientProvider) -> None:
    @mcp.tool()
    async def registrar_actividad(
        ocurrido_en: Annotated[
            str,
            Field(
                description=(
                    "Cuándo ocurrió el uso, en ISO 8601 y **con zona horaria** "
                    "(«2026-09-03T10:30:00Z» o «...+02:00»). Una marca sin zona se rechaza: un "
                    "instante sin zona no es un instante, y en un registro que se cruza entre "
                    "organizaciones eso son horas de diferencia sin avisar."
                )
            ),
        ],
        actor: Annotated[
            str,
            Field(
                description=(
                    "Quién lo usó, en la forma que tengas. Un identificador interno estable es "
                    "preferible a un correo: identifica igual y no propaga un dato personal."
                )
            ),
        ],
        herramienta: Annotated[
            str,
            Field(
                description=(
                    "El producto que se usó: «claude-cowork», «copilot», «gemini-cli». Usa "
                    "siempre el mismo valor para el mismo producto; es el eje por el que se "
                    "filtra y se agrega el registro."
                )
            ),
        ],
        finalidad: Annotated[
            str,
            Field(
                description=(
                    "Para qué se usó, en una frase. Es el campo que hace útil el registro en una "
                    "auditoría: sin él sólo consta que hubo uso."
                )
            ),
        ],
        agente: Annotated[
            str | None,
            Field(
                description=(
                    "El agente concreto dentro de esa herramienta, si lo hay: "
                    "«revisor-de-contratos»."
                )
            ),
        ] = None,
        modelo_usado: Annotated[
            str | None,
            Field(description="El modelo, si se conoce: «claude-opus-5»."),
        ] = None,
        categorias_datos: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Categorías de datos personales que se tocaron. **Pide el catálogo de tu "
                    "organización a `GET /api/v1/actividad/categorias` y usa esos códigos**: el "
                    "campo acepta cualquiera, pero si cada herramienta inventa los suyos el "
                    "registro deja de poder agregarse, que es para lo que existe."
                )
            ),
        ] = None,
        payload_hash: Annotated[
            str | None,
            Field(
                description=(
                    "SHA-256 en minúscula del texto procesado, sólo si hace falta dejar prueba "
                    "de cuál fue. Permite demostrar después que un texto concreto es el que se "
                    "procesó **sin guardar el texto**."
                )
            ),
        ] = None,
        funcion_sha256: Annotated[
            str | None,
            Field(
                description=(
                    "SHA-256 en minúscula del **programa** que se ejecutó, si está registrado "
                    "en el catálogo como función de origen externo. Es lo que cruza «qué "
                    "cuadernos existen» con «cuándo corrieron». No es `payload_hash`: aquél es "
                    "el contenido procesado, y éste el programa que lo procesó."
                )
            ),
        ] = None,
    ) -> dict:
        """Declara un uso de IA ocurrido fuera de la plataforma. [scope actividad:write]

        El evento lleva **metadatos de gobernanza, nunca el contenido**. El contrato no tiene
        ningún campo de texto y rechaza los que no declara, así que mandar el prompt no lo
        registra: falla. Si hace falta prueba del contenido, va su SHA-256 en `payload_hash`.

        La organización sale del token, no se elige. Devuelve `id` y `registrado_en`.

        Contrato campo a campo, mapeo a las convenciones OTel GenAI y cómo darse de alta: en
        `docs/REGISTRO_ACTIVIDAD_IA.md` de la plataforma.
        """
        # Lo que nadie declaró no viaja, y menos como `null`: `categorias_datos` no admite nulo
        # en el contrato —su defecto es la lista vacía—, así que rellenar el hueco sería provocar
        # un 422 desde el cliente.
        evento = {
            nombre: valor
            for nombre, valor in (
                ("ocurrido_en", ocurrido_en),
                ("actor", actor),
                ("herramienta", herramienta),
                ("finalidad", finalidad),
                ("agente", agente),
                ("modelo_usado", modelo_usado),
                ("categorias_datos", categorias_datos),
                ("payload_hash", payload_hash),
                ("funcion_sha256", funcion_sha256),
            )
            if valor is not None
        }
        return await run_registrar_actividad_core(client_provider(), evento)

    @mcp.tool()
    async def detectar_pii(text: str) -> dict:
        """Localiza datos personales en un texto sin modificarlo. [scope anonimizacion:use]

        Devuelve `spans` con posición, tipo y un sustituto propuesto. Úsalo para decidir o
        mostrar; para obtener el texto ya limpio, `anonimizar_texto`.
        """
        return await run_detectar_pii_core(client_provider(), text)

    @mcp.tool()
    async def anonimizar_texto(text: str) -> dict:
        """Sustituye los datos personales de un texto. [scope anonimizacion:use]

        Devuelve `text_anonimizado` y `spans_aplicados`, que describe exactamente lo que se
        sustituyó en ese texto. Ni el original ni el resultado se registran en el servidor.
        """
        return await run_anonimizar_texto_core(client_provider(), text)
