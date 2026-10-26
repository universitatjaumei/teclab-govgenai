"""Tests TDD — DeterministicQualityDetector (Prompt 9Q.3).

Detector determinista site-scoped: vacías, finas, stale, error de crawl,
huérfanas y supersesión por URL+fecha. Sin LLM, sin coste por llamada.

Fakes en memoria: no requieren BD.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

# ───────────────────────── Fakes ─────────────────────────

NOW = datetime(2026, 6, 2, 12, 0, 0, tzinfo=timezone.utc)


def _date(year: int, month: int = 1, day: int = 1) -> datetime:
    return datetime(year, month, day, tzinfo=timezone.utc)


class _FakePage:
    def __init__(self, site_id: uuid.UUID, url: str, **fields: Any) -> None:
        self.id = uuid.uuid4()
        self.site_id = site_id
        self.url = url
        self.canonical_url: str | None = fields.get("canonical_url", url)
        self.markdown_content: str | None = fields.get("markdown_content", "# Hola\n\n" + "x " * 200)
        self.token_count: int | None = fields.get("token_count", 200)
        self.status: str = fields.get("status", "active")
        self.error_message: str | None = fields.get("error_message")
        self.sitemap_lastmod: datetime | None = fields.get("sitemap_lastmod")
        self.http_last_modified: datetime | None = fields.get("http_last_modified")
        self.content_year: int | None = fields.get("content_year")
        self.first_seen_at: datetime = fields.get("first_seen_at", NOW - timedelta(days=10))


class _FakeDocument:
    def __init__(self, crawled_page_id: uuid.UUID) -> None:
        self.id = uuid.uuid4()
        self.crawled_page_id = crawled_page_id


class _FakeSession:
    """Soporta list_by_site (pages + documents) + flush + scalars."""

    def __init__(
        self,
        pages: list[_FakePage],
        documents: list[_FakeDocument] | None = None,
    ) -> None:
        self._pages = pages
        self._documents = documents or []

    async def execute(self, stmt: Any) -> Any:
        return _FakeResult(stmt, self._pages, self._documents)

    async def flush(self) -> None:
        return None


class _FakeResult:
    def __init__(self, stmt: Any, pages: list, documents: list) -> None:
        self._stmt = stmt
        self._pages = pages
        self._documents = documents

    def scalar_one_or_none(self) -> Any:
        return None  # para upsert: no existe → crea

    def scalars(self) -> "_FakeScalars":
        # El detector distingue por tipo de modelo qué lista devolver
        model = getattr(self._stmt, "_model_hint", None)
        if model == "document":
            return _FakeScalars(self._documents)
        return _FakeScalars(self._pages)

    def all(self) -> list:
        return self._pages


class _FakeScalars:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return list(self._items)


class _FakeFindingRepo:
    """Captura los hallazgos emitidos; simula idempotencia por clave dedup."""

    def __init__(self) -> None:
        self._by_key: dict[tuple, Any] = {}

    def _key(self, finding: Any) -> tuple:

        return (
            finding.site_id,
            finding.finding_type,
            finding.page_id,
            finding.related_page_id,
        )

    async def upsert(self, finding: Any) -> Any:
        self._by_key[self._key(finding)] = finding
        return finding

    @property
    def findings(self) -> list:
        return list(self._by_key.values())

    def of_type(self, t: str) -> list:
        return [f for f in self.findings if f.finding_type == t]


def _make_detector(pages: list[_FakePage], documents: list[_FakeDocument] | None = None, **kwargs: Any):
    from server.app.modules.curation.deterministic_detector import (
        DeterministicQualityDetector,
    )

    session = _FakeSession(pages, documents)
    repo = _FakeFindingRepo()
    detector = DeterministicQualityDetector(session, finding_repo=repo, now_fn=lambda: NOW, **kwargs)
    return detector, repo


# ───────────────────────── Tests: empty / thin ─────────────────────────


class TestEmptyAndThin:
    SITE = uuid.uuid4()

    @pytest.mark.asyncio
    async def test_empty_when_markdown_content_is_none(self) -> None:
        page = _FakePage(self.SITE, "https://u.es/x", markdown_content=None, token_count=0)
        detector, repo = _make_detector([page])
        await detector.analyze(self.SITE)
        assert any(f.finding_type == "empty" and f.page_id == page.id for f in repo.findings)

    @pytest.mark.asyncio
    async def test_empty_when_markdown_content_is_blank_string(self) -> None:
        page = _FakePage(self.SITE, "https://u.es/x", markdown_content="   \n", token_count=0)
        detector, repo = _make_detector([page])
        await detector.analyze(self.SITE)
        assert any(f.finding_type == "empty" for f in repo.findings)

    @pytest.mark.asyncio
    async def test_empty_when_token_count_is_zero(self) -> None:
        page = _FakePage(self.SITE, "https://u.es/x", markdown_content="hola", token_count=0)
        detector, repo = _make_detector([page])
        await detector.analyze(self.SITE)
        assert any(f.finding_type == "empty" for f in repo.findings)

    @pytest.mark.asyncio
    async def test_empty_severity_is_critical(self) -> None:
        page = _FakePage(self.SITE, "https://u.es/x", markdown_content=None, token_count=0)
        detector, repo = _make_detector([page])
        await detector.analyze(self.SITE)
        empties = repo.of_type("empty")
        assert empties
        assert empties[0].severity == "critical"

    @pytest.mark.asyncio
    async def test_thin_below_threshold(self) -> None:
        page = _FakePage(self.SITE, "https://u.es/x", token_count=50)
        detector, repo = _make_detector([page], thin_token_threshold=120)
        await detector.analyze(self.SITE)
        assert any(f.finding_type == "thin" for f in repo.findings)

    @pytest.mark.asyncio
    async def test_thin_at_threshold_not_flagged(self) -> None:
        page = _FakePage(self.SITE, "https://u.es/x", token_count=120)
        detector, repo = _make_detector([page], thin_token_threshold=120)
        await detector.analyze(self.SITE)
        assert not repo.of_type("thin")

    @pytest.mark.asyncio
    async def test_thin_severity_is_warning(self) -> None:
        page = _FakePage(self.SITE, "https://u.es/x", token_count=30)
        detector, repo = _make_detector([page], thin_token_threshold=120)
        await detector.analyze(self.SITE)
        thins = repo.of_type("thin")
        assert thins
        assert thins[0].severity == "warning"


# ───────────────────────── Tests: stale ─────────────────────────


class TestStale:
    SITE = uuid.uuid4()

    @pytest.mark.asyncio
    async def test_stale_by_sitemap_lastmod(self) -> None:
        old = NOW - timedelta(days=400)
        page = _FakePage(self.SITE, "https://u.es/x", sitemap_lastmod=old)
        detector, repo = _make_detector([page], stale_days=365)
        await detector.analyze(self.SITE)
        assert repo.of_type("stale")

    @pytest.mark.asyncio
    async def test_stale_by_http_last_modified(self) -> None:
        old = NOW - timedelta(days=400)
        page = _FakePage(self.SITE, "https://u.es/x", http_last_modified=old)
        detector, repo = _make_detector([page], stale_days=365)
        await detector.analyze(self.SITE)
        assert repo.of_type("stale")

    @pytest.mark.asyncio
    async def test_stale_by_content_year_in_the_url(self) -> None:
        # RAS.5 — el año tiene que estar **en la URL**. Cuando bastaba con que estuviera en el
        # texto, el primer rastreo real marcó 303 de 400 páginas: el portal no declara ninguna
        # fecha y la «fecha del contenido» salía del año más reciente citado en el cuerpo.
        page = _FakePage(self.SITE, "https://u.es/x/2020/", content_year=2020)
        detector, repo = _make_detector([page], stale_days=365)
        await detector.analyze(self.SITE)
        assert repo.of_type("stale")

    @pytest.mark.asyncio
    async def test_a_year_only_mentioned_in_the_text_is_not_a_date(self) -> None:
        page = _FakePage(self.SITE, "https://u.es/x", content_year=2020)
        detector, repo = _make_detector([page], stale_days=365)
        await detector.analyze(self.SITE)
        assert not repo.of_type("stale")

    @pytest.mark.asyncio
    async def test_recent_signal_not_stale(self) -> None:
        recent = NOW - timedelta(days=30)
        page = _FakePage(self.SITE, "https://u.es/x", sitemap_lastmod=recent)
        detector, repo = _make_detector([page], stale_days=365)
        await detector.analyze(self.SITE)
        assert not repo.of_type("stale")

    @pytest.mark.asyncio
    async def test_all_signals_none_skips_stale(self) -> None:
        """Si las tres señales de contenido son None, NO se evalúa stale."""
        page = _FakePage(
            self.SITE, "https://u.es/x",
            sitemap_lastmod=None,
            http_last_modified=None,
            content_year=None,
        )
        detector, repo = _make_detector([page], stale_days=365)
        await detector.analyze(self.SITE)
        assert not repo.of_type("stale")

    @pytest.mark.asyncio
    async def test_stale_signal_included_in_signal_dict(self) -> None:
        old = NOW - timedelta(days=400)
        page = _FakePage(self.SITE, "https://u.es/x", sitemap_lastmod=old)
        detector, repo = _make_detector([page], stale_days=365)
        await detector.analyze(self.SITE)
        stale = repo.of_type("stale")
        assert stale
        assert "date" in stale[0].signal

    @pytest.mark.asyncio
    async def test_stale_severity_is_info(self) -> None:
        old = NOW - timedelta(days=400)
        page = _FakePage(self.SITE, "https://u.es/x", sitemap_lastmod=old)
        detector, repo = _make_detector([page], stale_days=365)
        await detector.analyze(self.SITE)
        assert repo.of_type("stale")[0].severity == "info"


# ───────────────────────── Tests: crawl_error ─────────────────────────


class TestCrawlError:
    SITE = uuid.uuid4()

    @pytest.mark.asyncio
    async def test_crawl_error_from_page_status(self) -> None:
        page = _FakePage(
            self.SITE, "https://u.es/boom",
            status="error", error_message="404 Not Found",
        )
        detector, repo = _make_detector([page])
        await detector.analyze(self.SITE)
        errs = repo.of_type("crawl_error")
        assert errs
        assert errs[0].severity == "critical"
        assert errs[0].page_id == page.id

    @pytest.mark.asyncio
    async def test_active_page_no_crawl_error(self) -> None:
        page = _FakePage(self.SITE, "https://u.es/ok", status="active")
        detector, repo = _make_detector([page])
        await detector.analyze(self.SITE)
        assert not repo.of_type("crawl_error")


# ───────────────────────── Tests: orphan_page ─────────────────────────


class TestOrphanPage:
    SITE = uuid.uuid4()

    @pytest.mark.asyncio
    async def test_gone_page_with_document_is_orphan(self) -> None:
        page = _FakePage(self.SITE, "https://u.es/gone", status="gone")
        doc = _FakeDocument(crawled_page_id=page.id)
        detector, repo = _make_detector([page], documents=[doc])
        await detector.analyze(self.SITE)
        orphans = repo.of_type("orphan_page")
        assert orphans
        assert orphans[0].page_id == page.id
        assert orphans[0].severity == "warning"

    @pytest.mark.asyncio
    async def test_gone_page_without_document_not_orphan(self) -> None:
        page = _FakePage(self.SITE, "https://u.es/gone", status="gone")
        detector, repo = _make_detector([page], documents=[])
        await detector.analyze(self.SITE)
        assert not repo.of_type("orphan_page")


# ───────────────────────── Tests: superseded ─────────────────────────


class TestSuperseded:
    SITE = uuid.uuid4()

    @pytest.mark.asyncio
    async def test_three_versions_are_one_series_finding(self) -> None:
        """CUR.2 — tres versiones por año dan **un** hallazgo de serie, no dos acusaciones.

        Decía «2 superseded». Lo cambió un dato del dominio que aportó el usuario: el portal
        publica acuerdos y actas por año y **todos siguen vigentes**, así que decir que la de 2022
        está «superada» por la de 2024 es falso. Lo cierto es que la serie existe.
        """
        pages = [
            _FakePage(
                self.SITE, f"https://u.es/proc/{yr}/x",
                canonical_url=f"https://u.es/proc/{yr}/x",
                content_year=yr,
            )
            for yr in [2022, 2023, 2024]
        ]
        detector, repo = _make_detector(pages)
        await detector.analyze(self.SITE)

        series = repo.of_type("version_series")
        assert len(series) == 1
        assert series[0].severity == "info"
        assert series[0].signal["count"] == 3
        # La más reciente primero: es la que alguien va a querer mirar.
        assert series[0].signal["versions"][0]["url"].endswith("/2024/x")
        assert repo.of_type("superseded") == []

    @pytest.mark.asyncio
    async def test_year_in_path_groups_correctly(self) -> None:
        """'/proc/2023/x' y '/proc/2024/x' agrupan en una serie; '/proc/x' y '/otro/x' no."""
        pages = [
            _FakePage(self.SITE, "https://u.es/proc/2023/x",
                      canonical_url="https://u.es/proc/2023/x", content_year=2023),
            _FakePage(self.SITE, "https://u.es/proc/2024/x",
                      canonical_url="https://u.es/proc/2024/x", content_year=2024),
            _FakePage(self.SITE, "https://u.es/proc/x",
                      canonical_url="https://u.es/proc/x", content_year=2024),
            _FakePage(self.SITE, "https://u.es/otro/x",
                      canonical_url="https://u.es/otro/x", content_year=2024),
        ]
        detector, repo = _make_detector(pages)
        await detector.analyze(self.SITE)

        series = repo.of_type("version_series")
        assert len(series) == 1
        assert series[0].signal["count"] == 2
        agrupadas = {v["url"] for v in series[0].signal["versions"]}
        assert agrupadas == {"https://u.es/proc/2023/x", "https://u.es/proc/2024/x"}

    @pytest.mark.asyncio
    async def test_single_page_group_not_superseded(self) -> None:
        page = _FakePage(self.SITE, "https://u.es/unica/2024/a",
                         canonical_url="https://u.es/unica/2024/a", content_year=2024)
        detector, repo = _make_detector([page])
        await detector.analyze(self.SITE)
        assert not repo.of_type("superseded")

    @pytest.mark.asyncio
    async def test_superseded_does_not_mutate_hub_crawled_page(self) -> None:
        """El detector solo emite hallazgos; NO muta HubCrawledPage.superseded."""
        pages = [
            _FakePage(self.SITE, f"https://u.es/p/{yr}/x",
                      canonical_url=f"https://u.es/p/{yr}/x", content_year=yr)
            for yr in [2023, 2024]
        ]
        detector, repo = _make_detector(pages)
        await detector.analyze(self.SITE)
        for p in pages:
            assert not getattr(p, "superseded", False)


# ───────────────────────── Tests: idempotencia ─────────────────────────


class TestIdempotency:
    SITE = uuid.uuid4()

    @pytest.mark.asyncio
    async def test_second_run_does_not_duplicate_findings(self) -> None:
        page = _FakePage(self.SITE, "https://u.es/x", markdown_content=None, token_count=0)
        detector, repo = _make_detector([page])
        await detector.analyze(self.SITE)
        n1 = len(repo.findings)
        await detector.analyze(self.SITE)
        n2 = len(repo.findings)
        assert n1 == n2 == 1
