"""DIN.3 — parametrizar secciones dentro del proceso de curación, por HTTP.

DIN.1 dejó la sección como dato y DIN.2 la puso a rastrear; lo que falta es que quien cura pueda
crearla **sin pasar por la administración de sitios**, que es el motivo del bloque: «los apartados
se han de poder parametrizar como bloques o secciones dentro de un proceso de curación, no quedar
fijados».

Tres cosas que se prueban aquí y que no son CRUD:

* **La prueba del patrón antes de guardar.** Un regex que compila pero no casa nada hoy sólo se
  descubre cuando la pasada siguiente no ingiere nada — y como la ingesta automática es
  silenciosa, se descubre tarde. El endpoint cuenta cuántas páginas **ya rastreadas** casarían y
  devuelve una muestra.
* **El borrado que no deja selecciones colgando.** Con `section_id` puesto, el patrón efectivo lo
  manda la sección: borrarla dejaría una selección apuntando a un ámbito que no existe, y eso con
  la auto-retirada de DIN.4 detrás no es un dato huérfano, es corpus que se vacía.
* **La acotación por organización**, que aquí llega por el sitio (`docs/MULTITENENCIA.md`).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-at-least-32-chars-long")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_EXPIRATION_MINUTES", "60")

ORG = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
OTRA_ORG = uuid.UUID("00000000-0000-0000-0000-0000000000b2")


def _token(organizacion: uuid.UUID = ORG, role: str = "admin") -> str:
    from server.app.core.auth import UserInfo, create_token

    return create_token(
        UserInfo(
            user_id="admin-1",
            email="admin@test.com",
            role=role,
            organizacion_ids=(str(organizacion),),
        )
    )


def _sitio(**kw):
    m = MagicMock()
    m.id = kw.get("id", uuid.uuid4())
    m.organizacion_id = kw.get("organizacion_id", ORG)
    m.name = "Portal"
    m.root_url = "https://www.uji.es"
    m.sitemap_url = None
    m.spider_type = "generic"
    m.crawl_interval_hours = kw.get("crawl_interval_hours", 168)
    m.config_json = kw.get("config_json", {})
    m.audit_semantic_scope = "ingested"
    m.last_crawled_at = None
    m.status = "active"
    m.created_at = datetime.now(timezone.utc)
    return m


def _seccion(site_id: uuid.UUID, **kw):
    m = MagicMock()
    m.id = kw.get("id", uuid.uuid4())
    m.site_id = site_id
    m.name = kw.get("name", "Jornadas")
    m.pattern = kw.get("pattern", "/jornadas")
    m.pattern_kind = kw.get("pattern_kind", "path_prefix")
    m.crawl_interval_hours = kw.get("crawl_interval_hours", None)
    m.mode = kw.get("mode", "manual")
    m.criteria_json = kw.get("criteria_json", None)
    m.owner = kw.get("owner", None)
    m.last_crawled_at = None
    m.is_active = kw.get("is_active", True)
    m.created_at = datetime.now(timezone.utc)
    return m


def _app(session):
    from server.app.modules.agents_hub.database.connection import get_async_session
    from server.app.routers.hub_sites_router import router

    async def _override():
        yield session

    app = FastAPI()
    app.dependency_overrides[get_async_session] = _override
    app.include_router(router, prefix="/api/v1")
    return app


def _cliente(session) -> TestClient:
    return TestClient(_app(session))


def _cabeceras(organizacion: uuid.UUID = ORG) -> dict:
    return {"Authorization": f"Bearer {_token(organizacion)}"}


def _resultado(filas: list):
    r = MagicMock()
    r.scalars.return_value.all.return_value = filas
    return r


# ──────────────────────────── CRUD ────────────────────────────


class TestCrudDeSecciones:

    def test_should_create_a_section_of_a_site(self, monkeypatch):
        from server.app.modules.curation.site_repo import WebSectionRepo

        sitio = _sitio()
        seccion = _seccion(sitio.id, name="Jornadas", pattern="/jornadas")
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)
        monkeypatch.setattr(WebSectionRepo, "create", AsyncMock(return_value=seccion))

        resp = _cliente(session).post(
            f"/api/v1/hub/sites/{sitio.id}/sections",
            json={"name": "Jornadas", "pattern": "/jornadas"},
            headers=_cabeceras(),
        )

        assert resp.status_code == 201
        cuerpo = resp.json()
        assert cuerpo["name"] == "Jornadas"
        assert cuerpo["mode"] == "manual"

    def test_should_list_the_sections_saying_which_cadence_is_inherited(self, monkeypatch):
        """Quien mira la lista tiene que distinguir la cadencia **propia** de la heredada: sin
        eso, cambiar la del sitio parecería no hacer nada en las secciones que la heredan."""
        from server.app.modules.curation.site_repo import WebSectionRepo

        sitio = _sitio(crawl_interval_hours=168)
        heredada = _seccion(sitio.id, name="Jornadas", crawl_interval_hours=None)
        propia = _seccion(sitio.id, name="Eventos", crawl_interval_hours=6)
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)
        monkeypatch.setattr(
            WebSectionRepo, "list_by_site", AsyncMock(return_value=[heredada, propia])
        )

        resp = _cliente(session).get(
            f"/api/v1/hub/sites/{sitio.id}/sections", headers=_cabeceras()
        )

        assert resp.status_code == 200
        por_nombre = {s["name"]: s for s in resp.json()}
        assert por_nombre["Jornadas"]["crawl_interval_hours_effective"] == 168
        assert por_nombre["Jornadas"]["crawl_interval_inherited"] is True
        assert por_nombre["Eventos"]["crawl_interval_hours_effective"] == 6
        assert por_nombre["Eventos"]["crawl_interval_inherited"] is False

    def test_should_edit_a_section_and_deactivate_it(self, monkeypatch):
        from server.app.modules.curation.site_repo import WebSectionRepo

        sitio = _sitio()
        seccion = _seccion(sitio.id, is_active=False, mode="automatic")
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)
        monkeypatch.setattr(WebSectionRepo, "get", AsyncMock(return_value=seccion))
        monkeypatch.setattr(WebSectionRepo, "update", AsyncMock(return_value=seccion))

        resp = _cliente(session).patch(
            f"/api/v1/hub/sites/{sitio.id}/sections/{seccion.id}",
            json={"is_active": False, "mode": "automatic"},
            headers=_cabeceras(),
        )

        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        assert resp.json()["mode"] == "automatic"

    def test_should_refuse_a_pattern_that_does_not_compile_with_422(self, monkeypatch):
        """La validación de DIN.1, ahora por HTTP. El mensaje dice qué patrón y por qué: el
        formulario es donde se escribió, y es donde tiene que salir el fallo."""
        sitio = _sitio()
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)

        resp = _cliente(session).post(
            f"/api/v1/hub/sites/{sitio.id}/sections",
            json={"name": "Jornadas", "pattern": "/jornades/[2026", "pattern_kind": "regex"},
            headers=_cabeceras(),
        )

        assert resp.status_code == 422
        assert "/jornades/[2026" in resp.text

    def test_should_block_the_delete_of_a_section_with_selections_and_say_why(
        self, monkeypatch
    ):
        """Con `section_id` puesto el patrón lo manda la sección: borrarla dejaría la selección
        apuntando a un ámbito que no existe. Se desactiva, y el mensaje lo explica."""
        from server.app.modules.curation.site_repo import WebSectionRepo

        sitio = _sitio()
        seccion = _seccion(sitio.id)
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)
        session.execute = AsyncMock(return_value=_resultado([MagicMock()]))
        borrado = AsyncMock()
        monkeypatch.setattr(WebSectionRepo, "get", AsyncMock(return_value=seccion))
        monkeypatch.setattr(WebSectionRepo, "delete", borrado)

        resp = _cliente(session).delete(
            f"/api/v1/hub/sites/{sitio.id}/sections/{seccion.id}", headers=_cabeceras()
        )

        assert resp.status_code == 409
        # «desactívala»: el mensaje tiene que decir qué hacer en su lugar, no sólo que no se
        # puede. Se busca la raíz sin la tilde porque el verbo va acentuado.
        assert "desact" in resp.json()["detail"].lower()
        borrado.assert_not_awaited()

    def test_should_delete_a_section_that_nothing_points_to(self, monkeypatch):
        from server.app.modules.curation.site_repo import WebSectionRepo

        sitio = _sitio()
        seccion = _seccion(sitio.id)
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)
        session.execute = AsyncMock(return_value=_resultado([]))
        borrado = AsyncMock()
        monkeypatch.setattr(WebSectionRepo, "get", AsyncMock(return_value=seccion))
        monkeypatch.setattr(WebSectionRepo, "delete", borrado)

        resp = _cliente(session).delete(
            f"/api/v1/hub/sites/{sitio.id}/sections/{seccion.id}", headers=_cabeceras()
        )

        assert resp.status_code == 204
        borrado.assert_awaited_once()

    def test_should_answer_a_conflict_and_not_a_500_for_a_homonymous_section(
        self, monkeypatch
    ):
        """**Lo destapó la verificación en navegador de DIN.3.**

        `UniqueConstraint(site_id, name)` hace bien su trabajo —la homónima no se guarda— pero su
        `IntegrityError` subía sin que nadie lo tradujera: la respuesta era **500**, y en pantalla
        eso es «algo se ha roto» cuando lo que pasa es «ese nombre ya está usado». Es el mismo
        criterio de la retirada bloqueada: 409 con el motivo, no un error del servidor.
        """
        from sqlalchemy.exc import IntegrityError

        from server.app.modules.curation.site_repo import WebSectionRepo

        sitio = _sitio()
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)
        monkeypatch.setattr(
            WebSectionRepo,
            "create",
            AsyncMock(
                side_effect=IntegrityError(
                    'INSERT INTO hub_web_sections', {}, Exception("uq_section_site_name")
                )
            ),
        )

        resp = _cliente(session).post(
            f"/api/v1/hub/sites/{sitio.id}/sections",
            json={"name": "Jornadas", "pattern": "/otra"},
            headers=_cabeceras(),
        )

        assert resp.status_code == 409
        assert "Jornadas" in resp.json()["detail"]
        # Y la transacción se deshace: dejarla sucia haría fallar la siguiente consulta de esta
        # petición con un error que no tiene nada que ver con la causa.
        session.rollback.assert_awaited()

    def test_should_not_serve_the_sections_of_another_organizacion(self, monkeypatch):
        """La tenencia llega por el sitio, igual que en el resto del módulo."""
        sitio = _sitio(organizacion_id=OTRA_ORG)
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)

        resp = _cliente(session).get(
            f"/api/v1/hub/sites/{sitio.id}/sections", headers=_cabeceras(ORG)
        )

        assert resp.status_code == 403

    def test_should_refuse_a_section_of_another_site(self, monkeypatch):
        """Una sección ajena editada por la ruta de este sitio es un 404, no un cambio."""
        from server.app.modules.curation.site_repo import WebSectionRepo

        sitio = _sitio()
        ajena = _seccion(uuid.uuid4())
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)
        monkeypatch.setattr(WebSectionRepo, "get", AsyncMock(return_value=ajena))

        resp = _cliente(session).patch(
            f"/api/v1/hub/sites/{sitio.id}/sections/{ajena.id}",
            json={"mode": "automatic"},
            headers=_cabeceras(),
        )

        assert resp.status_code == 404


# ──────────────────────────── La prueba del patrón ────────────────────────────


class TestProbarElPatron:

    def test_should_count_and_sample_without_writing_anything(self):
        """Lo que evita el regex que no casa nada, que hoy sólo se descubre cuando la pasada
        siguiente no ingiere nada."""
        sitio = _sitio()
        # Issue #159: el endpoint pide la COLUMNA `url` y no el objeto, porque el patron se
        # evalua en Python y traer cientos de filas ORM para leerles una cadena es la forma
        # que dejo la VM 50 minutos sin responder. El doble tiene que devolver lo mismo que
        # devuelve la base: cadenas.
        urls = [f"https://www.uji.es/jornadas/{i}" for i in range(14)]
        urls += ["https://www.uji.es/eventos/uno"]
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)
        session.execute = AsyncMock(return_value=_resultado(urls))

        resp = _cliente(session).post(
            f"/api/v1/hub/sites/{sitio.id}/sections/test-pattern",
            json={"pattern": "/jornadas", "pattern_kind": "path_prefix"},
            headers=_cabeceras(),
        )

        assert resp.status_code == 200
        cuerpo = resp.json()
        assert cuerpo["matched"] == 14
        assert cuerpo["total"] == 15
        # Una muestra, no el volcado: la pantalla tiene que caber.
        assert len(cuerpo["sample"]) == 10
        assert all("/jornadas/" in url for url in cuerpo["sample"])
        session.add.assert_not_called()
        session.commit.assert_not_awaited()

    def test_should_say_out_loud_when_the_pattern_matches_nothing(self):
        sitio = _sitio()
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)
        session.execute = AsyncMock(
            return_value=_resultado(["https://www.uji.es/eventos/uno"])
        )

        resp = _cliente(session).post(
            f"/api/v1/hub/sites/{sitio.id}/sections/test-pattern",
            json={"pattern": "/jornades", "pattern_kind": "path_prefix"},
            headers=_cabeceras(),
        )

        assert resp.json()["matched"] == 0
        assert resp.json()["sample"] == []

    def test_should_refuse_to_test_a_pattern_that_does_not_compile(self):
        sitio = _sitio()
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)

        resp = _cliente(session).post(
            f"/api/v1/hub/sites/{sitio.id}/sections/test-pattern",
            json={"pattern": "[2026", "pattern_kind": "regex"},
            headers=_cabeceras(),
        )

        assert resp.status_code == 422


# ──────────────────────────── El diario de pasadas (DIN.6) ────────────────────────────


def _pasada(site_id: uuid.UUID, **kw):
    m = MagicMock()
    m.id = kw.get("id", uuid.uuid4())
    m.site_id = site_id
    m.section_id = kw.get("section_id", None)
    m.scope_label = kw.get("scope_label", "sitio")
    m.started_at = kw.get("started_at", datetime.now(timezone.utc))
    m.finished_at = m.started_at
    for contador in (
        "pages_total",
        "pages_new",
        "pages_changed",
        "pages_gone",
        "pages_error",
        "documents_auto_ingested",
        "documents_reingested",
        "documents_auto_retired",
        "pages_blocked_by_findings",
        "findings_retired",
    ):
        setattr(m, contador, kw.get(contador, 0))
    m.truncated = kw.get("truncated", False)
    m.stop_reason = kw.get("stop_reason", None)
    m.errors = kw.get("errors", [])
    return m


class TestElDiarioDePasadas:

    def test_should_serve_the_runs_of_a_site_with_their_scope(self):
        sitio = _sitio()
        seccion_id = uuid.uuid4()
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)
        total = MagicMock()
        total.scalar_one.return_value = 2
        session.execute = AsyncMock(
            side_effect=[
                total,
                _resultado([
                    _pasada(
                        sitio.id,
                        section_id=seccion_id,
                        scope_label="Jornadas",
                        documents_auto_retired=3,
                        pages_blocked_by_findings=1,
                    ),
                    _pasada(sitio.id, scope_label="sitio"),
                ]),
            ]
        )

        resp = _cliente(session).get(
            f"/api/v1/hub/sites/{sitio.id}/runs", headers=_cabeceras()
        )

        assert resp.status_code == 200
        cuerpo = resp.json()
        assert cuerpo["total"] == 2
        assert [p["scope_label"] for p in cuerpo["items"]] == ["Jornadas", "sitio"]
        assert cuerpo["items"][0]["documents_auto_retired"] == 3
        assert cuerpo["items"][0]["pages_blocked_by_findings"] == 1

    def test_should_order_with_a_deterministic_tiebreak(self):
        """DET.1 — dos pasadas pueden compartir `started_at` al microsegundo. Sin desempate, el
        orden dentro del empate lo decide el planificador y paginar devuelve una fila en dos
        páginas y otra en ninguna."""
        sitio = _sitio()
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)
        total = MagicMock()
        total.scalar_one.return_value = 0
        session.execute = AsyncMock(side_effect=[total, _resultado([])])

        _cliente(session).get(f"/api/v1/hub/sites/{sitio.id}/runs", headers=_cabeceras())

        consulta = str(session.execute.await_args_list[1].args[0])
        assert "started_at DESC" in consulta
        assert "id DESC" in consulta

    def test_should_filter_by_section(self):
        sitio = _sitio()
        seccion_id = uuid.uuid4()
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)
        total = MagicMock()
        total.scalar_one.return_value = 0
        session.execute = AsyncMock(side_effect=[total, _resultado([])])

        resp = _cliente(session).get(
            f"/api/v1/hub/sites/{sitio.id}/runs?section_id={seccion_id}",
            headers=_cabeceras(),
        )

        assert resp.status_code == 200
        assert "section_id" in str(session.execute.await_args_list[1].args[0])

    def test_should_paginate(self):
        sitio = _sitio()
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)
        total = MagicMock()
        total.scalar_one.return_value = 40
        session.execute = AsyncMock(side_effect=[total, _resultado([])])

        resp = _cliente(session).get(
            f"/api/v1/hub/sites/{sitio.id}/runs?page=3&size=5", headers=_cabeceras()
        )

        assert resp.status_code == 200
        consulta = session.execute.await_args_list[1].args[0]
        assert consulta._limit_clause.value == 5
        assert consulta._offset_clause.value == 10

    def test_should_not_serve_the_runs_of_another_organizacion(self):
        sitio = _sitio(organizacion_id=OTRA_ORG)
        session = AsyncMock()
        session.get = AsyncMock(return_value=sitio)

        resp = _cliente(session).get(
            f"/api/v1/hub/sites/{sitio.id}/runs", headers=_cabeceras(ORG)
        )

        assert resp.status_code == 403


# ──────────────────────────── La selección apunta a la sección ────────────────────────────


class TestLaSeleccionApuntaALaSeccion:

    def test_should_use_the_section_pattern_and_ignore_rule_value(self):
        """Dos sitios de verdad de la regla —el patrón de la sección y el `rule_value`—
        divergirían. Con `section_id` puesto, el patrón lo manda la sección."""
        from server.app.modules.curation.site_repo import CorpusSelectionRepo

        seccion = _seccion(uuid.uuid4(), pattern="/jornadas")
        sel = MagicMock()
        sel.rule_type = "path_prefix"
        sel.rule_value = "/eventos"  # el valor viejo, que ya no manda
        sel.section_id = seccion.id

        repo = CorpusSelectionRepo.__new__(CorpusSelectionRepo)
        secciones = {seccion.id: seccion}

        assert repo.matches(sel, "https://www.uji.es/jornadas/uno", secciones=secciones) is True
        assert repo.matches(sel, "https://www.uji.es/eventos/uno", secciones=secciones) is False

    def test_should_refuse_to_decide_when_the_section_was_not_loaded(self):
        """**Nunca un «no casa» en silencio.** Es el fallo de VER.8: una selección activa que no
        puede casar nada se ve en pantalla como activa y vacía, sin nada que lo explique. Si
        quien pregunta no ha cargado la sección, esto lo dice."""
        import pytest

        from server.app.modules.curation.site_repo import (
            CorpusSelectionRepo,
            SeccionNoCargada,
        )

        sel = MagicMock()
        sel.rule_type = "path_prefix"
        sel.rule_value = "/eventos"
        sel.section_id = uuid.uuid4()

        repo = CorpusSelectionRepo.__new__(CorpusSelectionRepo)

        with pytest.raises(SeccionNoCargada):
            repo.matches(sel, "https://www.uji.es/jornadas/uno")

    def test_should_keep_deciding_by_rule_value_when_there_is_no_section(self):
        """El camino de siempre, intacto: sin `section_id` manda `rule_value`."""
        from server.app.modules.curation.site_repo import CorpusSelectionRepo

        sel = MagicMock()
        sel.rule_type = "path_prefix"
        sel.rule_value = "/eventos"
        sel.section_id = None

        repo = CorpusSelectionRepo.__new__(CorpusSelectionRepo)

        assert repo.matches(sel, "https://www.uji.es/eventos/uno") is True
        assert repo.matches(sel, "https://www.uji.es/jornadas/uno") is False
