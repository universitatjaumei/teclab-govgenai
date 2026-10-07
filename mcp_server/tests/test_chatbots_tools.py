"""Tests MCP.3 — tools de configuración de chatbots.

Sin red (respx). Cubre mapeo tool→endpoint, diff/dry_run de update_chatbot, gating
de escritura (confirm), y mapeo de errores del servidor (400/422→ValidationError,
403→ScopeError).
"""
from __future__ import annotations

import httpx
import pytest
import respx

from api_client import ApiClient
from errors import ApiError, ScopeError, ValidationError
from server import build_server
from tools.chatbots import (
    CHATBOTS_PATH,
    ORGANIZACIONES_PATH,
    PROMPT_TEMPLATES_PATH,
    assign_child_core,
    child_path,
    children_path,
    chatbot_path,
    corpus_stats_path,
    create_chatbot_core,
    get_chatbot_core,
    get_corpus_stats_core,
    list_chatbots_core,
    list_organizaciones_core,
    list_prompt_templates_core,
    unassign_child_core,
    update_chatbot_core,
    update_prompt_template_core,
)

BASE = "http://testserver"
PAT = "pat_abcd1234_secretsecretsecret"

CB1 = "11111111-1111-1111-1111-111111111111"
CB2 = "22222222-2222-2222-2222-222222222222"
CLIENT_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
CLIENT_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def make_client() -> ApiClient:
    return ApiClient(BASE, PAT)


def _bots() -> list[dict]:
    return [
        {"id": CB1, "name": "Bot A", "organizacion_id": CLIENT_A, "retrieval_mode": "RAG", "retrieval_top_k": 8},
        {"id": CB2, "name": "Bot B", "organizacion_id": CLIENT_B, "retrieval_mode": "RAG", "retrieval_top_k": 8},
    ]


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

@respx.mock
async def test_list_organizaciones_calls_endpoint():
    route = respx.get(f"{BASE}{ORGANIZACIONES_PATH}").mock(
        return_value=httpx.Response(200, json=[{"id": CLIENT_A, "name": "Org A"}])
    )
    client = make_client()
    try:
        result = await list_organizaciones_core(client)
    finally:
        await client.aclose()
    assert route.called
    assert result[0]["name"] == "Org A"


@respx.mock
async def test_list_chatbots_returns_all_without_filter():
    respx.get(f"{BASE}{CHATBOTS_PATH}").mock(return_value=httpx.Response(200, json=_bots()))
    client = make_client()
    try:
        result = await list_chatbots_core(client)
    finally:
        await client.aclose()
    assert len(result) == 2


@respx.mock
async def test_list_chatbots_filters_by_organizacion_id():
    respx.get(f"{BASE}{CHATBOTS_PATH}").mock(return_value=httpx.Response(200, json=_bots()))
    client = make_client()
    try:
        result = await list_chatbots_core(client, organizacion_id=CLIENT_A)
    finally:
        await client.aclose()
    assert len(result) == 1
    assert result[0]["id"] == CB1


@respx.mock
async def test_get_chatbot_returns_matching():
    respx.get(f"{BASE}{CHATBOTS_PATH}").mock(return_value=httpx.Response(200, json=_bots()))
    client = make_client()
    try:
        result = await get_chatbot_core(client, CB2)
    finally:
        await client.aclose()
    assert result["name"] == "Bot B"


@respx.mock
async def test_get_chatbot_not_found_raises():
    respx.get(f"{BASE}{CHATBOTS_PATH}").mock(return_value=httpx.Response(200, json=_bots()))
    client = make_client()
    try:
        with pytest.raises(ApiError) as exc:
            await get_chatbot_core(client, "00000000-0000-0000-0000-000000000000")
    finally:
        await client.aclose()
    assert exc.value.status_code == 404


@respx.mock
async def test_get_corpus_stats_returns_recommendation():
    body = {
        "total_documents": 3,
        "total_tokens": 50000,
        "by_language": {"es": 3},
        "recommended_mode": "MD_LONG_CONTEXT",
        "recommendation_reason": "corpus pequeño",
    }
    route = respx.get(f"{BASE}{corpus_stats_path(CB1)}").mock(
        return_value=httpx.Response(200, json=body)
    )
    client = make_client()
    try:
        result = await get_corpus_stats_core(client, CB1)
    finally:
        await client.aclose()
    assert route.called
    assert result["recommended_mode"] == "MD_LONG_CONTEXT"


@respx.mock
async def test_list_prompt_templates_forwards_chatbot_id():
    route = respx.get(f"{BASE}{PROMPT_TEMPLATES_PATH}").mock(
        return_value=httpx.Response(200, json=[{"id": "p1", "chatbot_id": CB1}])
    )
    client = make_client()
    try:
        result = await list_prompt_templates_core(client, chatbot_id=CB1)
    finally:
        await client.aclose()
    assert route.called
    assert route.calls.last.request.url.params.get("chatbot_id") == CB1
    assert result[0]["chatbot_id"] == CB1


# ---------------------------------------------------------------------------
# update_chatbot — diff / dry_run
# ---------------------------------------------------------------------------

@respx.mock
async def test_update_chatbot_dry_run_returns_diff_without_patch():
    list_route = respx.get(f"{BASE}{CHATBOTS_PATH}").mock(
        return_value=httpx.Response(200, json=_bots())
    )
    patch_route = respx.patch(f"{BASE}{chatbot_path(CB1)}").mock(
        return_value=httpx.Response(200, json={})
    )
    client = make_client()
    try:
        result = await update_chatbot_core(
            client, CB1, {"retrieval_top_k": 12, "name": "Bot A"}, dry_run=True
        )
    finally:
        await client.aclose()
    assert list_route.called
    assert not patch_route.called  # dry_run NO persiste
    assert result["applied"] is False
    # solo cambia retrieval_top_k (8→12); name no cambia (igual a current)
    assert result["diff"] == {"retrieval_top_k": {"from": 8, "to": 12}}


@respx.mock
async def test_update_chatbot_apply_does_patch():
    patch_route = respx.patch(f"{BASE}{chatbot_path(CB1)}").mock(
        return_value=httpx.Response(200, json={"id": CB1, "retrieval_top_k": 12})
    )
    client = make_client()
    try:
        result = await update_chatbot_core(client, CB1, {"retrieval_top_k": 12}, dry_run=False)
    finally:
        await client.aclose()
    assert patch_route.called
    assert result["applied"] is True
    assert result["result"]["retrieval_top_k"] == 12


@respx.mock
async def test_update_chatbot_md_long_context_limit_is_validation_error():
    # El servidor devuelve 400 si el corpus excede 128K en MD_LONG_CONTEXT.
    respx.patch(f"{BASE}{chatbot_path(CB1)}").mock(
        return_value=httpx.Response(400, json={"detail": "límite 128K"})
    )
    client = make_client()
    try:
        with pytest.raises(ValidationError) as exc:
            await update_chatbot_core(
                client, CB1, {"retrieval_mode": "MD_LONG_CONTEXT"}, dry_run=False
            )
    finally:
        await client.aclose()
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# Escritura — gating con confirm
# ---------------------------------------------------------------------------

@respx.mock
async def test_create_chatbot_confirm_false_does_not_post():
    route = respx.post(f"{BASE}{CHATBOTS_PATH}").mock(
        return_value=httpx.Response(201, json={"id": CB1})
    )
    client = make_client()
    try:
        result = await create_chatbot_core(client, {"name": "Nuevo"}, confirm=False)
    finally:
        await client.aclose()
    assert not route.called
    assert result["created"] is False
    assert result["plan"]["name"] == "Nuevo"


@respx.mock
async def test_create_chatbot_confirm_true_posts():
    route = respx.post(f"{BASE}{CHATBOTS_PATH}").mock(
        return_value=httpx.Response(201, json={"id": CB1, "name": "Nuevo"})
    )
    client = make_client()
    try:
        result = await create_chatbot_core(client, {"name": "Nuevo"}, confirm=True)
    finally:
        await client.aclose()
    assert route.called
    assert result["created"] is True
    assert result["result"]["id"] == CB1


@respx.mock
async def test_assign_child_confirm_false_does_not_post():
    route = respx.post(f"{BASE}{children_path(CB1)}").mock(
        return_value=httpx.Response(200, json={})
    )
    client = make_client()
    try:
        result = await assign_child_core(client, CB1, CB2, confirm=False)
    finally:
        await client.aclose()
    assert not route.called
    assert result["assigned"] is False


@respx.mock
async def test_assign_child_confirm_true_posts_child_id():
    route = respx.post(f"{BASE}{children_path(CB1)}").mock(
        return_value=httpx.Response(200, json={"id": CB2, "parent_chatbot_id": CB1})
    )
    client = make_client()
    try:
        result = await assign_child_core(client, CB1, CB2, confirm=True)
    finally:
        await client.aclose()
    assert route.called
    assert result["assigned"] is True
    body = route.calls.last.request.content
    assert CB2.encode() in body
    assert b"child_chatbot_id" in body


@respx.mock
async def test_unassign_child_confirm_true_deletes():
    route = respx.delete(f"{BASE}{child_path(CB1, CB2)}").mock(
        return_value=httpx.Response(204)
    )
    client = make_client()
    try:
        result = await unassign_child_core(client, CB1, CB2, confirm=True)
    finally:
        await client.aclose()
    assert route.called
    assert result["unassigned"] is True


@respx.mock
async def test_assign_child_hierarchy_violation_is_validation_error():
    # El servidor devuelve 400 ante violaciones de jerarquía (>2 niveles, etc.).
    respx.post(f"{BASE}{children_path(CB1)}").mock(
        return_value=httpx.Response(400, json={"detail": "No se permite jerarquía de más de 2 niveles"})
    )
    client = make_client()
    try:
        with pytest.raises(ValidationError):
            await assign_child_core(client, CB1, CB2, confirm=True)
    finally:
        await client.aclose()


@respx.mock
async def test_update_prompt_template_confirm_true_patches():
    template_id = "33333333-3333-3333-3333-333333333333"
    route = respx.patch(f"{BASE}/api/v1/hub/prompt-templates/{template_id}").mock(
        return_value=httpx.Response(200, json={"id": template_id, "version": 2})
    )
    client = make_client()
    try:
        result = await update_prompt_template_core(
            client, template_id, {"template_text": "nuevo"}, confirm=True
        )
    finally:
        await client.aclose()
    assert route.called
    assert result["updated"] is True


@respx.mock
async def test_write_without_scope_raises_scope_error():
    respx.patch(f"{BASE}{chatbot_path(CB1)}").mock(
        return_value=httpx.Response(403, json={"code": "PAT_SCOPE_MISSING", "missing": ["chatbots:write"]})
    )
    client = make_client()
    try:
        with pytest.raises(ScopeError):
            await update_chatbot_core(client, CB1, {"name": "x"}, dry_run=False)
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Registro en el servidor
# ---------------------------------------------------------------------------

async def test_chatbot_tools_registered_on_server():
    srv = build_server(client_provider=lambda: None, config_provider=lambda: None)
    names = {t.name for t in await srv.list_tools()}
    assert {
        "list_organizaciones",
        "list_chatbots",
        "get_chatbot",
        "get_corpus_stats",
        "list_prompt_templates",
        "create_chatbot",
        "update_chatbot",
        "update_prompt_template",
        "assign_child",
        "unassign_child",
    } <= names


async def test_chatbot_resources_registered_on_server():
    srv = build_server(client_provider=lambda: None, config_provider=lambda: None)
    uris = {str(r.uri).rstrip("/") for r in await srv.list_resources()}
    assert "govgenai://chatbots/enums" in uris
    assert "govgenai://chatbots/schema" in uris
