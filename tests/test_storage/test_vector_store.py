"""Tests for EmailVectorStore — uses a real ChromaDB in a temp directory
with a deterministic fake embedding function to avoid model downloads."""

from pathlib import Path
from typing import Any

import pytest
from chromadb import EmbeddingFunction
from chromadb.api.types import Documents

from src.mcp.types import RawEmail
from src.processing.types import EmailAnalysis, Intent, Priority
from src.storage.vector_store import EmailVectorStore, SearchResult, _build_document, _build_metadata


# ── Fake embedding function ────────────────────────────────────────────────────


class FakeEmbeddingFunction(EmbeddingFunction[Documents]):  # type: ignore[misc]
    """Returns deterministic fixed-length vectors — no model download required."""

    _DIM = 384

    def __init__(self) -> None:  # explicit __init__ suppresses DeprecationWarning
        pass

    def __call__(self, input: Documents) -> list[list[float]]:
        return [[float(i) * 0.001 for i in range(self._DIM)] for _ in input]

    @staticmethod
    def name() -> str:
        return "fake-embedding-function"

    def get_config(self) -> dict[str, Any]:
        return {}

    @staticmethod
    def build_from_config(config: dict[str, Any]) -> "FakeEmbeddingFunction":
        return FakeEmbeddingFunction()


# ── Helpers ────────────────────────────────────────────────────────────────────


def make_email(
    id: str = "msg_1",
    sender: str = "alice@example.com",
    subject: str = "Budget review",
    body: str = "Please review the Q2 budget.",
    date: str = "2026-02-27",
) -> RawEmail:
    return RawEmail(
        id=id,
        thread_id=f"thread_{id}",
        sender=sender,
        subject=subject,
        snippet=body[:50],
        body=body,
        date=date,
    )


def make_analysis(
    email_id: str = "msg_1",
    sentiment: float = 0.5,
    intent: Intent = Intent.ACTION_REQUIRED,
    priority: Priority = Priority.HIGH,
    requires_reply: bool = True,
    summary: str = "Budget review needed.",
) -> EmailAnalysis:
    return EmailAnalysis(
        email_id=email_id,
        sentiment=sentiment,
        intent=intent,
        priority=priority,
        entities=["Q2 Budget"],
        summary=summary,
        requires_reply=requires_reply,
        deadline=None,
    )


@pytest.fixture
def store(tmp_path: Path) -> Any:
    s = EmailVectorStore(
        persist_dir=tmp_path / "chroma",
        collection_name="test_emails",
        embedding_function=FakeEmbeddingFunction(),
    )
    yield s
    s.close()  # release file handles (important on Windows)


# ── _build_document ────────────────────────────────────────────────────────────


class TestBuildDocument:
    def test_includes_subject(self) -> None:
        doc = _build_document(make_email(subject="Hello world"), make_analysis())
        assert "Hello world" in doc

    def test_includes_body(self) -> None:
        doc = _build_document(make_email(body="The body text here."), make_analysis())
        assert "The body text here." in doc

    def test_includes_summary(self) -> None:
        doc = _build_document(make_email(), make_analysis(summary="Short summary."))
        assert "Short summary." in doc

    def test_falls_back_to_snippet_when_no_body(self) -> None:
        email = RawEmail(
            id="x", thread_id="t", sender="a@b.com",
            subject="Subj", snippet="Snip text", body=None,
        )
        doc = _build_document(email, make_analysis())
        assert "Snip text" in doc


# ── _build_metadata ────────────────────────────────────────────────────────────


class TestBuildMetadata:
    def test_contains_expected_keys(self) -> None:
        meta = _build_metadata(make_email(), make_analysis())
        expected_keys = {"sender", "subject", "thread_id", "date", "priority",
                         "intent", "sentiment", "requires_reply", "summary"}
        assert expected_keys <= set(meta.keys())

    def test_priority_is_int(self) -> None:
        meta = _build_metadata(make_email(), make_analysis(priority=Priority.CRITICAL))
        assert meta["priority"] == 1
        assert isinstance(meta["priority"], int)

    def test_intent_is_string(self) -> None:
        meta = _build_metadata(make_email(), make_analysis(intent=Intent.FYI))
        assert meta["intent"] == "fyi"


# ── upsert ─────────────────────────────────────────────────────────────────────


class TestUpsert:
    def test_upsert_stores_document(self, store: EmailVectorStore) -> None:
        store.upsert(make_email("a"), make_analysis("a"))
        assert store._collection.count() == 1

    def test_upsert_two_documents(self, store: EmailVectorStore) -> None:
        store.upsert(make_email("a"), make_analysis("a"))
        store.upsert(make_email("b"), make_analysis("b"))
        assert store._collection.count() == 2

    def test_upsert_is_idempotent(self, store: EmailVectorStore) -> None:
        """Upserting the same email_id twice must not create duplicates."""
        store.upsert(make_email("a"), make_analysis("a"))
        store.upsert(make_email("a"), make_analysis("a"))
        assert store._collection.count() == 1


# ── search ─────────────────────────────────────────────────────────────────────


class TestSearch:
    def test_returns_empty_on_empty_collection(self, store: EmailVectorStore) -> None:
        results = store.search("anything")
        assert results == []

    def test_returns_search_results(self, store: EmailVectorStore) -> None:
        store.upsert(make_email("a"), make_analysis("a"))
        results = store.search("budget review")
        assert len(results) == 1
        assert isinstance(results[0], SearchResult)

    def test_result_contains_email_id(self, store: EmailVectorStore) -> None:
        store.upsert(make_email("msg_xyz"), make_analysis("msg_xyz"))
        results = store.search("budget")
        assert results[0].email_id == "msg_xyz"

    def test_result_contains_distance(self, store: EmailVectorStore) -> None:
        store.upsert(make_email("a"), make_analysis("a"))
        results = store.search("budget")
        assert isinstance(results[0].distance, float)

    def test_result_contains_metadata(self, store: EmailVectorStore) -> None:
        store.upsert(make_email("a", sender="bob@example.com"), make_analysis("a"))
        results = store.search("budget")
        assert results[0].metadata["sender"] == "bob@example.com"

    def test_n_results_respected(self, store: EmailVectorStore) -> None:
        for i in range(5):
            store.upsert(make_email(f"msg_{i}"), make_analysis(f"msg_{i}"))
        results = store.search("budget", n_results=3)
        assert len(results) == 3


# ── search_with_filter ─────────────────────────────────────────────────────────


class TestSearchWithFilter:
    def test_filter_by_sender(self, store: EmailVectorStore) -> None:
        store.upsert(make_email("a", sender="alice@example.com"), make_analysis("a"))
        store.upsert(make_email("b", sender="bob@example.com"), make_analysis("b"))

        results = store.search_with_filter(
            "budget", where={"sender": "alice@example.com"}
        )
        assert len(results) == 1
        assert results[0].email_id == "a"

    def test_filter_returns_empty_when_no_match(self, store: EmailVectorStore) -> None:
        store.upsert(make_email("a", sender="alice@example.com"), make_analysis("a"))

        results = store.search_with_filter(
            "budget", where={"sender": "nobody@example.com"}
        )
        assert results == []

    def test_filter_by_priority(self, store: EmailVectorStore) -> None:
        store.upsert(make_email("hi"), make_analysis("hi", priority=Priority.HIGH))
        store.upsert(make_email("lo"), make_analysis("lo", priority=Priority.LOW))

        results = store.search_with_filter(
            "budget", where={"priority": int(Priority.HIGH)}
        )
        assert len(results) == 1
        assert results[0].email_id == "hi"

    def test_empty_collection_returns_empty(self, store: EmailVectorStore) -> None:
        results = store.search_with_filter("budget", where={"sender": "x@y.com"})
        assert results == []
