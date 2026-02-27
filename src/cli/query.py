"""QueryEngine — coordinates EmailVectorStore and EmailDatabase for CLI queries."""

from src.storage.db import EmailDatabase
from src.storage.models import EmailRow
from src.storage.vector_store import EmailVectorStore, SearchResult


class QueryEngine:
    """Coordinates EmailVectorStore and EmailDatabase behind a single query interface.

    Both stores are exposed as public attributes so commands can pass them to
    AnalysisProcessor (e.g. during backfill) without creating duplicate instances.

    Phase 5 note: add get_urgent_emails(), get_pending_follow_ups(), and
    get_open_deadlines() here for the BriefingGenerator.

    Usage::

        engine = QueryEngine(vector_store, db)
        results = engine.search("budget dispute")
        emails = engine.get_emails_for_topic("Acme invoice")
    """

    def __init__(self, vector_store: EmailVectorStore, db: EmailDatabase) -> None:
        self.vector_store = vector_store
        self.db = db

    def close(self) -> None:
        """Release underlying store resources."""
        self.vector_store.close()
        self.db.close()

    def search(self, query: str, n: int = 10) -> list[SearchResult]:
        """Semantic search over indexed emails. Returns vector store results."""
        return self.vector_store.search(query, n_results=n)

    def get_emails_for_topic(self, topic: str, n: int = 10) -> list[EmailRow]:
        """Find emails related to a topic and return their full DB rows.

        Performs a vector search for IDs then fetches full rows (including
        body) from SQLite. Used by ``email status`` to build a Sonnet prompt.
        Emails present in ChromaDB but not yet in SQLite are silently skipped.
        """
        results = self.vector_store.search(topic, n_results=n)
        rows: list[EmailRow] = []
        for result in results:
            row = self.db.get_email_by_id(result.email_id)
            if row is not None:
                rows.append(row)
        return rows

    def get_stored_ids_since(self, days: int) -> set[str]:
        """Return IDs of emails already stored from the last N days.

        Used by ``email backfill`` to skip already-processed emails.
        """
        return self.db.get_stored_ids_since(days)
