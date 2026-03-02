"""FastMCP server — exposes processed email data to Claude Desktop as read-only tools.

Run via ``email-agent-mcp`` (stdio transport, spawned by Claude Desktop).

Tools are read-only: no Gmail dependency, no Anthropic API dependency.
All queries hit the local SQLite + ChromaDB stores via QueryEngine.

Environment variables:
    SQLITE_PATH  — path to the SQLite database (default: data/email_agent.db)
    CHROMA_PATH  — path to the ChromaDB directory (default: data/chroma)
"""

import atexit
import dataclasses
import json
import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.cli.query import QueryEngine
from src.storage.db import EmailDatabase
from src.storage.models import EmailRow
from src.storage.vector_store import EmailVectorStore

logger = logging.getLogger(__name__)

mcp = FastMCP("email-agent")

# ── Singleton engine ──────────────────────────────────────────────────────────
# Lazily created on first tool call; can be replaced in tests via:
#   import src.mcp.server as s; s._engine = my_test_engine
_engine: QueryEngine | None = None


def _build_engine() -> QueryEngine:
    """Instantiate QueryEngine from environment variables."""
    db_path = os.environ.get("SQLITE_PATH", "data/email_agent.db")
    chroma_path = os.environ.get("CHROMA_PATH", "data/chroma")
    db = EmailDatabase(db_path)
    vs = EmailVectorStore(chroma_path)
    return QueryEngine(vs, db)


def _get_engine() -> QueryEngine:
    """Return the module-level singleton QueryEngine, building it on first call."""
    global _engine
    if _engine is None:
        _engine = _build_engine()
        atexit.register(_close_engine)
    return _engine


def _close_engine() -> None:
    """Close the singleton engine on graceful process exit."""
    global _engine
    if _engine is not None:
        _engine.close()
        _engine = None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _email_row_to_dict(row: EmailRow) -> dict[str, Any]:
    """Convert an EmailRow to a plain dict, parsing the entities JSON string."""
    d = dataclasses.asdict(row)
    try:
        d["entities"] = json.loads(row.entities)
    except (json.JSONDecodeError, TypeError):
        d["entities"] = []
    return d


# ── Tools ─────────────────────────────────────────────────────────────────────


@mcp.tool()
def search_emails(query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Semantic search across all processed emails.

    Args:
        query: Natural language search query.
        limit: Maximum number of results to return (default 10).

    Returns:
        List of dicts with keys: email_id, distance (lower=better), metadata.
    """
    engine = _get_engine()
    results = engine.search(query, n=limit)
    return [dataclasses.asdict(r) for r in results]


@mcp.tool()
def get_emails_needing_reply(hours: int = 24) -> list[dict[str, Any]]:
    """Return human emails that have not been replied to yet.

    Args:
        hours: Look back this many hours when filtering by processing time (default 24).

    Returns:
        List of email record dicts that require a reply.
    """
    engine = _get_engine()
    rows = engine.get_human_emails_needing_reply(hours=hours)
    return [_email_row_to_dict(r) for r in rows]


@mcp.tool()
def get_pending_followups() -> list[dict[str, Any]]:
    """Return follow-ups the agent is tracking that are still pending.

    Returns:
        List of dicts, each with keys:
            follow_up — the FollowUpRecord fields (id, email_id, status, notes, created_at)
            email     — the full EmailRow dict, or None if the source email is missing
    """
    engine = _get_engine()
    pairs = engine.get_pending_follow_ups()
    return [
        {
            "follow_up": dataclasses.asdict(fu),
            "email": _email_row_to_dict(email) if email is not None else None,
        }
        for fu, email in pairs
    ]


@mcp.tool()
def get_open_deadlines() -> list[dict[str, Any]]:
    """Return deadlines extracted from emails that are still open.

    Returns:
        List of dicts, each with keys:
            deadline — the DeadlineRecord fields (id, email_id, description, status, created_at)
            email    — the full EmailRow dict, or None if the source email is missing
    """
    engine = _get_engine()
    pairs = engine.get_open_deadlines()
    return [
        {
            "deadline": dataclasses.asdict(dl),
            "email": _email_row_to_dict(email) if email is not None else None,
        }
        for dl, email in pairs
    ]


@mcp.tool()
def get_status() -> dict[str, Any]:
    """Return summary counts from both the SQLite and ChromaDB stores.

    Returns:
        Dict with integer counts:
            total_emails      — emails in SQLite
            vector_count      — embeddings in ChromaDB
            needing_reply     — human emails requiring a reply (last 24 h)
            pending_followups — open follow-up tracking records
            open_deadlines    — open deadline tracking records
    """
    engine = _get_engine()
    return {
        "total_emails": engine.db.get_email_count(),
        "vector_count": engine.vector_store.count(),
        "needing_reply": len(engine.get_human_emails_needing_reply(hours=24)),
        "pending_followups": len(engine.get_pending_follow_ups()),
        "open_deadlines": len(engine.get_open_deadlines()),
    }


@mcp.tool()
def get_email(email_id: str) -> dict[str, Any] | None:
    """Return the full stored record for a single email.

    Args:
        email_id: The Gmail message ID.

    Returns:
        Email record dict, or None if the email is not in the database.
    """
    engine = _get_engine()
    row = engine.db.get_email_by_id(email_id)
    return _email_row_to_dict(row) if row is not None else None


@mcp.tool()
def get_contact(email_address: str) -> dict[str, Any] | None:
    """Return contact history for an email address.

    Args:
        email_address: The contact's email address.

    Returns:
        Dict with keys: email_address, total_emails, last_contact.
        Returns None if the address is not in the database.
    """
    engine = _get_engine()
    record = engine.db.get_contact_history(email_address)
    return dataclasses.asdict(record) if record is not None else None


# ── Entry point ───────────────────────────────────────────────────────────────


def main() -> None:
    """Run the MCP server over stdio (for Claude Desktop)."""
    mcp.run(transport="stdio")
