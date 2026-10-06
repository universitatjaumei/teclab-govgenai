"""Servidor MCP stdio de Gov Gen AI Platform (MCP.1).

Expone autoría de plantillas y configuración de chatbots como tools/resources MCP,
actuando como un cliente HTTP más de la API (auth por PAT). El transporte es stdio:
se registra en Claude Code con ``claude mcp add`` (ver docs en MCP.4).

Arranque local (desde el directorio mcp_server/):
    GOVGENAI_API_BASE_URL=http://localhost:8000 GOVGENAI_PAT=pat_... \
        uv run mcp run server.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Permite ejecutar este fichero por ruta (`mcp run server.py`) resolviendo los
# imports hermanos (config/api_client/resources) sin instalar el paquete.
_PKG_DIR = str(Path(__file__).resolve().parent)
if _PKG_DIR not in sys.path:
    sys.path.insert(0, _PKG_DIR)

from mcp.server.fastmcp import FastMCP

from api_client import ApiClient
from config import Config, load_config
from resources import register_chatbot_resources, register_resources
from tools.agentes import register_agentes_tools
from tools.funciones import register_funciones_tools
from tools.chat import register_chat_tools
from tools.chatbots import register_chatbot_tools
from tools.templates import register_template_tools

# Singletons perezosos: la configuración (y por tanto el PAT) solo se exige cuando
# un resource/tool toca la API, no al importar el módulo.
_config: Config | None = None
_client: ApiClient | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = load_config()
    return _config


def get_client() -> ApiClient:
    global _client
    if _client is None:
        cfg = get_config()
        _client = ApiClient(cfg.api_base_url, cfg.pat)
    return _client


def build_server(
    *,
    client_provider=None,
    config_provider=None,
) -> FastMCP:
    """Construye el servidor FastMCP con los resources base registrados.

    Sin efectos de entorno: los providers por defecto son perezosos.
    """
    mcp = FastMCP("govgenai")
    cp = client_provider or get_client
    register_resources(
        mcp,
        client_provider=cp,
        config_provider=config_provider or get_config,
    )
    register_chatbot_resources(mcp, client_provider=cp)
    register_template_tools(mcp, client_provider=cp)
    register_chatbot_tools(mcp, client_provider=cp)
    register_chat_tools(mcp, client_provider=cp)
    # #226 — en local, la carga del índice puede leer una hoja del equipo.
    register_agentes_tools(mcp, client_provider=cp, con_ficheros_locales=True)
    # #236 — un agente de código registra los cuadernos que escribe.
    register_funciones_tools(mcp, client_provider=cp, con_ficheros_locales=True)
    return mcp


mcp = build_server()


if __name__ == "__main__":  # pragma: no cover
    mcp.run("stdio")
