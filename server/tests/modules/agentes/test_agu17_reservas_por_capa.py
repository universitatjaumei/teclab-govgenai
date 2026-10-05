"""#228 — plazas reservadas por capa en la selección de documentos.

Decisión del usuario (2026-10-05): el agente declara cuántas plazas reserva como mínimo para cada
valor de la columna `capa` del índice, y la selección las cubre **comparando dentro de cada capa**.
Orden: filtro de los datos de la consulta, prioritarias (que cuentan en el cupo de su capa),
reservas y el resto por similitud. Si una capa no tiene fichas que pasen el filtro, sus plazas
vuelven al reparto general.

Por qué: en el piloto de pliegos, la norma y la doctrina perdían frente a los ejemplos cuando la
pregunta nombra un equipo; comparando dentro de la capa, un artículo de la ley compite con los otros
trozos de la ley y no con cientos de ejemplos.
"""
from __future__ import annotations

import pytest

from server.tests.modules.agentes._comun import declaracion, persona, publicar

TIPO = {
    "etiqueta": "Tipo de contrato",
    "tipo": "opciones",
    "opciones": ["Obras", "Servicios", "Suministros"],
    "columna": "Tipo de contrato",
}


def _ejemplo(n: int) -> dict:
    """Parecido a la consulta, y menos cuanto mayor es `n`: sin reservas, gana."""
    return {
        "url": f"https://drive.google.com/file/d/e{n}",
        "titulo": f"PPT {n}",
        "resumen": "Prescripciones del contrato. " + "viaje " * n,
        "metadatos": {"capa": "Universidad"},
    }


def _de_capa(capa: str, n: int, prioritario: bool = False, tipo: str | None = None) -> dict:
    """Nada parecida a la consulta (y menos cuanto mayor es `n`): sólo entra por su reserva."""
    metadatos = {"capa": capa}
    if prioritario:
        metadatos["prioritario"] = "sí"
    if tipo:
        metadatos["Tipo de contrato"] = tipo
    return {
        "url": f"https://drive.google.com/file/d/{capa[:4].lower()}{n}",
        "titulo": f"{capa} {n}",
        "resumen": "Texto de la ley. " + "viaje " * n,
        "metadatos": metadatos,
    }


async def _documentos(http, fichas, presupuesto, reservas, datos=None) -> list[str]:
    c, quien = http
    agente = await publicar(c, datos_consulta=[TIPO], presupuesto_documentos=presupuesto, reservas=reservas)
    r = await c.put(f"/api/v1/agentes/{agente['id']}/indice", json={"fichas": fichas})
    assert r.status_code == 200, r.text
    quien.actual = persona()
    r = await c.post(f"/api/v1/agentes/{agente['id']}/consulta", json={"consulta": "contrato", "datos": datos or {}})
    assert r.status_code == 200, r.text
    return [d["url"].rsplit("/", 1)[-1] for d in r.json()["documentos"]]


EJEMPLOS = [_ejemplo(n) for n in range(1, 8)]
LEY = [_de_capa("LCSP", n) for n in range(1, 5)]


class TestLaReserva:

    @pytest.mark.asyncio
    async def test_sin_reservas_ganan_los_ejemplos(self, http):
        assert await _documentos(http, EJEMPLOS + LEY, 4, []) == ["e1", "e2", "e3", "e4"]

    @pytest.mark.asyncio
    async def test_la_reserva_trae_lo_mas_parecido_de_su_capa(self, http):
        elegidas = await _documentos(http, EJEMPLOS + LEY, 4, [{"capa": "LCSP", "plazas": 2}])
        assert sorted(elegidas) == ["e1", "e2", "lcsp1", "lcsp2"]

    @pytest.mark.asyncio
    async def test_las_reservas_van_antes_que_el_resto(self, http):
        elegidas = await _documentos(http, EJEMPLOS + LEY, 4, [{"capa": "LCSP", "plazas": 2}])
        assert elegidas[:2] == ["lcsp1", "lcsp2"]

    @pytest.mark.asyncio
    async def test_la_capa_se_compara_sin_mayusculas_ni_acentos(self, http):
        fichas = EJEMPLOS + [_de_capa("Pliego tipo GVA", 1)]
        elegidas = await _documentos(http, fichas, 4, [{"capa": "pliego tipo gva", "plazas": 1}])
        assert "plie1" in elegidas

    @pytest.mark.asyncio
    async def test_varias_capas_con_cupos_distintos(self, http):
        fichas = EJEMPLOS + LEY + [_de_capa("TACRC", n) for n in range(1, 4)]
        reservas = [{"capa": "LCSP", "plazas": 2}, {"capa": "TACRC", "plazas": 1}]
        elegidas = await _documentos(http, fichas, 6, reservas)
        assert sorted(elegidas) == ["e1", "e2", "e3", "lcsp1", "lcsp2", "tacr1"]


class TestConLoDemas:

    @pytest.mark.asyncio
    async def test_una_prioritaria_cuenta_en_el_cupo_de_su_capa(self, http):
        fichas = EJEMPLOS + LEY + [_de_capa("LCSP", 9, prioritario=True)]
        elegidas = await _documentos(http, fichas, 4, [{"capa": "LCSP", "plazas": 2}])
        assert sorted(elegidas) == ["e1", "e2", "lcsp1", "lcsp9"]

    @pytest.mark.asyncio
    async def test_una_capa_sin_fichas_devuelve_sus_plazas(self, http):
        elegidas = await _documentos(http, EJEMPLOS + LEY, 4, [{"capa": "TACRC", "plazas": 2}])
        assert elegidas == ["e1", "e2", "e3", "e4"]

    @pytest.mark.asyncio
    async def test_el_filtro_va_antes_que_la_reserva(self, http):
        """La ficha de la capa que contradice el tipo de contrato no ocupa la reserva."""
        fichas = EJEMPLOS + [_de_capa("LCSP", 1, tipo="Obras"), _de_capa("LCSP", 2)]
        elegidas = await _documentos(
            http, fichas, 4, [{"capa": "LCSP", "plazas": 2}], {"tipo_de_contrato": "Servicios"}
        )
        assert sorted(elegidas) == ["e1", "e2", "e3", "lcsp2"]


class TestLaDeclaracion:

    @pytest.mark.asyncio
    async def test_se_guardan_y_se_devuelven(self, http):
        c, _ = http
        agente = await publicar(c, presupuesto_documentos=10, reservas=[{"capa": "LCSP", "plazas": 2}])
        assert agente["version"]["reservas"] == [{"capa": "LCSP", "plazas": 2}]

    @pytest.mark.asyncio
    async def test_por_defecto_ninguna(self, http):
        c, _ = http
        assert (await publicar(c))["version"]["reservas"] == []

    @pytest.mark.parametrize(
        "reservas,presupuesto",
        [
            ([{"capa": "LCSP", "plazas": 4}, {"capa": "TACRC", "plazas": 2}], 5),  # más que el presupuesto
            ([{"capa": "LCSP", "plazas": 1}, {"capa": "lcsp", "plazas": 1}], 10),  # la misma capa dos veces
            ([{"capa": "LCSP", "plazas": 0}], 10),  # una reserva vacía
            ([{"capa": " ", "plazas": 1}], 10),  # sin capa
        ],
    )
    @pytest.mark.asyncio
    async def test_lo_que_no_se_sostiene_no_se_publica(self, http, reservas, presupuesto):
        c, _ = http
        r = await c.post(
            "/api/v1/agentes", json=declaracion(reservas=reservas, presupuesto_documentos=presupuesto)
        )
        assert r.status_code == 422, r.text
