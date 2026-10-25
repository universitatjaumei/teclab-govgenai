"""Los hallazgos, calibrados con el primer rastreo real (RAS.5).

400 páginas del apartado de la Escuela de Doctorado, y el informe salió así:

    stale/info          303
    superseded/warning  191
    empty/critical        3
    crawl_error/warning   3

Tres de los cuatro tipos estaban mal, y ninguno se veía sin un portal de verdad delante:

1. **`empty` sobre las tres páginas que dieron 404.** Una página que no se pudo descargar no
   tiene contenido *porque no se leyó*, y eso ya lo dice `crawl_error`. Acusarla además de estar
   vacía es afirmar dos cosas distintas del mismo hecho, y una es falsa.

2. **`superseded` entre `http://` y `https://` de la misma página.** El portal responde por los
   dos esquemas, el rastreo los tomó por páginas distintas y `_process_key` los agrupó: 191 avisos
   de «hay una versión nueva y la vieja sigue ahí» que en realidad eran la misma página dos veces.
   La clave de las URLs sin año decía ser «única, no participa en grupos» y no lo era.

3. **`stale` en 303 de 400 páginas.** El portal **no declara ninguna fecha**: sin `Last-Modified`,
   sin `ETag` y sin `sitemap.xml`. Así que la «fecha del contenido» salía del año más reciente
   *mencionado en el texto*; en una página se leen 1925, 2010, 2016, 2021, 2024 y 2071, y de ahí
   se concluía «contenido de 2024, 960 días de antigüedad». Un número en el texto no es una fecha
   de publicación. Un año en la **URL** sí es una señal del portal —así versiona sus documentos—,
   y esa se conserva.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from server.app.modules.curation.deterministic_detector import DeterministicQualityDetector

_AHORA = datetime(2026, 8, 18, tzinfo=timezone.utc)


@dataclass
class _Pagina:
    url: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    markdown_content: str | None = "Contenido suficiente para no ser pobre. " * 20
    token_count: int | None = 400
    status: str = "active"
    error_message: str | None = None
    error_kind: str | None = None
    error_attempts: int | None = None
    canonical_url: str | None = None
    sitemap_lastmod: datetime | None = None
    http_last_modified: datetime | None = None
    content_year: int | None = None
    content_published_at: datetime | None = None
    content_owner: str | None = None
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


async def _tipos(paginas: list[_Pagina]) -> list[str]:
    detector = DeterministicQualityDetector(
        session=_Sesion(paginas), finding_repo=_Repo(), now_fn=lambda: _AHORA
    )
    return [h.finding_type for h in await detector.analyze(uuid.uuid4())]


# ---------------------------------------------------------------------------
# 1. No se acusa de vacía a la que no se pudo descargar
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_una_pagina_con_404_no_es_ademas_una_pagina_vacia():
    pagina = _Pagina(
        url="https://www.uji.es/centres/escola-doctorat/estudiantat/",
        markdown_content=None, token_count=None, status="error",
        error_kind="not_found", error_message="404",
    )

    tipos = await _tipos([pagina])

    assert "crawl_error" in tipos
    assert "empty" not in tipos, "el 404 ya lo dice; «vacía» es una segunda afirmación, y falsa"


@pytest.mark.asyncio
async def test_una_pagina_con_error_de_red_tampoco_es_pobre():
    pagina = _Pagina(
        url="https://www.uji.es/x/", markdown_content="", token_count=2, status="error",
        error_kind="transient", error_attempts=3,
    )

    tipos = await _tipos([pagina])

    assert "thin" not in tipos
    assert "crawl_error" in tipos


@pytest.mark.asyncio
async def test_una_pagina_activa_y_vacia_sigue_siendo_un_hallazgo():
    """El arreglo no puede tapar el caso de verdad: página que responde 200 y no trae nada."""
    pagina = _Pagina(url="https://www.uji.es/y/", markdown_content="", token_count=0)

    assert "empty" in await _tipos([pagina])


# ---------------------------------------------------------------------------
# 2. http y https de la misma página no son dos versiones
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_la_misma_pagina_en_http_y_https_no_es_una_supersesion():
    ruta = "/centres/escola-doctorat/escola-doctorat/normativa/normestudi/"
    paginas = [
        _Pagina(url=f"http://www.uji.es{ruta}"),
        _Pagina(url=f"https://www.uji.es{ruta}"),
    ]

    tipos = await _tipos(paginas)

    assert "superseded" not in tipos, "191 avisos del primer rastreo eran exactamente esto"


@pytest.mark.asyncio
async def test_dos_versiones_por_ano_en_la_url_son_una_serie():
    """CUR.2 — lo que el detector puede afirmar de un grupo por años es que **existe**.

    Este test decía `superseded`. Lo corrigió el usuario con un dato del dominio: el portal publica
    por años y todos los documentos siguen vigentes, así que «superada» era falso.
    """
    paginas = [
        _Pagina(url="https://www.uji.es/x/2024/beques/", content_year=2024),
        _Pagina(url="https://www.uji.es/x/2025/beques/", content_year=2025),
    ]

    tipos = await _tipos(paginas)
    assert "version_series" in tipos
    assert "superseded" not in tipos


@pytest.mark.asyncio
async def test_dos_paginas_distintas_del_mismo_portal_no_se_agrupan():
    paginas = [
        _Pagina(url="https://www.uji.es/centres/escola-doctorat/beques/"),
        _Pagina(url="https://www.uji.es/centres/escola-doctorat/tesis/"),
    ]

    assert "superseded" not in await _tipos(paginas)


# ---------------------------------------------------------------------------
# 3. `stale` necesita una fecha, no un número suelto en el texto
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_ano_mencionado_en_el_texto_no_convierte_la_pagina_en_antigua():
    """Era el 76 % del informe. La página menciona 2024 —y también 1925 y 2071—."""
    pagina = _Pagina(
        url="https://www.uji.es/centres/escola-doctorat/escola-doctorat/normativa/normestudi/",
        content_year=2024,
    )

    assert "stale" not in await _tipos([pagina])


@pytest.mark.asyncio
async def test_un_ano_en_la_url_si_fecha_la_pagina():
    """Es como el portal versiona sus documentos: `/pext/19-20/`, `/2019/`."""
    pagina = _Pagina(
        url="https://www.uji.es/estudis/centres/escola-doctorat/base/contractes/2019/",
        content_year=2019,
    )

    assert "stale" in await _tipos([pagina])


@pytest.mark.asyncio
async def test_una_fecha_declarada_por_el_servidor_si_fecha_la_pagina():
    pagina = _Pagina(
        url="https://www.uji.es/z/",
        http_last_modified=_AHORA - timedelta(days=900),
    )

    assert "stale" in await _tipos([pagina])


@pytest.mark.asyncio
async def test_una_fecha_del_sitemap_tambien_vale():
    pagina = _Pagina(
        url="https://www.uji.es/z/", sitemap_lastmod=_AHORA - timedelta(days=800)
    )

    assert "stale" in await _tipos([pagina])


@pytest.mark.asyncio
async def test_el_hallazgo_dice_de_donde_sale_la_fecha():
    """Quien revisa tiene que poder distinguir «lo dice el servidor» de «lo dice la URL»."""
    pagina = _Pagina(
        url="https://www.uji.es/x/2019/", content_year=2019,
    )
    detector = DeterministicQualityDetector(
        session=_Sesion([pagina]), finding_repo=_Repo(), now_fn=lambda: _AHORA
    )

    hallazgos = await detector.analyze(uuid.uuid4())

    stale = next(h for h in hallazgos if h.finding_type == "stale")
    assert stale.signal["source"] == "url_year"


# ───────── El hallazgo tiene que decir por qué lo es (CUR.8) ─────────
#
# Del usuario: «cuando se dice que están desactualizadas o potencialmente desactualizadas, se debería
# decir la razón (que la fecha que se indica como fecha de actualización es anterior a x años, meses o
# el criterio que se utilice)». El umbral con el que se juzgó **tiene que viajar en el hallazgo**: es
# de cada sitio desde CUR.2.1, así que leerlo de la configuración al pintar la pantalla daría el
# criterio de hoy y no el que produjo el aviso.


@pytest.mark.asyncio
async def test_una_desactualizada_lleva_el_umbral_con_el_que_se_juzgo():
    pagina = _Pagina(
        url="https://www.uji.es/x/",
        content_published_at=datetime(2021, 11, 18, tzinfo=timezone.utc),
    )
    detector = DeterministicQualityDetector(
        session=_Sesion([pagina]), finding_repo=_Repo(), now_fn=lambda: _AHORA, stale_days=400
    )

    hallazgos = await detector.analyze(uuid.uuid4())

    stale = next(h for h in hallazgos if h.finding_type == "stale")
    assert stale.signal["threshold"] == 400
    assert stale.signal["age_days"] > 400
