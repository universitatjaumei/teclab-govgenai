"""Tests TDD — SiteCrawler (Prompt 9Q.2).

Orquesta el crawl de un sitio entero: une URLs de sitemap + enlaces del spider,
upsert de cada página con señales, y diff de sitemap (nuevas/cambiadas/desaparecidas).

Se prueba con fakes en memoria (sin BD): page_repo, spider y session falsos.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from server.app.modules.agents_hub.ingestion.hasher import hash_content


# ───────────────────────── Fakes ─────────────────────────


class _FakeSite:
    def __init__(self, root_url: str, sitemap_url: str | None = None) -> None:
        self.id = uuid.uuid4()
        self.root_url = root_url
        self.sitemap_url = sitemap_url
        self.config_json: dict = {}
        self.spider_type = "generic"
        self.status = "active"
        self.error_message: str | None = None
        self.last_crawled_at: datetime | None = None


class _FakePage:
    def __init__(self, site_id: uuid.UUID, url: str, **fields) -> None:
        self.id = uuid.uuid4()
        self.site_id = site_id
        self.url = url
        self.content_hash = fields.get("content_hash")
        self.status = fields.get("status", "active")
        self.error_message = fields.get("error_message")
        for k, v in fields.items():
            setattr(self, k, v)


class _FakeSession:
    """Sólo necesita get(HubWebSite, id) + flush()."""

    def __init__(self, site: _FakeSite) -> None:
        self._site = site

    async def get(self, model, ident):
        return self._site if ident == self._site.id else None

    async def flush(self) -> None:
        return None


class _FakePageRepo:
    """In-memory upsert keyed por (site_id, url)."""

    def __init__(self, existing: list[_FakePage] | None = None) -> None:
        self.pages: dict[tuple[uuid.UUID, str], _FakePage] = {}
        for p in existing or []:
            self.pages[(p.site_id, p.url)] = p

    async def upsert(self, *, site_id, url, **fields):
        key = (site_id, url)
        existing = self.pages.get(key)
        if existing is not None:
            for k, v in fields.items():
                setattr(existing, k, v)
            return existing
        page = _FakePage(site_id, url, **fields)
        self.pages[key] = page
        return page

    async def list_by_site(self, site_id, status=None):
        out = [p for p in self.pages.values() if p.site_id == site_id]
        if status is not None:
            out = [p for p in out if p.status == status]
        return out

    async def mark_gone(self, page_ids):
        n = 0
        ids = set(page_ids)
        for p in self.pages.values():
            if p.id in ids:
                p.status = "gone"
                n += 1
        return n


class _FakeSpider:
    """Devuelve crawled_urls fijos y _fetch desde un dict de cuerpos."""

    def __init__(self, crawled_urls: list[str], bodies: dict[str, str],
                 headers: dict[str, dict] | None = None,
                 fetch_errors: dict[str, Exception] | None = None) -> None:
        self._crawled_urls = crawled_urls
        self._bodies = bodies
        self._headers = headers or {}
        self._fetch_errors = fetch_errors or {}

    async def crawl(self, source):
        from server.app.modules.curation.spider import CrawlResult, CrawlStatus

        return CrawlResult(
            crawled_urls=list(self._crawled_urls),
            pages_crawled=len(self._crawled_urls),
            pages_skipped=0,
            status=CrawlStatus.COMPLETED,
        )

    async def _fetch(self, url: str) -> tuple[str, dict]:
        if url in self._fetch_errors:
            raise self._fetch_errors[url]
        return self._bodies.get(url, "<html></html>"), self._headers.get(url, {})


class _FakeSignals:
    """Señales triviales; sitemap inyectado directamente."""

    def __init__(self, sitemap: dict | None = None) -> None:
        self._sitemap = sitemap or {}

    def extract_from_headers(self, headers):
        return {
            "http_last_modified": headers.get("_lm"),
            "http_etag": headers.get("ETag"),
        }

    def extract_canonical(self, html):
        return None

    def extract_content_year(self, url, text):
        return None

    async def fetch_sitemap(self, url, fetch_fn):
        return dict(self._sitemap)


def _make_crawler(site, page_repo, spider, signals):
    from server.app.modules.curation.site_crawler import SiteCrawler

    return SiteCrawler(
        session=_FakeSession(site),
        spider=spider,
        signal_extractor=signals,
        page_repo=page_repo,
    )


# ───────────────────────── Tests ─────────────────────────


class TestSiteCrawlerHappyPath:

    @pytest.mark.asyncio
    async def test_upserts_pages_with_content_and_signals(self) -> None:
        site = _FakeSite("https://uji.es")
        bodies = {
            "https://uji.es/a": "<html><body>Contenido A en español, informativo.</body></html>",
            "https://uji.es/b": "<html><body>Contenido B en español, informativo.</body></html>",
        }
        spider = _FakeSpider(
            crawled_urls=["https://uji.es/a", "https://uji.es/b"],
            bodies=bodies,
            headers={"https://uji.es/a": {"ETag": '"a1"'}},
        )
        page_repo = _FakePageRepo()
        crawler = _make_crawler(site, page_repo, spider, _FakeSignals())

        summary = await crawler.crawl_site(site.id)

        assert summary.pages_total == 2
        assert summary.pages_new == 2
        assert summary.pages_changed == 0
        assert summary.pages_gone == 0
        assert summary.pages_error == 0

        page_a = page_repo.pages[(site.id, "https://uji.es/a")]
        # RAS.2 — de una página HTML se guarda su texto, no su marcado: con el marcado dentro,
        # `token_count` medía plantillas y al corpus llegaban `<div>`. El hash sigue siendo del
        # cuerpo servido, que es lo que permite detectar que la página cambió.
        assert page_a.markdown_content == "Contenido A en español, informativo."
        assert page_a.content_hash == hash_content(bodies["https://uji.es/a"])
        assert page_a.http_etag == '"a1"'
        assert page_a.status == "active"
        assert page_a.last_crawled_at is not None

    @pytest.mark.asyncio
    async def test_includes_sitemap_only_urls_in_target_set(self) -> None:
        site = _FakeSite("https://uji.es", sitemap_url="https://uji.es/sitemap.xml")
        spider = _FakeSpider(
            crawled_urls=["https://uji.es/a"],
            bodies={
                "https://uji.es/a": "<html>a</html>",
                "https://uji.es/from-sitemap": "<html>sm</html>",
            },
        )
        signals = _FakeSignals(sitemap={"https://uji.es/from-sitemap": None})
        page_repo = _FakePageRepo()
        crawler = _make_crawler(site, page_repo, spider, signals)

        summary = await crawler.crawl_site(site.id)

        assert summary.pages_total == 2
        assert (site.id, "https://uji.es/from-sitemap") in page_repo.pages

    @pytest.mark.asyncio
    async def test_writes_sitemap_lastmod_signal(self) -> None:
        site = _FakeSite("https://uji.es")
        lm = datetime(2024, 5, 1, tzinfo=timezone.utc)
        spider = _FakeSpider(
            crawled_urls=["https://uji.es/a"],
            bodies={"https://uji.es/a": "<html>a</html>"},
        )
        signals = _FakeSignals(sitemap={"https://uji.es/a": lm})
        page_repo = _FakePageRepo()
        crawler = _make_crawler(site, page_repo, spider, signals)

        await crawler.crawl_site(site.id)

        page = page_repo.pages[(site.id, "https://uji.es/a")]
        assert page.sitemap_lastmod == lm

    @pytest.mark.asyncio
    async def test_updates_site_last_crawled_at(self) -> None:
        site = _FakeSite("https://uji.es")
        spider = _FakeSpider(["https://uji.es/a"], {"https://uji.es/a": "<html>a</html>"})
        crawler = _make_crawler(site, _FakePageRepo(), spider, _FakeSignals())

        await crawler.crawl_site(site.id)

        assert site.last_crawled_at is not None
        assert site.status == "active"


class TestSiteCrawlerIdempotency:

    @pytest.mark.asyncio
    async def test_second_crawl_is_idempotent(self) -> None:
        site = _FakeSite("https://uji.es")
        spider = _FakeSpider(
            ["https://uji.es/a"],
            {"https://uji.es/a": "<html>contenido estable</html>"},
        )
        page_repo = _FakePageRepo()
        crawler = _make_crawler(site, page_repo, spider, _FakeSignals())

        first = await crawler.crawl_site(site.id)
        page_id_first = page_repo.pages[(site.id, "https://uji.es/a")].id

        second = await crawler.crawl_site(site.id)
        page_id_second = page_repo.pages[(site.id, "https://uji.es/a")].id

        assert first.pages_new == 1
        assert second.pages_new == 0
        assert second.pages_changed == 0
        assert page_id_first == page_id_second
        assert len(page_repo.pages) == 1


class TestSiteCrawlerDiff:

    @pytest.mark.asyncio
    async def test_new_url_counts_as_new(self) -> None:
        site = _FakeSite("https://uji.es")
        existing = _FakePage(
            site.id, "https://uji.es/old",
            content_hash=hash_content("<html>old</html>"), status="active",
        )
        page_repo = _FakePageRepo(existing=[existing])
        spider = _FakeSpider(
            ["https://uji.es/old", "https://uji.es/new"],
            {
                "https://uji.es/old": "<html>old</html>",
                "https://uji.es/new": "<html>new</html>",
            },
        )
        crawler = _make_crawler(site, page_repo, spider, _FakeSignals())

        summary = await crawler.crawl_site(site.id)

        assert summary.pages_new == 1
        assert summary.pages_changed == 0
        assert summary.pages_gone == 0

    @pytest.mark.asyncio
    async def test_changed_content_hash_counts_as_changed(self) -> None:
        site = _FakeSite("https://uji.es")
        existing = _FakePage(
            site.id, "https://uji.es/p",
            content_hash=hash_content("<html>v1</html>"), status="active",
        )
        page_repo = _FakePageRepo(existing=[existing])
        spider = _FakeSpider(
            ["https://uji.es/p"],
            {"https://uji.es/p": "<html>v2 distinto</html>"},
        )
        crawler = _make_crawler(site, page_repo, spider, _FakeSignals())

        summary = await crawler.crawl_site(site.id)

        assert summary.pages_new == 0
        assert summary.pages_changed == 1
        assert summary.pages_gone == 0

    @pytest.mark.asyncio
    async def test_disappeared_url_marked_gone(self) -> None:
        site = _FakeSite("https://uji.es")
        existing = _FakePage(
            site.id, "https://uji.es/desaparecida",
            content_hash=hash_content("x"), status="active",
        )
        page_repo = _FakePageRepo(existing=[existing])
        spider = _FakeSpider(
            ["https://uji.es/sigue"],
            {"https://uji.es/sigue": "<html>sigue</html>"},
        )
        crawler = _make_crawler(site, page_repo, spider, _FakeSignals())

        summary = await crawler.crawl_site(site.id)

        assert summary.pages_gone == 1
        assert page_repo.pages[(site.id, "https://uji.es/desaparecida")].status == "gone"

    @pytest.mark.asyncio
    async def test_unchanged_page_not_counted_as_new_or_changed(self) -> None:
        site = _FakeSite("https://uji.es")
        body = "<html>idéntico</html>"
        existing = _FakePage(
            site.id, "https://uji.es/p",
            content_hash=hash_content(body), status="active",
        )
        page_repo = _FakePageRepo(existing=[existing])
        spider = _FakeSpider(["https://uji.es/p"], {"https://uji.es/p": body})
        crawler = _make_crawler(site, page_repo, spider, _FakeSignals())

        summary = await crawler.crawl_site(site.id)

        assert summary.pages_new == 0
        assert summary.pages_changed == 0
        assert summary.pages_gone == 0


class TestSiteCrawlerErrorHandling:

    @pytest.mark.asyncio
    async def test_page_fetch_error_does_not_abort_crawl(self) -> None:
        site = _FakeSite("https://uji.es")
        spider = _FakeSpider(
            ["https://uji.es/ok", "https://uji.es/boom"],
            {"https://uji.es/ok": "<html>ok</html>"},
            fetch_errors={"https://uji.es/boom": RuntimeError("500 Server Error")},
        )
        page_repo = _FakePageRepo()
        crawler = _make_crawler(site, page_repo, spider, _FakeSignals())

        summary = await crawler.crawl_site(site.id)

        assert summary.pages_error == 1
        assert summary.pages_total == 2
        boom = page_repo.pages[(site.id, "https://uji.es/boom")]
        assert boom.status == "error"
        assert "500 Server Error" in (boom.error_message or "")
        # la página buena sigue procesándose
        assert page_repo.pages[(site.id, "https://uji.es/ok")].status == "active"

    @pytest.mark.asyncio
    async def test_global_crawl_failure_marks_site_error(self) -> None:
        site = _FakeSite("https://uji.es")

        class _ExplodingSpider(_FakeSpider):
            async def crawl(self, source):
                raise RuntimeError("DNS resolution failed")

        spider = _ExplodingSpider([], {})
        page_repo = _FakePageRepo()
        crawler = _make_crawler(site, page_repo, spider, _FakeSignals())

        summary = await crawler.crawl_site(site.id)

        assert site.status == "error"
        assert "DNS resolution failed" in (site.error_message or "")
        assert summary.pages_total == 0
        assert summary.errors
