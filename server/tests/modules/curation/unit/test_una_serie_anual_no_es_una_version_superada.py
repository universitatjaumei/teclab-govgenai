"""Una serie anual no es una versión superada, y nada sale en dos apartados (CUR.2).

Lo dijo el usuario tras revisar el informe, y es un dato del dominio que no se deduce del HTML:

> «se utiliza el sistema de publicar acuerdos o actas por años pero **todos son válidos**. Los más
> recientes no derogan a los anteriores. No me parece mal que se identifiquen por si acaso sí que
> sobran los antiguos pero **no deberían aparecer en los dos apartados**.»

Dos cosas mal, entonces:

1. **Afirmábamos algo falso**: nueve hallazgos «superada por la de 2025» sobre acuerdos que siguen
   vigentes. Un grupo de versiones anuales es una **serie**, y lo único cierto que se puede decir es
   que existe: «hay nueve versiones por año de este recurso, revisa si sobran las antiguas».
2. **La misma página salía dos veces**, como `stale` y como `superseded`. Una lista de trabajo con
   la misma página repetida no se usa.

Y una tercera que el usuario pidió y sí es un hallazgo de verdad: **dos URLs distintas con el mismo
contenido**, mostradas juntas con sus dos fechas.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest

from server.app.modules.curation.deterministic_detector import DeterministicQualityDetector

_AHORA = datetime(2026, 8, 19, tzinfo=timezone.utc)
_BASE = "https://www.uji.es/centres/escola-doctorat/base/escola/normativa/acordacded"


@dataclass
class _Pagina:
    url: str
    content_year: int | None = None
    content_published_at: datetime | None = None
    content_hash: str | None = None
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    markdown_content: str | None = "Acord del consell de doctorat. " * 30
    token_count: int | None = 300
    status: str = "active"
    error_message: str | None = None
    error_kind: str | None = None
    error_attempts: int | None = None
    canonical_url: str | None = None
    sitemap_lastmod: datetime | None = None
    http_last_modified: datetime | None = None
    content_owner: str | None = "Escola de Doctorat"
    first_seen_at: datetime | None = None
    render_signals: list[dict] | None = None


class _Repo:
    async def upsert(self, finding: Any) -> Any:
        return finding


class _Sesion:
    def __init__(self, paginas: list[_Pagina]) -> None:
        self._paginas = paginas

    async def execute(self, stmt: Any) -> Any:
        filas = self._paginas if getattr(stmt, "_model_hint", "page") == "page" else []

        class _R:
            def scalars(self_inner) -> Any:
                return self_inner

            def all(self_inner) -> list:
                return filas

        return _R()


async def _hallazgos(paginas: list[_Pagina]) -> list[Any]:
    detector = DeterministicQualityDetector(
        session=_Sesion(paginas), finding_repo=_Repo(), now_fn=lambda: _AHORA
    )
    return await detector.analyze(uuid.uuid4())


def _serie_anual(anios: range) -> list[_Pagina]:
    return [
        _Pagina(
            url=f"{_BASE}/{anio}/",
            content_year=anio,
            content_published_at=datetime(anio, 6, 1, tzinfo=timezone.utc),
            content_hash=f"hash-{anio}",
        )
        for anio in anios
    ]


# ---------------------------------------------------------------------------
# Un grupo, un hallazgo
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_una_serie_de_nueve_anos_da_un_solo_hallazgo():
    """Antes: nueve acusaciones de «obsoleta» sobre acuerdos que siguen vigentes."""
    hallazgos = await _hallazgos(_serie_anual(range(2017, 2026)))

    series = [h for h in hallazgos if h.finding_type == "version_series"]
    assert len(series) == 1


@pytest.mark.asyncio
async def test_el_hallazgo_de_la_serie_es_informativo_y_no_acusa():
    hallazgos = await _hallazgos(_serie_anual(range(2017, 2026)))

    serie = next(h for h in hallazgos if h.finding_type == "version_series")
    assert serie.severity == "info"


@pytest.mark.asyncio
async def test_el_hallazgo_lleva_las_urls_y_sus_fechas_para_poder_decidir():
    hallazgos = await _hallazgos(_serie_anual(range(2017, 2026)))

    serie = next(h for h in hallazgos if h.finding_type == "version_series")
    versiones = serie.signal["versions"]
    assert len(versiones) == 9
    assert all("url" in v and "date" in v for v in versiones)
    # La más reciente primero: es la que alguien va a querer mirar.
    assert versiones[0]["url"].endswith("/2025/")


@pytest.mark.asyncio
async def test_ya_no_se_emite_superseded_para_una_serie_por_anos():
    """`superseded` afirma «hay una nueva y la vieja sobra». En una serie anual eso es falso."""
    hallazgos = await _hallazgos(_serie_anual(range(2017, 2026)))

    assert [h for h in hallazgos if h.finding_type == "superseded"] == []


@pytest.mark.asyncio
async def test_una_sola_version_no_es_una_serie():
    hallazgos = await _hallazgos(_serie_anual(range(2025, 2026)))

    assert [h for h in hallazgos if h.finding_type == "version_series"] == []


# ---------------------------------------------------------------------------
# Nada en dos apartados
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_una_pagina_de_la_serie_no_sale_ademas_como_desactualizada():
    """Era la queja literal: las mismas páginas en los dos apartados.

    La primera versión de este test agrupaba por `page_id` y comprobaba que ninguna página tuviera
    dos hallazgos. **No servía**: el hallazgo de la serie no lleva `page_id` —habla del grupo—, así
    que cada página seguía teniendo exactamente uno, su `stale`, y el test pasaba con la
    deduplicación completamente rota (los ids se guardaban como texto y se comparaban como UUID).
    Lo que hay que comprobar es que las páginas del grupo **no aparecen** en ningún otro hallazgo.
    """
    paginas = _serie_anual(range(2017, 2026))
    hallazgos = await _hallazgos(paginas)

    serie = next(h for h in hallazgos if h.finding_type == "version_series")
    del_grupo = set(serie.signal["page_ids"])
    assert len(del_grupo) == 9

    otros = [
        (h.finding_type, str(h.page_id))
        for h in hallazgos
        if h.page_id and str(h.page_id) in del_grupo
    ]
    assert otros == [], f"páginas de la serie repetidas en otro apartado: {otros}"


@pytest.mark.asyncio
async def test_una_pagina_antigua_que_no_es_de_ninguna_serie_sigue_siendo_desactualizada():
    """El arreglo no puede tapar el hallazgo que sí vale."""
    pagina = _Pagina(
        url="https://www.uji.es/centres/escola-doctorat/info-general/organitzacio/",
        content_published_at=datetime(2015, 4, 10, tzinfo=timezone.utc),
    )

    tipos = [h.finding_type for h in await _hallazgos([pagina])]

    assert "stale" in tipos


# ---------------------------------------------------------------------------
# Dos URLs con el mismo contenido
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dos_urls_con_el_mismo_contenido_salen_juntas_con_sus_fechas():
    """Pedido por el usuario: «si hay dos páginas con el mismo contenido, se mostraran las dos url
    con las fechas de las dos como hallazgo». Y aquí sí sobra una: es duplicado, no serie."""
    paginas = [
        _Pagina(
            url="https://www.uji.es/centres/escola-doctorat/base/beques/",
            content_hash="mismo-contenido",
            content_published_at=datetime(2024, 3, 1, tzinfo=timezone.utc),
        ),
        _Pagina(
            url="https://www.uji.es/estudis/centres/escola-doctorat/base/beques/",
            content_hash="mismo-contenido",
            content_published_at=datetime(2025, 7, 15, tzinfo=timezone.utc),
        ),
    ]

    hallazgos = await _hallazgos(paginas)

    duplicados = [h for h in hallazgos if h.finding_type == "duplicate"]
    assert len(duplicados) == 1
    señal = duplicados[0].signal
    assert len(señal["versions"]) == 2
    fechas = {v["date"][:10] for v in señal["versions"]}
    assert fechas == {"2024-03-01", "2025-07-15"}


@pytest.mark.asyncio
async def test_dos_paginas_con_contenido_distinto_no_son_duplicado():
    paginas = [
        _Pagina(url="https://www.uji.es/a/", content_hash="uno"),
        _Pagina(url="https://www.uji.es/b/", content_hash="dos"),
    ]

    assert [h for h in await _hallazgos(paginas) if h.finding_type == "duplicate"] == []


@pytest.mark.asyncio
async def test_una_pagina_sin_hash_no_se_empareja_con_nadie():
    """Sin hash no se puede afirmar que dos páginas digan lo mismo."""
    paginas = [
        _Pagina(url="https://www.uji.es/a/", content_hash=None),
        _Pagina(url="https://www.uji.es/b/", content_hash=None),
    ]

    assert [h for h in await _hallazgos(paginas) if h.finding_type == "duplicate"] == []


def test_version_series_es_un_tipo_de_hallazgo_del_contrato():
    from typing import get_args

    from server.app.modules.curation.contracts import FindingType

    assert "version_series" in get_args(FindingType)


# ---------------------------------------------------------------------------
# Cursos académicos: la misma serie, escrita de otra forma (CUR.7)
# ---------------------------------------------------------------------------
#
# Salió al ejecutar el detector semántico contra el apartado real. Sus diez primeros hallazgos eran
# **el mismo falso positivo que este fichero arregló**, con otra sintaxis: el archivo de formación
# transversal publica una página por curso académico —`/23-24/`, `/24-25/`, `/25-26/`— y el modelo
# las declaraba «contradicción» porque las fechas de impartición no coinciden. No se contradicen:
# son ediciones distintas del mismo curso, todas archivadas.
#
# La causa es que la identidad de serie sólo reconocía años de cuatro cifras, así que estas páginas
# no se agrupaban aquí tampoco. Se arregla en un sitio y sirve a los dos detectores.

_CURSOS = "https://www.uji.es/estudis/centres/escola-doctorat/base/arxiu/Formacio-transversal"


def _serie_de_cursos(cursos: list[str]) -> list[_Pagina]:
    return [
        _Pagina(
            url=f"{_CURSOS}/{curso}/recerca/multivariant/",
            content_published_at=datetime(2000 + int(curso[:2]), 9, 1, tzinfo=timezone.utc),
            content_hash=f"hash-{curso}",
        )
        for curso in cursos
    ]


@pytest.mark.asyncio
async def test_un_curso_academico_tambien_es_una_serie():
    hallazgos = await _hallazgos(_serie_de_cursos(["23-24", "24-25", "25-26"]))

    series = [h for h in hallazgos if h.finding_type == "version_series"]
    assert len(series) == 1
    assert series[0].signal["count"] == 3


@pytest.mark.asyncio
async def test_una_serie_de_cursos_no_acusa_de_superada_a_la_edicion_anterior():
    hallazgos = await _hallazgos(_serie_de_cursos(["23-24", "24-25", "25-26"]))

    assert [h for h in hallazgos if h.finding_type == "superseded"] == []


@pytest.mark.asyncio
async def test_dos_numeros_que_no_son_un_curso_academico_no_agrupan_nada():
    """`/12-34/` no es un curso: agrupar por cualquier pareja de cifras juntaría cosas ajenas."""
    paginas = [
        _Pagina(url=f"{_CURSOS}/12-34/x/", content_hash="a"),
        _Pagina(url=f"{_CURSOS}/56-78/x/", content_hash="b"),
    ]

    hallazgos = await _hallazgos(paginas)

    assert [h for h in hallazgos if h.finding_type == "version_series"] == []
