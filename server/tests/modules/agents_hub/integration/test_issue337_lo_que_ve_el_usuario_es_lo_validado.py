"""#337 — lo que ve el usuario es la respuesta validada, no los tokens tal como salieron.

El contrato de citas y el aviso de vigencia corren dentro de `generate_answer`, **después** de
generar. `turno_de_chat` emite los tokens según salen del modelo y sólo usaba la respuesta
validada cuando el contrato se rendía. Así que:

- **El aviso de vigencia (VIS.3) no llegaba nunca.** Es un añadido al final, y se emite como un
  token más: no hace falta reemplazar nada. Siempre, sin interruptor: es una garantía.
- **Las correcciones de citas** —un ancla que nadie leyó bajada al documento, el enlace quitado
  a lo que no se entregó— tampoco. Mostrarlas exige reemplazar el texto al final, y eso se ve:
  va detrás de un interruptor por chatbot, `show_citation_corrections`, apagado por defecto.

Lo que se guarda en `hub_interactions` es lo que el usuario vio.
"""
from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.modules.agents_hub.database.config_models import HubChatbot
from server.tests.dobles import completar_chatbot

ORG = "00000000-0000-0000-0000-00000000dead"
JWT = {
    "JWT_SECRET_KEY": "test-secret-key-that-is-at-least-32-characters-long",
    "JWT_ALGORITHM": "HS256",
    "JWT_EXPIRATION_MINUTES": "60",
}
CRUDO = "Es X [Reglament](https://n.example.org/r.html#art-9)."
CORREGIDO = "Es X [Reglament](https://n.example.org/r.html)."
AVISO = "---\nAviso: la vigencia de la normativa citada no esta validada."


def _token() -> str:
    os.environ.update(JWT)
    from server.app.core.auth import UserInfo, create_token

    return create_token(UserInfo(user_id="u", email="u@t.com", role="user", organizacion_ids=(ORG,)))


def _eventos(respuesta_validada: str, aviso: str | None, crudo: str = CRUDO) -> list[dict]:
    mitad = len(crudo) // 2
    return [
        {"event": "on_chain_start", "name": "generate_answer", "data": {}},
        *(
            {
                "event": "on_chat_model_stream",
                "name": "llm",
                "metadata": {"langgraph_node": "generate_answer"},
                "data": {"chunk": SimpleNamespace(content=parte)},
            }
            for parte in (crudo[:mitad], crudo[mitad:])
        ),
        {
            "event": "on_chain_end",
            "name": "generate_answer",
            "data": {"output": {
                "answer": respuesta_validada, "aviso": aviso, "sources": [],
                "fallback_used": False, "fallback_reason": None,
            }},
        },
    ]


def _lanzar(eventos: list[dict], corregir: bool) -> tuple[list[tuple[str, dict]], list]:
    from server.app.api.deps import get_session
    from server.app.api.v1.hub_chat import router

    cb = MagicMock(spec=HubChatbot)
    cb.id = uuid.uuid4()
    cb.organizacion_id = uuid.UUID(ORG)
    completar_chatbot(cb)
    cb.retrieval_mode = "MD_LONG_CONTEXT"
    cb.kind = "atomic"
    cb.name = "Bot"

    anadidos: list = []
    sesion = AsyncMock()
    resultado = MagicMock()
    resultado.scalar_one_or_none = MagicMock(return_value=cb)
    sesion.execute = AsyncMock(return_value=resultado)
    sesion.get = AsyncMock(return_value=None)
    sesion.add = MagicMock(side_effect=anadidos.append)

    async def _astream(state, config=None, version="v2"):
        for ev in eventos:
            yield ev

    compilado = MagicMock()
    compilado.astream_events = _astream
    grafo = MagicMock()
    grafo.compile = MagicMock(return_value=compilado)
    grafo.cfg = SimpleNamespace(quality_threshold=0.0, show_citation_corrections=corregir)

    async def _sesion():
        yield sesion

    app = FastAPI()
    app.dependency_overrides[get_session] = _sesion
    app.include_router(router, prefix="/api/v1")
    raiz = "server.app.modules.agents_hub.services.turno_de_chat"
    with (
        patch(f"{raiz}.GraphFactory", return_value=MagicMock(build=AsyncMock(return_value=grafo))),
        patch(f"{raiz}.resolve_embedding_service", new_callable=AsyncMock),
        patch(f"{raiz}.get_model", new_callable=AsyncMock),
        TestClient(app) as cliente,
        cliente.stream(
            "POST", f"/api/v1/hub/chat/{cb.id}", json={"message": "q"},
            headers={"Authorization": f"Bearer {_token()}"},
        ) as r,
    ):
        lineas = list(r.iter_lines())

    eventos_sse: list[tuple[str, dict]] = []
    actual = "message"
    for linea in lineas:
        if linea.startswith("event:"):
            actual = linea.removeprefix("event:").strip()
        elif linea.startswith("data:"):
            eventos_sse.append((actual, json.loads(linea.removeprefix("data:").strip())))
    return eventos_sse, anadidos


def _visto(eventos: list[tuple[str, dict]]) -> str:
    """Lo que acaba en pantalla: los tokens, empezando de nuevo tras cada `discard`."""
    texto = ""
    for tipo, datos in eventos:
        if tipo == "discard":
            texto = ""
        elif tipo == "token":
            texto += datos["delta"]
    return texto


def _guardado(anadidos: list) -> str:
    from server.app.modules.agents_hub.database.operational_models import HubInteraction

    return next(a for a in anadidos if isinstance(a, HubInteraction)).assistant_message


@patch.dict("os.environ", JWT)
def test_el_aviso_de_vigencia_llega_aunque_no_se_corrija_nada() -> None:
    eventos, anadidos = _lanzar(_eventos(f"{CORREGIDO}\n\n{AVISO}", AVISO), corregir=False)

    assert _visto(eventos) == f"{CRUDO}\n\n{AVISO}"
    assert "discard" not in [t for t, _ in eventos]
    assert _guardado(anadidos) == _visto(eventos)


@patch.dict("os.environ", JWT)
def test_sin_interruptor_las_citas_se_ven_como_salieron() -> None:
    eventos, anadidos = _lanzar(_eventos(CORREGIDO, None), corregir=False)

    assert _visto(eventos) == CRUDO
    assert _guardado(anadidos) == CRUDO


@patch.dict("os.environ", JWT)
def test_con_interruptor_se_ve_la_respuesta_validada() -> None:
    eventos, anadidos = _lanzar(_eventos(f"{CORREGIDO}\n\n{AVISO}", AVISO), corregir=True)

    assert ("discard", {"reason": "citation_corrections"}) in eventos
    assert _visto(eventos) == f"{CORREGIDO}\n\n{AVISO}"
    assert _guardado(anadidos) == _visto(eventos)


@patch.dict("os.environ", JWT)
def test_con_interruptor_y_nada_que_corregir_no_se_reemplaza() -> None:
    """El reemplazo se ve; si no cambia nada, no se hace."""
    eventos, _ = _lanzar(_eventos(CRUDO, None), corregir=True)

    assert "discard" not in [t for t, _ in eventos]
    assert _visto(eventos) == CRUDO


# --- El grafo dice qué aviso añadió, y de qué documentos se avisa ----------------------------------


@pytest.mark.asyncio
async def test_el_grafo_devuelve_el_aviso_aparte() -> None:
    from server.tests.public_graphs.test_vis_vigencia import _ejecutar_grafo, _item

    estado = await _ejecutar_grafo([_item("Sense validar", True)])

    assert estado["aviso"]
    assert estado["answer"].endswith(estado["aviso"])


def test_un_documento_que_no_es_una_norma_no_lleva_aviso() -> None:
    """Sin `estat_vigencia` no hay ciclo de vida que validar: un documento subido o una página
    rastreada. Con el aviso visible, a quien sube sus documentos le saldría «la vigencia de la
    normativa citada no está validada»."""
    from server.app.modules.agents_hub.services.retrieval.vigencia import vigencia_no_validada

    assert vigencia_no_validada(None, None) is False
    assert vigencia_no_validada("vigent?", None) is True
    assert vigencia_no_validada("vigent", "2026-10-01") is False


# --- El interruptor -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_el_interruptor_se_hereda_apagado_y_lo_enciende_el_chatbot() -> None:
    from server.app.modules.agents_hub.agent.public_graphs.core.config_resolver import (
        get_effective_public_graph_config,
    )

    cb = MagicMock(spec=HubChatbot)
    completar_chatbot(cb)
    sesion = AsyncMock()
    sesion.get = AsyncMock(side_effect=lambda modelo, _id: cb if modelo is HubChatbot else None)

    assert (await get_effective_public_graph_config(uuid.uuid4(), sesion)).show_citation_corrections is False
    cb.show_citation_corrections = True
    assert (await get_effective_public_graph_config(uuid.uuid4(), sesion)).show_citation_corrections is True


def test_la_api_acepta_el_interruptor() -> None:
    from server.app.routers.hub_chatbots_router import ChatbotRead, ChatbotUpdate

    assert ChatbotUpdate(show_citation_corrections=True).show_citation_corrections is True
    assert "show_citation_corrections" in ChatbotRead.model_fields
