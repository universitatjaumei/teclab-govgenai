"""#220 — el guion extrae los datos de la consulta al resumir.

Decisión del usuario (2026-10-04): si el agente declara datos ligados a una columna del índice
—tipo de contrato, CPV—, **el mismo prompt de resumen los extrae del documento**, y nadie rellena
columnas a mano.

Lo que fija este lado (el del guion lo fijan sus pruebas en `guionDelIndice.test.ts`):
- la plataforma sirve el prompt de resumen **del agente**, que pide los datos detrás de una línea
  fija, separados del resumen: **el resumen es lo que se embebe** y los datos no pueden entrar en él
  (regla 5 de AGENTS.md: reclasificar no puede obligar a re-embeber);
- un agente sin datos ligados recibe el prompt de siempre, con su versión;
- **la versión cambia si cambian los datos**, para que lo resumido antes salga desfasado y la unidad
  decida si regenera; y el recuento de desfasadas compara con la versión **de ese agente**.
"""
from __future__ import annotations

import pytest

from server.app.modules.agentes import indice
from server.tests.modules.agentes._comun import publicar

TIPO = {
    "etiqueta": "Tipo de contrato",
    "tipo": "opciones",
    "opciones": ["Obras", "Servicios", "Suministros"],
    "columna": "Tipo de contrato",
}
CPV = {"etiqueta": "Código CPV", "tipo": "texto", "columna": "CPV", "prefijo": True}
SIN_COLUMNA = {"etiqueta": "Importe", "tipo": "texto"}
TOKEN_DEL_GUION = {"X-Prueba-Scopes": "agentes:indice"}


def _declarados(*datos) -> list[dict]:
    from server.app.modules.agentes.datos import clave

    return [{"clave": clave(d["etiqueta"]), "obligatorio": False, "ayuda": None, "opciones": [], "prefijo": False, **d} for d in datos]


class TestElPromptDelAgente:

    def test_sin_datos_ligados_el_de_siempre(self):
        version, texto, extraer = indice.prompt_de_resumen(_declarados(SIN_COLUMNA))
        assert (version, texto, extraer) == (indice.VERSION_PROMPT_RESUMEN, indice.PROMPT_DE_RESUMEN, [])

    def test_con_datos_pide_extraerlos_detras_de_una_linea_fija(self):
        version, texto, extraer = indice.prompt_de_resumen(_declarados(TIPO, CPV, SIN_COLUMNA))
        assert version.startswith(indice.VERSION_PROMPT_RESUMEN + "+datos-")
        assert texto.startswith(indice.PROMPT_DE_RESUMEN)
        assert indice.SEPARADOR_DE_DATOS in texto
        assert "Tipo de contrato: una de estas opciones: Obras, Servicios, Suministros" in texto
        assert "- CPV:" in texto
        assert "Importe" not in texto  # sin columna no hay dónde guardarlo
        assert extraer == [
            {"columna": "Tipo de contrato", "etiqueta": "Tipo de contrato", "tipo": "opciones", "opciones": ["Obras", "Servicios", "Suministros"]},
            {"columna": "CPV", "etiqueta": "Código CPV", "tipo": "texto", "opciones": []},
        ]

    def test_la_version_sigue_a_los_datos(self):
        v1, _, _ = indice.prompt_de_resumen(_declarados(TIPO, CPV))
        assert indice.prompt_de_resumen(_declarados(TIPO, CPV))[0] == v1
        otra = {**TIPO, "opciones": ["Obras", "Servicios"]}
        assert indice.prompt_de_resumen(_declarados(otra, CPV))[0] != v1
        # Cambiar la ayuda o la etiqueta no cambia lo que se extrae: no desfasa nada.
        assert indice.prompt_de_resumen(_declarados({**TIPO, "etiqueta": "Tipo"}, CPV))[0] == v1


class TestElEndpoint:

    @pytest.mark.asyncio
    async def test_el_guion_pide_el_de_su_agente(self, http):
        c, _ = http
        agente = await publicar(c, datos_consulta=[TIPO, CPV])
        r = await c.get("/api/v1/agentes/prompt-de-resumen", params={"agente_id": agente["id"]}, headers=TOKEN_DEL_GUION)
        assert r.status_code == 200, r.text
        cuerpo = r.json()
        assert cuerpo["version"].startswith("resumen-v1+datos-")
        assert indice.SEPARADOR_DE_DATOS in cuerpo["texto"]
        assert [d["columna"] for d in cuerpo["datos"]] == ["Tipo de contrato", "CPV"]

    @pytest.mark.asyncio
    async def test_sin_agente_el_de_siempre(self, http):
        c, _ = http
        cuerpo = (await c.get("/api/v1/agentes/prompt-de-resumen", headers=TOKEN_DEL_GUION)).json()
        assert cuerpo == {"version": indice.VERSION_PROMPT_RESUMEN, "texto": indice.PROMPT_DE_RESUMEN, "datos": []}


class TestLasDesfasadas:

    @pytest.mark.asyncio
    async def test_se_comparan_con_la_version_de_su_agente(self, http):
        c, _ = http
        agente = await publicar(c, datos_consulta=[TIPO, CPV])
        suya = (await c.get("/api/v1/agentes/prompt-de-resumen", params={"agente_id": agente["id"]}, headers=TOKEN_DEL_GUION)).json()["version"]
        fichas = [
            {"url": "https://drive.google.com/file/d/1", "titulo": "Al día", "resumen": "r", "version_prompt_resumen": suya},
            {"url": "https://drive.google.com/file/d/2", "titulo": "De antes de los datos", "resumen": "r", "version_prompt_resumen": "resumen-v1"},
        ]
        assert (await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": fichas})).status_code == 200
        [vista] = (await c.get("/api/v1/agentes")).json()["agentes"]
        assert vista["indice"]["desfasadas"] == 1
