"""Tests TDD — Contratos de hallazgos + HubContentFinding + repo (Prompt 9Q.1)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest


_SITE_ID = uuid.uuid4()
_PAGE_ID = uuid.uuid4()
_NOW = datetime.now(timezone.utc)


def _make_finding(**overrides):
    from server.app.modules.curation.contracts import ContentFinding

    defaults = dict(
        id=uuid.uuid4(),
        site_id=_SITE_ID,
        finding_type="stale",
        severity="warning",
        confidence=0.8,
        detected_at=_NOW,
    )
    defaults.update(overrides)
    return ContentFinding(**defaults)


# ---------------------------------------------------------------------------
# Contract — frozen + validation
# ---------------------------------------------------------------------------


class TestContentFindingContract:

    def test_content_finding_is_frozen(self) -> None:

        finding = _make_finding()
        with pytest.raises(ValueError, match="frozen"):
            finding.status = "confirmed"  # type: ignore[misc]

    def test_confidence_accepts_zero(self) -> None:
        finding = _make_finding(confidence=0.0)
        assert finding.confidence == 0.0

    def test_confidence_accepts_one(self) -> None:
        finding = _make_finding(confidence=1.0)
        assert finding.confidence == 1.0

    def test_confidence_rejects_below_zero(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_finding(confidence=-0.01)

    def test_confidence_rejects_above_one(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            _make_finding(confidence=1.01)

    def test_all_finding_types_accepted(self) -> None:

        types = [
            "superseded", "duplicate", "contradiction", "empty",
            "thin", "stale", "crawl_error", "orphan_page",
        ]
        for ft in types:
            f = _make_finding(finding_type=ft)
            assert f.finding_type == ft

    def test_optional_fields_default_none(self) -> None:
        finding = _make_finding()
        assert finding.page_id is None
        assert finding.related_page_id is None
        assert finding.reviewed_at is None
        assert finding.reviewed_by is None
        assert finding.resolution_note is None


# ---------------------------------------------------------------------------
# Contract — valid transitions
# ---------------------------------------------------------------------------


class TestFindingTransitions:

    def test_new_can_go_to_confirmed_or_dismissed(self) -> None:
        from server.app.modules.curation.contracts import (
            _VALID_FINDING_TRANSITIONS,
        )

        assert _VALID_FINDING_TRANSITIONS["new"] == {"confirmed", "dismissed"}

    def test_confirmed_can_go_to_resolved_or_dismissed(self) -> None:
        from server.app.modules.curation.contracts import (
            _VALID_FINDING_TRANSITIONS,
        )

        assert _VALID_FINDING_TRANSITIONS["confirmed"] == {"resolved", "dismissed"}

    def test_dismissed_can_go_back_to_new(self) -> None:
        from server.app.modules.curation.contracts import (
            _VALID_FINDING_TRANSITIONS,
        )

        assert _VALID_FINDING_TRANSITIONS["dismissed"] == {"new"}

    def test_resolved_is_terminal(self) -> None:
        from server.app.modules.curation.contracts import (
            _VALID_FINDING_TRANSITIONS,
        )

        assert _VALID_FINDING_TRANSITIONS["resolved"] == set()

    def test_invalid_transition_new_to_resolved_not_allowed(self) -> None:
        from server.app.modules.curation.contracts import (
            _VALID_FINDING_TRANSITIONS,
        )

        assert "resolved" not in _VALID_FINDING_TRANSITIONS["new"]


# ---------------------------------------------------------------------------
# ORM model inspection (no BD needed)
# ---------------------------------------------------------------------------


class TestHubContentFindingModel:

    def test_site_fk_has_cascade_delete(self) -> None:
        from server.app.modules.agents_hub.database.operational_models import HubContentFinding
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(HubContentFinding)
        site_col = mapper.columns["site_id"]
        fks = list(site_col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].ondelete == "CASCADE"

    def test_page_fk_has_set_null_on_delete(self) -> None:
        from server.app.modules.agents_hub.database.operational_models import HubContentFinding
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(HubContentFinding)
        page_col = mapper.columns["page_id"]
        fks = list(page_col.foreign_keys)
        assert len(fks) == 1
        assert fks[0].ondelete == "SET NULL"

    def test_uq_finding_dedup_constraint_defined(self) -> None:
        from server.app.modules.agents_hub.database.operational_models import HubContentFinding

        constraint_names = {
            c.name
            for c in HubContentFinding.__table__.constraints
        }
        assert "uq_finding_dedup" in constraint_names

    def test_status_has_index(self) -> None:
        from server.app.modules.agents_hub.database.operational_models import HubContentFinding
        from sqlalchemy import inspect as sa_inspect

        mapper = sa_inspect(HubContentFinding)
        status_col = mapper.columns["status"]
        assert status_col.index is True

    def test_status_default_is_new(self) -> None:
        from server.app.modules.agents_hub.database.operational_models import HubContentFinding

        orm = HubContentFinding()
        assert orm.status == "new"


# ---------------------------------------------------------------------------
# Repo — mock session
# ---------------------------------------------------------------------------


class TestContentFindingRepo:

    def _make_mock_session(self, existing_orm=None) -> AsyncMock:
        mock_exec_result = MagicMock()
        mock_exec_result.scalar_one_or_none = MagicMock(return_value=existing_orm)
        mock_exec_scalars = MagicMock()
        mock_exec_scalars.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))

        session = AsyncMock()
        session.execute = AsyncMock(side_effect=[mock_exec_result, mock_exec_scalars])
        session.get = AsyncMock(return_value=existing_orm)
        session.add = MagicMock()
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        return session

    @pytest.mark.asyncio
    async def test_upsert_creates_new_finding_when_not_exists(self) -> None:
        from server.app.modules.curation.findings_repo import (
            ContentFindingRepo,
        )

        finding = _make_finding(page_id=_PAGE_ID)
        session = self._make_mock_session(existing_orm=None)
        repo = ContentFindingRepo(session)

        await repo.upsert(finding)

        session.add.assert_called_once()
        session.flush.assert_called()

    @pytest.mark.asyncio
    async def test_upsert_updates_existing_finding_not_duplicate(self) -> None:
        from server.app.modules.curation.findings_repo import (
            ContentFindingRepo,
        )
        from server.app.modules.agents_hub.database.operational_models import HubContentFinding

        existing = HubContentFinding(
            id=uuid.uuid4(),
            site_id=_SITE_ID,
            finding_type="stale",
            severity="info",
            confidence=0.5,
            signal_json={},
            status="new",
            detected_at=_NOW,
        )
        finding = _make_finding(severity="warning", confidence=0.9)
        session = self._make_mock_session(existing_orm=existing)
        repo = ContentFindingRepo(session)

        await repo.upsert(finding)

        session.add.assert_not_called()
        assert existing.severity == "warning"
        assert existing.confidence == 0.9

    @pytest.mark.asyncio
    async def test_list_by_site_returns_results(self) -> None:
        from server.app.modules.curation.findings_repo import (
            ContentFindingRepo,
        )
        from server.app.modules.agents_hub.database.operational_models import HubContentFinding

        fake_orm = HubContentFinding(
            id=uuid.uuid4(), site_id=_SITE_ID, finding_type="stale",
            severity="info", confidence=0.5, signal_json={}, status="new", detected_at=_NOW,
        )
        mock_exec = MagicMock()
        mock_exec.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[fake_orm])))

        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_exec)
        repo = ContentFindingRepo(session)

        results = await repo.list_by_site(_SITE_ID)
        assert results == [fake_orm]

    @pytest.mark.asyncio
    async def test_list_by_site_filters_by_status(self) -> None:
        from server.app.modules.curation.findings_repo import (
            ContentFindingRepo,
        )

        mock_exec = MagicMock()
        mock_exec.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_exec)
        repo = ContentFindingRepo(session)

        await repo.list_by_site(_SITE_ID, status="confirmed")
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_list_by_site_filters_by_finding_type(self) -> None:
        from server.app.modules.curation.findings_repo import (
            ContentFindingRepo,
        )

        mock_exec = MagicMock()
        mock_exec.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        session = AsyncMock()
        session.execute = AsyncMock(return_value=mock_exec)
        repo = ContentFindingRepo(session)

        await repo.list_by_site(_SITE_ID, finding_type="duplicate")
        session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_transition_valid_updates_reviewed_fields(self) -> None:
        from server.app.modules.curation.findings_repo import (
            ContentFindingRepo,
        )
        from server.app.modules.agents_hub.database.operational_models import HubContentFinding

        reviewer_id = uuid.uuid4()
        orm = HubContentFinding(
            id=uuid.uuid4(), site_id=_SITE_ID, finding_type="stale",
            severity="info", confidence=0.5, signal_json={}, status="new", detected_at=_NOW,
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=orm)
        session.flush = AsyncMock()
        session.refresh = AsyncMock()
        repo = ContentFindingRepo(session)

        result = await repo.transition(orm.id, "confirmed", reviewed_by=reviewer_id)

        assert result.status == "confirmed"
        assert result.reviewed_by == reviewer_id
        assert result.reviewed_at is not None

    @pytest.mark.asyncio
    async def test_transition_invalid_raises_error(self) -> None:
        from server.app.modules.curation.findings_repo import (
            ContentFindingRepo,
        )
        from server.app.modules.curation.contracts import (
            InvalidFindingTransitionError,
        )
        from server.app.modules.agents_hub.database.operational_models import HubContentFinding

        orm = HubContentFinding(
            id=uuid.uuid4(), site_id=_SITE_ID, finding_type="stale",
            severity="info", confidence=0.5, signal_json={}, status="new", detected_at=_NOW,
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=orm)
        repo = ContentFindingRepo(session)

        with pytest.raises(InvalidFindingTransitionError):
            await repo.transition(orm.id, "resolved", reviewed_by=uuid.uuid4())

    @pytest.mark.asyncio
    async def test_transition_resolved_terminal_raises_error(self) -> None:
        from server.app.modules.curation.findings_repo import (
            ContentFindingRepo,
        )
        from server.app.modules.curation.contracts import (
            InvalidFindingTransitionError,
        )
        from server.app.modules.agents_hub.database.operational_models import HubContentFinding

        orm = HubContentFinding(
            id=uuid.uuid4(), site_id=_SITE_ID, finding_type="stale",
            severity="info", confidence=0.5, signal_json={}, status="resolved", detected_at=_NOW,
        )
        session = AsyncMock()
        session.get = AsyncMock(return_value=orm)
        repo = ContentFindingRepo(session)

        with pytest.raises(InvalidFindingTransitionError):
            await repo.transition(orm.id, "confirmed", reviewed_by=uuid.uuid4())
