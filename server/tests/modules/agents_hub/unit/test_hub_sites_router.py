"""Tests TDD — hub_sites_router (Prompt 9Q.7).

CRUD de HubWebSite, selecciones y endpoints de candidatas/ingestión.
Usa FastAPI TestClient con dependencias sobreescritas.
"""
from __future__ import annotations

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-at-least-32-chars-long")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRATION_MINUTES", "60")


# SEC.8.1: estos endpoints resuelven ahora el sitio (o el chatbot) a su organización antes
# de operar, así que el actor tiene que pertenecer a alguna. Antes el token no llevaba
# ninguna y daba igual: el router solo miraba el rol.
ORG = uuid.UUID("00000000-0000-0000-0000-0000000000a1")


def _make_token(role: str = "admin") -> str:
    from server.app.core.auth import UserInfo, create_token
    return create_token(
        UserInfo(
            user_id="admin-1",
            email="admin@test.com",
            role=role,
            organizacion_ids=(str(ORG),),
        )
    )


def _fake_site(**kw):
    m = MagicMock()
    m.id = kw.get("id", uuid.uuid4())
    m.organizacion_id = kw.get("organizacion_id", ORG)
    m.name = kw.get("name", "Sitio Test")
    m.root_url = kw.get("root_url", "https://ej.es")
    m.sitemap_url = kw.get("sitemap_url", None)
    m.spider_type = kw.get("spider_type", "generic")
    m.crawl_interval_hours = kw.get("crawl_interval_hours", 24)
    m.audit_semantic_scope = kw.get("audit_semantic_scope", "ingested")
    m.last_crawled_at = None
    m.status = kw.get("status", "active")
    m.created_at = kw.get("created_at", __import__("datetime").datetime.utcnow())
    return m


def _fake_selection(**kw):
    m = MagicMock()
    m.id = kw.get("id", uuid.uuid4())
    m.chatbot_id = kw.get("chatbot_id", uuid.uuid4())
    m.site_id = kw.get("site_id", uuid.uuid4())
    m.rule_type = kw.get("rule_type", "path_prefix")
    m.rule_value = kw.get("rule_value", "/temas/")
    # DIN.3 — la selección puede apuntar a una sección; estas no lo hacen. Con un `MagicMock` el
    # valor por defecto sería un mock y la validación de la respuesta lo rechazaría.
    m.section_id = kw.get("section_id", None)
    m.auto_ingest_new = kw.get("auto_ingest_new", True)
    m.created_at = kw.get("created_at", __import__("datetime").datetime.utcnow())
    return m


def _fake_page(**kw):
    m = MagicMock()
    m.id = kw.get("id", uuid.uuid4())
    m.site_id = kw.get("site_id", uuid.uuid4())
    m.url = kw.get("url", "https://ej.es/temas/agua")
    m.title = kw.get("title", "Página")
    m.status = kw.get("status", "active")
    m.token_count = kw.get("token_count", 500)
    m.superseded = kw.get("superseded", False)
    m.quality_score = kw.get("quality_score", None)
    m.last_crawled_at = None
    # 2026-10-08 — sin esto, MagicMock inventa un objeto para la propuesta y la respuesta no valida.
    m.propuesta_at = kw.get("propuesta_at", None)
    m.propuesta_por = kw.get("propuesta_por", None)
    return m


def _build_app(session_mock=None, site_repo_mock=None, selection_service_mock=None, quality_job_mock=None):
    from server.app.routers.hub_sites_router import router, get_quality_job
    from server.app.modules.agents_hub.database.connection import get_async_session

    _session = session_mock or AsyncMock()

    # SEC.8.1: `assert_site_org_access` / `assert_chatbot_org_access` cargan el recurso con
    # `session.get` para resolver su organización. Sin esto, un `AsyncMock` devuelve un
    # `organizacion_id` que no es el del token y todos los endpoints darían 403.
    #
    # Devuelve un sitio COMPLETO y no un objeto con solo la organización: varios endpoints
    # (`patch_site`) acaban sirviendo lo que salga de `session.get`, y un doble a medias
    # pasaría la frontera para caer después en la validación de la respuesta.
    _session.get = AsyncMock(return_value=_fake_site())

    async def _session_override():
        yield _session

    app = FastAPI()
    app.dependency_overrides[get_async_session] = _session_override

    if quality_job_mock is not None:
        app.dependency_overrides[get_quality_job] = lambda: quality_job_mock

    app.include_router(router, prefix="/api/v1")
    return app


# ───────────────────────── Tests de sites CRUD ─────────────────────────


def test_create_site_returns_201(monkeypatch):
    """POST /hub/sites → 201 con el sitio creado."""
    site = _fake_site(name="Mi Sitio")
    session = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    # Simula WebSiteRepo.create retornando el site. Vía monkeypatch y NUNCA por
    # asignación directa a la clase: `WebSiteRepo.create = AsyncMock(...)` dejaba el
    # mock instalado para el resto del proceso, y todo test posterior que creara un
    # sitio de verdad recibía este objeto desanclado sin ejecutar ni un INSERT — el
    # origen de los 10 fallos de test_site_model.py en ejecución conjunta (TST.1).
    from server.app.modules.curation.site_repo import WebSiteRepo
    monkeypatch.setattr(WebSiteRepo, "create", AsyncMock(return_value=site))

    client = TestClient(_build_app(session_mock=session))
    # SEC.8.1: la organización se declara y se valida contra el token. Sin ella el sitio
    # sería de plataforma —fuera de toda cascada y de todo listado acotado—, y crear uno
    # así queda reservado al superadministrador.
    resp = client.post(
        f"/api/v1/hub/sites?organizacion_id={ORG}",
        json={"name": "Mi Sitio", "root_url": "https://ej.es"},
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "Mi Sitio"


def test_list_sites_returns_200():
    """GET /hub/sites → 200 con la lista de sitios."""
    site = _fake_site()
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [site]
    session.execute = AsyncMock(return_value=result)

    client = TestClient(_build_app(session_mock=session))
    resp = client.get(
        "/api/v1/hub/sites",
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_list_sites_401_without_auth():
    """GET /hub/sites sin JWT → 401 o 403."""
    session = AsyncMock()
    client = TestClient(_build_app(session_mock=session))
    resp = client.get("/api/v1/hub/sites")
    assert resp.status_code in (401, 403)


def test_patch_site_returns_200():
    """PATCH /hub/sites/{id} → 200 con el sitio actualizado."""
    site_id = uuid.uuid4()
    site = _fake_site(id=site_id, name="Actualizado")
    session = AsyncMock()
    session.get = AsyncMock(return_value=site)
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    client = TestClient(_build_app(session_mock=session))
    resp = client.patch(
        f"/api/v1/hub/sites/{site_id}",
        json={"name": "Actualizado"},
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 200


def test_delete_site_returns_204():
    """DELETE /hub/sites/{id} → 204."""
    site_id = uuid.uuid4()
    site = _fake_site(id=site_id)
    session = AsyncMock()
    session.get = AsyncMock(return_value=site)
    session.delete = AsyncMock()
    session.flush = AsyncMock()

    client = TestClient(_build_app(session_mock=session))
    resp = client.delete(
        f"/api/v1/hub/sites/{site_id}",
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 204


# ───────────────────────── Test de crawl ─────────────────────────


def test_trigger_crawl_returns_202_and_calls_job():
    """POST /hub/sites/{id}/crawl → 202 y encola run_for_site."""
    site_id = uuid.uuid4()
    site = _fake_site(id=site_id)
    session = AsyncMock()
    session.get = AsyncMock(return_value=site)

    quality_job = MagicMock()
    quality_job.run_for_site = AsyncMock()

    client = TestClient(_build_app(session_mock=session, quality_job_mock=quality_job))
    resp = client.post(
        f"/api/v1/hub/sites/{site_id}/crawl",
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 202


# ───────────────────────── Test de páginas ─────────────────────────


def test_list_site_pages_returns_200():
    """GET /hub/sites/{id}/pages → 200 con la lista de páginas."""
    site_id = uuid.uuid4()
    page = _fake_page(site_id=site_id)
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [page]
    session.execute = AsyncMock(return_value=result)

    client = TestClient(_build_app(session_mock=session))
    resp = client.get(
        f"/api/v1/hub/sites/{site_id}/pages",
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ───────────────────────── Tests de selecciones ─────────────────────────


def test_create_selection_returns_201(monkeypatch):
    """POST /hub/chatbots/{id}/selections → 201."""
    chatbot_id = uuid.uuid4()
    sel = _fake_selection(chatbot_id=chatbot_id)
    session = AsyncMock()
    session.flush = AsyncMock()
    session.refresh = AsyncMock()

    # monkeypatch, no asignación a la clase: ver el comentario de test_create_site.
    from server.app.modules.curation.site_repo import CorpusSelectionRepo
    monkeypatch.setattr(CorpusSelectionRepo, "create", AsyncMock(return_value=sel))

    client = TestClient(_build_app(session_mock=session))
    resp = client.post(
        f"/api/v1/hub/chatbots/{chatbot_id}/selections",
        json={"site_id": str(sel.site_id), "rule_type": "path_prefix", "rule_value": "/temas/"},
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 201


def test_list_selections_returns_200():
    """GET /hub/chatbots/{id}/selections → 200."""
    chatbot_id = uuid.uuid4()
    sel = _fake_selection(chatbot_id=chatbot_id)
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = [sel]
    session.execute = AsyncMock(return_value=result)

    client = TestClient(_build_app(session_mock=session))
    resp = client.get(
        f"/api/v1/hub/chatbots/{chatbot_id}/selections",
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 200


def test_delete_selection_returns_204():
    """DELETE /hub/chatbots/{id}/selections/{sid} → 204."""
    chatbot_id = uuid.uuid4()
    sel_id = uuid.uuid4()
    sel = _fake_selection(id=sel_id, chatbot_id=chatbot_id)
    session = AsyncMock()
    session.get = AsyncMock(return_value=sel)
    session.delete = AsyncMock()
    session.flush = AsyncMock()

    client = TestClient(_build_app(session_mock=session))
    resp = client.delete(
        f"/api/v1/hub/chatbots/{chatbot_id}/selections/{sel_id}",
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 204


# ───────────────────────── Test de candidatas ─────────────────────────


def test_list_candidates_returns_200():
    """GET /hub/sites/{id}/candidates?chatbot_id= → 200."""
    site_id = uuid.uuid4()
    chatbot_id = uuid.uuid4()
    session = AsyncMock()

    from server.app.modules.curation.selection_contracts import CandidatePageView
    candidate = CandidatePageView(
        page_id=uuid.uuid4(),
        url="https://ej.es/temas/agua",
        title="Agua",
        matched_rule="/temas/",
        is_new=False,
    )

    from server.app.routers.hub_sites_router import get_selection_service
    mock_svc = MagicMock()
    mock_svc.candidates = AsyncMock(return_value=[candidate])

    from server.app.routers.hub_sites_router import router

    app = FastAPI()
    from server.app.modules.agents_hub.database.connection import get_async_session
    # SEC.8.1: la guarda de organización resuelve el recurso con `session.get`.
    session.get = AsyncMock(return_value=_fake_site())
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_selection_service] = lambda: mock_svc
    app.include_router(router, prefix="/api/v1")

    client = TestClient(app)
    resp = client.get(
        f"/api/v1/hub/sites/{site_id}/candidates",
        params={"chatbot_id": str(chatbot_id)},
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["url"] == "https://ej.es/temas/agua"


# ───────────────────────── Tests ingest / retire ─────────────────────────


def test_ingest_page_returns_202(monkeypatch):
    """POST /hub/chatbots/{id}/pages/{pid}/ingest → 202.

    RAS.5 — el endpoint ya no usa el servicio inyectado, que venía **sin watcher** y hacía que la
    ingestión reventara en background mientras la respuesta decía «queued». Aquí se dobla el
    servicio que sí puede ingerir para que este test siga hablando del contrato HTTP; que el
    cableado real lleva watcher lo comprueba
    `tests/modules/curation/integration/test_ingerir_una_pagina_al_corpus.py`.
    """
    chatbot_id = uuid.uuid4()
    page_id = uuid.uuid4()
    session = AsyncMock()

    from server.app.routers.hub_sites_router import get_selection_service
    mock_svc = MagicMock()
    mock_svc.ingest_page = AsyncMock(return_value=MagicMock(id=uuid.uuid4()))

    async def _servicio_doble(sesion, cid):
        return mock_svc

    monkeypatch.setattr(
        "server.app.routers.hub_sites_router._servicio_que_puede_ingerir", _servicio_doble
    )

    from server.app.routers.hub_sites_router import router
    app = FastAPI()
    from server.app.modules.agents_hub.database.connection import get_async_session
    # SEC.8.1: la guarda de organización resuelve el recurso con `session.get`.
    session.get = AsyncMock(return_value=_fake_site())
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_selection_service] = lambda: mock_svc
    app.include_router(router, prefix="/api/v1")

    client = TestClient(app)
    resp = client.post(
        f"/api/v1/hub/chatbots/{chatbot_id}/pages/{page_id}/ingest",
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 202


def test_retire_page_returns_200_with_count():
    """DELETE /hub/chatbots/{id}/pages/{pid} → 200 con el count de documentos retirados."""
    chatbot_id = uuid.uuid4()
    page_id = uuid.uuid4()
    session = AsyncMock()

    from server.app.routers.hub_sites_router import get_selection_service
    mock_svc = MagicMock()
    mock_svc.retire_page = AsyncMock(return_value=2)

    from server.app.routers.hub_sites_router import router
    app = FastAPI()
    from server.app.modules.agents_hub.database.connection import get_async_session
    # SEC.8.1: la guarda de organización resuelve el recurso con `session.get`.
    session.get = AsyncMock(return_value=_fake_site())
    app.dependency_overrides[get_async_session] = lambda: session
    app.dependency_overrides[get_selection_service] = lambda: mock_svc
    app.include_router(router, prefix="/api/v1")

    client = TestClient(app)
    resp = client.delete(
        f"/api/v1/hub/chatbots/{chatbot_id}/pages/{page_id}",
        headers={"Authorization": f"Bearer {_make_token()}"},
    )
    assert resp.status_code == 200
    assert resp.json()["documents_removed"] == 2
