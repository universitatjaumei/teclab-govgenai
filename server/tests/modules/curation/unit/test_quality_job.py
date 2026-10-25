"""Tests TDD — SiteQualityAnalysisJob y scheduler (Prompt 9Q.5).

Job asíncrono por sitio: crawl + detección + consolidación de flags
(superseded/quality_score) + auto-ingesta de páginas nuevas. Scheduler
filtra sitios cuyo crawl_interval_hours ha vencido.

Fakes en memoria: sin BD ni LLM real.
"""
from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

NOW = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)


# ───────────────────────── Fakes ─────────────────────────


@dataclass
class _FakeSiteCrawlSummary:
    pages_new: int = 0
    pages_changed: int = 0
    pages_gone: int = 0
    pages_error: int = 0
    pages_total: int = 0
    errors: list[str] = field(default_factory=list)
    new_page_ids: list[uuid.UUID] = field(default_factory=list)
    changed_page_ids: list[uuid.UUID] = field(default_factory=list)
    gone_page_ids: list[uuid.UUID] = field(default_factory=list)


class _FakeSiteCrawler:
    def __init__(self, summary: _FakeSiteCrawlSummary | None = None, raises: Exception | None = None) -> None:
        self._summary = summary or _FakeSiteCrawlSummary()
        self._raises = raises
        self.called_site_ids: list[uuid.UUID] = []

    async def crawl_site(
        self, site_id: uuid.UUID, section_id: uuid.UUID | None = None
    ) -> _FakeSiteCrawlSummary:
        self.called_site_ids.append(site_id)
        if self._raises:
            raise self._raises
        return self._summary


class _FakeFinding:
    def __init__(
        self,
        site_id: uuid.UUID,
        finding_type: str,
        severity: str,
        page_id: uuid.UUID | None = None,
        related_page_id: uuid.UUID | None = None,
        status: str = "new",
    ) -> None:
        self.id = uuid.uuid4()
        self.site_id = site_id
        self.finding_type = finding_type
        self.severity = severity
        self.page_id = page_id
        self.related_page_id = related_page_id
        self.status = status


class _FakeDetector:
    """Detector fake: devuelve findings predefinidos. Opcionalmente es «semántico»."""

    _is_semantic: bool = False

    def __init__(
        self,
        findings: list | None = None,
        raises: Exception | None = None,
        is_semantic: bool = False,
    ) -> None:
        self._findings = findings or []
        self._raises = raises
        self._is_semantic = is_semantic
        self.called_site_ids: list[uuid.UUID] = []

    async def analyze(self, site_id: uuid.UUID) -> list:
        self.called_site_ids.append(site_id)
        if self._raises:
            raise self._raises
        return self._findings


class _FakePage:
    def __init__(self, site_id: uuid.UUID, url: str, **kw: Any) -> None:
        self.id = uuid.uuid4()
        self.site_id = site_id
        self.url = url
        self.markdown_content: str | None = kw.get("markdown_content", f"# {url}")
        self.title: str | None = kw.get("title", url)
        self.superseded: bool = kw.get("superseded", False)
        self.superseded_by_page_id: uuid.UUID | None = kw.get("superseded_by_page_id")
        self.quality_score: float | None = kw.get("quality_score")
        self.status: str = kw.get("status", "active")


class _FakeSession:
    """Soporta get(model, pk) y flush(). Almacena objetos registrados."""

    def __init__(self, pages: dict[uuid.UUID, _FakePage] | None = None) -> None:
        self._pages = pages or {}
        self.confirmada = False

    async def get(self, model: type, pk: uuid.UUID) -> Any:
        # Devolvemos una _FakePage si la clave existe, independientemente del modelo
        return self._pages.get(pk)

    async def execute(self, stmt: Any) -> Any:
        """DIN.4 — el paso de auto-retirada consulta los avisos `page_gone` abiertos. Estos
        tests no siembran ninguno, así que la respuesta es vacía."""

        class _R:
            def scalars(self_inner) -> Any:
                return self_inner

            def all(self_inner) -> list:
                return []

        return _R()

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        """DIN.7 — el job **confirma** su sesión al terminar. No lo hacía, y por eso perdía el
        `quality_score` y las supersesiones que escribe aquí mismo."""
        self.confirmada = True


@asynccontextmanager
async def _make_session_factory(session: _FakeSession):
    yield session


class _FakeSelection:
    def __init__(self, chatbot_id: uuid.UUID, site_id: uuid.UUID, auto_ingest_new: bool = True, rule_prefix: str = "/") -> None:
        self.id = uuid.uuid4()
        self.chatbot_id = chatbot_id
        self.site_id = site_id
        self.auto_ingest_new = auto_ingest_new
        self.rule_type = "path_prefix"
        self.rule_value = rule_prefix


class _FakeSelectionRepo:
    def __init__(self, selections: list[_FakeSelection] | None = None) -> None:
        self._selections = selections or []

    async def list_by_site(self, site_id: uuid.UUID) -> list[_FakeSelection]:
        return [s for s in self._selections if s.site_id == site_id]

    async def secciones_de(self, selections: list) -> dict:
        """DIN.3 — ninguna de estas selecciones apunta a una sección."""
        return {}

    def matches(
        self, selection: _FakeSelection, page_url: str, *, secciones: dict | None = None
    ) -> bool:
        if selection.rule_type == "path_prefix" and selection.rule_value:
            from urllib.parse import urlparse
            return urlparse(page_url).path.startswith(selection.rule_value)
        return False


class _FakeWatcher:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def process_source(
        self,
        source_url: str,
        chatbot_id: uuid.UUID,
        *,
        prefetched_content: str | None = None,
        title: str | None = None,
        crawled_page_id: uuid.UUID | None = None,
    ) -> Any:
        self.calls.append({
            "source_url": source_url,
            "chatbot_id": chatbot_id,
            "crawled_page_id": crawled_page_id,
        })
        return (object(), 1)


class _FakeSiteModel:
    """Fake de HubWebSite para los tests del scheduler."""
    def __init__(
        self,
        crawl_interval_hours: int = 24,
        last_crawled_at: datetime | None = None,
        status: str = "active",
    ) -> None:
        self.id = uuid.uuid4()
        self.crawl_interval_hours = crawl_interval_hours
        self.last_crawled_at = last_crawled_at
        self.status = status


class _FakeSchedulerSession:
    """Responde sitios o secciones según la entidad que pida la consulta (DIN.2)."""

    def __init__(
        self, sites: list[_FakeSiteModel], sections: list | None = None
    ) -> None:
        self._sites = sites
        self._sections = sections or []

    async def execute(self, stmt: Any) -> Any:
        entidad = stmt.column_descriptions[0]["entity"].__name__
        if entidad == "HubWebSection":
            return _FakeSchedulerResult(self._sections)
        return _FakeSchedulerResult(self._sites)


class _FakeSchedulerResult:
    def __init__(self, sites: list) -> None:
        self._sites = sites

    def scalars(self) -> "_FakeScalars":
        return _FakeScalars(self._sites)


class _FakeScalars:
    def __init__(self, items: list) -> None:
        self._items = items

    def all(self) -> list:
        return self._items


# ───────────────────────── Helpers de construcción ─────────────────────────


def _make_job(
    *,
    crawler: _FakeSiteCrawler | None = None,
    detectors: list | None = None,
    watcher: _FakeWatcher | None = None,
    selection_repo: _FakeSelectionRepo | None = None,
    pages: dict[uuid.UUID, _FakePage] | None = None,
    run_semantic: bool = True,
):
    from server.app.modules.curation.quality_job import SiteQualityAnalysisJob

    session = _FakeSession(pages or {})

    @asynccontextmanager
    async def _session_factory():
        yield session

    return SiteQualityAnalysisJob(
        session_factory=_session_factory,
        site_crawler=crawler or _FakeSiteCrawler(),
        detectors=detectors or [],
        watcher=watcher or _FakeWatcher(),
        selection_repo=selection_repo or _FakeSelectionRepo(),
        run_semantic=run_semantic,
    ), session


# ───────────────────────── Tests del job ─────────────────────────


@pytest.mark.asyncio
async def test_run_for_site_chains_crawl_and_detectors():
    """run_for_site llama al crawl y a ambos detectores; el summary agrega sus resultados."""
    site_id = uuid.uuid4()
    page_id = uuid.uuid4()

    crawl_summary = _FakeSiteCrawlSummary(pages_new=1, pages_total=1)
    crawler = _FakeSiteCrawler(crawl_summary)

    finding = _FakeFinding(site_id, "stale", "info", page_id=page_id)
    det1 = _FakeDetector(findings=[finding])
    det2 = _FakeDetector(findings=[], is_semantic=True)

    job, _ = _make_job(crawler=crawler, detectors=[det1, det2])
    summary = await job.run_for_site(site_id)

    assert crawler.called_site_ids == [site_id]
    assert det1.called_site_ids == [site_id]
    assert det2.called_site_ids == [site_id]
    assert summary.pages_new == 1
    assert summary.findings_by_type.get("stale", 0) == 1
    assert summary.errors == []


@pytest.mark.asyncio
async def test_semantic_detector_failure_does_not_block_deterministic():
    """Fallo del detector semántico no impide consolidación del determinista."""
    site_id = uuid.uuid4()
    page_id = uuid.uuid4()
    vigente_id = uuid.uuid4()

    page = _FakePage(site_id, "https://ejemplo.es/proc/2022/x")
    page.id = page_id

    crawl_summary = _FakeSiteCrawlSummary()
    crawler = _FakeSiteCrawler(crawl_summary)

    det_finding = _FakeFinding(
        site_id, "superseded", "warning",
        page_id=page_id, related_page_id=vigente_id,
    )
    det = _FakeDetector(findings=[det_finding])
    sem = _FakeDetector(raises=RuntimeError("LLM down"), is_semantic=True)

    job, session = _make_job(
        crawler=crawler,
        detectors=[det, sem],
        pages={page_id: page},
    )
    summary = await job.run_for_site(site_id)

    # El error semántico queda en summary.errors pero no tumba el job
    assert any("detector" in e for e in summary.errors)
    # La consolidación del hallazgo determinista se aplicó
    assert page.superseded is True
    assert page.superseded_by_page_id == vigente_id
    assert summary.pages_marked_superseded == 1


@pytest.mark.asyncio
async def test_consolidation_sets_superseded_flag():
    """Consolidación fija superseded=True + superseded_by_page_id en la página antigua."""
    site_id = uuid.uuid4()
    old_id = uuid.uuid4()
    new_id = uuid.uuid4()

    old_page = _FakePage(site_id, "https://ej.es/proc/2022/res", superseded=False)
    old_page.id = old_id

    finding = _FakeFinding(
        site_id, "superseded", "warning",
        page_id=old_id, related_page_id=new_id,
    )
    det = _FakeDetector(findings=[finding])

    job, session = _make_job(detectors=[det], pages={old_id: old_page})
    summary = await job.run_for_site(site_id)

    assert old_page.superseded is True
    assert old_page.superseded_by_page_id == new_id
    assert summary.pages_marked_superseded == 1


@pytest.mark.asyncio
async def test_auto_ingest_on_new_matching_page():
    """Página nueva que casa una selección auto_ingest → watcher invocado con crawled_page_id."""
    site_id = uuid.uuid4()
    chatbot_id = uuid.uuid4()
    page_id = uuid.uuid4()

    page = _FakePage(site_id, "https://ej.es/temas/residuos")
    page.id = page_id

    crawl_summary = _FakeSiteCrawlSummary(pages_new=1, new_page_ids=[page_id])
    crawler = _FakeSiteCrawler(crawl_summary)

    selection = _FakeSelection(chatbot_id, site_id, auto_ingest_new=True, rule_prefix="/temas/")
    sel_repo = _FakeSelectionRepo([selection])
    watcher = _FakeWatcher()

    job, _ = _make_job(
        crawler=crawler,
        watcher=watcher,
        selection_repo=sel_repo,
        pages={page_id: page},
    )
    summary = await job.run_for_site(site_id)

    assert len(watcher.calls) == 1
    call = watcher.calls[0]
    assert call["chatbot_id"] == chatbot_id
    assert call["crawled_page_id"] == page_id
    assert call["source_url"] == "https://ej.es/temas/residuos"
    assert summary.documents_auto_ingested == 1


@pytest.mark.asyncio
async def test_no_auto_ingest_without_matching_selection():
    """Página nueva sin selección que case → NO se ingiere (candidata para 9Q.7)."""
    site_id = uuid.uuid4()
    chatbot_id = uuid.uuid4()
    page_id = uuid.uuid4()

    page = _FakePage(site_id, "https://ej.es/tramites/licencia")
    page.id = page_id

    crawl_summary = _FakeSiteCrawlSummary(pages_new=1, new_page_ids=[page_id])
    crawler = _FakeSiteCrawler(crawl_summary)

    # Selección para /temas/ no casa /tramites/
    selection = _FakeSelection(chatbot_id, site_id, auto_ingest_new=True, rule_prefix="/temas/")
    sel_repo = _FakeSelectionRepo([selection])
    watcher = _FakeWatcher()

    job, _ = _make_job(
        crawler=crawler,
        watcher=watcher,
        selection_repo=sel_repo,
        pages={page_id: page},
    )
    summary = await job.run_for_site(site_id)

    assert watcher.calls == []
    assert summary.documents_auto_ingested == 0


@pytest.mark.asyncio
async def test_quality_score_decreases_with_critical_findings():
    """quality_score se reduce con findings críticos; con warnings baja menos."""
    site_id = uuid.uuid4()
    page_id = uuid.uuid4()

    page = _FakePage(site_id, "https://ej.es/tramites/licencia")
    page.id = page_id

    critical = _FakeFinding(site_id, "empty", "critical", page_id=page_id)
    warning = _FakeFinding(site_id, "thin", "warning", page_id=page_id)
    det = _FakeDetector(findings=[critical, warning])

    job, session = _make_job(detectors=[det], pages={page_id: page})
    await job.run_for_site(site_id)

    # 1.0 - 0.5 (critical) - 0.2 (warning) = 0.3
    assert page.quality_score is not None
    assert abs(page.quality_score - 0.3) < 0.01


@pytest.mark.asyncio
async def test_run_semantic_false_skips_semantic_detector():
    """run_semantic=False no llama al detector semántico."""
    site_id = uuid.uuid4()

    det = _FakeDetector(findings=[])
    sem = _FakeDetector(findings=[], is_semantic=True)

    job, _ = _make_job(detectors=[det, sem], run_semantic=False)
    await job.run_for_site(site_id)

    assert det.called_site_ids == [site_id]
    assert sem.called_site_ids == []


@pytest.mark.asyncio
async def test_run_for_site_crawl_failure_returns_errors():
    """Si el crawl falla, summary.errors contiene el mensaje y no se ejecutan detectores."""
    site_id = uuid.uuid4()

    crawler = _FakeSiteCrawler(raises=RuntimeError("Connection refused"))
    det = _FakeDetector(findings=[])

    job, _ = _make_job(crawler=crawler, detectors=[det])
    summary = await job.run_for_site(site_id)

    assert any("crawl" in e for e in summary.errors)
    # Detectores no se llaman si el crawl falla
    assert det.called_site_ids == []


@pytest.mark.asyncio
async def test_scheduler_get_due_sites_by_interval():
    """Un sitio sin secciones vence por su `crawl_interval_hours`, como siempre.

    DIN.2 sustituyó `_get_due_sites` por `_get_due_scopes`, que devuelve **ámbitos**: un sitio
    sin secciones sigue siendo uno de ellos, y ése es el caso de este test.
    """
    from server.app.modules.curation.quality_scheduler import _get_due_scopes

    site_due = _FakeSiteModel(
        crawl_interval_hours=24,
        last_crawled_at=NOW - timedelta(hours=25),
    )
    site_not_due = _FakeSiteModel(
        crawl_interval_hours=24,
        last_crawled_at=NOW - timedelta(hours=10),
    )
    session = _FakeSchedulerSession([site_due, site_not_due])

    due = await _get_due_scopes(session, NOW)

    assert [a.site for a in due] == [site_due]
    assert due[0].section_id is None


@pytest.mark.asyncio
async def test_scheduler_get_due_sites_never_crawled():
    """Un sitio nunca rastreado (last_crawled_at=None) vence."""
    from server.app.modules.curation.quality_scheduler import _get_due_scopes

    site_new = _FakeSiteModel(crawl_interval_hours=24, last_crawled_at=None)
    session = _FakeSchedulerSession([site_new])

    due = await _get_due_scopes(session, NOW)

    assert [a.site for a in due] == [site_new]


@pytest.mark.asyncio
async def test_idempotency_no_new_pages_no_auto_ingest():
    """Segunda ejecución sin páginas nuevas no lanza auto-ingesta."""
    site_id = uuid.uuid4()
    chatbot_id = uuid.uuid4()

    # No new pages in second run
    crawl_summary = _FakeSiteCrawlSummary(pages_new=0, new_page_ids=[])
    crawler = _FakeSiteCrawler(crawl_summary)

    selection = _FakeSelection(chatbot_id, site_id, auto_ingest_new=True, rule_prefix="/")
    sel_repo = _FakeSelectionRepo([selection])
    watcher = _FakeWatcher()

    job, _ = _make_job(crawler=crawler, watcher=watcher, selection_repo=sel_repo)
    summary = await job.run_for_site(site_id)

    assert watcher.calls == []
    assert summary.documents_auto_ingested == 0
    assert summary.errors == []


@pytest.mark.asyncio
async def test_quality_score_min_clamped_at_zero():
    """quality_score nunca baja de 0.0 aunque los findings acumulen más de 1.0 de penalización."""
    site_id = uuid.uuid4()
    page_id = uuid.uuid4()

    page = _FakePage(site_id, "https://ej.es/vacio")
    page.id = page_id

    findings = [
        _FakeFinding(site_id, "empty", "critical", page_id=page_id),
        _FakeFinding(site_id, "crawl_error", "critical", page_id=page_id),
        _FakeFinding(site_id, "thin", "warning", page_id=page_id),
    ]
    det = _FakeDetector(findings=findings)

    job, session = _make_job(detectors=[det], pages={page_id: page})
    await job.run_for_site(site_id)

    assert page.quality_score is not None
    assert page.quality_score >= 0.0


@pytest.mark.asyncio
async def test_auto_ingest_disabled_selection_not_called():
    """Selección con auto_ingest_new=False → watcher NO se invoca aunque la regla case."""
    site_id = uuid.uuid4()
    chatbot_id = uuid.uuid4()
    page_id = uuid.uuid4()

    page = _FakePage(site_id, "https://ej.es/temas/agua")
    page.id = page_id

    crawl_summary = _FakeSiteCrawlSummary(pages_new=1, new_page_ids=[page_id])
    crawler = _FakeSiteCrawler(crawl_summary)

    selection = _FakeSelection(
        chatbot_id, site_id, auto_ingest_new=False, rule_prefix="/temas/"
    )
    sel_repo = _FakeSelectionRepo([selection])
    watcher = _FakeWatcher()

    job, _ = _make_job(
        crawler=crawler, watcher=watcher, selection_repo=sel_repo, pages={page_id: page}
    )
    summary = await job.run_for_site(site_id)

    assert watcher.calls == []
    assert summary.documents_auto_ingested == 0
