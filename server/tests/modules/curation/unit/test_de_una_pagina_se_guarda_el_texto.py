"""De una página web se guarda su texto, no su marcado (RAS.2).

`SiteCrawler` guardaba el cuerpo de la respuesta tal cual en `markdown_content`, y nadie convertía
el HTML. Medido contra el portal real: **51.098 bytes de HTML con 4.249 caracteres de texto**. Tres
consecuencias, y ninguna se veía:

* `token_count` medía el marcado, así que el umbral de `thin` (120 tokens) **no podía dispararse
  nunca** por mucho que la página tuviera tres frases de contenido: el menú y los scripts la hacían
  parecer rica. El falso negativo simétrico del falso positivo de `empty`.
* El detector semántico embebe `markdown_content`: comparaba plantillas HTML entre sí, y en un
  portal el marcado es idéntico en todas las páginas.
* La selección al corpus pasa `prefetched_content=page.markdown_content` a la ingesta, así que al
  asistente entraban 51 KB de `<div>` por página.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

import pytest

from server.app.modules.curation.site_crawler import SiteCrawler
from server.app.modules.curation.spider import CrawlResult, CrawlStatus

_HTML_COMO_EL_DEL_PORTAL = (
    "<html><head><title>Beques de doctorat</title>"
    '<script src="/js/a.js"></script><style>.x{color:#fff}</style></head>'
    "<body><noscript>Activa JavaScript</noscript><nav><a href='/inicio'>Inici</a></nav>"
    "<h1>Beques de doctorat</h1><p>Convocatoria oberta fins al 30 de setembre.</p>"
    "</body></html>"
)


@dataclass
class _RepoDePaginas:
    guardadas: dict = field(default_factory=dict)

    async def upsert(self, *, site_id: uuid.UUID, url: str, **campos: Any) -> Any:
        self.guardadas[url] = campos

        class _P:
            id = uuid.uuid4()

        return _P()

    async def list_by_site(self, site_id: uuid.UUID, status: str | None = None) -> list:
        return []

    async def mark_gone(self, page_ids: list[uuid.UUID]) -> int:
        return 0


@dataclass
class _Sitio:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    root_url: str = "https://www.uji.es/centres/escola-doctorat/"
    sitemap_url: str | None = None
    config_json: dict = field(default_factory=dict)
    last_crawled_at: Any = None
    status: str = "active"
    error_message: str | None = None


class _Sesion:
    def __init__(self, sitio: Any) -> None:
        self._sitio = sitio

    async def get(self, modelo: Any, ident: Any) -> Any:
        return self._sitio

    async def flush(self) -> None:
        return None


class _SpiderQueDevuelveHtml:
    def __init__(self, html: str) -> None:
        self._html = html

    async def crawl(self, source: Any) -> CrawlResult:
        return CrawlResult(
            crawled_urls=[source.root_url],
            pages_crawled=1,
            pages_skipped=0,
            status=CrawlStatus.COMPLETED,
        )

    async def _fetch(self, url: str) -> tuple[str, dict]:
        return self._html, {}


class _SinSitemap:
    def extract_from_headers(self, headers: dict) -> dict:
        return {"http_last_modified": None, "http_etag": None}

    def extract_canonical(self, html: str) -> str | None:
        return None

    def extract_content_year(self, url: str, text: str) -> int | None:
        return None

    async def fetch_sitemap(self, url: str, fetch_fn: Any) -> dict:
        return {}


async def _rastrear(html: str) -> dict:
    repo = _RepoDePaginas()
    sitio = _Sitio()
    crawler = SiteCrawler(
        session=_Sesion(sitio),
        spider=_SpiderQueDevuelveHtml(html),
        signal_extractor=_SinSitemap(),
        page_repo=repo,
    )
    await crawler.crawl_site(sitio.id)
    return repo.guardadas[sitio.root_url]


@pytest.mark.asyncio
async def test_se_guarda_el_texto_y_no_el_html():
    campos = await _rastrear(_HTML_COMO_EL_DEL_PORTAL)

    contenido = campos["markdown_content"]
    assert "Convocatoria oberta fins al 30 de setembre." in contenido
    assert "<div" not in contenido
    assert "<script" not in contenido
    assert "color:#fff" not in contenido


@pytest.mark.asyncio
async def test_el_recuento_de_tokens_mide_el_texto_y_no_el_marcado():
    campos = await _rastrear(_HTML_COMO_EL_DEL_PORTAL)

    # El HTML son ~450 caracteres; el texto, unos 100. Si el recuento midiera el marcado,
    # el umbral de `thin` sería inalcanzable.
    assert campos["token_count"] < 60


@pytest.mark.asyncio
async def test_el_titulo_sale_del_html():
    campos = await _rastrear(_HTML_COMO_EL_DEL_PORTAL)

    assert campos["title"] == "Beques de doctorat"


@pytest.mark.asyncio
async def test_las_senales_de_dinamismo_se_guardan_con_la_pagina():
    """El detector se ejecuta después y ya no tiene el HTML: la evidencia hay que persistirla."""
    dinamica = (
        "<html><head>" + "<script>x</script>" * 10 + '</head><body><div id="root"></div>'
        "</body></html>"
    )

    campos = await _rastrear(dinamica)

    assert campos["render_signals"], "una página ilegible sin navegador tiene que dejar constancia"


@pytest.mark.asyncio
async def test_una_pagina_normal_no_guarda_senales_de_dinamismo():
    campos = await _rastrear(_HTML_COMO_EL_DEL_PORTAL)

    assert not campos["render_signals"]


@pytest.mark.asyncio
async def test_un_contenido_que_no_es_html_se_guarda_tal_cual():
    """El corpus normativo ya entra como Markdown por otra vía; convertir lo que no es HTML
    sería estropearlo."""
    markdown = "# Titol\n\nParagraf amb **negreta**.\n"

    campos = await _rastrear(markdown)

    assert campos["markdown_content"] == markdown


@pytest.mark.asyncio
async def test_se_guardan_los_textos_de_los_enlaces_del_contenido():
    """#345 — el texto guardado no dice qué líneas eran enlaces, y es lo que distingue una página
    de navegación. Los del `<nav>` no: son plantilla y tampoco están en el texto."""
    campos = await _rastrear(
        _HTML_COMO_EL_DEL_PORTAL.replace(
            "<p>Convocatoria", "<ul><li><a href='/b'>Bases</a></li></ul><p>Convocatoria"
        )
    )

    assert campos["textos_de_enlace"] == ["Bases"]
