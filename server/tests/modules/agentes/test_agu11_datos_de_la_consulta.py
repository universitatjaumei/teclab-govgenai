"""#219 — los datos de la consulta: para preguntar, seleccionar y componer el prompt.

Decisiones del usuario (2026-10-04): la unidad declara los datos esenciales que tiene que dar
quien pregunta —en un agente de pliegos, el tipo de contrato y el código CPV—, de dos tipos
(**lista de opciones** y **texto**), y cada dato sirve a la vez para:

* **preguntar**: la pantalla pinta el formulario a partir de lo declarado;
* **seleccionar**: si está ligado a una columna del índice, **filtro suave** —se excluye la ficha
  cuyo valor contradice el indicado y se conserva la que no tiene el dato: la ley de contratos
  vale para todos—; para códigos jerárquicos como el CPV, coincidencia por **prefijo**;
* **componer el prompt**: la plataforma añade los datos.

Por qué: la selección compara por embeddings, que van bien con conceptos y mal con códigos.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from server.tests.modules.agentes._comun import declaracion, persona, publicar

TIPO = {
    "etiqueta": "Tipo de contrato",
    "tipo": "opciones",
    "opciones": ["Obras", "Servicios", "Suministros"],
    "obligatorio": True,
    "columna": "Tipo de contrato",
}
CPV = {
    "etiqueta": "Código CPV",
    "tipo": "texto",
    "ayuda": "Ocho cifras; basta con las primeras",
    "columna": "CPV",
    "prefijo": True,
}
DATOS = [TIPO, CPV]


def _ficha(n, tipo=None, cpv=None) -> dict:
    metadatos = {}
    if tipo:
        metadatos["TIPO DE CONTRATO"] = tipo  # otra grafía de la cabecera: se normaliza
    if cpv:
        metadatos["cpv"] = cpv
    return {
        "url": f"https://drive.google.com/file/d/{n}",
        "titulo": f"Pliego {n}",
        "resumen": "Pliego de cláusulas de un contrato.",
        "metadatos": metadatos,
    }


async def _agente(c, fichas, **extra) -> dict:
    agente = await publicar(c, datos_consulta=DATOS, presupuesto_documentos=10, **extra)
    assert (await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": fichas})).status_code == 200
    return agente


async def _consultar(c, quien, agente_id, datos, **extra):
    quien.actual = persona()
    return await c.post(
        f"/api/v1/agentes/{agente_id}/consulta",
        json={"consulta": "¿Qué cláusulas de solvencia pongo?", "datos": datos, **extra},
    )


def _urls(cuerpo) -> set[str]:
    return {d["url"].rsplit("/", 1)[-1] for d in cuerpo["documentos"]}


class TestLaDeclaracion:

    @pytest.mark.asyncio
    async def test_se_declaran_con_su_clave_y_unas_indicaciones(self, http):
        c, quien = http
        agente = await publicar(c, datos_consulta=DATOS, indicaciones="Indica el tipo de contrato y el CPV.")
        datos = agente["version"]["datos_consulta"]
        assert [d["clave"] for d in datos] == ["tipo_de_contrato", "codigo_cpv"]
        assert datos[0]["opciones"] == ["Obras", "Servicios", "Suministros"]
        assert datos[1]["prefijo"] is True
        assert agente["version"]["indicaciones"] == "Indica el tipo de contrato y el CPV."
        quien.actual = persona()
        [en_catalogo] = (await c.get("/api/v1/agentes/catalogo")).json()
        assert [d["clave"] for d in en_catalogo["datos_consulta"]] == ["tipo_de_contrato", "codigo_cpv"]
        assert en_catalogo["indicaciones"] == "Indica el tipo de contrato y el CPV."

    @pytest.mark.asyncio
    async def test_por_defecto_ninguno(self, http):
        c, _ = http
        version = (await publicar(c))["version"]
        assert version["datos_consulta"] == []
        assert version["indicaciones"] is None

    @pytest.mark.parametrize(
        "datos",
        [
            [{**TIPO, "opciones": ["Obras"]}],  # una lista de una sola opción no es elegir
            [{**TIPO, "prefijo": True}],  # el prefijo es para códigos escritos
            [TIPO, {**TIPO}],  # dos con la misma etiqueta
            [{**CPV, "etiqueta": f"Dato {n}"} for n in range(9)],  # más de ocho
            [{**CPV, "opciones": ["a", "b"]}],  # opciones en un texto
        ],
    )
    @pytest.mark.asyncio
    async def test_lo_que_no_se_sostiene_no_se_publica(self, http, datos):
        c, _ = http
        r = await c.post("/api/v1/agentes", json=declaracion(datos_consulta=datos))
        assert r.status_code == 422, r.text


class TestLaConsulta:

    @pytest.mark.asyncio
    async def test_el_prompt_lleva_los_datos(self, http):
        c, quien = http
        agente = await _agente(c, [_ficha(1)])
        r = await _consultar(c, quien, agente["id"], {"tipo_de_contrato": "Servicios", "codigo_cpv": "79341000"})
        assert r.status_code == 200, r.text
        assert "Datos de la consulta:\n- Tipo de contrato: Servicios\n- Código CPV: 79341000" in r.json()["prompt"]

    @pytest.mark.asyncio
    async def test_un_obligatorio_que_falta(self, http):
        c, quien = http
        agente = await _agente(c, [_ficha(1)])
        r = await _consultar(c, quien, agente["id"], {"codigo_cpv": "79341000"})
        assert r.status_code == 422
        assert "Tipo de contrato" in r.text

    @pytest.mark.asyncio
    async def test_una_opcion_que_no_esta(self, http):
        c, quien = http
        agente = await _agente(c, [_ficha(1)])
        r = await _consultar(c, quien, agente["id"], {"tipo_de_contrato": "Concesiones"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_un_dato_que_el_agente_no_declara(self, http):
        c, quien = http
        agente = await _agente(c, [_ficha(1)])
        r = await _consultar(c, quien, agente["id"], {"tipo_de_contrato": "Obras", "importe": "10000"})
        assert r.status_code == 422

    @pytest.mark.asyncio
    async def test_en_validacion_se_guardan_con_la_pregunta(self, http, db_session):
        from server.app.modules.agents_hub.database.operational_models import HubAgenteConsulta

        c, quien = http
        agente = await _agente(c, [_ficha(1)])
        r = await _consultar(c, quien, agente["id"], {"tipo_de_contrato": "Obras"})
        fila = (await db_session.execute(select(HubAgenteConsulta))).scalars().one()
        assert str(fila.id) == r.json()["consulta_id"]
        assert fila.datos == {"tipo_de_contrato": "Obras"}


class TestElFiltroSuave:

    @pytest.mark.asyncio
    async def test_excluye_lo_que_contradice_y_conserva_lo_que_no_dice_nada(self, http):
        c, quien = http
        agente = await _agente(c, [_ficha(1, tipo="Obras"), _ficha(2, tipo="Servicios"), _ficha(3)])
        cuerpo = (await _consultar(c, quien, agente["id"], {"tipo_de_contrato": "Servicios"})).json()
        assert _urls(cuerpo) == {"2", "3"}

    @pytest.mark.asyncio
    async def test_sin_mayusculas_ni_espacios(self, http):
        c, quien = http
        agente = await _agente(c, [_ficha(1, tipo=" servicios ")])
        cuerpo = (await _consultar(c, quien, agente["id"], {"tipo_de_contrato": "Servicios"})).json()
        assert _urls(cuerpo) == {"1"}

    @pytest.mark.asyncio
    async def test_el_cpv_por_prefijo_en_los_dos_sentidos(self, http):
        c, quien = http
        fichas = [
            _ficha(1, tipo="Servicios", cpv="79341000"),
            _ficha(2, tipo="Servicios", cpv="45000000"),
            _ficha(3, tipo="Servicios", cpv="793"),  # un pliego tipo de toda la división
        ]
        agente = await _agente(c, fichas)
        exacto = (await _consultar(c, quien, agente["id"], {"tipo_de_contrato": "Servicios", "codigo_cpv": "79341000"})).json()
        assert _urls(exacto) == {"1", "3"}
        corto = (await _consultar(c, quien, agente["id"], {"tipo_de_contrato": "Servicios", "codigo_cpv": "7934"})).json()
        assert _urls(corto) == {"1", "3"}

    @pytest.mark.asyncio
    async def test_lo_excluido_no_ocupa_plaza(self, http):
        c, quien = http
        agente = await publicar(c, datos_consulta=DATOS, presupuesto_documentos=1)
        await c.put(
            f"/api/v1/agentes/{agente['id']}/indice",
            json={"fichas": [_ficha(1, tipo="Obras"), _ficha(2, tipo="Servicios")]},
        )
        cuerpo = (await _consultar(c, quien, agente["id"], {"tipo_de_contrato": "Servicios"})).json()
        assert _urls(cuerpo) == {"2"}

    @pytest.mark.asyncio
    async def test_un_dato_sin_columna_no_filtra(self, http):
        c, quien = http
        sin_columna = [{**TIPO, "columna": None}]
        agente = await publicar(c, datos_consulta=sin_columna, presupuesto_documentos=10)
        await c.put(
            f"/api/v1/agentes/{agente['id']}/indice",
            json={"fichas": [_ficha(1, tipo="Obras"), _ficha(2, tipo="Servicios")]},
        )
        cuerpo = (await _consultar(c, quien, agente["id"], {"tipo_de_contrato": "Servicios"})).json()
        assert _urls(cuerpo) == {"1", "2"}
