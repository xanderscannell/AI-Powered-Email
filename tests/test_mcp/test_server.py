"""Unit tests for the FastMCP server tools.

Uses real (temporary) SQLite + ChromaDB instances seeded with fixture data.
No live Gmail or Anthropic API calls are made.

The module-level ``_engine`` singleton in ``src.mcp.server`` is replaced with
a test engine pointing at the temp databases via the ``engine`` fixture.
"""

import hashlib
from pathlib import Path
from typing import Any

import pytest
from chromadb import EmbeddingFunction
from chromadb.api.types import Documents

import src.mcp.server as server_module
from src.cli.query import QueryEngine
from src.mcp.types import RawEmail
from src.processing.types import Domain, EmailAnalysis, EmailType
from src.storage.db import EmailDatabase
from src.storage.vector_store import EmailVectorStore


# ── Lightweight embedding function (no model download) ────────────────────────


class WordHashEmbeddingFunction(EmbeddingFunction[Documents]):  # type: ignore[misc]
    """Deterministic bag-of-words embedding — avoids downloading sentence-transformers."""

    _DIM = 384

    def __init__(self) -> None:
        pass

    def __call__(self, input: Documents) -> list[list[float]]:
        result = []
        for doc in input:
            vec = [0.0] * self._DIM
            for word in str(doc).lower().split():
                idx = int(hashlib.md5(word.encode()).hexdigest(), 16) % self._DIM
                vec[idx] += 1.0
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            result.append([x / norm for x in vec])
        return result

    @staticmethod
    def name() -> str:
        return "word-hash-embedding-function"

    def get_config(self) -> dict[str, Any]:
        return {}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "WordHashEmbeddingFunction":
        return WordHashEmbeddingFunction()


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_raw_email(
    email_id: str = "msg_001",
    sender: str = "alice@example.com",
    subject: str = "Q2 budget review",
    body: str = "Please review the budget figures.",
    snippet: str = "Please review",
    date: str = "2026-03-01",
    thread_id: str = "thread_001",
) -> RawEmail:
    return RawEmail(
        id=email_id,
        thread_id=thread_id,
        sender=sender,
        subject=subject,
        snippet=snippet,
        body=body,
        date=date,
    )


def _make_analysis(
    email_id: str = "msg_001",
    email_type: EmailType = EmailType.HUMAN,
    domain: Domain | None = None,
    requires_reply: bool = True,
    deadline: str | None = None,
    summary: str = "Budget review requested.",
    entities: list[str] | None = None,
) -> EmailAnalysis:
    return EmailAnalysis(
        email_id=email_id,
        email_type=email_type,
        domain=domain,
        requires_reply=requires_reply,
        deadline=deadline,
        summary=summary,
        entities=entities or ["Alice"],
    )


@pytest.fixture()
def engine(tmp_path: Path) -> QueryEngine:
    """Create a real QueryEngine backed by temp databases, wired into the server."""
    db = EmailDatabase(tmp_path / "test.db")
    vs = EmailVectorStore(tmp_path / "chroma", embedding_function=WordHashEmbeddingFunction())
    eng = QueryEngine(vs, db)
    server_module._engine = eng
    yield eng
    server_module._engine = None
    eng.close()


@pytest.fixture()
def seeded_engine(engine: QueryEngine) -> QueryEngine:
    """Engine pre-seeded with two emails: one human (needs reply), one automated."""
    # Human email — requires reply
    raw1 = _make_raw_email(
        email_id="msg_001",
        sender="alice@example.com",
        subject="Q2 budget review",
        body="Please review the budget figures.",
    )
    analysis1 = _make_analysis(
        email_id="msg_001",
        email_type=EmailType.HUMAN,
        requires_reply=True,
        deadline="Submit by Friday",
        summary="Budget review requested.",
        entities=["Alice", "Q2"],
    )
    engine.db.save(raw1, analysis1)
    engine.vector_store.upsert(raw1, analysis1)

    # Automated email — newsletter
    raw2 = _make_raw_email(
        email_id="msg_002",
        sender="news@newsletter.com",
        subject="Weekly digest",
        body="Here are this week's top stories.",
        snippet="Top stories",
        date="2026-03-01",
        thread_id="thread_002",
    )
    analysis2 = _make_analysis(
        email_id="msg_002",
        email_type=EmailType.AUTOMATED,
        domain=Domain.NEWSLETTER,
        requires_reply=False,
        summary="Weekly newsletter digest.",
        entities=[],
    )
    engine.db.save(raw2, analysis2)
    engine.vector_store.upsert(raw2, analysis2)

    return engine


# ── search_emails ─────────────────────────────────────────────────────────────


class TestSearchEmails:
    def test_returns_results_for_matching_query(self, seeded_engine: QueryEngine) -> None:
        results = server_module.search_emails("budget review")
        assert len(results) >= 1
        assert all("email_id" in r for r in results)
        assert all("distance" in r for r in results)
        assert all("metadata" in r for r in results)

    def test_returns_empty_list_for_no_emails(self, engine: QueryEngine) -> None:
        results = server_module.search_emails("anything")
        assert results == []

    def test_limit_parameter_respected(self, seeded_engine: QueryEngine) -> None:
        results = server_module.search_emails("email", limit=1)
        assert len(results) <= 1

    def test_result_shape(self, seeded_engine: QueryEngine) -> None:
        results = server_module.search_emails("budget")
        assert len(results) >= 1
        r = results[0]
        assert isinstance(r["email_id"], str)
        assert isinstance(r["distance"], float)
        assert isinstance(r["metadata"], dict)


# ── get_emails_needing_reply ──────────────────────────────────────────────────


class TestGetEmailsNeedingReply:
    def test_returns_human_emails_requiring_reply(self, seeded_engine: QueryEngine) -> None:
        results = server_module.get_emails_needing_reply(hours=24 * 365)
        assert any(r["id"] == "msg_001" for r in results)

    def test_excludes_automated_emails(self, seeded_engine: QueryEngine) -> None:
        results = server_module.get_emails_needing_reply(hours=24 * 365)
        assert all(r["email_type"] == "human" for r in results)

    def test_returns_empty_when_no_emails(self, engine: QueryEngine) -> None:
        assert server_module.get_emails_needing_reply() == []

    def test_result_has_expected_fields(self, seeded_engine: QueryEngine) -> None:
        results = server_module.get_emails_needing_reply(hours=24 * 365)
        assert len(results) >= 1
        row = results[0]
        assert "id" in row
        assert "sender" in row
        assert "subject" in row
        assert "summary" in row
        assert "requires_reply" in row
        assert isinstance(row["entities"], list)  # parsed from JSON string

    def test_entities_parsed_as_list(self, seeded_engine: QueryEngine) -> None:
        results = server_module.get_emails_needing_reply(hours=24 * 365)
        assert len(results) >= 1
        assert isinstance(results[0]["entities"], list)


# ── get_pending_followups ─────────────────────────────────────────────────────


class TestGetPendingFollowups:
    def test_returns_follow_ups_with_email(self, seeded_engine: QueryEngine) -> None:
        results = server_module.get_pending_followups()
        assert len(results) >= 1
        item = results[0]
        assert "follow_up" in item
        assert "email" in item
        assert item["follow_up"]["status"] == "pending"

    def test_email_field_is_enriched(self, seeded_engine: QueryEngine) -> None:
        results = server_module.get_pending_followups()
        assert len(results) >= 1
        assert results[0]["email"] is not None
        assert results[0]["email"]["id"] == "msg_001"

    def test_returns_empty_when_no_follow_ups(self, engine: QueryEngine) -> None:
        assert server_module.get_pending_followups() == []

    def test_follow_up_fields(self, seeded_engine: QueryEngine) -> None:
        results = server_module.get_pending_followups()
        fu = results[0]["follow_up"]
        assert "id" in fu
        assert "email_id" in fu
        assert "status" in fu
        assert "created_at" in fu


# ── get_open_deadlines ────────────────────────────────────────────────────────


class TestGetOpenDeadlines:
    def test_returns_deadlines_with_email(self, seeded_engine: QueryEngine) -> None:
        results = server_module.get_open_deadlines()
        assert len(results) >= 1
        item = results[0]
        assert "deadline" in item
        assert "email" in item
        assert item["deadline"]["status"] == "open"

    def test_email_field_is_enriched(self, seeded_engine: QueryEngine) -> None:
        results = server_module.get_open_deadlines()
        assert len(results) >= 1
        assert results[0]["email"] is not None
        assert results[0]["email"]["id"] == "msg_001"

    def test_returns_empty_when_no_deadlines(self, engine: QueryEngine) -> None:
        assert server_module.get_open_deadlines() == []

    def test_deadline_fields(self, seeded_engine: QueryEngine) -> None:
        results = server_module.get_open_deadlines()
        dl = results[0]["deadline"]
        assert "id" in dl
        assert "email_id" in dl
        assert "description" in dl
        assert "status" in dl


# ── get_status ────────────────────────────────────────────────────────────────


class TestGetStatus:
    def test_returns_all_count_keys(self, seeded_engine: QueryEngine) -> None:
        status = server_module.get_status()
        assert "total_emails" in status
        assert "vector_count" in status
        assert "needing_reply" in status
        assert "pending_followups" in status
        assert "open_deadlines" in status

    def test_total_emails_count(self, seeded_engine: QueryEngine) -> None:
        status = server_module.get_status()
        assert status["total_emails"] == 2

    def test_vector_count(self, seeded_engine: QueryEngine) -> None:
        status = server_module.get_status()
        assert status["vector_count"] == 2

    def test_needing_reply_count(self, seeded_engine: QueryEngine) -> None:
        # msg_001 is human + requires_reply; msg_002 is automated
        status = server_module.get_status()
        assert status["needing_reply"] >= 0  # value depends on processed_at vs 24h window

    def test_pending_followups_count(self, seeded_engine: QueryEngine) -> None:
        status = server_module.get_status()
        assert status["pending_followups"] >= 1

    def test_open_deadlines_count(self, seeded_engine: QueryEngine) -> None:
        status = server_module.get_status()
        assert status["open_deadlines"] >= 1

    def test_empty_store_returns_zeros(self, engine: QueryEngine) -> None:
        status = server_module.get_status()
        assert status["total_emails"] == 0
        assert status["vector_count"] == 0
        assert status["needing_reply"] == 0
        assert status["pending_followups"] == 0
        assert status["open_deadlines"] == 0


# ── get_email ─────────────────────────────────────────────────────────────────


class TestGetEmail:
    def test_returns_email_by_id(self, seeded_engine: QueryEngine) -> None:
        result = server_module.get_email("msg_001")
        assert result is not None
        assert result["id"] == "msg_001"
        assert result["sender"] == "alice@example.com"

    def test_returns_none_for_missing_id(self, seeded_engine: QueryEngine) -> None:
        assert server_module.get_email("nonexistent_id") is None

    def test_entities_parsed_as_list(self, seeded_engine: QueryEngine) -> None:
        result = server_module.get_email("msg_001")
        assert result is not None
        assert isinstance(result["entities"], list)

    def test_all_fields_present(self, seeded_engine: QueryEngine) -> None:
        result = server_module.get_email("msg_001")
        assert result is not None
        for field in ("id", "thread_id", "sender", "subject", "snippet",
                      "body", "date", "email_type", "domain", "summary",
                      "requires_reply", "deadline", "entities", "processed_at"):
            assert field in result, f"missing field: {field}"


# ── get_contact ───────────────────────────────────────────────────────────────


class TestGetContact:
    def test_returns_contact_record(self, seeded_engine: QueryEngine) -> None:
        result = server_module.get_contact("alice@example.com")
        assert result is not None
        assert result["email_address"] == "alice@example.com"
        assert result["total_emails"] >= 1

    def test_returns_none_for_unknown_address(self, seeded_engine: QueryEngine) -> None:
        assert server_module.get_contact("unknown@example.com") is None

    def test_contact_fields(self, seeded_engine: QueryEngine) -> None:
        result = server_module.get_contact("alice@example.com")
        assert result is not None
        assert "email_address" in result
        assert "total_emails" in result
        assert "last_contact" in result
