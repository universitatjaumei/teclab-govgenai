"""Tools MCP de configuración de chatbots (MCP.3).

Envuelven `hub_chatbots_router` / `hub_organizaciones_router` / `hub_prompt_templates_router`
(`Deploy: cloud`). El riesgo dominante es la **mutación in-place** sobre bots en
producción (sin historial; el widget público cambia al instante, ver mcp.md val.2).
Mitigaciones por construcción:

- ``update_chatbot`` por defecto ``dry_run=True``: hace GET del estado actual y
  devuelve el *diff* (actual→propuesta) SIN persistir.
- el resto de escrituras requieren ``confirm=True`` para persistir.

Notas de mapeo (la API no ofrece todo lo que las tools necesitan, y MCP.3 es
tools-only —sin cambios de backend—):
- No existe ``GET /hub/chatbots/{id}`` individual: ``get_chatbot`` lista y filtra.
- ``list_chatbots`` filtra en el cliente por ``organizacion_id``, que es como lo llama el
  contrato (#234). El servidor también admite ``?organizacion_id=``.
- ``GET /hub/prompt-templates/`` SÍ acepta ``chatbot_id`` (filtro server-side).

Lógica en funciones ``_core`` (ApiClient explícito, testeables con respx); los
``@mcp.tool()`` son envoltorios finos que resuelven el cliente vía ``client_provider``.
"""
from __future__ import annotations

from typing import Any, Callable

from mcp.server.fastmcp import FastMCP

from api_client import ApiClient, ApiError

ORGANIZACIONES_PATH = "/api/v1/hub/organizaciones"
CHATBOTS_PATH = "/api/v1/hub/chatbots"
PROMPT_TEMPLATES_PATH = "/api/v1/hub/prompt-templates/"


def chatbot_path(chatbot_id: str) -> str:
    return f"/api/v1/hub/chatbots/{chatbot_id}"


def corpus_stats_path(chatbot_id: str) -> str:
    return f"/api/v1/hub/chatbots/{chatbot_id}/corpus-stats"


def children_path(router_id: str) -> str:
    return f"/api/v1/hub/chatbots/{router_id}/children"


def child_path(router_id: str, child_id: str) -> str:
    return f"/api/v1/hub/chatbots/{router_id}/children/{child_id}"


def prompt_template_path(template_id: str) -> str:
    return f"/api/v1/hub/prompt-templates/{template_id}"


ClientProvider = Callable[[], ApiClient]


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

async def list_organizaciones_core(client: ApiClient) -> Any:
    return await client.get(ORGANIZACIONES_PATH)


async def list_chatbots_core(client: ApiClient, organizacion_id: str | None = None) -> Any:
    bots = await client.get(CHATBOTS_PATH)
    if organizacion_id is not None and isinstance(bots, list):
        return [b for b in bots if str(b.get("organizacion_id")) == str(organizacion_id)]
    return bots


async def get_chatbot_core(client: ApiClient, chatbot_id: str) -> dict:
    bots = await client.get(CHATBOTS_PATH)
    for bot in bots or []:
        if str(bot.get("id")) == str(chatbot_id):
            return bot
    raise ApiError(f"Chatbot {chatbot_id} no encontrado", status_code=404)


async def get_corpus_stats_core(client: ApiClient, chatbot_id: str) -> Any:
    return await client.get(corpus_stats_path(chatbot_id))


async def list_prompt_templates_core(
    client: ApiClient, chatbot_id: str | None = None
) -> Any:
    params = {"chatbot_id": chatbot_id} if chatbot_id is not None else None
    return await client.get(PROMPT_TEMPLATES_PATH, params=params)


# ---------------------------------------------------------------------------
# Escritura
# ---------------------------------------------------------------------------

def _compute_diff(current: dict, patch: dict) -> dict:
    """Diff field-a-field: solo los campos del patch que cambian respecto a current."""
    diff: dict[str, dict] = {}
    for field, new_value in patch.items():
        old_value = current.get(field)
        if old_value != new_value:
            diff[field] = {"from": old_value, "to": new_value}
    return diff


async def create_chatbot_core(
    client: ApiClient, payload: dict, confirm: bool = False
) -> dict:
    if not confirm:
        return {"created": False, "plan": payload}
    created = await client.post(CHATBOTS_PATH, json=payload)
    return {"created": True, "result": created}


async def update_chatbot_core(
    client: ApiClient, chatbot_id: str, patch: dict, dry_run: bool = True
) -> dict:
    if dry_run:
        current = await get_chatbot_core(client, chatbot_id)
        return {"applied": False, "diff": _compute_diff(current, patch)}
    updated = await client.patch(chatbot_path(chatbot_id), json=patch)
    return {"applied": True, "result": updated}


async def update_prompt_template_core(
    client: ApiClient, template_id: str, payload: dict, confirm: bool = False
) -> dict:
    if not confirm:
        return {"updated": False, "plan": payload}
    updated = await client.patch(prompt_template_path(template_id), json=payload)
    return {"updated": True, "result": updated}


async def assign_child_core(
    client: ApiClient, router_id: str, child_id: str, confirm: bool = False
) -> dict:
    if not confirm:
        return {"assigned": False, "plan": {"router_id": router_id, "child_id": child_id}}
    result = await client.post(
        children_path(router_id), json={"child_chatbot_id": child_id}
    )
    return {"assigned": True, "result": result}


async def unassign_child_core(
    client: ApiClient, router_id: str, child_id: str, confirm: bool = False
) -> dict:
    if not confirm:
        return {"unassigned": False, "plan": {"router_id": router_id, "child_id": child_id}}
    await client.delete(child_path(router_id, child_id))
    return {"unassigned": True, "router_id": router_id, "child_id": child_id}


# ---------------------------------------------------------------------------
# Registro de tools MCP
# ---------------------------------------------------------------------------

def register_chatbot_tools(mcp: FastMCP, *, client_provider: ClientProvider) -> None:
    @mcp.tool()
    async def list_organizaciones() -> Any:
        """Lista las organizaciones que ve el token, con su id: el que pide create_chatbot. [scope chatbots:read]"""
        return await list_organizaciones_core(client_provider())

    @mcp.tool()
    async def list_chatbots(organizacion_id: str | None = None) -> Any:
        """Lista chatbots, opcionalmente de una organización. [scope chatbots:read]"""
        return await list_chatbots_core(client_provider(), organizacion_id)

    @mcp.tool()
    async def get_chatbot(chatbot_id: str) -> dict:
        """Devuelve la configuración de un chatbot por id. [scope chatbots:read]"""
        return await get_chatbot_core(client_provider(), chatbot_id)

    @mcp.tool()
    async def get_corpus_stats(chatbot_id: str) -> Any:
        """Estadísticas del corpus + modo de retrieval recomendado. [scope chatbots:read]"""
        return await get_corpus_stats_core(client_provider(), chatbot_id)

    @mcp.tool()
    async def list_prompt_templates(chatbot_id: str | None = None) -> Any:
        """Lista plantillas de prompt, opcionalmente de un chatbot. [scope chatbots:read]"""
        return await list_prompt_templates_core(client_provider(), chatbot_id)

    @mcp.tool()
    async def create_chatbot(payload: dict, confirm: bool = False) -> dict:
        """Crea un chatbot. [scope chatbots:write]

        ``confirm=False`` (por defecto) devuelve el plan sin crear nada;
        ``confirm=True`` persiste el chatbot.
        """
        return await create_chatbot_core(client_provider(), payload, confirm=confirm)

    @mcp.tool()
    async def update_chatbot(chatbot_id: str, patch: dict, dry_run: bool = True) -> dict:
        """Actualiza la configuración de un chatbot (mutación in-place). [scope chatbots:write]

        ``dry_run=True`` (por defecto) devuelve el diff actual→propuesta SIN aplicar;
        ``dry_run=False`` aplica el PATCH. Revisa siempre el diff antes de aplicar:
        el cambio impacta al widget público al instante.
        """
        return await update_chatbot_core(
            client_provider(), chatbot_id, patch, dry_run=dry_run
        )

    @mcp.tool()
    async def update_prompt_template(
        template_id: str, payload: dict, confirm: bool = False
    ) -> dict:
        """Actualiza una plantilla de prompt. [scope chatbots:write]

        ``confirm=False`` devuelve el plan sin aplicar; ``confirm=True`` aplica el PATCH.
        """
        return await update_prompt_template_core(
            client_provider(), template_id, payload, confirm=confirm
        )

    @mcp.tool()
    async def assign_child(router_id: str, child_id: str, confirm: bool = False) -> dict:
        """Asigna un chatbot hijo a un router. [scope chatbots:write]

        ``confirm=False`` devuelve el plan; ``confirm=True`` ejecuta la asignación
        (el servidor valida jerarquía: máx. 2 niveles, mismo cliente, hijo no router).
        """
        return await assign_child_core(
            client_provider(), router_id, child_id, confirm=confirm
        )

    @mcp.tool()
    async def unassign_child(router_id: str, child_id: str, confirm: bool = False) -> dict:
        """Desasigna un chatbot hijo de un router. [scope chatbots:write]

        ``confirm=False`` devuelve el plan; ``confirm=True`` ejecuta la desasignación.
        """
        return await unassign_child_core(
            client_provider(), router_id, child_id, confirm=confirm
        )
