# Phase 4 CLI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a `click`-based CLI with `email search`, `email status`, and `email backfill` commands backed by a `QueryEngine` that coordinates `EmailVectorStore` and `EmailDatabase`.

**Architecture:** `QueryEngine` (`src/cli/query.py`) wraps both stores with three methods: `search`, `get_emails_for_topic`, and `get_stored_ids_since`. CLI commands (`src/cli/commands.py`) stay thin — they parse args, call `QueryEngine`, and format output with `rich`. Two new storage-layer methods (`get_email_by_id`, `get_stored_ids_since`) and one new Gmail client method (`get_emails_since`) are added as prerequisites.

**Tech Stack:** `click 8.x`, `rich>=13`, `anthropic` (Sonnet for `status` synthesis), existing `EmailVectorStore`, `EmailDatabase`, `GmailClient`, `EmailAnalyzer`, `AnalysisProcessor`

**Reference:** Design doc at `docs/plans/2026-02-27-phase4-cli-design.md`

---

### Task 1: Add `EmailRow` dataclass and `get_email_by_id()` to the storage layer

The `status` command needs full email bodies from SQLite. There is currently no `get_email_by_id()` method and no typed return type for a full email row.

**Files:**
- Modify: `src/storage/models.py`
- Modify: `src/storage/db.py`
- Modify: `tests/test_storage/test_db.py`

**Step 1: Write the failing tests**

Add to the bottom of `tests/test_storage/test_db.py`:

```python
# ── get_email_by_id ─────────────────────────────────────────────────────────────


class TestGetEmailById:
    def test_returns_row_for_known_id(self, db: EmailDatabase) -> None:
        email = make_email()
        db.save(email, make_analysis())
        row = db.get_email_by_id(email.id)
        assert row is not None
        assert row.id == email.id
        assert row.sender == email.sender
        assert row.subject == email.subject
        assert row.body == email.body
        assert row.requires_reply is False

    def test_returns_none_for_unknown_id(self, db: EmailDatabase) -> None:
        assert db.get_email_by_id("nonexistent") is None

    def test_requires_reply_is_bool(self, db: EmailDatabase) -> None:
        email = make_email()
        db.save(email, make_analysis(requires_reply=True))
        row = db.get_email_by_id(email.id)
        assert row is not None
        assert row.requires_reply is True
        assert isinstance(row.requires_reply, bool)
```

Also add this import at the top of `tests/test_storage/test_db.py`:

```python
from src.storage.models import ContactRecord, DeadlineRecord, EmailRow, FollowUpRecord
```

**Step 2: Run the tests to confirm they fail**

```
pytest tests/test_storage/test_db.py::TestGetEmailById -v
```

Expected: `ImportError: cannot import name 'EmailRow'`

**Step 3: Add `EmailRow` to `src/storage/models.py`**

Add this block after `_CREATE_DEADLINES` and before `ALL_TABLES`:

```python
@dataclass(frozen=True)
class EmailRow:
    """A full row from the emails table."""

    id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    body: str | None
    date: str | None
    sentiment: float
    intent: str
    priority: int
    summary: str
    requires_reply: bool
    deadline: str | None
    entities: str  # JSON-encoded list[str]
    processed_at: str
```

**Step 4: Add `get_email_by_id()` to `src/storage/db.py`**

Add this method to `EmailDatabase` in the `# ── Read API` section, after `get_contact_history`:

```python
def get_email_by_id(self, email_id: str) -> EmailRow | None:
    """Return the stored email row for email_id, or None if not found."""
    row = self._conn.execute(
        """SELECT id, thread_id, sender, subject, snippet, body, date,
                  sentiment, intent, priority, summary, requires_reply,
                  deadline, entities, processed_at
           FROM emails WHERE id = ?""",
        (email_id,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["requires_reply"] = bool(d["requires_reply"])
    return EmailRow(**d)
```

Also update the import at the top of `src/storage/db.py`:

```python
from src.storage.models import (
    ALL_TABLES,
    ContactRecord,
    DeadlineRecord,
    EmailRow,
    FollowUpRecord,
)
```

**Step 5: Run the tests to confirm they pass**

```
pytest tests/test_storage/test_db.py::TestGetEmailById -v
```

Expected: 3 PASSED

**Step 6: Run the full suite to confirm nothing broke**

```
pytest tests/ -v --tb=short
```

Expected: all existing tests + 3 new = green

**Step 7: Commit**

```bash
git add src/storage/models.py src/storage/db.py tests/test_storage/test_db.py
git commit -m "feat(storage): add EmailRow dataclass and get_email_by_id() to EmailDatabase"
```

---

### Task 2: Add `get_stored_ids_since()` to `EmailDatabase`

The `backfill` command needs to know which email IDs are already stored so it can skip them.

**Files:**
- Modify: `src/storage/db.py`
- Modify: `tests/test_storage/test_db.py`

**Step 1: Write the failing tests**

Add to the bottom of `tests/test_storage/test_db.py`:

```python
# ── get_stored_ids_since ────────────────────────────────────────────────────────


class TestGetStoredIdsSince:
    def test_returns_recently_processed_id(self, db: EmailDatabase) -> None:
        email = make_email()
        db.save(email, make_analysis())
        ids = db.get_stored_ids_since(days=30)
        assert email.id in ids

    def test_returns_empty_set_when_no_emails(self, db: EmailDatabase) -> None:
        assert db.get_stored_ids_since(days=30) == set()

    def test_excludes_emails_older_than_window(self, db: EmailDatabase) -> None:
        email = make_email()
        db.save(email, make_analysis())
        # Backdate the processed_at timestamp to 60 days ago
        db._conn.execute(
            "UPDATE emails SET processed_at = datetime('now', '-60 days') WHERE id = ?",
            (email.id,),
        )
        db._conn.commit()
        ids = db.get_stored_ids_since(days=30)
        assert email.id not in ids

    def test_returns_set_not_list(self, db: EmailDatabase) -> None:
        email = make_email()
        db.save(email, make_analysis())
        result = db.get_stored_ids_since(days=30)
        assert isinstance(result, set)
```

**Step 2: Run to confirm they fail**

```
pytest tests/test_storage/test_db.py::TestGetStoredIdsSince -v
```

Expected: `AttributeError: 'EmailDatabase' object has no attribute 'get_stored_ids_since'`

**Step 3: Implement `get_stored_ids_since()` in `src/storage/db.py`**

Add after `get_email_by_id()` in the `# ── Read API` section:

```python
def get_stored_ids_since(self, days: int) -> set[str]:
    """Return IDs of emails processed within the last N days.

    Uses SQLite's own datetime arithmetic so there is no UTC/local-time mismatch.
    """
    rows = self._conn.execute(
        "SELECT id FROM emails WHERE processed_at >= datetime('now', ?)",
        (f"-{days} days",),
    ).fetchall()
    return {row["id"] for row in rows}
```

**Step 4: Run the tests to confirm they pass**

```
pytest tests/test_storage/test_db.py::TestGetStoredIdsSince -v
```

Expected: 4 PASSED

**Step 5: Run the full suite**

```
pytest tests/ -v --tb=short
```

Expected: all green

**Step 6: Commit**

```bash
git add src/storage/db.py tests/test_storage/test_db.py
git commit -m "feat(storage): add get_stored_ids_since() to EmailDatabase"
```

---

### Task 3: Add `get_emails_since()` to `GmailClient`

The `backfill` command needs to fetch all emails (read + unread) from the last N days. `GmailClient` currently only fetches unread emails.

**Files:**
- Modify: `src/mcp/gmail_client.py`
- Modify: `tests/test_mcp/test_gmail_client.py`

**Step 1: Write the failing tests**

Add to the bottom of `tests/test_mcp/test_gmail_client.py`. First check how the existing session fixture looks — it is a `MagicMock` with `call_tool` as an `AsyncMock`. Use the same `_tool_result()` helper already defined in that file.

```python
# ── get_emails_since ────────────────────────────────────────────────────────────


class TestGetEmailsSince:
    async def test_returns_emails_matching_date_query(
        self, client: GmailClient, session: MagicMock
    ) -> None:
        summaries = [{"message_id": "msg_1"}, {"message_id": "msg_2"}]
        full_messages = [
            {
                "message_id": "msg_1",
                "thread_id": "t1",
                "from": "alice@example.com",
                "subject": "Hello",
                "snippet": "Hi there",
                "body": "Full body",
                "date": "2026-02-20",
                "to": "me@example.com",
            },
            {
                "message_id": "msg_2",
                "thread_id": "t2",
                "from": "bob@example.com",
                "subject": "Check in",
                "snippet": "Just checking",
                "body": "Hey",
                "date": "2026-02-21",
                "to": "me@example.com",
            },
        ]
        session.call_tool = AsyncMock(
            side_effect=[_tool_result(summaries), _tool_result(full_messages)]
        )
        emails = await client.get_emails_since(days=7)
        assert len(emails) == 2
        assert emails[0].id == "msg_1"
        assert emails[1].id == "msg_2"

    async def test_returns_empty_list_when_no_emails_found(
        self, client: GmailClient, session: MagicMock
    ) -> None:
        session.call_tool = AsyncMock(return_value=_tool_result([]))
        emails = await client.get_emails_since(days=7)
        assert emails == []

    async def test_search_query_includes_after_date(
        self, client: GmailClient, session: MagicMock
    ) -> None:
        session.call_tool = AsyncMock(return_value=_tool_result([]))
        await client.get_emails_since(days=30)
        call_args = session.call_tool.call_args_list[0]
        arguments = call_args[0][1]
        assert "after:" in arguments["query"]
```

**Step 2: Run to confirm they fail**

```
pytest tests/test_mcp/test_gmail_client.py::TestGetEmailsSince -v
```

Expected: `AttributeError: 'GmailClient' object has no attribute 'get_emails_since'`

**Step 3: Implement `get_emails_since()` in `src/mcp/gmail_client.py`**

Add after `get_unread_emails()` in the `# ── Public API` section:

```python
async def get_emails_since(self, days: int, max_results: int = 500) -> list[RawEmail]:
    """Return all emails (read and unread) received in the last N days.

    Uses Gmail's ``after:YYYY/MM/DD`` search operator. The max_results cap
    defaults to 500 — the same limit used for startup ID seeding.
    """
    from datetime import datetime, timedelta

    since = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
    summaries = await self._call(
        "search_gmail_messages",
        {"query": f"after:{since}", "max_results": max_results},
    )
    if not isinstance(summaries, list) or not summaries:
        return []

    ids = [str(m.get("message_id", "")) for m in summaries if isinstance(m, dict)]
    ids = [i for i in ids if i]
    if not ids:
        return []

    messages = await self._call(
        "get_gmail_messages_content_batch",
        {"message_ids": ids, "user_google_email": self._user_email},
    )
    if not isinstance(messages, list):
        return []
    return [self._parse_email(m) for m in messages if isinstance(m, dict)]
```

**Step 4: Run the tests**

```
pytest tests/test_mcp/test_gmail_client.py::TestGetEmailsSince -v
```

Expected: 3 PASSED

**Step 5: Full suite**

```
pytest tests/ -v --tb=short
```

Expected: all green

**Step 6: Commit**

```bash
git add src/mcp/gmail_client.py tests/test_mcp/test_gmail_client.py
git commit -m "feat(mcp): add get_emails_since() to GmailClient for backfill support"
```

---

### Task 4: Add `rich` to project dependencies

`rich` is currently a transitive dependency of ChromaDB but is not declared explicitly. The CLI depends on it directly and needs it in `pyproject.toml`.

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add `rich` to dependencies**

In `pyproject.toml`, add `"rich>=13.0.0"` to the `dependencies` list:

```toml
dependencies = [
    "anthropic>=0.40.0",
    "chromadb>=0.5.0",
    "apscheduler>=3.10.0,<4.0",
    "click>=8.1.0",
    "python-dotenv>=1.0.0",
    "mcp>=1.0",
    "rich>=13.0.0",
]
```

**Step 2: Sync the environment**

```
uv sync
```

**Step 3: Verify the import works**

```
python -c "from rich.console import Console; Console().print('[green]rich ok[/green]')"
```

Expected: `rich ok` printed in green

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore(deps): add rich as explicit dependency"
```

---

### Task 5: Implement `QueryEngine`

The `QueryEngine` sits between CLI commands and the two stores. It exposes `search`, `get_emails_for_topic`, and `get_stored_ids_since`. Both stores are public attributes so `backfill` can pass them to `AnalysisProcessor` without creating duplicates.

**Files:**
- Create: `src/cli/query.py`
- Create: `tests/test_cli/test_query_engine.py`

Note: `src/cli/__init__.py` and `tests/test_cli/__init__.py` already exist.

**Step 1: Write the failing tests** — create `tests/test_cli/test_query_engine.py`:

```python
"""Tests for QueryEngine — both stores are mocked."""

from unittest.mock import MagicMock

import pytest

from src.cli.query import QueryEngine
from src.storage.models import EmailRow
from src.storage.vector_store import SearchResult


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _make_result(email_id: str = "msg_1", distance: float = 0.1) -> SearchResult:
    return SearchResult(
        email_id=email_id,
        distance=distance,
        metadata={
            "sender": "alice@example.com",
            "subject": "Budget review",
            "thread_id": "thread_1",
            "date": "2026-02-27",
            "priority": 2,
            "intent": "action_required",
            "sentiment": 0.2,
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
        sentiment=0.2,
        intent="action_required",
        priority=2,
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
```

**Step 2: Run to confirm they fail**

```
pytest tests/test_cli/test_query_engine.py -v
```

Expected: `ModuleNotFoundError: No module named 'src.cli.query'`

**Step 3: Create `src/cli/query.py`**

```python
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
```

**Step 4: Run the tests**

```
pytest tests/test_cli/test_query_engine.py -v
```

Expected: 8 PASSED

**Step 5: Full suite**

```
pytest tests/ -v --tb=short
```

Expected: all green

**Step 6: Commit**

```bash
git add src/cli/query.py tests/test_cli/test_query_engine.py
git commit -m "feat(cli): implement QueryEngine for cross-store CLI coordination"
```

---

### Task 6: CLI scaffold — `main.py` with click group and QueryEngine wiring

`pyproject.toml` already declares `email-agent = "src.cli.main:cli"`. This task creates the `cli` group and initialises `QueryEngine` in context so all commands share a single set of store instances.

**Files:**
- Create: `src/cli/main.py`

No dedicated test for the scaffold itself — it will be exercised by the command tests in Tasks 7–9.

**Step 1: Create `src/cli/main.py`**

```python
"""CLI entry point for the AI-powered email agent."""

import logging

import click
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """AI-powered email agent — search, status, and backfill commands."""
    load_dotenv()
    logging.basicConfig(
        level=logging.WARNING,  # keep CLI output clean; errors still surface
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )
    from pathlib import Path

    from src.cli.query import QueryEngine
    from src.storage.db import EmailDatabase
    from src.storage.vector_store import EmailVectorStore

    ctx.ensure_object(dict)
    db = EmailDatabase(db_path=Path("data/email_agent.db"))
    vector_store = EmailVectorStore(persist_dir=Path("data/chroma"))
    ctx.obj = QueryEngine(vector_store, db)
    ctx.call_on_close(ctx.obj.close)


# Import and register commands after cli is defined to avoid circular imports.
from src.cli.commands import backfill, search, status  # noqa: E402

cli.add_command(search)
cli.add_command(status)
cli.add_command(backfill)
```

**Step 2: Verify the CLI loads**

```
python -m src.cli.main --help
```

Expected: shows `search`, `status`, `backfill` subcommands (they don't exist yet so this will fail with an ImportError — that's expected and will be fixed in Tasks 7–9).

**Step 3: Commit** (after Tasks 7–9 pass — hold this commit)

---

### Task 7: `email search` command

**Files:**
- Create: `src/cli/commands.py`
- Create: `tests/test_cli/test_commands.py`

**Step 1: Write the failing tests** — create `tests/test_cli/test_commands.py`:

```python
"""Tests for CLI commands — QueryEngine is mocked, CliRunner used throughout."""

from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from src.cli.main import cli
from src.storage.models import EmailRow
from src.storage.vector_store import SearchResult


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _make_result(email_id: str = "msg_1") -> SearchResult:
    return SearchResult(
        email_id=email_id,
        distance=0.1,
        metadata={
            "sender": "alice@example.com",
            "subject": "Budget review",
            "thread_id": "thread_1",
            "date": "2026-02-27",
            "priority": 2,
            "intent": "action_required",
            "sentiment": -0.3,
            "requires_reply": True,
            "summary": "Alice wants the budget reviewed by Friday.",
        },
    )


def _make_row(email_id: str = "msg_1") -> EmailRow:
    return EmailRow(
        id=email_id,
        thread_id="thread_1",
        sender="alice@example.com",
        subject="Budget review",
        snippet="snippet",
        body="Please review the budget and respond by Friday.",
        date="2026-02-27",
        sentiment=-0.3,
        intent="action_required",
        priority=2,
        summary="Alice wants the budget reviewed by Friday.",
        requires_reply=True,
        deadline=None,
        entities='["Alice"]',
        processed_at="2026-02-27 09:00:00",
    )


def _runner_with_engine(engine: MagicMock) -> CliRunner:
    """Return a CliRunner that injects the mock engine into click context."""
    return CliRunner(mix_stderr=False)


def _invoke(engine: MagicMock, *args: str) -> "click.testing.Result":
    from click.testing import CliRunner

    runner = CliRunner(mix_stderr=False)
    with patch("src.cli.main.EmailDatabase"), patch(
        "src.cli.main.EmailVectorStore"
    ), patch("src.cli.main.QueryEngine", return_value=engine):
        return runner.invoke(cli, list(args), catch_exceptions=False)


# ── email search ─────────────────────────────────────────────────────────────────


class TestSearchCommand:
    def test_displays_results_table(self) -> None:
        engine = MagicMock()
        engine.search.return_value = [_make_result()]
        result = _invoke(engine, "search", "budget dispute")
        assert result.exit_code == 0
        assert "Budget review" in result.output
        assert "alice@example.com" in result.output

    def test_no_emails_indexed_message(self) -> None:
        engine = MagicMock()
        engine.search.return_value = []
        result = _invoke(engine, "search", "nothing")
        assert result.exit_code == 0
        assert "No emails indexed" in result.output

    def test_limit_option_passed_to_engine(self) -> None:
        engine = MagicMock()
        engine.search.return_value = []
        _invoke(engine, "search", "budget", "--limit", "5")
        engine.search.assert_called_once_with("budget", n=5)

    def test_default_limit_is_ten(self) -> None:
        engine = MagicMock()
        engine.search.return_value = []
        _invoke(engine, "search", "budget")
        engine.search.assert_called_once_with("budget", n=10)
```

**Step 2: Run to confirm they fail**

```
pytest tests/test_cli/test_commands.py::TestSearchCommand -v
```

Expected: `ModuleNotFoundError: No module named 'src.cli.commands'`

**Step 3: Create `src/cli/commands.py` with the `search` command**

```python
"""CLI command implementations — all commands delegate to QueryEngine."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import click
from rich import box
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from src.cli.query import QueryEngine

logger = logging.getLogger(__name__)
console = Console()

_PRIORITY_LABEL = {1: "CRITICAL", 2: "HIGH", 3: "MEDIUM", 4: "LOW", 5: "FYI"}
_PRIORITY_STYLE = {
    1: "red bold",
    2: "orange3",
    3: "yellow",
    4: "white",
    5: "dim",
}


@click.command()
@click.argument("query")
@click.option("--limit", default=10, show_default=True, help="Number of results.")
@click.pass_obj
def search(engine: QueryEngine, query: str, limit: int) -> None:
    """Semantic search over indexed emails."""
    results = engine.search(query, n=limit)

    if not results:
        console.print(
            "[yellow]No emails indexed yet. "
            "Run `email-agent backfill --days 30` to get started.[/yellow]"
        )
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Subject", max_width=38)
    table.add_column("From", max_width=26)
    table.add_column("Date", width=12)
    table.add_column("Priority", width=10)
    table.add_column("Score", width=6)

    for i, result in enumerate(results, start=1):
        m = result.metadata
        pri = int(m.get("priority", 3))
        pri_label = _PRIORITY_LABEL.get(pri, str(pri))
        pri_style = _PRIORITY_STYLE.get(pri, "white")
        score = f"{max(0.0, 1.0 - result.distance):.2f}"
        table.add_row(
            str(i),
            str(m.get("subject", "")),
            str(m.get("sender", "")),
            str(m.get("date", ""))[:10],
            f"[{pri_style}]{pri_label}[/{pri_style}]",
            score,
        )

    console.print(f"\nSearch results for [bold]{query!r}[/bold]\n")
    console.print(table)

    top = results[0].metadata
    if top.get("summary"):
        console.print(f"\n  [dim]Top result:[/dim] {top['summary']}")
```

**Step 4: Run the tests**

```
pytest tests/test_cli/test_commands.py::TestSearchCommand -v
```

Expected: 4 PASSED

**Step 5: Smoke-test from the terminal**

```
python -m src.cli.main search "test query"
```

Expected: either the "no emails indexed" message or a results table (depends on whether local DB has data)

**Step 6: Commit** (hold — bundle with status and backfill in Task 9 for a single clean commit)

---

### Task 8: `email status` command

**Files:**
- Modify: `src/cli/commands.py`
- Modify: `tests/test_cli/test_commands.py`

**Step 1: Write the failing tests**

Add to `tests/test_cli/test_commands.py`:

```python
# ── email status ─────────────────────────────────────────────────────────────────


class TestStatusCommand:
    def test_no_emails_found_message(self) -> None:
        engine = MagicMock()
        engine.get_emails_for_topic.return_value = []
        result = _invoke(engine, "status", "unknown topic")
        assert result.exit_code == 0
        assert "No emails found" in result.output

    def test_calls_engine_with_topic_and_limit(self) -> None:
        engine = MagicMock()
        engine.get_emails_for_topic.return_value = []
        _invoke(engine, "status", "Acme invoice", "--limit", "5")
        engine.get_emails_for_topic.assert_called_once_with("Acme invoice", n=5)

    def test_displays_sonnet_synthesis(self) -> None:
        engine = MagicMock()
        engine.get_emails_for_topic.return_value = [_make_row()]

        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="The invoice dispute is unresolved.")]

        with patch("src.cli.commands.AsyncAnthropic") as mock_anthropic:
            mock_client = MagicMock()
            mock_client.messages.create = asyncio.coroutine(
                lambda **kw: mock_response
            ) if False else MagicMock(
                return_value=_async_return(mock_response)
            )
            mock_anthropic.return_value = mock_client
            result = _invoke(engine, "status", "invoice dispute")

        assert result.exit_code == 0
        assert "invoice dispute is unresolved" in result.output
```

Add this helper above the test classes in `test_commands.py`:

```python
import asyncio as _asyncio


def _async_return(value: object) -> object:
    """Return an awaitable that resolves to value."""
    async def _inner() -> object:
        return value
    return _inner()
```

Also add `import asyncio` at the top of `tests/test_cli/test_commands.py`.

**Step 2: Run to confirm they fail**

```
pytest tests/test_cli/test_commands.py::TestStatusCommand -v
```

Expected: `ImportError` (status not defined yet)

**Step 3: Add the `status` command to `src/cli/commands.py`**

Add these imports near the top of `commands.py`:

```python
from anthropic import AsyncAnthropic
from rich.panel import Panel
```

Add the command after `search`:

```python
_STATUS_MODEL = "claude-sonnet-4-6"
_STATUS_MAX_TOKENS = 1024


@click.command()
@click.argument("topic")
@click.option("--limit", default=10, show_default=True, help="Emails to include.")
@click.pass_obj
def status(engine: QueryEngine, topic: str, limit: int) -> None:
    """Synthesise a thread status for a topic using Claude Sonnet."""
    asyncio.run(_status_async(engine, topic, limit))


async def _status_async(engine: QueryEngine, topic: str, limit: int) -> None:
    console.print(f"Fetching emails related to [bold]{topic!r}[/bold]...")
    rows = engine.get_emails_for_topic(topic, n=limit)

    if not rows:
        console.print("[yellow]No emails found for that topic.[/yellow]")
        return

    console.print(f"Found {len(rows)} email(s). Generating summary with Sonnet...")

    email_context = "\n\n---\n\n".join(
        f"From: {r.sender}\nDate: {r.date or 'unknown'}\n"
        f"Subject: {r.subject}\n\n{r.body or r.snippet}"
        for r in rows
    )
    prompt = (
        f"Here are {len(rows)} emails related to the topic '{topic}':\n\n"
        f"{email_context}\n\n"
        "Provide a concise status summary covering: current state, last action taken, "
        "who needs to respond next (if anyone), and recommended next step. "
        "Be specific — reference actual names, dates, and details from the emails."
    )

    client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    try:
        response = await client.messages.create(
            model=_STATUS_MODEL,
            max_tokens=_STATUS_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response.content[0].text if response.content else "(no response)"
    except Exception as exc:  # noqa: BLE001
        logger.error("Sonnet synthesis failed: %s", exc)
        console.print(f"[red]Synthesis failed: {exc}[/red]")
        console.print("\n[dim]Raw emails found:[/dim]")
        for row in rows:
            console.print(f"  • {row.subject} — {row.sender} ({row.date})")
        return

    console.print(Panel(summary, title=f"[bold]{topic}[/bold]", border_style="blue"))
```

**Step 4: Run the tests**

```
pytest tests/test_cli/test_commands.py::TestStatusCommand -v
```

Expected: 3 PASSED

**Step 5: Full command test suite**

```
pytest tests/test_cli/ -v
```

Expected: all green

---

### Task 9: `email backfill` command

**Files:**
- Modify: `src/cli/commands.py`
- Modify: `tests/test_cli/test_commands.py`

**Step 1: Write the failing tests**

Add to `tests/test_cli/test_commands.py`:

```python
# ── email backfill ───────────────────────────────────────────────────────────────


class TestBackfillCommand:
    def test_skips_already_stored_emails(self) -> None:
        engine = MagicMock()
        engine.get_stored_ids_since.return_value = {"msg_1", "msg_2"}

        from src.mcp.types import RawEmail

        all_emails = [
            RawEmail(
                id="msg_1", thread_id="t1", sender="a@b.com",
                subject="Old", snippet="old"
            ),
            RawEmail(
                id="msg_3", thread_id="t3", sender="c@d.com",
                subject="New", snippet="new", body="New email body."
            ),
        ]

        mock_gmail = MagicMock()
        mock_gmail.get_emails_since = MagicMock(
            return_value=_async_return(all_emails)
        )
        mock_gmail.__aenter__ = MagicMock(return_value=_async_return(mock_gmail))
        mock_gmail.__aexit__ = MagicMock(return_value=_async_return(None))

        mock_processor = MagicMock()
        mock_processor.process = MagicMock(return_value=_async_return(None))

        with patch("src.cli.commands.gmail_client", return_value=mock_gmail), patch(
            "src.cli.commands.EmailAnalyzer"
        ), patch("src.cli.commands.AnalysisProcessor", return_value=mock_processor):
            result = _invoke(engine, "backfill", "--days", "30")

        assert result.exit_code == 0
        assert "1 already stored" in result.output or "msg_3" in result.output or "1 new" in result.output

    def test_requires_days_option(self) -> None:
        engine = MagicMock()
        result = _invoke(engine, "backfill")
        assert result.exit_code != 0

    def test_nothing_to_do_when_all_stored(self) -> None:
        engine = MagicMock()
        engine.get_stored_ids_since.return_value = {"msg_1"}

        from src.mcp.types import RawEmail
        all_emails = [
            RawEmail(id="msg_1", thread_id="t1", sender="a@b.com", subject="Old", snippet="old"),
        ]

        mock_gmail = MagicMock()
        mock_gmail.get_emails_since = MagicMock(return_value=_async_return(all_emails))
        mock_gmail.__aenter__ = MagicMock(return_value=_async_return(mock_gmail))
        mock_gmail.__aexit__ = MagicMock(return_value=_async_return(None))

        with patch("src.cli.commands.gmail_client", return_value=mock_gmail):
            result = _invoke(engine, "backfill", "--days", "7")

        assert result.exit_code == 0
        assert "Nothing to do" in result.output
```

**Step 2: Run to confirm they fail**

```
pytest tests/test_cli/test_commands.py::TestBackfillCommand -v
```

Expected: `ImportError` (backfill not defined yet)

**Step 3: Add the `backfill` command to `src/cli/commands.py`**

Add these imports to the top of `commands.py`:

```python
from src.mcp.gmail_client import MCPError, gmail_client
from src.processing.analyzer import AnalysisProcessor, EmailAnalyzer
```

Add the command after `status`:

```python
@click.command()
@click.option("--days", required=True, type=int, help="Days of history to process.")
@click.option(
    "--rate-limit",
    default=1.0,
    show_default=True,
    help="Max Haiku API calls per second.",
)
@click.pass_obj
def backfill(engine: QueryEngine, days: int, rate_limit: float) -> None:
    """Process historical emails from the last N days."""
    asyncio.run(_backfill_async(engine, days, rate_limit))


async def _backfill_async(engine: QueryEngine, days: int, rate_limit: float) -> None:
    import asyncio as _asyncio

    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

    stored_ids = engine.get_stored_ids_since(days)

    try:
        async with gmail_client() as gmail:
            console.print(f"Fetching all emails from the last {days} day(s)...")
            all_emails = await gmail.get_emails_since(days)
    except MCPError as exc:
        console.print(f"[red]Gmail MCP error: {exc}[/red]")
        return

    new_emails = [e for e in all_emails if e.id not in stored_ids]
    console.print(
        f"Found {len(all_emails)} email(s). "
        f"[dim]{len(stored_ids)} already stored,[/dim] "
        f"[bold]{len(new_emails)} new.[/bold]"
    )

    if not new_emails:
        console.print("[green]Nothing to do.[/green]")
        return

    delay = 1.0 / rate_limit
    processed = 0
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Processing...", total=len(new_emails))
        analyzer = EmailAnalyzer()

        async with gmail_client() as gmail:
            processor = AnalysisProcessor(
                analyzer=analyzer,
                gmail=gmail,
                vector_store=engine.vector_store,
                db=engine.db,
            )
            for email in new_emails:
                try:
                    await processor.process(email)
                    processed += 1
                except Exception as exc:  # noqa: BLE001
                    logger.error("Backfill: failed on email %s: %s", email.id, exc)
                    failed += 1
                finally:
                    progress.advance(task)
                    await _asyncio.sleep(delay)

    console.print(
        f"[green]Done.[/green] {processed} processed"
        + (f", [red]{failed} failed[/red]" if failed else "")
        + "."
    )
```

**Step 4: Run the backfill tests**

```
pytest tests/test_cli/test_commands.py::TestBackfillCommand -v
```

Expected: 3 PASSED

**Step 5: Run the full test suite**

```
pytest tests/ -v --tb=short
```

Expected: all 126 existing + ~25 new = green

**Step 6: Smoke-test the CLI help**

```
python -m src.cli.main --help
python -m src.cli.main search --help
python -m src.cli.main status --help
python -m src.cli.main backfill --help
```

Expected: all three subcommands listed with correct options

**Step 7: Commit everything**

```bash
git add src/cli/main.py src/cli/commands.py tests/test_cli/test_commands.py
git commit -m "feat(cli): implement search, status, and backfill commands with QueryEngine"
```

---

## Summary

| Task | Files changed | Tests added |
|------|--------------|-------------|
| 1 — EmailRow + get_email_by_id | models.py, db.py, test_db.py | 3 |
| 2 — get_stored_ids_since | db.py, test_db.py | 4 |
| 3 — get_emails_since | gmail_client.py, test_gmail_client.py | 3 |
| 4 — Add rich dep | pyproject.toml | 0 |
| 5 — QueryEngine | cli/query.py, test_query_engine.py | 8 |
| 6 — CLI scaffold | cli/main.py | 0 |
| 7 — search command | cli/commands.py, test_commands.py | 4 |
| 8 — status command | cli/commands.py, test_commands.py | 3 |
| 9 — backfill command | cli/commands.py, test_commands.py | 3 |
| **Total** | | **~28 new tests** |

After all tasks: run `pytest tests/ --cov=src --cov-report=term-missing` to verify coverage.
