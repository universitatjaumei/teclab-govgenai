"""#226 — los agentes de unidad como tools MCP: consultar, ampliar y cargar el índice.

Envuelven endpoints que ya existen (`docs/ESPECIFICACIONES.md` §5.14):

- **Consultar** permite usar un agente desde Claude además de desde Gemini: el agente es
  configuración —prompt, carpeta, índice—, así que sirve a los dos asistentes. Token con
  `agentes:consulta`, el mismo que recibe la extensión.
- **Cargar el índice** es lo que necesita la actualización del corpus de un agente si se hace con
  una skill de Claude. Token con `agentes:indice`. En el servidor **local** acepta además la ruta
  de una hoja CSV o Excel del equipo, que se manda tal cual: **la hoja la interpreta el servidor**
  —columnas, vigencia, fechas—, en un solo sitio.

Lo que queda fuera, a propósito: publicar, versionar o retirar agentes. Exige la sesión de una
persona (#214), y un token no publica nada.

El arnés es el de REG.4: streamable HTTP contra la aplicación ASGI del servidor remoto, para que
se vea que el token de cada petición llega al endpoint.
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

AGENTE = "c82f0a85-4376-43d0-a7d1-a2944abc60ae"
CONSULTA = "db308ef9-1950-4784-a5cb-f39c039fe328"
RESPUESTA = {
    "agente": "Asistente PPT investigación UJI",
    "version": 4,
    "prompt": "PROMPT COMPUESTO",
    "documentos": [
        {"url": "https://drive.google.com/file/d/1", "titulo": "[LCSP] Arts. 74-95", "score": 0.71, "revision_vencida": False}
    ],
    "espera_adjunto": False,
    "consulta_id": CONSULTA,
    "modo_registro": "validacion",
}


class TestElCatalogo:

    @respx.mock
    async def test_lista_los_agentes_que_se_le_ofrecen(self):
        ruta = respx.get(f"{API}/api/v1/agentes/catalogo").mock(
            return_value=httpx.Response(200, json=[{"id": AGENTE, "nombre": "Asistente PPT investigación UJI"}])
        )
        async with servidor_mcp() as app:
            resultado = await _llama(app, "catalogo_de_agentes", {}, pat=PAT_UNO)
        assert ruta.called
        assert ruta.calls.last.request.headers["Authorization"] == f"Bearer {PAT_UNO}"
        assert _payload(resultado)["agentes"][0]["id"] == AGENTE


class TestConsultar:

    @respx.mock
    async def test_manda_la_pregunta_y_los_datos_y_devuelve_prompt_y_enlaces(self):
        ruta = respx.post(f"{API}/api/v1/agentes/{AGENTE}/consulta").mock(
            return_value=httpx.Response(200, json=RESPUESTA)
        )
        async with servidor_mcp() as app:
            resultado = await _llama(
                app,
                "consultar_agente",
                {
                    "agente_id": AGENTE,
                    "consulta": "¿Qué solvencia pido para un espectrofotómetro?",
                    "datos": {"tipo_de_contrato": "Suministros"},
                },
                pat=PAT_UNO,
            )
        enviado = json.loads(ruta.calls.last.request.content)
        assert enviado == {
            "consulta": "¿Qué solvencia pido para un espectrofotómetro?",
            "lengua": "es",
            "adjunta": False,
            "datos": {"tipo_de_contrato": "Suministros"},
        }
        assert _payload(resultado)["prompt"] == "PROMPT COMPUESTO"

    @respx.mock
    async def test_el_403_del_servidor_se_ve(self):
        """Sin el alcance, el servidor lo dice; la tool no lo convierte en «no se pudo»."""
        respx.post(f"{API}/api/v1/agentes/{AGENTE}/consulta").mock(
            return_value=httpx.Response(403, json={"detail": {"code": "PAT_SCOPE_MISSING", "missing": ["agentes:consulta"]}})
        )
        async with servidor_mcp() as app:
            resultado = await _llama(app, "consultar_agente", {"agente_id": AGENTE, "consulta": "x"}, pat=PAT_UNO)
        assert resultado.get("isError")
        assert "agentes:consulta" in _texto(resultado)


class TestAmpliar:

    @respx.mock
    async def test_pide_mas_documentos_para_la_misma_conversacion(self):
        ruta = respx.post(f"{API}/api/v1/agentes/consultas/{CONSULTA}/ampliacion").mock(
            return_value=httpx.Response(200, json={**RESPUESTA, "prompt": "AMPLIACION"})
        )
        async with servidor_mcp() as app:
            resultado = await _llama(
                app,
                "ampliar_consulta",
                {"consulta_id": CONSULTA, "texto": "la justificación de la exclusividad"},
                pat=PAT_UNO,
            )
        assert json.loads(ruta.calls.last.request.content) == {
            "texto": "la justificación de la exclusividad",
            "lengua": "es",
            "datos": {},
        }
        assert _payload(resultado)["prompt"] == "AMPLIACION"


class TestCargarElIndice:

    @respx.mock
    async def test_manda_las_fichas_como_estado_completo(self):
        ruta = respx.put(f"{API}/api/v1/agentes/{AGENTE}/indice").mock(
            return_value=httpx.Response(200, json={"nuevas": 1, "actualizadas": 0, "sin_cambios": 0, "retiradas": 0})
        )
        ficha = {"url": "https://drive.google.com/file/d/9", "titulo": "Pliego", "resumen": "Un pliego."}
        async with servidor_mcp() as app:
            resultado = await _llama(app, "cargar_indice_de_agente", {"agente_id": AGENTE, "fichas": [ficha]}, pat=PAT_UNO)
        assert json.loads(ruta.calls.last.request.content) == {"fichas": [ficha]}
        assert _payload(resultado)["nuevas"] == 1

    async def test_el_servidor_remoto_no_lee_ficheros(self):
        """La ruta sería del disco del servidor, no del de quien llama: allí no se ofrece."""
        async with servidor_mcp() as app:
            resultado = await _llama(
                app, "cargar_indice_de_agente", {"agente_id": AGENTE, "ruta_hoja": "C:/x.csv"}, pat=PAT_UNO
            )
        assert resultado.get("isError")


class TestLaHojaEnElServidorLocal:
    """El servidor stdio corre en el equipo de quien lo usa: ahí sí tiene sentido una ruta."""

    @respx.mock
    async def test_sube_la_hoja_tal_cual_y_la_interpreta_el_servidor(self, tmp_path):
        from api_client import ApiClient
        from tools.agentes import run_cargar_indice_core

        hoja = tmp_path / "indice.csv"
        hoja.write_bytes("url,titulo,resumen\nhttps://d/1,Pliego,Un pliego.\n".encode("utf-8"))
        ruta = respx.post(f"{API}/api/v1/agentes/{AGENTE}/indice/hoja").mock(
            return_value=httpx.Response(200, json={"nuevas": 1, "actualizadas": 0, "sin_cambios": 0, "retiradas": 0})
        )
        async with ApiClient(API, PAT_UNO) as cliente:
            informe = await run_cargar_indice_core(cliente, AGENTE, ruta_hoja=str(hoja))
        peticion = ruta.calls.last.request
        assert b"filename=\"indice.csv\"" in peticion.content
        assert b"https://d/1,Pliego,Un pliego." in peticion.content
        assert informe["nuevas"] == 1

    async def test_las_dos_cosas_a_la_vez_no(self, tmp_path):
        from api_client import ApiClient
        from tools.agentes import run_cargar_indice_core

        async with ApiClient(API, PAT_UNO) as cliente:
            with pytest.raises(ValueError):
                await run_cargar_indice_core(cliente, AGENTE, fichas=[], ruta_hoja=str(tmp_path / "x.csv"))

    def test_el_servidor_local_la_ofrece(self):
        from server import build_server

        nombres = {t.name for t in build_server(client_provider=lambda: None)._tool_manager.list_tools()}
        assert {"catalogo_de_agentes", "consultar_agente", "ampliar_consulta", "cargar_indice_de_agente"} <= nombres
