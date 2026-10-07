"""#236 — un agente de código registra por MCP los cuadernos que escribe, y consulta el catálogo.

`registrar_cuaderno` envuelve `POST /api/v1/funciones/externas` con el alcance `funciones:register`;
`catalogo_de_funciones`, `GET /api/v1/funciones`, que admite ése o `funciones:execute`. La
plataforma **no ejecuta** lo que se registra así: sabe que existe, de qué versión y quién responde.

Y dos pulidos que la revisión de la PR #235 pidió en el mismo trabajo:
- el 403 de un endpoint que no admite tokens (`PAT_NO_PERMITIDO`) no se explica como «te falta
  un alcance», que manda a buscar donde no está;
- la carga del índice con una hoja no descarta en silencio `documentos_en_carpeta`.
"""
from __future__ import annotations

import json

import httpx
import pytest
import respx

from tests.test_actividad_tools import (  # noqa: F401 — se reutiliza el arnés de REG.4
    API,
    PAT_UNO,
    _llama,
    _payload,
    _texto,
    servidor_mcp,
)

CUADERNO = '{"cells": [{"cell_type": "code", "source": ["print(1)"]}]}'
DECLARACION = {
    "nombre": "Subvenciones nominativas",
    "finalidad": "Extraer las subvenciones nominativas del presupuesto",
    "categorias_datos": ["sin_datos_personales"],
    "entorno_ejecucion": "el equipo de quien lo usa",
}


class TestRegistrarUnCuaderno:

    @respx.mock
    async def test_manda_el_fichero_y_la_declaracion_como_escrito_por_ia(self):
        ruta = respx.post(f"{API}/api/v1/funciones/externas").mock(
            return_value=httpx.Response(201, json={"id": "f1", "nombre": "Subvenciones nominativas"})
        )
        async with servidor_mcp() as app:
            resultado = await _llama(app, "registrar_cuaderno", {**DECLARACION, "contenido": CUADERNO}, pat=PAT_UNO)
        enviado = json.loads(ruta.calls.last.request.content)
        assert enviado == {**DECLARACION, "fichero": CUADERNO, "autoria": "ia"}
        assert _payload(resultado)["id"] == "f1"

    @respx.mock
    async def test_una_version_nueva_lleva_el_id_de_la_funcion(self):
        ruta = respx.post(f"{API}/api/v1/funciones/externas").mock(return_value=httpx.Response(201, json={"id": "f1"}))
        async with servidor_mcp() as app:
            await _llama(
                app, "registrar_cuaderno", {**DECLARACION, "contenido": CUADERNO, "funcion_id": "f1"}, pat=PAT_UNO
            )
        assert json.loads(ruta.calls.last.request.content)["funcion_id"] == "f1"

    async def test_el_remoto_no_lee_ficheros(self):
        async with servidor_mcp() as app:
            resultado = await _llama(app, "registrar_cuaderno", {**DECLARACION, "ruta": "C:/x.ipynb"}, pat=PAT_UNO)
        assert resultado.get("isError")


class TestEnElServidorLocal:

    @respx.mock
    async def test_lee_el_cuaderno_de_su_ruta(self, tmp_path):
        from api_client import ApiClient
        from tools.funciones import run_registrar_cuaderno_core

        fichero = tmp_path / "subvenciones.ipynb"
        fichero.write_text(CUADERNO, encoding="utf-8")
        ruta = respx.post(f"{API}/api/v1/funciones/externas").mock(return_value=httpx.Response(201, json={"id": "f1"}))
        async with ApiClient(API, PAT_UNO) as cliente:
            await run_registrar_cuaderno_core(cliente, DECLARACION, ruta=str(fichero))
        assert json.loads(ruta.calls.last.request.content)["fichero"] == CUADERNO

    async def test_contenido_y_ruta_a_la_vez_no(self, tmp_path):
        from api_client import ApiClient
        from tools.funciones import run_registrar_cuaderno_core

        async with ApiClient(API, PAT_UNO) as cliente:
            with pytest.raises(ValueError):
                await run_registrar_cuaderno_core(cliente, DECLARACION, contenido="x", ruta=str(tmp_path / "a.py"))

    def test_el_servidor_local_ofrece_las_dos(self):
        from server import build_server

        nombres = {t.name for t in build_server(client_provider=lambda: None)._tool_manager.list_tools()}
        assert {"registrar_cuaderno", "catalogo_de_funciones"} <= nombres


class TestElCatalogo:

    @respx.mock
    async def test_lista_las_funciones_dentro_de_un_objeto(self):
        respx.get(f"{API}/api/v1/funciones").mock(return_value=httpx.Response(200, json=[{"id": "f1"}, {"id": "f2"}]))
        async with servidor_mcp() as app:
            resultado = await _llama(app, "catalogo_de_funciones", {}, pat=PAT_UNO)
        assert [f["id"] for f in _payload(resultado)["funciones"]] == ["f1", "f2"]


class TestLosMensajesDeError:

    @respx.mock
    async def test_un_endpoint_sin_tokens_no_se_explica_como_falta_de_alcance(self):
        respx.get(f"{API}/api/v1/agentes/catalogo").mock(
            return_value=httpx.Response(403, json={"detail": {"code": "PAT_NO_PERMITIDO", "message": "Este endpoint no admite tokens"}})
        )
        async with servidor_mcp() as app:
            resultado = await _llama(app, "catalogo_de_agentes", {}, pat=PAT_UNO)
        texto = _texto(resultado)
        assert "no admite tokens" in texto
        assert "no porta el scope" not in texto


class TestLaHojaYLosDocumentosDeLaCarpeta:

    async def test_no_se_descartan_en_silencio(self, tmp_path):
        from api_client import ApiClient
        from tools.agentes import run_cargar_indice_core

        hoja = tmp_path / "indice.csv"
        hoja.write_text("url,titulo,resumen\n", encoding="utf-8")
        async with ApiClient(API, PAT_UNO) as cliente:
            with pytest.raises(ValueError):
                await run_cargar_indice_core(cliente, "a1", ruta_hoja=str(hoja), documentos_en_carpeta=3)

    @respx.mock
    async def test_la_ruta_admite_la_carpeta_personal(self, tmp_path, monkeypatch):
        from api_client import ApiClient
        from tools.agentes import run_cargar_indice_core

        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))
        (tmp_path / "indice.csv").write_text("url,titulo,resumen\n", encoding="utf-8")
        ruta = respx.post(f"{API}/api/v1/agentes/a1/indice/hoja").mock(
            return_value=httpx.Response(200, json={"nuevas": 0, "actualizadas": 0, "sin_cambios": 0, "retiradas": 0})
        )
        async with ApiClient(API, PAT_UNO) as cliente:
            await run_cargar_indice_core(cliente, "a1", ruta_hoja="~/indice.csv")
        assert ruta.called
