import os
from unittest.mock import patch

from server.tests.rutas import caminos

import pytest


def test_deploy_mode_invalid_raises():
    with patch.dict(os.environ, {"DEPLOY_MODE": "foo"}):
        import importlib
        with pytest.raises(RuntimeError, match="Invalid DEPLOY_MODE: foo"):  # noqa: PT012 — lanza el import o el reload, según si ya estaba cargado
            import server.app.main
            importlib.reload(server.app.main)

def test_deploy_mode_cloud_excludes_edge_routers():
    with patch.dict(os.environ, {"DEPLOY_MODE": "cloud"}):
        import importlib
        import server.app.main
        importlib.reload(server.app.main)
        
        # Check if cloud routers exist and edge routers do not
        routes = sorted(caminos(server.app.main.app))
        assert any(p.startswith("/api/v1/hub/chatbots") for p in routes)
        assert not any(p == "/api/v1/hub/chat" for p in routes)

def test_deploy_mode_edge_excludes_cloud_routers():
    with patch.dict(os.environ, {"DEPLOY_MODE": "edge"}):
        import importlib
        import server.app.main
        importlib.reload(server.app.main)

        routes = sorted(caminos(server.app.main.app))
        assert any(p.startswith("/api/v1/hub/chat") for p in routes)
        # El endpoint raíz /api/v1/hub/chatbots (CRUD admin de chatbots) es cloud-only.
        # Los endpoints /api/v1/hub/chatbots/{id}/selections etc. son edge y sí aparecen.
        assert not any(p == "/api/v1/hub/chatbots" for p in routes)

def test_default_deploy_mode_registers_all_routers():
    with patch.dict(os.environ, clear=True):
        import importlib
        import server.app.main
        importlib.reload(server.app.main)
        
        routes = sorted(caminos(server.app.main.app))
        assert any(p.startswith("/api/v1/hub/chatbots") for p in routes)
        assert any(p.startswith("/api/v1/hub/chat") for p in routes)
