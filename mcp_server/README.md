# Servidor MCP — Gov Gen AI Platform

Servidor MCP **stdio** que expone, a un cliente como Claude Code, la autoría de
plantillas de informe y la configuración de chatbots. Es un **cliente HTTP más de
la API** (igual que el frontend): se autentica con un **PAT** y no importa nada de
`server/app`, por lo que no cruza la frontera edge/cloud.

> Estado: **MCP.4 — Bloque MCP completo.** Scaffolding (MCP.1) + tools de plantillas
> (MCP.2) + tools de chatbots (MCP.3) + tool `test_chat` (MCP.4). Guía de instalación,
> scopes, seguridad y `claude mcp add` en [`docs/MCP_SERVER.md`](../docs/MCP_SERVER.md).

## Configuración (variables de entorno)

| Variable | Obligatoria | Descripción |
|---|---|---|
| `GOVGENAI_API_BASE_URL` | sí | URL base de la API, p. ej. `http://localhost:8000` |
| `GOVGENAI_PAT` | sí | Personal Access Token (`pat_<prefix>_<secret>`), emitido en `/plataforma/tokens` |
| `GOVGENAI_GRAPH_PROFILES_PATH` | no | Ruta a `GRAPH_PROFILES.md` (por defecto `<repo>/docs/GRAPH_PROFILES.md`) |

Si falta alguna obligatoria, el servidor falla al arrancar con un mensaje claro.

## Resources

| URI | Fuente |
|---|---|
| `govgenai://redaccion/template-schema` | API: `GET /api/v1/hub/redaccion/template-schema` (dinámico) |
| `govgenai://redaccion/profiles` | empaquetado: espejo de `ReportProfileId` (`contracts/template.py`) |
| `govgenai://docs/graph-profiles` | fichero: `docs/GRAPH_PROFILES.md` del repo (única fuente de verdad) |
| `govgenai://chatbots/enums` | empaquetado: valores válidos de `retrieval_mode`/`public_graph_profile`/`kind`/`language_mode` |
| `govgenai://chatbots/schema` | API: `ChatbotCreate`/`ChatbotUpdate` extraídos del `/openapi.json` vivo |

## Tools (MCP.2 — plantillas de redacción)

| Tool | Scope | Efecto |
|---|---|---|
| `list_templates()` | `redaccion:templates:read` | Lista plantillas visibles |
| `get_template_spec(version_id)` | read | Spec completa de una versión |
| `validate_template_draft(draft)` | read | Valida un draft (DraftValidator), no persiste |
| `create_template(draft, name, is_global, confirm)` | `redaccion:templates:write` | `confirm=False` solo valida; `confirm=True` crea plantilla+v1 |
| `publish_template_version(template_id, spec, confirm)` | write | `confirm=False` valida (dry-run); `confirm=True` publica versión (append-only) |

Gate HITL por construcción: las tools de escritura no persisten sin `confirm=True`.

## Tools (MCP.3 — configuración de chatbots)

| Tool | Scope | Efecto |
|---|---|---|
| `list_organizaciones()` | `chatbots:read` | Las organizaciones que ve el token, con el id que pide `create_chatbot` |
| `list_chatbots(organizacion_id?)` | read | Lista chatbots (filtra en el cliente por organización) |
| `get_chatbot(chatbot_id)` | read | Config de un chatbot (vía listado, no hay GET individual) |
| `get_corpus_stats(chatbot_id)` | read | Stats del corpus + modo recomendado |
| `list_prompt_templates(chatbot_id?)` | read | Plantillas de prompt (filtro server-side) |
| `create_chatbot(payload, confirm)` | `chatbots:write` | `confirm=False` plan; `confirm=True` crea |
| `update_chatbot(id, patch, dry_run=True)` | write | `dry_run=True` devuelve diff sin aplicar; `dry_run=False` aplica PATCH |
| `update_prompt_template(id, payload, confirm)` | write | `confirm=False` plan; `confirm=True` aplica |
| `assign_child(router_id, child_id, confirm)` | write | Asigna hijo a router (server valida jerarquía) |
| `unassign_child(router_id, child_id, confirm)` | write | Desasigna hijo |

Mitigación de mutación in-place: `update_chatbot` es `dry_run=True` por defecto
(devuelve el diff actual→propuesta); el cambio impacta al widget público al instante.

## Tools (MCP.4 — chat de prueba)

| Tool | Scope | Efecto |
|---|---|---|
| `test_chat(chatbot_id, message, lang?)` | `chat:test` | Lanza una pregunta a un chatbot; devuelve `answer` + `sources` (consume el stream SSE) |

Cierra el bucle configurar→probar→ajustar: tras `update_chatbot`, evalúa el bot con
`test_chat` y ajusta. `lang` es opcional (el endpoint detecta el idioma).

## Desarrollo

Desde este directorio (`mcp_server/`):

```bash
uv sync --extra dev      # crea el venv con dependencias
uv run pytest            # ejecuta los tests
```

## Arranque stdio

```bash
GOVGENAI_API_BASE_URL=http://localhost:8000 GOVGENAI_PAT=pat_... \
    uv run mcp run server.py
```

El registro en Claude Code (`claude mcp add`) se documenta en MCP.4.
