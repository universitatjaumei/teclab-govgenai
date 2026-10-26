"""AIS.6 — El §13 de la AGPL: el enlace al fuente sale del despliegue, no del código."""
from __future__ import annotations

from pathlib import Path


def test_should_serve_the_source_url_from_configuration(monkeypatch):
    from server.app.main import instancia
    import asyncio

    monkeypatch.setenv("SOURCE_URL", "https://git.example.org/fork")
    assert asyncio.run(instancia())["source_url"] == "https://git.example.org/fork"


def test_should_serve_nothing_when_not_configured(monkeypatch):
    from server.app.main import instancia
    import asyncio

    monkeypatch.delenv("SOURCE_URL", raising=False)
    assert asyncio.run(instancia())["source_url"] is None
    monkeypatch.setenv("SOURCE_URL", "   ")
    assert asyncio.run(instancia())["source_url"] is None


def test_should_not_hardcode_the_upstream_url():
    texto = Path("app/main.py").read_text(encoding="utf-8")
    bloque = texto.split("async def instancia")[1][:1600]
    assert "http://" not in bloque
    assert "https://" not in bloque


def test_should_document_the_variable():
    ejemplo = Path("../.env.example").read_text(encoding="utf-8")
    assert "SOURCE_URL=" in ejemplo
