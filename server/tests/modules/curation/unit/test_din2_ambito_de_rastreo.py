"""DIN.2 — rastrear por sección sin que el censo se lleve el resto del sitio.

**La trampa que este fichero cierra.** `site_crawler` declaraba las bajas así:

    gone_ids = [p.id for p in existing_pages if p.url not in seen_urls]

Era correcto porque **el sitio *era* el apartado**: lo rastreado y lo existente eran el mismo
conjunto. En cuanto un sitio tiene varias secciones con cadencias distintas, eso se rompe: una
pasada de `/eventos` que termine completa vería `seen_urls` sólo con las de `/eventos` y
`existing_pages` con **todo el sitio** — y declararía baja el resto del portal. Con la
auto-retirada de DIN.4 encima, eso vacía corpus.

Es literalmente la lección que `ingestion/corpus/source.py` ya tiene escrita para el corpus
normativo: «solo con un censo se puede detectar una retirada, porque solo entonces *ausente*
significa algo». **El censo se acota al ámbito realmente rastreado**, y es la regla dura nº 1 del
bloque.

El primer test de `TestElCensoSeAcota` es el que justifica el prompt: sin la acotación es rojo, y
lo que declara de más es el portal entero.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from server.app.modules.curation.site_crawler import SiteCrawler
from server.app.modules.curation.spider import CrawlResult, CrawlStatus

AHORA = datetime(2026, 9, 17, 12, 0, 0, tzinfo=timezone.utc)


# ──────────────────────────── Dobles ────────────────────────────


@dataclass
class _Pagina:
    url: str
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    content_hash: str | None = "viejo"
    status: str = "active"
    markdown_content: str | None = None
    title: str | None = None


@dataclass
class _Sitio:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    root_url: str = "https://www.uji.es"
    sitemap_url: str | None = None
    config_json: dict = field(default_factory=dict)
    crawl_interval_hours: int = 24
    last_crawled_at: Any = None
    crawl_frontier: dict | None = None
    status: str = "active"
    error_message: str | None = None


@dataclass
class _Seccion:
    site_id: uuid.UUID
    name: str = "Jornadas"
    pattern: str = "/jornadas"
    pattern_kind: str = "path_prefix"
    crawl_interval_hours: int | None = None
    criteria_json: dict | None = None
    mode: str = "manual"
    owner: str | None = None
    last_crawled_at: Any = None
    is_active: bool = True
    id: uuid.UUID = field(default_factory=uuid.uuid4)


class _RepoDePaginas:
    def __init__(self, existentes: list[_Pagina]) -> None:
        self.existentes = existentes
        self.marcadas_como_ida: list[uuid.UUID] = []

    async def upsert(self, *, site_id: uuid.UUID, url: str, **campos: Any) -> Any:
        for pagina in self.existentes:
            if pagina.url == url:
                for clave, valor in campos.items():
                    setattr(pagina, clave, valor)
                return pagina
        nueva = _Pagina(url=url, content_hash=campos.get("content_hash"))
        self.existentes.append(nueva)
        return nueva

    async def list_by_site(self, site_id: uuid.UUID, status: str | None = None) -> list:
        return [
            p
            for p in self.existentes
            if status is None or p.status == status
        ]

    async def mark_gone(self, page_ids: list[uuid.UUID]) -> int:
        self.marcadas_como_ida.extend(page_ids)
        for pagina in self.existentes:
            if pagina.id in page_ids:
                pagina.status = "gone"
        return len(page_ids)


class _Sesion:
    """Devuelve el sitio o la sección según el modelo que se le pida."""

    def __init__(self, sitio: _Sitio, secciones: list[_Seccion] | None = None) -> None:
        self._sitio = sitio
        self._secciones = {s.id: s for s in (secciones or [])}

    async def get(self, modelo: Any, ident: Any) -> Any:
        if getattr(modelo, "__name__", "") == "HubWebSection":
            return self._secciones.get(ident)
        return self._sitio if ident == self._sitio.id else None

    async def flush(self) -> None:
        return None


class _Spider:
    """Recorre lo que se le dice, aplicando el filtro del sitio y el del ámbito como lo hace
    `GenericSpider`: sobre los enlaces, nunca sobre la raíz."""

    def __init__(self, urls: list[str], stop_reason: str | None = None) -> None:
        self._urls = urls
        self._stop_reason = stop_reason
        self.fuentes: list[Any] = []

    async def crawl(self, source: Any) -> CrawlResult:
        self.fuentes.append(source)
        from server.app.modules.curation.secciones import predicado_de_ambito

        en_ambito = predicado_de_ambito(source.config_json)
        visitadas = [u for u in self._urls if en_ambito(u)]
        return CrawlResult(
            crawled_urls=visitadas,
            pages_crawled=len(visitadas),
            pages_skipped=7 if self._stop_reason else 0,
            status=(
                CrawlStatus.COMPLETED_PARTIAL
                if self._stop_reason
                else CrawlStatus.COMPLETED
            ),
            stop_reason=self._stop_reason,
        )

    async def _fetch(self, url: str) -> tuple[str, dict]:
        return f"<html><body><main>Contenido de {url}</main></body></html>", {}


class _SpiderQueNoFiltra(_Spider):
    """El recorrido devuelve también lo que está fuera del ámbito, que es lo que pasa de verdad:
    el menú de cada página enlaza al portal entero y la raíz nunca lleva el filtro. Es
    `SiteCrawler` quien tiene que no declarar nada de eso."""

    async def crawl(self, source: Any) -> CrawlResult:
        self.fuentes.append(source)
        return CrawlResult(
            crawled_urls=list(self._urls),
            pages_crawled=len(self._urls),
            pages_skipped=0,
            status=CrawlStatus.COMPLETED,
            stop_reason=None,
        )


class _SinSitemap:
    def extract_from_headers(self, headers: dict) -> dict:
        return {"http_last_modified": None, "http_etag": None}

    def extract_canonical(self, html: str) -> str | None:
        return None

    def extract_content_year(self, url: str, text: str) -> int | None:
        return None

    async def fetch_sitemap(self, url: str, fetch_fn: Any) -> dict:
        return {}


def _crawler(sesion: _Sesion, spider: _Spider, repo: _RepoDePaginas) -> SiteCrawler:
    return SiteCrawler(
        session=sesion, spider=spider, signal_extractor=_SinSitemap(), page_repo=repo
    )


# ──────────────────────────── El censo acotado ────────────────────────────


class TestElCensoSeAcota:

    @pytest.mark.asyncio
    async def test_should_not_declare_gone_the_pages_of_another_section(self):
        """**El test que justifica el prompt.** Sitio con dos secciones, pasada completa de una:
        las páginas de la OTRA no se marcan `gone`. Sin la acotación este test es rojo y el
        portal entero queda declarado de baja."""
        sitio = _Sitio()
        jornadas = _Seccion(site_id=sitio.id, name="Jornadas", pattern="/jornadas")
        eventos = _Seccion(site_id=sitio.id, name="Eventos", pattern="/eventos")
        de_eventos = _Pagina(url="https://www.uji.es/eventos/uno")
        repo = _RepoDePaginas([
            _Pagina(url="https://www.uji.es/jornadas/uno"),
            de_eventos,
            _Pagina(url="https://www.uji.es/noticias/otra"),
        ])
        spider = _Spider(["https://www.uji.es/jornadas/uno"])

        resumen = await _crawler(_Sesion(sitio, [jornadas, eventos]), spider, repo).crawl_site(
            sitio.id, section_id=jornadas.id
        )

        assert repo.marcadas_como_ida == []
        assert resumen.pages_gone == 0
        assert de_eventos.status == "active"

    @pytest.mark.asyncio
    async def test_should_declare_gone_a_page_of_the_scope_that_no_longer_appears(self):
        """Dentro del ámbito, una baja sigue siendo una baja: acotar no es dejar de detectar."""
        sitio = _Sitio()
        jornadas = _Seccion(site_id=sitio.id, pattern="/jornadas")
        desaparecida = _Pagina(url="https://www.uji.es/jornadas/vieja")
        repo = _RepoDePaginas([
            _Pagina(url="https://www.uji.es/jornadas/uno"),
            desaparecida,
            _Pagina(url="https://www.uji.es/eventos/uno"),
        ])
        spider = _Spider(["https://www.uji.es/jornadas/uno"])

        resumen = await _crawler(_Sesion(sitio, [jornadas]), spider, repo).crawl_site(
            sitio.id, section_id=jornadas.id
        )

        assert repo.marcadas_como_ida == [desaparecida.id]
        assert resumen.pages_gone == 1
        assert resumen.gone_page_ids == [desaparecida.id]

    @pytest.mark.asyncio
    async def test_should_declare_nothing_when_the_scoped_pass_was_truncated(self):
        """`truncated` sigue vetando las bajas, ahora por ámbito: «no apareció» sigue
        significando «no se llegó a mirar»."""
        sitio = _Sitio()
        jornadas = _Seccion(site_id=sitio.id, pattern="/jornadas")
        repo = _RepoDePaginas([
            _Pagina(url="https://www.uji.es/jornadas/uno"),
            _Pagina(url="https://www.uji.es/jornadas/vieja"),
        ])
        spider = _Spider(["https://www.uji.es/jornadas/uno"], stop_reason="max_pages")

        resumen = await _crawler(_Sesion(sitio, [jornadas]), spider, repo).crawl_site(
            sitio.id, section_id=jornadas.id
        )

        assert repo.marcadas_como_ida == []
        assert resumen.pages_gone == 0
        assert resumen.truncated is True
        assert resumen.stop_reason == "max_pages"

    @pytest.mark.asyncio
    async def test_should_not_report_a_change_outside_the_scope(self):
        """«Fuera del ámbito no se declara nada — ni baja ni cambio». La página de otra sección
        que el recorrido ve de paso no puede aparecer como cambiada: DIN.5 la reingeriría."""
        sitio = _Sitio()
        jornadas = _Seccion(site_id=sitio.id, pattern="/jornadas")
        repo = _RepoDePaginas([
            _Pagina(url="https://www.uji.es/jornadas/uno", content_hash="viejo"),
            _Pagina(url="https://www.uji.es/eventos/uno", content_hash="viejo"),
        ])
        # El spider no filtra la de eventos: simula el enlace que aparece en el menú.
        spider = _SpiderQueNoFiltra([
            "https://www.uji.es/jornadas/uno",
            "https://www.uji.es/eventos/uno",
        ])

        resumen = await _crawler(_Sesion(sitio, [jornadas]), spider, repo).crawl_site(
            sitio.id, section_id=jornadas.id
        )

        cambiadas = {
            p.url for p in repo.existentes if p.id in resumen.changed_page_ids
        }
        assert "https://www.uji.es/eventos/uno" not in cambiadas

    @pytest.mark.asyncio
    async def test_should_behave_exactly_as_today_when_the_scope_is_the_whole_site(self):
        """**El test de no-regresión**: sin sección, el mismo diff de siempre."""
        sitio = _Sitio()
        desaparecida = _Pagina(url="https://www.uji.es/vieja")
        repo = _RepoDePaginas([
            _Pagina(url="https://www.uji.es/jornadas/uno"),
            desaparecida,
        ])
        spider = _Spider(["https://www.uji.es/jornadas/uno"])

        resumen = await _crawler(_Sesion(sitio), spider, repo).crawl_site(sitio.id)

        assert repo.marcadas_como_ida == [desaparecida.id]
        assert resumen.pages_gone == 1
        assert resumen.ambito == "sitio"
        assert resumen.section_id is None


# ──────────────────────────── El ámbito viaja y se compone ────────────────────────────


class TestElAmbitoQueSeRastrea:

    @pytest.mark.asyncio
    async def test_should_say_which_scope_the_pass_covered(self):
        """El job y el diario de DIN.6 tienen que poder decirlo."""
        sitio = _Sitio()
        jornadas = _Seccion(site_id=sitio.id, pattern="/jornadas")
        spider = _Spider(["https://www.uji.es/jornadas/uno"])

        resumen = await _crawler(
            _Sesion(sitio, [jornadas]), spider, _RepoDePaginas([])
        ).crawl_site(sitio.id, section_id=jornadas.id)

        assert resumen.section_id == jornadas.id
        assert resumen.ambito == str(jornadas.id)

    @pytest.mark.asyncio
    async def test_should_compose_the_section_pattern_with_the_site_fence(self):
        """El filtro del sitio es **la valla del dominio** y el de la sección el apartado dentro:
        se aplica ADEMÁS, no en su lugar. Una URL que casa la sección pero no la valla no se
        rastrea."""
        sitio = _Sitio(config_json={"url_regex_filter": r"^https://www\.uji\.es/"})
        jornadas = _Seccion(site_id=sitio.id, pattern="/jornadas")
        spider = _Spider(["https://www.uji.es/jornadas/uno"])

        await _crawler(_Sesion(sitio, [jornadas]), spider, _RepoDePaginas([])).crawl_site(
            sitio.id, section_id=jornadas.id
        )

        config = spider.fuentes[0].config_json
        assert config["url_regex_filter"] == r"^https://www\.uji\.es/"
        assert config["ambito_pattern"] == "/jornadas"
        assert config["ambito_pattern_kind"] == "path_prefix"

    @pytest.mark.asyncio
    async def test_should_hand_the_spider_the_effective_criteria(self):
        """Los parámetros efectivos de DIN.1, de verdad en uso: un apartado puede recortar la
        plantilla con otro selector que su portal."""
        sitio = _Sitio(config_json={"content_selector": "main", "max_pages": 50})
        jornadas = _Seccion(
            site_id=sitio.id, pattern="/jornadas", criteria_json={"max_pages": 5}
        )
        spider = _Spider(["https://www.uji.es/jornadas/uno"])

        await _crawler(_Sesion(sitio, [jornadas]), spider, _RepoDePaginas([])).crawl_site(
            sitio.id, section_id=jornadas.id
        )

        config = spider.fuentes[0].config_json
        assert config["max_pages"] == 5
        assert config["content_selector"] == "main"

    @pytest.mark.asyncio
    async def test_should_seal_the_section_clock_and_not_lie_about_the_site(self):
        """`last_crawled_at` del sitio diciendo que se vio todo cuando sólo se vio un apartado es
        una mentira que dejaría al resto del portal sin rastrear para siempre."""
        sitio = _Sitio(last_crawled_at=None)
        jornadas = _Seccion(site_id=sitio.id, pattern="/jornadas")
        spider = _Spider(["https://www.uji.es/jornadas/uno"])

        await _crawler(_Sesion(sitio, [jornadas]), spider, _RepoDePaginas([])).crawl_site(
            sitio.id, section_id=jornadas.id
        )

        assert jornadas.last_crawled_at is not None
        assert sitio.last_crawled_at is None

    @pytest.mark.asyncio
    async def test_should_seal_the_site_clock_when_the_scope_was_the_whole_site(self):
        sitio = _Sitio(last_crawled_at=None)
        spider = _Spider(["https://www.uji.es/jornadas/uno"])

        await _crawler(_Sesion(sitio), spider, _RepoDePaginas([])).crawl_site(sitio.id)

        assert sitio.last_crawled_at is not None

    @pytest.mark.asyncio
    async def test_should_not_touch_the_site_queue_from_a_scoped_pass(self):
        """La cola de RAS.3 vive en la fila del **sitio**, y es de un recorrido del sitio entero.
        Si una pasada de `/jornadas` la escribiera, la siguiente pasada de `/eventos` arrancaría
        por la mitad del recorrido de otra sección — y con el censo acotado creería haber visto
        su ámbito sin haberlo visto. Una sección es pequeña por definición: si se trunca, la
        siguiente pasada empieza de nuevo."""
        cola = {"pending": [["https://www.uji.es/x", 1]], "visited": [], "dropped": 0}
        sitio = _Sitio(crawl_frontier=dict(cola))
        jornadas = _Seccion(site_id=sitio.id, pattern="/jornadas")
        spider = _Spider(["https://www.uji.es/jornadas/uno"], stop_reason="max_pages")

        await _crawler(_Sesion(sitio, [jornadas]), spider, _RepoDePaginas([])).crawl_site(
            sitio.id, section_id=jornadas.id
        )

        assert sitio.crawl_frontier == cola
        assert spider.fuentes[0].crawl_frontier is None

    @pytest.mark.asyncio
    async def test_should_fail_clearly_when_the_section_does_not_belong_to_the_site(self):
        """Un ámbito que no existe no se degrada a «el sitio entero»: con la auto-retirada de
        DIN.4 detrás, eso sería una pasada de sección que declara baja el portal."""
        sitio = _Sitio()
        spider = _Spider([])

        resumen = await _crawler(_Sesion(sitio), spider, _RepoDePaginas([])).crawl_site(
            sitio.id, section_id=uuid.uuid4()
        )

        assert resumen.errors
        assert "secci" in resumen.errors[0].lower()
        assert resumen.pages_gone == 0


# ──────────────────────────── Elegibilidad ────────────────────────────


class _SesionDeElegibilidad:
    """Responde sitios o secciones según la entidad que pida la consulta."""

    def __init__(self, sitios: list[_Sitio], secciones: list[_Seccion]) -> None:
        self._sitios = sitios
        self._secciones = secciones

    async def execute(self, stmt: Any) -> Any:
        entidad = stmt.column_descriptions[0]["entity"].__name__
        filas = self._secciones if entidad == "HubWebSection" else self._sitios

        class _R:
            def scalars(self_inner) -> Any:
                return self_inner

            def all(self_inner) -> list:
                return list(filas)

        return _R()


async def _vencidos(sitios: list[_Sitio], secciones: list[_Seccion]) -> list:
    from server.app.modules.curation.quality_scheduler import _get_due_scopes

    return await _get_due_scopes(_SesionDeElegibilidad(sitios, secciones), AHORA)


class TestQueVence:

    @pytest.mark.asyncio
    async def test_should_make_a_section_due_by_its_own_interval(self):
        sitio = _Sitio(crawl_interval_hours=240, last_crawled_at=AHORA)
        vencida = _Seccion(
            site_id=sitio.id,
            name="Eventos",
            crawl_interval_hours=6,
            last_crawled_at=AHORA - timedelta(hours=7),
        )
        no_vencida = _Seccion(
            site_id=sitio.id,
            name="Jornadas",
            crawl_interval_hours=6,
            last_crawled_at=AHORA - timedelta(hours=2),
        )

        ambitos = await _vencidos([sitio], [vencida, no_vencida])

        assert [a.section_id for a in ambitos] == [vencida.id]

    @pytest.mark.asyncio
    async def test_should_not_make_a_section_due_by_the_inherited_interval_it_overrode(self):
        """La cadencia del sitio no puede resucitar una sección que dijo otra cosa."""
        sitio = _Sitio(crawl_interval_hours=1, last_crawled_at=AHORA)
        seccion = _Seccion(
            site_id=sitio.id,
            crawl_interval_hours=48,
            last_crawled_at=AHORA - timedelta(hours=10),
        )

        assert await _vencidos([sitio], [seccion]) == []

    @pytest.mark.asyncio
    async def test_should_use_the_inherited_interval_when_the_section_leaves_it_null(self):
        sitio = _Sitio(crawl_interval_hours=6, last_crawled_at=AHORA)
        seccion = _Seccion(
            site_id=sitio.id,
            crawl_interval_hours=None,
            last_crawled_at=AHORA - timedelta(hours=7),
        )

        ambitos = await _vencidos([sitio], [seccion])

        assert [a.section_id for a in ambitos] == [seccion.id]

    @pytest.mark.asyncio
    async def test_should_make_a_never_crawled_section_due(self):
        """Igual que un sitio nuevo: nunca rastreada vence."""
        sitio = _Sitio(last_crawled_at=AHORA)
        seccion = _Seccion(site_id=sitio.id, last_crawled_at=None)

        ambitos = await _vencidos([sitio], [seccion])

        assert [a.section_id for a in ambitos] == [seccion.id]

    @pytest.mark.asyncio
    async def test_should_never_make_an_inactive_section_due(self):
        sitio = _Sitio(last_crawled_at=AHORA)
        seccion = _Seccion(site_id=sitio.id, last_crawled_at=None, is_active=False)

        assert await _vencidos([sitio], [seccion]) == []

    @pytest.mark.asyncio
    async def test_should_keep_a_site_without_sections_due_as_a_site(self):
        """El comportamiento de hoy, intacto."""
        sitio = _Sitio(crawl_interval_hours=24, last_crawled_at=AHORA - timedelta(hours=25))
        reciente = _Sitio(crawl_interval_hours=24, last_crawled_at=AHORA)

        ambitos = await _vencidos([sitio, reciente], [])

        assert [(a.site_id, a.section_id) for a in ambitos] == [(sitio.id, None)]

    @pytest.mark.asyncio
    async def test_should_stop_crawling_a_sectioned_site_as_a_whole(self):
        """Un sitio con secciones **vence por sección**, no además como sitio: si venciera por
        los dos caminos, cada pasada del sitio entero volvería a rastrear lo que la sección
        acababa de mirar, y con cadencias distintas sería el doble de peticiones contra el mismo
        servidor. Lo que queda fuera de toda sección sigue en manos de quien cura, con el rastreo
        del sitio a mano."""
        sitio = _Sitio(crawl_interval_hours=24, last_crawled_at=AHORA - timedelta(hours=99))
        seccion = _Seccion(site_id=sitio.id, last_crawled_at=AHORA)

        assert await _vencidos([sitio], [seccion]) == []

    @pytest.mark.asyncio
    async def test_should_ignore_sections_of_a_site_that_is_not_active(self):
        sitio = _Sitio(status="error", last_crawled_at=None)
        seccion = _Seccion(site_id=sitio.id, last_crawled_at=None)

        # La consulta de sitios ya filtra por `status='active'`; aquí se comprueba que la de
        # secciones no se salta ese filtro por el otro camino.
        assert await _vencidos([], [seccion]) == []
