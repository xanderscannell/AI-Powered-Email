"""Tests for EmailVectorStore — uses a real ChromaDB in a temp directory
with a deterministic word-hash embedding function to avoid model downloads.

The WordHashEmbeddingFunction produces bag-of-words style vectors: documents
that share many words get similar vectors, so semantic ranking tests are
actually meaningful (unlike a fixed-vector fake where all distances are equal).
"""

import hashlib
from pathlib import Path
from typing import Any

import pytest
from chromadb import EmbeddingFunction
from chromadb.api.types import Documents

from src.mcp.types import RawEmail
from src.processing.types import Domain, EmailAnalysis, EmailType
from src.storage.vector_store import EmailVectorStore, SearchResult, _build_document, _build_metadata


# ── Embedding function ─────────────────────────────────────────────────────────


class WordHashEmbeddingFunction(EmbeddingFunction[Documents]):  # type: ignore[misc]
    """Bag-of-words embedding using word hashing — no model download required.

    Each word is hashed to a dimension index; the vector is the normalised
    word-frequency histogram.  Documents that share vocabulary end up with
    similar vectors, so distance-based ranking tests are meaningful.
    """

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
    email_type: EmailType = EmailType.HUMAN,
    domain: Domain | None = None,
    requires_reply: bool = True,
    summary: str = "Budget review needed.",
) -> EmailAnalysis:
    return EmailAnalysis(
        email_id=email_id,
        email_type=email_type,
        domain=domain,
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
        embedding_function=WordHashEmbeddingFunction(),
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
        expected_keys = {"sender", "subject", "thread_id", "date", "email_type",
                         "domain", "requires_reply", "summary"}
        assert expected_keys <= set(meta.keys())

    def test_email_type_is_string(self) -> None:
        meta = _build_metadata(make_email(), make_analysis(email_type=EmailType.HUMAN))
        assert meta["email_type"] == "human"
        assert isinstance(meta["email_type"], str)

    def test_domain_is_string(self) -> None:
        meta = _build_metadata(make_email(), make_analysis(email_type=EmailType.AUTOMATED, domain=Domain.FINANCE))
        assert meta["domain"] == "finance"

    def test_domain_empty_string_when_none(self) -> None:
        meta = _build_metadata(make_email(), make_analysis(email_type=EmailType.HUMAN, domain=None))
        assert meta["domain"] == ""


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

    def test_filter_by_email_type(self, store: EmailVectorStore) -> None:
        store.upsert(make_email("hi"), make_analysis("hi", email_type=EmailType.HUMAN))
        store.upsert(make_email("lo"), make_analysis("lo", email_type=EmailType.AUTOMATED, domain=Domain.NEWSLETTER))

        results = store.search_with_filter(
            "budget", where={"email_type": "human"}
        )
        assert len(results) == 1
        assert results[0].email_id == "hi"

    def test_empty_collection_returns_empty(self, store: EmailVectorStore) -> None:
        results = store.search_with_filter("budget", where={"sender": "x@y.com"})
        assert results == []


# ── semantic ranking ───────────────────────────────────────────────────────────
#
# These tests verify that the ranking order is meaningful — i.e. that a query
# about finance returns finance emails above travel emails, not just that
# *something* is returned.  They rely on WordHashEmbeddingFunction producing
# different vectors for different vocabulary, which the old fixed-vector fake
# could never do.


class TestSemanticRanking:
    def test_relevant_email_ranks_above_unrelated(self, store: EmailVectorStore) -> None:
        """A finance query should rank a finance email above a travel email."""
        store.upsert(
            make_email("fin", subject="Invoice overdue payment", body="Your invoice is overdue. Please pay the outstanding balance immediately."),
            make_analysis("fin", email_type=EmailType.AUTOMATED, domain=Domain.FINANCE, summary="Invoice overdue."),
        )
        store.upsert(
            make_email("trv", subject="Flight booking confirmed", body="Your flight to Tokyo is confirmed. Gate opens at 07:00."),
            make_analysis("trv", email_type=EmailType.AUTOMATED, domain=Domain.TRAVEL, summary="Flight confirmed."),
        )

        results = store.search("invoice overdue payment balance", n_results=2)
        assert results[0].email_id == "fin"

    def test_query_ranks_matching_subject_first(self, store: EmailVectorStore) -> None:
        """Querying with the exact words from an email's subject should surface it first."""
        store.upsert(
            make_email("x", subject="quarterly budget review meeting", body="Please attend the quarterly budget review."),
            make_analysis("x", summary="Budget review meeting scheduled."),
        )
        store.upsert(
            make_email("y", subject="team lunch Thursday", body="Join us for lunch on Thursday at noon."),
            make_analysis("y", summary="Team lunch invitation."),
        )
        store.upsert(
            make_email("z", subject="server maintenance window", body="Scheduled maintenance this weekend."),
            make_analysis("z", email_type=EmailType.AUTOMATED, domain=Domain.ALERTS, summary="Maintenance alert."),
        )

        results = store.search("quarterly budget review", n_results=3)
        assert results[0].email_id == "x"

    def test_distance_ordering_is_ascending(self, store: EmailVectorStore) -> None:
        """Results should be returned nearest-first (ascending distance)."""
        for i in range(5):
            store.upsert(
                make_email(f"msg_{i}", subject=f"topic {i}", body=f"content about topic {i}"),
                make_analysis(f"msg_{i}"),
            )
        results = store.search("topic content", n_results=5)
        distances = [r.distance for r in results]
        assert distances == sorted(distances)

    def test_human_emails_outrank_automated_on_personal_query(self, store: EmailVectorStore) -> None:
        """A personal reply query should prefer human email over marketing noise."""
        store.upsert(
            make_email("human", subject="Re: project proposal feedback", body="Thanks for sending the proposal. I have reviewed it and have some feedback for you."),
            make_analysis("human", email_type=EmailType.HUMAN, requires_reply=True, summary="Colleague has feedback on proposal."),
        )
        store.upsert(
            make_email("auto", subject="50% off sale this weekend only", body="Don't miss our weekend sale. Huge discounts on everything."),
            make_analysis("auto", email_type=EmailType.AUTOMATED, domain=Domain.MARKETING, summary="Weekend sale promotion."),
        )

        results = store.search("project proposal feedback review", n_results=2)
        assert results[0].email_id == "human"


# ── scale and integrity ────────────────────────────────────────────────────────


class TestScaleAndIntegrity:
    def test_thousand_inserts_correct_count(self, store: EmailVectorStore) -> None:
        for i in range(1_000):
            store.upsert(make_email(f"msg_{i}"), make_analysis(f"msg_{i}"))
        assert store._collection.count() == 1_000

    def test_no_duplicates_on_repeated_upsert(self, store: EmailVectorStore) -> None:
        """Re-upserting all IDs must not inflate the count."""
        for i in range(200):
            store.upsert(make_email(f"msg_{i}"), make_analysis(f"msg_{i}"))
        for i in range(200):
            store.upsert(make_email(f"msg_{i}"), make_analysis(f"msg_{i}"))
        assert store._collection.count() == 200

    def test_metadata_intact_at_scale(self, store: EmailVectorStore) -> None:
        """Metadata values are stored and retrieved correctly across many documents."""
        for i in range(100):
            store.upsert(
                make_email(f"msg_{i}", sender=f"user{i}@example.com", subject=f"Subject {i}"),
                make_analysis(f"msg_{i}"),
            )

        results = store.search_with_filter("subject", where={"sender": "user42@example.com"})
        assert len(results) == 1
        assert results[0].email_id == "msg_42"
        assert results[0].metadata["sender"] == "user42@example.com"
        assert results[0].metadata["subject"] == "Subject 42"

    def test_upsert_overwrites_metadata(self, store: EmailVectorStore) -> None:
        """Re-upserting the same ID with updated metadata must replace the old values."""
        store.upsert(make_email("a", subject="Original subject"), make_analysis("a"))
        store.upsert(make_email("a", subject="Updated subject"), make_analysis("a"))

        assert store._collection.count() == 1
        results = store.search("subject")
        assert results[0].metadata["subject"] == "Updated subject"

    def test_n_results_never_exceeds_collection_size(self, store: EmailVectorStore) -> None:
        """Requesting more results than exist must not raise — just return what's there."""
        for i in range(3):
            store.upsert(make_email(f"msg_{i}"), make_analysis(f"msg_{i}"))
        results = store.search("anything", n_results=100)
        assert len(results) == 3
