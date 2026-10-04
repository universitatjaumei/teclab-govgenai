"""#173 — cargar el índice por HTTP: el guion por API y la unidad subiendo la hoja.

Decisión del usuario (2026-10-02): **las dos vías**, con el mismo cargador. Por API carga el
guion de curación (#174) con un token personal; desde el panel, la unidad sube la hoja —que es
lo que permite validar el piloto antes de que exista el guion—.

Y el presupuesto de documentos **lo declara cada agente**, entre 1 y 10, con 5 por defecto.
"""
from __future__ import annotations

import io
import uuid

import pytest

from server.tests.modules.agentes._comun import (
    FICHAS,
    declaracion as _declaracion,
    persona as _persona,
    publicar as _publicar,
)

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
        assert listado["agentes"][0]["indice"]["fichas"] == 2

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
