"""#344 — cuando el modelo falla, el Copilot lo dice en vez de dar un 500.

El 30-10 el modelo por defecto del nivel 1 era `gemini-2.0-flash`, ya retirado. `get_copilot_service`
lo resolvía sin problema —la fila existía—, la llamada a Google devolvía `404 NOT_FOUND` y la
excepción subía sin capturar: un usuario de la OPAQ vio «error intern», sin forma de saber que lo
que había que mirar era el modelo configurado. El 503 de `get_copilot_service` ya dice qué falta
cuando **no hay** modelo; esto es lo mismo para cuando lo hay y no responde.

El fallo se recoge alrededor de la llamada al modelo y no de toda la respuesta: un fallo del
buscador de documentación no es del modelo, y decir que sí mandaría a mirar la pantalla equivocada.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from server.app.core.auth.models import UserInfo

pytestmark = pytest.mark.asyncio


class _EmbeddingDeMentira:
    async def embed(self, text: str, purpose: str = "query") -> list[float]:
        return [float(len(text) % 7), 1.0, 0.5]


class _ModeloRetirado:
    model = "gemini-2.0-flash"

    async def ainvoke(self, messages):
        raise RuntimeError(
            "404 NOT_FOUND. This model models/gemini-2.0-flash is no longer available."
        )


class _BuscadorRoto:
    async def retrieve(self, *_a, **_k):
        raise RuntimeError("el índice de la documentación no se pudo leer")


@pytest.fixture
def docs(tmp_path: Path) -> Path:
    (tmp_path / "CONTRATO.md").write_text(
        "# Contrato del corpus\n\nAl corpus solo entra Markdown conforme al contrato.\n",
        encoding="utf-8",
    )
    return tmp_path


def _app(servicio) -> FastAPI:
    from server.app.api.deps import get_current_user
    from server.app.core.errores import instalar_errores
    from server.app.routers.redaccion.copilot_router import get_copilot_service, router

    app = FastAPI()
    instalar_errores(app)
    app.dependency_overrides[get_current_user] = lambda: UserInfo(
        user_id="u1", email="u@uji.es", role="admin", organizacion_ids=()
    )
    app.dependency_overrides[get_copilot_service] = lambda: servicio
    app.include_router(router, prefix="/api/v1")
    return app


async def _preguntar(servicio):
    transporte = ASGITransport(app=_app(servicio), raise_app_exceptions=False)
    async with AsyncClient(transport=transporte, base_url="http://t") as c:
        return await c.post(
            "/api/v1/redaccion/copilot/ask", json={"question": "¿Qué entra al corpus?"}
        )


async def test_un_modelo_que_no_responde_es_un_502_que_dice_cual_y_por_que(docs: Path) -> None:
    from server.app.modules.redaccion.services.copilot.copilot_service import CopilotService
    from server.app.modules.redaccion.services.copilot.docs_retriever import DocsRetriever

    servicio = CopilotService(
        llm=_ModeloRetirado(),
        retriever=DocsRetriever(embedding_service=_EmbeddingDeMentira(), docs_dir=docs),
    )

    r = await _preguntar(servicio)

    assert r.status_code == 502, r.text
    mensaje = r.json()["detail"]["message"]
    assert "gemini-2.0-flash" in mensaje
    assert "Modelos IA" in mensaje, "tiene que decir dónde se arregla"


async def test_el_motivo_del_proveedor_va_al_registro_y_no_a_la_pantalla(docs: Path, caplog) -> None:
    """Revisión de la PR #347: el texto del proveedor lo vería cualquiera con el módulo de Informes,
    y un SDK puede meter ahí la URL con su clave o la dirección interna del modelo."""
    from server.app.modules.redaccion.services.copilot.copilot_service import CopilotService
    from server.app.modules.redaccion.services.copilot.docs_retriever import DocsRetriever

    servicio = CopilotService(
        llm=_ModeloRetirado(),
        retriever=DocsRetriever(embedding_service=_EmbeddingDeMentira(), docs_dir=docs),
    )

    with caplog.at_level("WARNING"):
        r = await _preguntar(servicio)

    assert "no longer available" not in r.text
    assert "no longer available" in caplog.text


async def test_un_fallo_del_buscador_no_se_atribuye_al_modelo() -> None:
    from server.app.modules.redaccion.services.copilot.copilot_service import CopilotService

    r = await _preguntar(CopilotService(llm=_ModeloRetirado(), retriever=_BuscadorRoto()))

    assert r.status_code == 500
    assert "gemini-2.0-flash" not in r.text
