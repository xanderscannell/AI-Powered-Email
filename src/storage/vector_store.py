"""ChromaDB vector store for semantic email search."""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import chromadb
from chromadb.utils import embedding_functions

from src.mcp.types import RawEmail
from src.processing.types import EmailAnalysis

logger = logging.getLogger(__name__)

_DEFAULT_CHROMA_DIR = Path("data/chroma")
_COLLECTION_NAME = "emails"


# ── Result type ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SearchResult:
    """A single result from a vector similarity search."""

    email_id: str
    distance: float
    metadata: dict[str, Any]


# ── Store ───────────────────────────────────────────────────────────────────────


class EmailVectorStore:
    """ChromaDB-backed semantic search over email content.

    Stores subject + body + Haiku summary as the embedded document, with
    structured metadata for filtered queries.

    Usage::

        store = EmailVectorStore()
        store.upsert(raw_email, analysis)
        results = store.search("budget dispute with vendor")
    """

    def __init__(
        self,
        persist_dir: str | Path = _DEFAULT_CHROMA_DIR,
        collection_name: str = _COLLECTION_NAME,
        embedding_function: Any = None,
    ) -> None:
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(persist_dir))
        ef = embedding_function or embedding_functions.DefaultEmbeddingFunction()
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=ef,  # type: ignore[arg-type]
        )

    def close(self) -> None:
        """Release ChromaDB resources (important on Windows where files stay locked)."""
        try:
            self._client._system.stop()
        except Exception:  # noqa: BLE001
            pass

    # ── Write ───────────────────────────────────────────────────────────────────

    def upsert(self, email: RawEmail, analysis: EmailAnalysis) -> None:
        """Embed and store an email.  Calling again with the same ID overwrites."""
        document = _build_document(email, analysis)
        metadata = _build_metadata(email, analysis)
        self._collection.upsert(
            documents=[document],
            metadatas=[metadata],  # type: ignore[list-item]
            ids=[email.id],
        )

    # ── Read ────────────────────────────────────────────────────────────────────

    def search(self, query: str, n_results: int = 10) -> list[SearchResult]:
        """Return the n_results most semantically similar emails to query."""
        count = self._collection.count()
        if count == 0:
            return []
        results = self._collection.query(
            query_texts=[query],
            n_results=min(n_results, count),
        )
        return _parse_results(results)

    def search_with_filter(
        self,
        query: str,
        where: dict[str, Any],
        n_results: int = 10,
    ) -> list[SearchResult]:
        """Semantic search filtered by metadata (e.g. sender, priority).

        ``where`` uses ChromaDB's filter syntax, e.g.::

            {"priority": {"$lte": 2}}         # priority 1 or 2
            {"sender": "alice@example.com"}    # exact sender match
        """
        count = self._collection.count()
        if count == 0:
            return []
        results = self._collection.query(
            query_texts=[query],
            n_results=min(n_results, count),
            where=where,  # type: ignore[arg-type]
        )
        return _parse_results(results)


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _build_document(email: RawEmail, analysis: EmailAnalysis) -> str:
    """Concatenate subject + body + summary into the embeddable document text."""
    parts = [email.subject]
    if email.body:
        parts.append(email.body)
    elif email.snippet:
        parts.append(email.snippet)
    if analysis.summary:
        parts.append(analysis.summary)
    return "\n\n".join(parts)


def _build_metadata(email: RawEmail, analysis: EmailAnalysis) -> dict[str, Any]:
    """Build the flat metadata dict stored alongside the vector."""
    return {
        "sender": email.sender,
        "subject": email.subject,
        "thread_id": email.thread_id,
        "date": email.date or "",
        "priority": int(analysis.priority),
        "intent": analysis.intent.value,
        "sentiment": analysis.sentiment,
        "requires_reply": analysis.requires_reply,
        "summary": analysis.summary,
    }


def _parse_results(raw: dict[str, Any]) -> list[SearchResult]:
    """Convert a raw ChromaDB query result dict into SearchResult objects."""
    ids: list[str] = raw["ids"][0]
    distances: list[float] = raw["distances"][0]
    metadatas: list[dict[str, Any]] = raw["metadatas"][0]
    return [
        SearchResult(email_id=eid, distance=dist, metadata=meta)
        for eid, dist, meta in zip(ids, distances, metadatas)
    ]
