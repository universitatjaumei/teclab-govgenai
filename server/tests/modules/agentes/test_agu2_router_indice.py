"""#173 — cargar el índice por HTTP: el guion por API y la unidad subiendo la hoja.

Decisión del usuario (2026-10-02): **las dos vías**, con el mismo cargador. Por API carga el
guion de curación (#174) con un token personal; desde el panel, la unidad sube la hoja —que es
lo que permite validar el piloto antes de que exista el guion—.

Y el presupuesto de documentos **lo declara cada agente**, entre 1 y 10, con 5 por defecto.
"""
from __future__ import annotations

import io
import uuid
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from server.app.core.auth.models import UserInfo
from server.tests.modules.agentes.test_agu2_indice import EmbebedorFalso

ORG = str(uuid.uuid4())


def _persona(role="user", orgs=(ORG,)) -> UserInfo:
    return UserInfo(
        user_id=str(uuid.uuid4()), email=f"{role}@uji.es", role=role, organizacion_ids=tuple(orgs)
    )


AUTORA = _persona()


class _Quien:
    def __init__(self) -> None:
        self.actual = AUTORA


@pytest.fixture
async def http(db_session):
    from server.app.api.deps import get_current_user, get_session
    from server.app.routers.agentes_router import obtener_embedder, router, router_catalogo

    quien = _Quien()
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.include_router(router_catalogo, prefix="/api/v1")

    async def _sesion():
        yield db_session

    app.dependency_overrides[get_current_user] = lambda: quien.actual
    app.dependency_overrides[get_session] = _sesion
    app.dependency_overrides[obtener_embedder] = lambda: EmbebedorFalso()
    for dependencia in router.dependencies:
        app.dependency_overrides[dependencia.dependency] = lambda: quien.actual

    @app.middleware("http")
    async def _como_un_pat(request, call_next):
        # Lo que hace `get_current_user` con un token personal: dejar sus scopes en el estado.
        if "x-prueba-scopes" in request.headers:
            request.state.pat_scopes = set(request.headers["x-prueba-scopes"].split(","))
        return await call_next(request)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://prueba") as c:
        yield c, quien


def _declaracion(**cambios) -> dict:
    cuerpo = {
        "nombre": "Contratación menor",
        "unidad": "Servicio de Contratación",
        "prompt": "Eres el asistente de contratación.",
        "carpeta_url": "https://drive.google.com/drive/folders/abc",
        "finalidad": "Orientar",
        "responsable": "Jefatura",
        "colectivo": "organizacion",
        "grupos": [],
        "revision_prevista_en": (date.today() + timedelta(days=180)).isoformat(),
    }
    cuerpo.update(cambios)
    return cuerpo


async def _publicar(c, **cambios) -> dict:
    r = await c.post("/api/v1/agentes", json=_declaracion(**cambios))
    assert r.status_code == 201, r.text
    return r.json()


FICHAS = [
    {"url": "https://drive.google.com/file/d/1", "titulo": "Instrucción de contrato menor", "resumen": "Trata del contrato menor."},
    {"url": "https://drive.google.com/file/d/2", "titulo": "Guía de viajes", "resumen": "Trata de viajes.", "vigente": False},
]

HOJA = (
    "url;título;resumen;vigente;materia\n"
    "https://drive.google.com/file/d/1;Instrucción;Trata del contrato menor.;sí;Contratación\n"
    "https://drive.google.com/file/d/2;Guía;Trata de viajes.;no;Viajes\n"
).encode("utf-8")


class TestPresupuesto:

    @pytest.mark.asyncio
    async def test_por_defecto_son_cinco(self, http):
        c, _ = http
        agente = await _publicar(c)
        assert agente["version"]["presupuesto_documentos"] == 5

    @pytest.mark.asyncio
    @pytest.mark.parametrize("valor", [0, 11])
    async def test_entre_uno_y_diez(self, http, valor):
        c, _ = http
        r = await c.post("/api/v1/agentes", json=_declaracion(presupuesto_documentos=valor))
        assert r.status_code == 422


class TestCargarPorApi:

    @pytest.mark.asyncio
    async def test_la_autora_carga_y_recibe_el_informe(self, http):
        c, _ = http
        agente = await _publicar(c)
        assert "cargar_indice" in agente["version"]["acciones_permitidas"]

        r = await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": FICHAS})
        assert r.status_code == 200, r.text
        assert r.json() == {"nuevas": 2, "actualizadas": 0, "sin_cambios": 0, "retiradas": 0}

    @pytest.mark.asyncio
    async def test_quien_no_lo_gestiona_no_carga(self, http):
        c, quien = http
        agente = await _publicar(c)
        quien.actual = _persona()
        r = await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": FICHAS})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_una_hoja_incoherente_es_un_422_que_dice_la_fila(self, http):
        c, _ = http
        agente = await _publicar(c)
        r = await c.put(
            f"/api/v1/agentes/{agente['id']}/indice",
            json={"fichas": [FICHAS[0], FICHAS[0]]},
        )
        assert r.status_code == 422
        assert "fila 3" in r.text

    @pytest.mark.asyncio
    async def test_un_agente_retirado_no_admite_indice(self, http):
        c, _ = http
        agente = await _publicar(c)
        await c.post(f"/api/v1/agentes/{agente['id']}/retirar")
        r = await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": FICHAS})
        assert r.status_code == 403


class TestSubirLaHoja:

    @pytest.mark.asyncio
    async def test_la_hoja_csv_carga_lo_mismo(self, http):
        c, _ = http
        agente = await _publicar(c)
        r = await c.post(
            f"/api/v1/agentes/{agente['id']}/indice/hoja",
            files={"file": ("indice.csv", io.BytesIO(HOJA), "text/csv")},
        )
        assert r.status_code == 200, r.text
        assert r.json()["nuevas"] == 2

        fichas = (await c.get(f"/api/v1/agentes/{agente['id']}/indice")).json()
        por_url = {f["url"]: f for f in fichas}
        assert por_url["https://drive.google.com/file/d/2"]["vigente"] is False
        assert por_url["https://drive.google.com/file/d/1"]["metadatos"] == {"materia": "Contratación"}

    @pytest.mark.asyncio
    async def test_una_hoja_sin_url_es_un_422(self, http):
        c, _ = http
        agente = await _publicar(c)
        r = await c.post(
            f"/api/v1/agentes/{agente['id']}/indice/hoja",
            files={"file": ("indice.csv", io.BytesIO(b"titulo;resumen\nA;B\n"), "text/csv")},
        )
        assert r.status_code == 422
        assert "url" in r.text


class TestLoQueSeVe:

    @pytest.mark.asyncio
    async def test_la_ficha_del_agente_dice_cuantas_fichas_tiene(self, http):
        c, _ = http
        agente = await _publicar(c)
        await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": FICHAS})
        listado = (await c.get("/api/v1/agentes")).json()
        assert listado["agentes"][0]["fichas"] == 2

    @pytest.mark.asyncio
    async def test_el_listado_del_indice_no_lleva_vectores(self, http):
        c, _ = http
        agente = await _publicar(c)
        await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": FICHAS})
        ficha = (await c.get(f"/api/v1/agentes/{agente['id']}/indice")).json()[0]
        assert "embedding" not in ficha
        assert set(ficha) >= {"url", "titulo", "resumen", "vigente", "revision_prevista_en"}

    @pytest.mark.asyncio
    async def test_el_indice_de_otra_organizacion_es_un_404(self, http):
        c, quien = http
        agente = await _publicar(c)
        quien.actual = _persona("admin", orgs=(str(uuid.uuid4()),))
        r = await c.get(f"/api/v1/agentes/{agente['id']}/indice")
        assert r.status_code == 404


class TestElToken:

    def test_hay_un_scope_para_cargar_el_indice_y_lo_puede_emitir_un_admin(self):
        """El guion de curación corre con la identidad de la unidad: lo emite quien la administra."""
        from server.app.core.auth.pat.scopes import (
            AGENTES_INDICE_WRITE,
            ALL_SCOPES,
            allowed_scopes_for_role,
        )

        assert AGENTES_INDICE_WRITE in ALL_SCOPES
        assert AGENTES_INDICE_WRITE in allowed_scopes_for_role("admin")

    @pytest.mark.asyncio
    async def test_un_token_sin_ese_scope_no_carga(self, http):
        """Como lo vería un PAT: `request.state.pat_scopes` lo pone la autenticación."""
        c, _ = http
        agente = await _publicar(c)
        r = await c.put(
            f"/api/v1/agentes/{agente['id']}/indice",
            json={"fichas": FICHAS},
            headers={"X-Prueba-Scopes": "actividad:write"},
        )
        assert r.status_code == 403
        assert "PAT_SCOPE_MISSING" in r.text

    @pytest.mark.asyncio
    async def test_un_token_con_ese_scope_carga(self, http):
        c, _ = http
        agente = await _publicar(c)
        r = await c.put(
            f"/api/v1/agentes/{agente['id']}/indice",
            json={"fichas": FICHAS},
            headers={"X-Prueba-Scopes": "agentes:indice"},
        )
        assert r.status_code == 200, r.text
