"""Ingerir al corpus una página rastreada (RAS.5).

El endpoint respondía **202 «queued»** y la página no entraba nunca: `get_selection_service`
construye el servicio con `watcher=None` —su propio docstring dice que para `ingest_page` el
endpoint tiene que construir el watcher de verdad, y no lo hacía—, así que `ingest_page` reventaba
con `AttributeError` **dentro de un `BackgroundTask`**, donde nadie ve la excepción.

Es el circuito completo del módulo: rastrear → curar → que el asistente lo cite. Sin este paso, la
curación acaba en una bandeja que no lleva a ninguna parte.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.app.api.deps import get_current_user
from server.app.core.auth.models import UserInfo
from server.app.api.deps import get_session
from server.app.routers.hub_sites_router import router as sites_router

_ORG = uuid.uuid4()


def _app(sesion: Any) -> FastAPI:
    async def _sesion():
        yield sesion

    async def _usuario():
        return UserInfo(
            user_id=str(uuid.uuid4()), email="admin@example.local", role="admin",
            organizacion_ids=(str(_ORG),),
        )

    app = FastAPI()
    app.include_router(sites_router, prefix="/api/v1")
    app.dependency_overrides[get_session] = _sesion
    app.dependency_overrides[get_current_user] = _usuario
    return app


def _sesion_con_chatbot_y_pagina(page_id: uuid.UUID) -> Any:
    chatbot = MagicMock()
    chatbot.id = uuid.uuid4()
    chatbot.organizacion_id = _ORG
    pagina = MagicMock()
    pagina.id = page_id
    pagina.url = "https://www.uji.es/centres/escola-doctorat/beques/"
    pagina.markdown_content = "Convocatòria de beques del programa de doctorat."
    pagina.title = "Beques de doctorat"

    async def _get(modelo: Any, ident: Any):
        # La sesión sirve dos cosas distintas: el chatbot al comprobar el acceso y la página al
        # ingerir. Devolver lo mismo para las dos hacía que el test hablara del doble, no del código.
        return pagina if getattr(modelo, "__name__", "") == "HubCrawledPage" else chatbot

    sesion = AsyncMock()
    sesion.get = AsyncMock(side_effect=_get)
    resultado = MagicMock()
    resultado.scalars.return_value.all.return_value = [pagina]
    resultado.scalar_one_or_none.return_value = pagina
    sesion.execute = AsyncMock(return_value=resultado)
    sesion.commit = AsyncMock()
    return sesion


def test_ingerir_una_pagina_la_manda_de_verdad_al_watcher(monkeypatch):
    """El 202 tiene que significar que se ha encolado algo que funciona."""
    from server.app.routers import hub_sites_router as router_mod

    page_id = uuid.uuid4()
    llamadas: list[dict] = []

    class _WatcherFalso:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

        async def process_source(self, **kwargs: Any):
            llamadas.append(kwargs)
            return MagicMock(), True

    # El router importa las dos piezas dentro de la función, así que se doblan en su módulo.
    monkeypatch.setattr(
        "server.app.modules.agents_hub.ingestion.watcher.IngestionWatcher",
        _WatcherFalso,
    )

    async def _embedding_falso(session: Any, chatbot_id: Any):
        return MagicMock()

    monkeypatch.setattr(
        "server.app.modules.agents_hub.services.embedding_resolver.resolve_embedding_service",
        _embedding_falso,
    )
    assert router_mod is not None

    sesion = _sesion_con_chatbot_y_pagina(page_id)
    with TestClient(_app(sesion)) as client:
        respuesta = client.post(
            f"/api/v1/hub/chatbots/{uuid.uuid4()}/pages/{page_id}/ingest"
        )

    assert respuesta.status_code == 202, respuesta.text
    assert llamadas, "el 202 se respondia sin que la pagina llegara nunca al corpus"
    assert llamadas[0]["source_url"].endswith("/beques/")
    assert llamadas[0]["crawled_page_id"] == page_id


@pytest.mark.asyncio
async def test_el_servicio_que_ingiere_lleva_watcher(monkeypatch):
    """La comprobación de raíz: el servicio que ingiere no puede venir sin watcher.

    El que inyecta `get_selection_service` viene con `watcher=None`, y con él `ingest_page` no
    puede hacer nada; el fallo además ocurría en background, donde no se ve.
    """
    from server.app.routers.hub_sites_router import _servicio_que_puede_ingerir

    async def _embedding_falso(session: Any, chatbot_id: Any):
        return MagicMock()

    monkeypatch.setattr(
        "server.app.modules.agents_hub.services.embedding_resolver.resolve_embedding_service",
        _embedding_falso,
    )

    servicio = await _servicio_que_puede_ingerir(AsyncMock(), uuid.uuid4())

    assert servicio._watcher is not None
