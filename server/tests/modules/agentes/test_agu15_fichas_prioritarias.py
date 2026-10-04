"""#223 — las fichas prioritarias: entran antes, si encajan con la consulta.

Decisión del usuario (2026-10-04): un solo agente general de pliegos, no uno por tipo de contrato.
La columna `prioritario` de la hoja marca el pliego tipo o el modelo de la casa, y la selección va
en este orden: vigencia, filtro suave por los datos de la consulta, **las prioritarias que pasan
el filtro con un tope de la mitad del presupuesto**, y el resto por similitud.

La marca no dice «siempre»: dice «si encaja, primero». Y el tope deja al menos la mitad para los
ejemplos, que son lo que trae el contenido técnico.

Por qué: con sólo similitud, en una consulta concreta los más parecidos son los ejemplos de otras
entidades, y el pliego tipo se queda fuera.
"""
from __future__ import annotations

import pytest

from server.tests.modules.agentes._comun import persona, publicar

TIPO = {
    "etiqueta": "Tipo de contrato",
    "tipo": "opciones",
    "opciones": ["Obras", "Servicios", "Suministros"],
    "columna": "Tipo de contrato",
}


def _ejemplo(n: int) -> dict:
    """Parecido a la consulta, y menos cuanto mayor es `n`: sin prioridad, gana."""
    return {
        "url": f"https://drive.google.com/file/d/e{n}",
        "titulo": f"PPT {n}",
        "resumen": "Prescripciones del contrato. " + "viaje " * n,
    }


def _prioritaria(n: int, marca: str = "sí", cabecera: str = "prioritario", tipo: str | None = None) -> dict:
    """Nada parecida a la consulta (y menos cuanto mayor es `n`): sólo entra si la prioridad cuenta."""
    metadatos = {cabecera: marca}
    if tipo:
        metadatos["Tipo de contrato"] = tipo
    return {
        "url": f"https://drive.google.com/file/d/p{n}",
        "titulo": f"Pliego tipo {n}",
        "resumen": "Modelo de cláusulas. " + "viaje " * n,
        "metadatos": metadatos,
    }


async def _documentos(http, fichas: list[dict], presupuesto: int, datos: dict | None = None) -> list[str]:
    c, quien = http
    agente = await publicar(c, datos_consulta=[TIPO], presupuesto_documentos=presupuesto)
    r = await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": fichas})
    assert r.status_code == 200, r.text
    quien.actual = persona()
    r = await c.post(
        f"/api/v1/agentes/{agente['id']}/consulta",
        json={"consulta": "contrato", "datos": datos or {}},
    )
    assert r.status_code == 200, r.text
    return [d["url"].rsplit("/", 1)[-1] for d in r.json()["documentos"]]


class TestLaPrioridad:

    @pytest.mark.asyncio
    async def test_sin_prioridad_ganan_los_parecidos(self, http):
        """El punto de partida: la que no es parecida se queda fuera."""
        assert await _documentos(http, [_ejemplo(1), _ejemplo(2), _prioritaria(1, marca="")], 2) == ["e1", "e2"]

    @pytest.mark.asyncio
    async def test_la_prioritaria_entra_y_va_primero(self, http):
        assert await _documentos(http, [_ejemplo(1), _ejemplo(2), _prioritaria(1)], 2) == ["p1", "e1"]

    @pytest.mark.parametrize("cabecera,marca", [("Prioritario", "Sí"), ("PRIORITARIO", "x"), ("prioritario", "true")])
    @pytest.mark.asyncio
    async def test_cualquier_grafia(self, http, cabecera, marca):
        fichas = [_ejemplo(1), _ejemplo(2), _prioritaria(1, marca=marca, cabecera=cabecera)]
        assert (await _documentos(http, fichas, 2))[0] == "p1"

    @pytest.mark.asyncio
    async def test_no_es_no(self, http):
        assert "p1" not in await _documentos(http, [_ejemplo(1), _ejemplo(2), _prioritaria(1, marca="no")], 2)


class TestSiEncaja:

    @pytest.mark.asyncio
    async def test_la_que_contradice_la_consulta_no_entra(self, http):
        fichas = [_ejemplo(1), _ejemplo(2), _prioritaria(1, tipo="Obras")]
        assert await _documentos(http, fichas, 2, {"tipo_de_contrato": "Servicios"}) == ["e1", "e2"]

    @pytest.mark.asyncio
    async def test_la_que_encaja_entra(self, http):
        fichas = [_ejemplo(1), _ejemplo(2), _prioritaria(1, tipo="Obras"), _prioritaria(2, tipo="Servicios")]
        assert await _documentos(http, fichas, 2, {"tipo_de_contrato": "Servicios"}) == ["p2", "e1"]

    @pytest.mark.asyncio
    async def test_la_que_no_tiene_el_dato_encaja_con_todo(self, http):
        """Una guía transversal: sin tipo de contrato, vale para cualquiera."""
        fichas = [_ejemplo(1), _ejemplo(2), _prioritaria(1)]
        assert await _documentos(http, fichas, 2, {"tipo_de_contrato": "Obras"}) == ["p1", "e1"]


class TestElTope:

    @pytest.mark.parametrize("presupuesto,prioritarias", [(4, 2), (5, 2), (10, 5)])
    @pytest.mark.asyncio
    async def test_como_mucho_la_mitad(self, http, presupuesto, prioritarias):
        fichas = [_ejemplo(n) for n in range(1, 11)] + [_prioritaria(n) for n in range(1, 11)]
        elegidas = await _documentos(http, fichas, presupuesto)
        assert len(elegidas) == presupuesto
        assert sum(u.startswith("p") for u in elegidas) == prioritarias
        assert all(u.startswith("p") for u in elegidas[:prioritarias])

    @pytest.mark.asyncio
    async def test_con_presupuesto_uno_no_hay_plaza_prioritaria(self, http):
        assert await _documentos(http, [_ejemplo(1), _prioritaria(1)], 1) == ["e1"]

    @pytest.mark.asyncio
    async def test_las_que_sobran_compiten_como_las_demas(self, http):
        """Sin ejemplos que las superen, las prioritarias de más llenan el resto por similitud."""
        elegidas = await _documentos(http, [_prioritaria(n) for n in range(1, 5)], 4)
        assert sorted(elegidas) == ["p1", "p2", "p3", "p4"]
