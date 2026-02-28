"""Tests for QueryEngine — both stores are mocked."""

from unittest.mock import MagicMock

import pytest

from src.cli.query import QueryEngine
from src.storage.models import DeadlineRecord, EmailRow, FollowUpRecord
from src.storage.vector_store import SearchResult


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _make_follow_up(email_id: str = "msg_1") -> FollowUpRecord:
    return FollowUpRecord(
        id=1, email_id=email_id, status="pending", notes=None, created_at="2026-02-26 08:00:00"
    )


def _make_deadline(email_id: str = "msg_1") -> DeadlineRecord:
    return DeadlineRecord(
        id=1, email_id=email_id, description="Submit report by Friday", status="open",
        created_at="2026-02-26 08:00:00"
    )


def _make_result(email_id: str = "msg_1", distance: float = 0.1) -> SearchResult:
    return SearchResult(
        email_id=email_id,
        distance=distance,
        metadata={
            "sender": "alice@example.com",
            "subject": "Budget review",
            "thread_id": "thread_1",
            "date": "2026-02-27",
            "email_type": "human",
            "domain": "",
            "requires_reply": True,
            "summary": "Budget review requested.",
        },
    )


def _make_row(email_id: str = "msg_1") -> EmailRow:
    return EmailRow(
        id=email_id,
        thread_id="thread_1",
        sender="alice@example.com",
        subject="Budget review",
        snippet="snippet",
        body="Please review the budget.",
        date="2026-02-27",
        email_type="human",
        domain=None,
        summary="Budget review requested.",
        requires_reply=True,
        deadline=None,
        entities='["Alice"]',
        processed_at="2026-02-27 09:00:00",
    )


# ── Fixtures ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_store() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture
def engine(mock_store: MagicMock, mock_db: MagicMock) -> QueryEngine:
    return QueryEngine(mock_store, mock_db)


# ── search ───────────────────────────────────────────────────────────────────────


class TestSearch:
    def test_delegates_to_vector_store(
        self, engine: QueryEngine, mock_store: MagicMock
    ) -> None:
        mock_store.search.return_value = [_make_result()]
        results = engine.search("budget dispute", n=5)
        mock_store.search.assert_called_once_with("budget dispute", n_results=5)
        assert len(results) == 1

    def test_returns_empty_list_when_no_results(
        self, engine: QueryEngine, mock_store: MagicMock
    ) -> None:
        mock_store.search.return_value = []
        assert engine.search("nothing") == []


# ── get_emails_for_topic ─────────────────────────────────────────────────────────


class TestGetEmailsForTopic:
    def test_joins_vector_results_with_db_rows(
        self, engine: QueryEngine, mock_store: MagicMock, mock_db: MagicMock
    ) -> None:
        mock_store.search.return_value = [_make_result("msg_1")]
        mock_db.get_email_by_id.return_value = _make_row("msg_1")
        rows = engine.get_emails_for_topic("budget")
        assert len(rows) == 1
        assert rows[0].id == "msg_1"
        mock_db.get_email_by_id.assert_called_once_with("msg_1")

    def test_skips_emails_not_in_db(
        self, engine: QueryEngine, mock_store: MagicMock, mock_db: MagicMock
    ) -> None:
        mock_store.search.return_value = [_make_result("msg_missing")]
        mock_db.get_email_by_id.return_value = None
        assert engine.get_emails_for_topic("budget") == []

    def test_no_db_calls_when_no_vector_results(
        self, engine: QueryEngine, mock_store: MagicMock, mock_db: MagicMock
    ) -> None:
        mock_store.search.return_value = []
        engine.get_emails_for_topic("nothing")
        mock_db.get_email_by_id.assert_not_called()

    def test_returns_multiple_rows_in_order(
        self, engine: QueryEngine, mock_store: MagicMock, mock_db: MagicMock
    ) -> None:
        mock_store.search.return_value = [_make_result("msg_1"), _make_result("msg_2")]
        mock_db.get_email_by_id.side_effect = [_make_row("msg_1"), _make_row("msg_2")]
        rows = engine.get_emails_for_topic("budget", n=2)
        assert [r.id for r in rows] == ["msg_1", "msg_2"]


# ── get_stored_ids_since ─────────────────────────────────────────────────────────


class TestGetStoredIdsSince:
    def test_delegates_to_db(
        self, engine: QueryEngine, mock_db: MagicMock
    ) -> None:
        mock_db.get_stored_ids_since.return_value = {"msg_1", "msg_2"}
        ids = engine.get_stored_ids_since(30)
        mock_db.get_stored_ids_since.assert_called_once_with(30)
        assert ids == {"msg_1", "msg_2"}


# ── close ────────────────────────────────────────────────────────────────────────


class TestClose:
    def test_closes_both_stores(
        self, engine: QueryEngine, mock_store: MagicMock, mock_db: MagicMock
    ) -> None:
        engine.close()
        mock_store.close.assert_called_once()
        mock_db.close.assert_called_once()


# ── get_human_emails_needing_reply ───────────────────────────────────────────────


class TestGetHumanEmailsNeedingReply:
    def test_delegates_to_db(
        self, engine: QueryEngine, mock_db: MagicMock
    ) -> None:
        mock_db.get_human_emails_needing_reply.return_value = [_make_row()]
        result = engine.get_human_emails_needing_reply(hours=12)
        mock_db.get_human_emails_needing_reply.assert_called_once_with(12)
        assert len(result) == 1

    def test_default_hours_is_24(
        self, engine: QueryEngine, mock_db: MagicMock
    ) -> None:
        mock_db.get_human_emails_needing_reply.return_value = []
        engine.get_human_emails_needing_reply()
        mock_db.get_human_emails_needing_reply.assert_called_once_with(24)


# ── get_pending_follow_ups ───────────────────────────────────────────────────────


class TestGetPendingFollowUps:
    def test_enriches_follow_ups_with_email_rows(
        self, engine: QueryEngine, mock_db: MagicMock
    ) -> None:
        follow_up = _make_follow_up("msg_1")
        mock_db.get_follow_ups.return_value = [follow_up]
        mock_db.get_email_by_id.return_value = _make_row("msg_1")
        result = engine.get_pending_follow_ups()
        assert len(result) == 1
        assert result[0][0] is follow_up
        assert result[0][1].id == "msg_1"

    def test_email_row_can_be_none(
        self, engine: QueryEngine, mock_db: MagicMock
    ) -> None:
        mock_db.get_follow_ups.return_value = [_make_follow_up("msg_missing")]
        mock_db.get_email_by_id.return_value = None
        result = engine.get_pending_follow_ups()
        assert len(result) == 1
        assert result[0][1] is None

    def test_returns_empty_when_no_follow_ups(
        self, engine: QueryEngine, mock_db: MagicMock
    ) -> None:
        mock_db.get_follow_ups.return_value = []
        result = engine.get_pending_follow_ups()
        assert result == []


# ── get_open_deadlines ───────────────────────────────────────────────────────────


class TestGetOpenDeadlines:
    def test_enriches_deadlines_with_email_rows(
        self, engine: QueryEngine, mock_db: MagicMock
    ) -> None:
        deadline = _make_deadline("msg_1")
        mock_db.get_open_deadlines.return_value = [deadline]
        mock_db.get_email_by_id.return_value = _make_row("msg_1")
        result = engine.get_open_deadlines()
        assert len(result) == 1
        assert result[0][0] is deadline
        assert result[0][1].id == "msg_1"

    def test_email_row_can_be_none(
        self, engine: QueryEngine, mock_db: MagicMock
    ) -> None:
        mock_db.get_open_deadlines.return_value = [_make_deadline("msg_missing")]
        mock_db.get_email_by_id.return_value = None
        result = engine.get_open_deadlines()
        assert len(result) == 1
        assert result[0][1] is None

    def test_returns_empty_when_no_deadlines(
        self, engine: QueryEngine, mock_db: MagicMock
    ) -> None:
        mock_db.get_open_deadlines.return_value = []
        result = engine.get_open_deadlines()
        assert result == []
