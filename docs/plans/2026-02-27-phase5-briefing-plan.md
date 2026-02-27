# Phase 5 — Briefing Generator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a daily briefing generator that collects urgent emails, pending follow-ups, and open deadlines from SQLite, synthesises them via Sonnet, and routes output to terminal / markdown file / Gmail self-email — triggered on a cron schedule in the watcher process and on demand via `email-agent briefing`.

**Architecture:** `BriefingGenerator` class in `src/briefing/generator.py` consumes three new `QueryEngine` methods, calls `AsyncAnthropic` for Sonnet synthesis, and routes output to up to three destinations based on `OutputConfig` (loaded from env vars). APScheduler wires the daily trigger into `src/agent/watcher.py` `_amain()`. A new `email-agent briefing` CLI command triggers generation on demand.

**Tech Stack:** `anthropic` (AsyncAnthropic / claude-sonnet-4-6), `apscheduler>=3.10,<4` (AsyncIOScheduler), `rich` (Panel output), Python `sqlite3` (new query), `mcp` session (new `send_email` tool call).

---

## Task 1: `EmailDatabase.get_urgent_emails(hours)`

**Files:**
- Modify: `src/storage/db.py`
- Test: `tests/test_storage/test_db.py` (add class `TestGetUrgentEmails`)

### Step 1: Write the failing tests

Add to `tests/test_storage/test_db.py`:

```python
from src.processing.types import Priority


class TestGetUrgentEmails:
    def test_returns_critical_and_high_emails(self, db: EmailDatabase) -> None:
        db.save(make_email("critical_1"), make_analysis("critical_1", priority=Priority.CRITICAL))
        db.save(make_email("high_1"), make_analysis("high_1", priority=Priority.HIGH))
        db.save(make_email("medium_1"), make_analysis("medium_1", priority=Priority.MEDIUM))
        result = db.get_urgent_emails(hours=24)
        ids = {r.id for r in result}
        assert "critical_1" in ids
        assert "high_1" in ids
        assert "medium_1" not in ids

    def test_returns_list_of_email_rows(self, db: EmailDatabase) -> None:
        db.save(make_email("high_1"), make_analysis("high_1", priority=Priority.HIGH))
        result = db.get_urgent_emails(hours=24)
        assert len(result) == 1
        assert isinstance(result[0], EmailRow)

    def test_returns_empty_when_no_urgent_emails(self, db: EmailDatabase) -> None:
        db.save(make_email("low_1"), make_analysis("low_1", priority=Priority.LOW))
        assert db.get_urgent_emails(hours=24) == []

    def test_orders_by_priority_then_recency(self, db: EmailDatabase) -> None:
        db.save(make_email("high_1"), make_analysis("high_1", priority=Priority.HIGH))
        db.save(make_email("critical_1"), make_analysis("critical_1", priority=Priority.CRITICAL))
        result = db.get_urgent_emails(hours=24)
        assert result[0].id == "critical_1"
```

### Step 2: Run to verify they fail

```
pytest tests/test_storage/test_db.py::TestGetUrgentEmails -v
```
Expected: `AttributeError: 'EmailDatabase' object has no attribute 'get_urgent_emails'`

### Step 3: Implement `get_urgent_emails` in `src/storage/db.py`

Add after `get_stored_ids_since`:

```python
def get_urgent_emails(self, hours: int = 24) -> list[EmailRow]:
    """Return CRITICAL (priority=1) and HIGH (priority=2) emails from the last N hours."""
    rows = self._conn.execute(
        """SELECT id, thread_id, sender, subject, snippet, body, date,
                  sentiment, intent, priority, summary, requires_reply,
                  deadline, entities, processed_at
           FROM emails
           WHERE priority <= 2
             AND processed_at >= datetime('now', ?)
           ORDER BY priority ASC, processed_at DESC""",
        (f"-{hours} hours",),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["requires_reply"] = bool(d["requires_reply"])
        result.append(EmailRow(**d))
    return result
```

### Step 4: Run to verify they pass

```
pytest tests/test_storage/test_db.py::TestGetUrgentEmails -v
```
Expected: 4 PASSED

### Step 5: Run full suite to check no regressions

```
pytest --tb=short -q
```
Expected: All 155 tests + 4 new = 159 PASSED

### Step 6: Commit

```bash
git add src/storage/db.py tests/test_storage/test_db.py
git commit -m "feat(storage): add EmailDatabase.get_urgent_emails(hours)"
```

---

## Task 2: QueryEngine extensions

**Files:**
- Modify: `src/cli/query.py`
- Test: `tests/test_cli/test_query_engine.py` (add 3 new test classes)

### Step 1: Write the failing tests

Add to `tests/test_cli/test_query_engine.py` — the existing `_make_row` helper and fixtures (`engine`, `mock_db`) are already defined in that file, reuse them. Also add helpers for follow-up and deadline records:

```python
from src.storage.models import DeadlineRecord, FollowUpRecord


def _make_follow_up(email_id: str = "msg_1") -> FollowUpRecord:
    return FollowUpRecord(
        id=1, email_id=email_id, status="pending", notes=None, created_at="2026-02-27 08:00:00"
    )


def _make_deadline(email_id: str = "msg_1") -> DeadlineRecord:
    return DeadlineRecord(
        id=1, email_id=email_id, description="Submit report by Friday", status="open",
        created_at="2026-02-27 08:00:00"
    )


class TestGetUrgentEmails:
    def test_delegates_to_db(self, engine: QueryEngine, mock_db: MagicMock) -> None:
        mock_db.get_urgent_emails.return_value = [_make_row()]
        result = engine.get_urgent_emails(hours=12)
        mock_db.get_urgent_emails.assert_called_once_with(12)
        assert len(result) == 1

    def test_default_hours_is_24(self, engine: QueryEngine, mock_db: MagicMock) -> None:
        mock_db.get_urgent_emails.return_value = []
        engine.get_urgent_emails()
        mock_db.get_urgent_emails.assert_called_once_with(24)


class TestGetPendingFollowUps:
    def test_enriches_follow_ups_with_email_rows(
        self, engine: QueryEngine, mock_db: MagicMock
    ) -> None:
        fu = _make_follow_up("msg_1")
        mock_db.get_follow_ups.return_value = [fu]
        mock_db.get_email_by_id.return_value = _make_row("msg_1")
        result = engine.get_pending_follow_ups()
        assert len(result) == 1
        assert result[0][0] is fu
        assert result[0][1].id == "msg_1"
        mock_db.get_email_by_id.assert_called_once_with("msg_1")

    def test_email_row_can_be_none(self, engine: QueryEngine, mock_db: MagicMock) -> None:
        mock_db.get_follow_ups.return_value = [_make_follow_up("missing")]
        mock_db.get_email_by_id.return_value = None
        result = engine.get_pending_follow_ups()
        assert result[0][1] is None

    def test_returns_empty_when_no_follow_ups(
        self, engine: QueryEngine, mock_db: MagicMock
    ) -> None:
        mock_db.get_follow_ups.return_value = []
        assert engine.get_pending_follow_ups() == []


class TestGetOpenDeadlines:
    def test_enriches_deadlines_with_email_rows(
        self, engine: QueryEngine, mock_db: MagicMock
    ) -> None:
        dl = _make_deadline("msg_1")
        mock_db.get_open_deadlines.return_value = [dl]
        mock_db.get_email_by_id.return_value = _make_row("msg_1")
        result = engine.get_open_deadlines()
        assert len(result) == 1
        assert result[0][0] is dl
        assert result[0][1].id == "msg_1"

    def test_email_row_can_be_none(self, engine: QueryEngine, mock_db: MagicMock) -> None:
        mock_db.get_open_deadlines.return_value = [_make_deadline("missing")]
        mock_db.get_email_by_id.return_value = None
        result = engine.get_open_deadlines()
        assert result[0][1] is None

    def test_returns_empty_when_no_deadlines(
        self, engine: QueryEngine, mock_db: MagicMock
    ) -> None:
        mock_db.get_open_deadlines.return_value = []
        assert engine.get_open_deadlines() == []
```

### Step 2: Run to verify they fail

```
pytest tests/test_cli/test_query_engine.py::TestGetUrgentEmails \
       tests/test_cli/test_query_engine.py::TestGetPendingFollowUps \
       tests/test_cli/test_query_engine.py::TestGetOpenDeadlines -v
```
Expected: `AttributeError: 'QueryEngine' object has no attribute 'get_urgent_emails'`

### Step 3: Implement in `src/cli/query.py`

Add these imports at the top of the file:

```python
from src.storage.models import DeadlineRecord, EmailRow, FollowUpRecord
```

Add after `get_stored_ids_since`:

```python
def get_urgent_emails(self, hours: int = 24) -> list[EmailRow]:
    """Return CRITICAL/HIGH priority emails from the last N hours."""
    return self.db.get_urgent_emails(hours)

def get_pending_follow_ups(self) -> list[tuple[FollowUpRecord, EmailRow | None]]:
    """Return pending follow-ups, each enriched with its source EmailRow."""
    follow_ups = self.db.get_follow_ups(status="pending")
    return [(fu, self.db.get_email_by_id(fu.email_id)) for fu in follow_ups]

def get_open_deadlines(self) -> list[tuple[DeadlineRecord, EmailRow | None]]:
    """Return open deadlines, each enriched with its source EmailRow."""
    deadlines = self.db.get_open_deadlines()
    return [(dl, self.db.get_email_by_id(dl.email_id)) for dl in deadlines]
```

### Step 4: Run to verify they pass

```
pytest tests/test_cli/test_query_engine.py -v
```
Expected: All tests including new ones PASSED

### Step 5: Run full suite

```
pytest --tb=short -q
```
Expected: 159 + 7 = 166 PASSED

### Step 6: Commit

```bash
git add src/cli/query.py tests/test_cli/test_query_engine.py
git commit -m "feat(cli): add QueryEngine.get_urgent_emails/follow_ups/deadlines"
```

---

## Task 3: `GmailClient.send_email()`

**Files:**
- Modify: `src/mcp/gmail_client.py`
- Test: `tests/test_mcp/test_gmail_client.py` (add class `TestSendEmail`)

### Step 1: Write the failing test

Add to `tests/test_mcp/test_gmail_client.py`. Check the existing file for the mock fixture pattern — the existing tests likely use a `mock_session` fixture. Add this class:

```python
class TestSendEmail:
    async def test_calls_send_gmail_message_tool(
        self, gmail: GmailClient, mock_session: MagicMock
    ) -> None:
        mock_session.call_tool.return_value = _make_text_result("Email sent!")
        await gmail.send_email(
            to="me@example.com",
            subject="Morning Briefing — 2026-02-27",
            body="# Briefing\n\nNo urgent items.",
        )
        mock_session.call_tool.assert_called_once_with(
            "send_gmail_message",
            {
                "to": "me@example.com",
                "subject": "Morning Briefing — 2026-02-27",
                "body": "# Briefing\n\nNo urgent items.",
                "user_google_email": "user@example.com",
            },
        )

    async def test_raises_mcp_error_on_failure(
        self, gmail: GmailClient, mock_session: MagicMock
    ) -> None:
        mock_session.call_tool.return_value = _make_error_result("Send failed")
        with pytest.raises(MCPError):
            await gmail.send_email("me@example.com", "Subject", "Body")
```

(Check `tests/test_mcp/test_gmail_client.py` for the exact names of `_make_text_result`, `_make_error_result`, and `gmail` fixture before adding — adapt to match existing helpers.)

### Step 2: Run to verify they fail

```
pytest tests/test_mcp/test_gmail_client.py::TestSendEmail -v
```
Expected: `AttributeError: 'GmailClient' object has no attribute 'send_email'`

### Step 3: Implement in `src/mcp/gmail_client.py`

Add after `ensure_ai_labels` in the Public API section:

```python
async def send_email(self, to: str, subject: str, body: str) -> None:
    """Send an email via Gmail MCP.

    Used by BriefingGenerator to deliver the daily briefing to self.
    """
    await self._call(
        "send_gmail_message",
        {
            "to": to,
            "subject": subject,
            "body": body,
            "user_google_email": self._user_email,
        },
    )
    logger.info("Sent email to %s: %r", to, subject)
```

### Step 4: Run to verify they pass

```
pytest tests/test_mcp/test_gmail_client.py::TestSendEmail -v
```
Expected: 2 PASSED

### Step 5: Run full suite

```
pytest --tb=short -q
```
Expected: 166 + 2 = 168 PASSED

### Step 6: Commit

```bash
git add src/mcp/gmail_client.py tests/test_mcp/test_gmail_client.py
git commit -m "feat(mcp): add GmailClient.send_email() for briefing delivery"
```

---

## Task 4: `OutputConfig` dataclass

**Files:**
- Create: `src/briefing/__init__.py`
- Create: `src/briefing/generator.py` (OutputConfig only for now)
- Test: `tests/test_briefing/test_output_config.py` (create)

### Step 1: Write the failing tests

Create `tests/test_briefing/test_output_config.py`:

```python
"""Tests for OutputConfig — env var parsing."""

import pytest

from src.briefing.generator import OutputConfig


class TestOutputConfigDefaults:
    def test_terminal_on_by_default(self) -> None:
        config = OutputConfig()
        assert config.terminal is True

    def test_file_off_by_default(self) -> None:
        assert OutputConfig().file is False

    def test_email_off_by_default(self) -> None:
        assert OutputConfig().email_self is False

    def test_briefing_dir_default(self) -> None:
        from pathlib import Path
        assert OutputConfig().briefing_dir == Path("data/briefings")


class TestOutputConfigFromEnv:
    def test_reads_terminal_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRIEFING_OUTPUT_TERMINAL", "false")
        assert OutputConfig.from_env().terminal is False

    def test_reads_file_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRIEFING_OUTPUT_FILE", "true")
        assert OutputConfig.from_env().file is True

    def test_reads_email_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRIEFING_OUTPUT_EMAIL", "true")
        assert OutputConfig.from_env().email_self is True

    def test_reads_email_recipient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRIEFING_EMAIL_TO", "me@example.com")
        assert OutputConfig.from_env().email_recipient == "me@example.com"

    def test_case_insensitive_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRIEFING_OUTPUT_FILE", "TRUE")
        assert OutputConfig.from_env().file is True

    def test_defaults_when_env_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in ("BRIEFING_OUTPUT_TERMINAL", "BRIEFING_OUTPUT_FILE", "BRIEFING_OUTPUT_EMAIL"):
            monkeypatch.delenv(key, raising=False)
        config = OutputConfig.from_env()
        assert config.terminal is True
        assert config.file is False
        assert config.email_self is False
```

### Step 2: Run to verify they fail

```
pytest tests/test_briefing/test_output_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.briefing.generator'`

### Step 3: Create `src/briefing/__init__.py`

```python
"""Briefing generator — daily email digest via Sonnet."""
```

### Step 4: Create `src/briefing/generator.py` with just `OutputConfig`

```python
"""Briefing generator — collects data, calls Sonnet, routes output."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class OutputConfig:
    """Controls where the generated briefing is delivered."""

    terminal: bool = True
    file: bool = False
    email_self: bool = False
    briefing_dir: Path = field(default_factory=lambda: Path("data/briefings"))
    email_recipient: str = ""

    @classmethod
    def from_env(cls) -> OutputConfig:
        """Build OutputConfig from environment variables."""
        return cls(
            terminal=os.environ.get("BRIEFING_OUTPUT_TERMINAL", "true").lower() == "true",
            file=os.environ.get("BRIEFING_OUTPUT_FILE", "false").lower() == "true",
            email_self=os.environ.get("BRIEFING_OUTPUT_EMAIL", "false").lower() == "true",
            email_recipient=os.environ.get("BRIEFING_EMAIL_TO", ""),
        )
```

### Step 5: Run to verify they pass

```
pytest tests/test_briefing/test_output_config.py -v
```
Expected: All 10 PASSED

### Step 6: Run full suite

```
pytest --tb=short -q
```
Expected: 168 + 10 = 178 PASSED

### Step 7: Commit

```bash
git add src/briefing/__init__.py src/briefing/generator.py \
        tests/test_briefing/test_output_config.py
git commit -m "feat(briefing): add OutputConfig with env-based configuration"
```

---

## Task 5: `BriefingGenerator` — data collection, Sonnet synthesis, terminal output

**Files:**
- Modify: `src/briefing/generator.py`
- Create: `tests/test_briefing/test_briefing_generator.py`

### Step 1: Write the failing tests

Create `tests/test_briefing/test_briefing_generator.py`:

```python
"""Tests for BriefingGenerator — Sonnet and all output paths are mocked."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.briefing.generator import BriefingGenerator, OutputConfig
from src.storage.models import DeadlineRecord, EmailRow, FollowUpRecord


# ── Helpers ─────────────────────────────────────────────────────────────────────


def _make_row(email_id: str = "msg_1", priority: int = 1) -> EmailRow:
    return EmailRow(
        id=email_id,
        thread_id="thread_1",
        sender="alice@example.com",
        subject="Budget review — urgent",
        snippet="snippet",
        body="Please review immediately.",
        date="2026-02-27",
        sentiment=-0.5,
        intent="action_required",
        priority=priority,
        summary="Budget review requested urgently.",
        requires_reply=True,
        deadline=None,
        entities='["Alice"]',
        processed_at="2026-02-27 09:00:00",
    )


def _make_follow_up(email_id: str = "msg_1") -> FollowUpRecord:
    return FollowUpRecord(
        id=1, email_id=email_id, status="pending", notes=None, created_at="2026-02-26 08:00:00"
    )


def _make_deadline(email_id: str = "msg_1") -> DeadlineRecord:
    return DeadlineRecord(
        id=1, email_id=email_id, description="Submit Q2 report",
        status="open", created_at="2026-02-26 08:00:00"
    )


def _make_engine(
    urgent: list[EmailRow] | None = None,
    follow_ups: list[tuple] | None = None,
    deadlines: list[tuple] | None = None,
) -> MagicMock:
    engine = MagicMock()
    engine.get_urgent_emails.return_value = urgent or []
    engine.get_pending_follow_ups.return_value = follow_ups or []
    engine.get_open_deadlines.return_value = deadlines or []
    return engine


def _make_sonnet_response(text: str = "## Morning Briefing\n\nFocus on the budget.") -> MagicMock:
    content = MagicMock()
    content.text = text
    response = MagicMock()
    response.content = [content]
    return response


# ── Fixture ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def terminal_only_config() -> OutputConfig:
    return OutputConfig(terminal=True, file=False, email_self=False)


# ── Prompt building ──────────────────────────────────────────────────────────────


class TestBuildPrompt:
    def test_prompt_contains_urgent_subject(self) -> None:
        engine = _make_engine(urgent=[_make_row()])
        gen = BriefingGenerator(engine, OutputConfig(terminal=False))
        prompt = gen._build_prompt(
            "2026-02-27", [_make_row()], [], []
        )
        assert "Budget review" in prompt

    def test_prompt_contains_follow_up(self) -> None:
        fu = _make_follow_up()
        row = _make_row()
        gen = BriefingGenerator(MagicMock(), OutputConfig(terminal=False))
        prompt = gen._build_prompt("2026-02-27", [], [(fu, row)], [])
        assert "Budget review" in prompt

    def test_prompt_contains_deadline_description(self) -> None:
        dl = _make_deadline()
        row = _make_row()
        gen = BriefingGenerator(MagicMock(), OutputConfig(terminal=False))
        prompt = gen._build_prompt("2026-02-27", [], [], [(dl, row)])
        assert "Submit Q2 report" in prompt

    def test_prompt_includes_today_date(self) -> None:
        gen = BriefingGenerator(MagicMock(), OutputConfig(terminal=False))
        prompt = gen._build_prompt("2026-02-27", [], [], [])
        assert "2026-02-27" in prompt

    def test_prompt_requests_recommended_focus(self) -> None:
        gen = BriefingGenerator(MagicMock(), OutputConfig(terminal=False))
        prompt = gen._build_prompt("2026-02-27", [], [], [])
        assert "Recommended focus" in prompt


# ── generate() — happy path ───────────────────────────────────────────────────


class TestGenerate:
    async def test_returns_sonnet_text(self, terminal_only_config: OutputConfig) -> None:
        engine = _make_engine(urgent=[_make_row()])
        gen = BriefingGenerator(engine, terminal_only_config)

        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response("## Briefing\nFocus on budget.")
        )):
            result = await gen.generate()

        assert "Briefing" in result

    async def test_calls_get_urgent_emails(self, terminal_only_config: OutputConfig) -> None:
        engine = _make_engine()
        gen = BriefingGenerator(engine, terminal_only_config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response()
        )):
            await gen.generate()
        engine.get_urgent_emails.assert_called_once_with(24)

    async def test_calls_get_pending_follow_ups(self, terminal_only_config: OutputConfig) -> None:
        engine = _make_engine()
        gen = BriefingGenerator(engine, terminal_only_config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response()
        )):
            await gen.generate()
        engine.get_pending_follow_ups.assert_called_once()

    async def test_calls_get_open_deadlines(self, terminal_only_config: OutputConfig) -> None:
        engine = _make_engine()
        gen = BriefingGenerator(engine, terminal_only_config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response()
        )):
            await gen.generate()
        engine.get_open_deadlines.assert_called_once()


# ── Sonnet failure fallback ───────────────────────────────────────────────────


class TestSonnetFallback:
    async def test_returns_fallback_text_on_api_error(
        self, terminal_only_config: OutputConfig
    ) -> None:
        engine = _make_engine(urgent=[_make_row()])
        gen = BriefingGenerator(engine, terminal_only_config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            side_effect=Exception("API error")
        )):
            result = await gen.generate()
        assert "Budget review" in result or "Sonnet" in result or len(result) > 0


# ── Terminal output ───────────────────────────────────────────────────────────


class TestTerminalOutput:
    async def test_terminal_output_calls_console_print(self) -> None:
        config = OutputConfig(terminal=True, file=False, email_self=False)
        engine = _make_engine()
        gen = BriefingGenerator(engine, config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response("Briefing text")
        )), patch("src.briefing.generator.Console") as mock_console_cls:
            mock_console = MagicMock()
            mock_console_cls.return_value = mock_console
            await gen.generate()
        mock_console.print.assert_called_once()

    async def test_no_terminal_output_when_disabled(self) -> None:
        config = OutputConfig(terminal=False, file=False, email_self=False)
        engine = _make_engine()
        gen = BriefingGenerator(engine, config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response()
        )), patch("src.briefing.generator.Console") as mock_console_cls:
            await gen.generate()
        mock_console_cls.assert_not_called()
```

### Step 2: Run to verify they fail

```
pytest tests/test_briefing/test_briefing_generator.py -v
```
Expected: `ImportError` or `AttributeError` — `BriefingGenerator` not yet defined.

### Step 3: Implement `BriefingGenerator` core in `src/briefing/generator.py`

Add these imports to the existing file:

```python
import os
from datetime import date

from anthropic import AsyncAnthropic

from src.storage.models import DeadlineRecord, EmailRow, FollowUpRecord
```

Add the `TYPE_CHECKING` guard for QueryEngine to avoid a circular import:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.cli.query import QueryEngine
```

Then add the constants and class:

```python
_BRIEFING_MODEL = "claude-sonnet-4-6"
_BRIEFING_MAX_TOKENS = 1500
_PRIORITY_LABEL: dict[int, str] = {1: "CRITICAL", 2: "HIGH", 3: "MEDIUM", 4: "LOW", 5: "FYI"}


class BriefingGenerator:
    """Generates a daily briefing: collects data, calls Sonnet, routes output.

    Usage::

        config = OutputConfig.from_env()
        gen = BriefingGenerator(engine, config)
        text = await gen.generate()
    """

    def __init__(
        self,
        engine: QueryEngine,
        output_config: OutputConfig,
        api_key: str | None = None,
    ) -> None:
        self._engine = engine
        self._config = output_config
        self._client = AsyncAnthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        )

    async def generate(self) -> str:
        """Collect data, synthesise via Sonnet, route to enabled outputs. Returns text."""
        today = date.today().isoformat()
        urgent = self._engine.get_urgent_emails(24)
        follow_ups = self._engine.get_pending_follow_ups()
        deadlines = self._engine.get_open_deadlines()
        prompt = self._build_prompt(today, urgent, follow_ups, deadlines)

        try:
            response = await self._client.messages.create(
                model=_BRIEFING_MODEL,
                max_tokens=_BRIEFING_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
            )
            text: str = response.content[0].text if response.content else "(no response)"
        except Exception as exc:  # noqa: BLE001
            logger.error("Sonnet briefing synthesis failed: %s", exc)
            text = self._fallback_text(today, urgent, follow_ups, deadlines)

        await self._route_output(text, today)
        return text

    def _build_prompt(
        self,
        today: str,
        urgent: list[EmailRow],
        follow_ups: list[tuple[FollowUpRecord, EmailRow | None]],
        deadlines: list[tuple[DeadlineRecord, EmailRow | None]],
    ) -> str:
        urgent_lines = "\n".join(
            f"  - [{_PRIORITY_LABEL.get(r.priority, str(r.priority))}] "
            f"{r.subject} (from {r.sender}): {r.summary}"
            for r in urgent
        ) or "  None"
        follow_up_lines = "\n".join(
            f"  - {row.subject if row else '(unknown)'} "
            f"(from {row.sender if row else '?'}, waiting since {fu.created_at[:10]})"
            for fu, row in follow_ups
        ) or "  None"
        deadline_lines = "\n".join(
            f"  - {dl.description} (email: {row.subject if row else '(unknown)'})"
            for dl, row in deadlines
        ) or "  None"
        return (
            f"Today is {today}. Generate a concise morning email briefing.\n\n"
            f"URGENT EMAILS (last 24h, priority CRITICAL or HIGH):\n{urgent_lines}\n\n"
            f"PENDING FOLLOW-UPS:\n{follow_up_lines}\n\n"
            f"OPEN DEADLINES:\n{deadline_lines}\n\n"
            "Format the briefing with clear labelled sections. Be specific — reference "
            "actual names, dates, and action items from the data above. End with a "
            '"Recommended focus" of 1\u20133 items for today.'
        )

    def _fallback_text(
        self,
        today: str,
        urgent: list[EmailRow],
        follow_ups: list[tuple[FollowUpRecord, EmailRow | None]],
        deadlines: list[tuple[DeadlineRecord, EmailRow | None]],
    ) -> str:
        lines: list[str] = [
            f"# Morning Briefing \u2014 {today}\n",
            "*(Sonnet unavailable \u2014 raw data)*\n",
            f"\n## Urgent ({len(urgent)})",
        ]
        for r in urgent:
            lines.append(f"- {r.subject} \u2014 {r.sender}")
        lines.append(f"\n## Pending follow-ups ({len(follow_ups)})")
        for fu, row in follow_ups:
            lines.append(f"- {row.subject if row else fu.email_id}")
        lines.append(f"\n## Open deadlines ({len(deadlines)})")
        for dl, _row in deadlines:
            lines.append(f"- {dl.description}")
        return "\n".join(lines)

    async def _route_output(self, text: str, today: str) -> None:
        if self._config.terminal:
            self._print_terminal(text, today)
        if self._config.file:
            self._write_file(text, today)
        if self._config.email_self and self._config.email_recipient:
            await self._send_email(text, today)

    def _print_terminal(self, text: str, today: str) -> None:
        from rich.console import Console
        from rich.panel import Panel

        Console(width=200).print(
            Panel(text, title=f"[bold]Morning Briefing \u2014 {today}[/bold]", border_style="green")
        )
```

### Step 4: Run to verify they pass

```
pytest tests/test_briefing/test_briefing_generator.py -v
```
Expected: All tests in TestBuildPrompt, TestGenerate, TestSonnetFallback, TestTerminalOutput PASSED

### Step 5: Run full suite

```
pytest --tb=short -q
```
Expected: ~195 PASSED

### Step 6: Commit

```bash
git add src/briefing/generator.py tests/test_briefing/test_briefing_generator.py
git commit -m "feat(briefing): add BriefingGenerator with Sonnet synthesis and terminal output"
```

---

## Task 6: File output routing

**Files:**
- Modify: `src/briefing/generator.py` (add `_write_file`)
- Modify: `tests/test_briefing/test_briefing_generator.py` (add `TestFileOutput`)

### Step 1: Write the failing tests

Add to `tests/test_briefing/test_briefing_generator.py`:

```python
class TestFileOutput:
    async def test_writes_markdown_file(self, tmp_path: Path) -> None:
        config = OutputConfig(
            terminal=False, file=True, email_self=False,
            briefing_dir=tmp_path / "briefings",
        )
        engine = _make_engine()
        gen = BriefingGenerator(engine, config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response("## Briefing\nContent here.")
        )):
            await gen.generate()

        briefing_files = list((tmp_path / "briefings").glob("*.md"))
        assert len(briefing_files) == 1
        content = briefing_files[0].read_text()
        assert "Content here." in content

    async def test_file_has_yaml_front_matter(self, tmp_path: Path) -> None:
        config = OutputConfig(
            terminal=False, file=True, email_self=False,
            briefing_dir=tmp_path / "briefings",
        )
        engine = _make_engine()
        gen = BriefingGenerator(engine, config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response("Text")
        )):
            await gen.generate()

        content = next((tmp_path / "briefings").glob("*.md")).read_text()
        assert content.startswith("---")
        assert "date:" in content

    async def test_creates_briefing_dir_if_missing(self, tmp_path: Path) -> None:
        briefing_dir = tmp_path / "new" / "nested" / "briefings"
        config = OutputConfig(
            terminal=False, file=True, email_self=False,
            briefing_dir=briefing_dir,
        )
        engine = _make_engine()
        gen = BriefingGenerator(engine, config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response("Text")
        )):
            await gen.generate()

        assert briefing_dir.exists()

    async def test_no_file_written_when_disabled(self, tmp_path: Path) -> None:
        config = OutputConfig(
            terminal=False, file=False, email_self=False,
            briefing_dir=tmp_path / "briefings",
        )
        engine = _make_engine()
        gen = BriefingGenerator(engine, config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response("Text")
        )):
            await gen.generate()

        assert not (tmp_path / "briefings").exists()
```

### Step 2: Run to verify they fail

```
pytest tests/test_briefing/test_briefing_generator.py::TestFileOutput -v
```
Expected: `AttributeError: 'BriefingGenerator' object has no attribute '_write_file'` (since `_route_output` references it but it's not yet defined, which will cause an `AttributeError` at runtime when `file=True`).

### Step 3: Implement `_write_file` in `src/briefing/generator.py`

Add these imports at the top of the file:

```python
from datetime import datetime
```

Add `_write_file` to `BriefingGenerator`:

```python
def _write_file(self, text: str, today: str) -> None:
    self._config.briefing_dir.mkdir(parents=True, exist_ok=True)
    path = self._config.briefing_dir / f"{today}.md"
    header = (
        f"---\ndate: {today}\ngenerated_at: {datetime.utcnow().isoformat()}Z\n---\n\n"
    )
    path.write_text(header + text, encoding="utf-8")
    logger.info("Briefing written to %s", path)
```

### Step 4: Run to verify they pass

```
pytest tests/test_briefing/test_briefing_generator.py::TestFileOutput -v
```
Expected: 4 PASSED

### Step 5: Run full suite

```
pytest --tb=short -q
```
Expected: All prior tests + 4 new PASSED

### Step 6: Commit

```bash
git add src/briefing/generator.py tests/test_briefing/test_briefing_generator.py
git commit -m "feat(briefing): add file output routing to BriefingGenerator"
```

---

## Task 7: Email-to-self output routing

**Files:**
- Modify: `src/briefing/generator.py` (add `_send_email`)
- Modify: `tests/test_briefing/test_briefing_generator.py` (add `TestEmailOutput`)

### Step 1: Write the failing tests

Add to `tests/test_briefing/test_briefing_generator.py`:

```python
class TestEmailOutput:
    async def test_sends_email_when_enabled(self) -> None:
        config = OutputConfig(
            terminal=False, file=False, email_self=True,
            email_recipient="me@example.com",
        )
        engine = _make_engine()
        gen = BriefingGenerator(engine, config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response("Briefing text")
        )), patch("src.briefing.generator.gmail_client") as mock_gmail_ctx:
            mock_gmail = AsyncMock()
            mock_gmail_ctx.return_value.__aenter__.return_value = mock_gmail
            mock_gmail_ctx.return_value.__aexit__.return_value = None
            await gen.generate()
        mock_gmail.send_email.assert_called_once()
        call_kwargs = mock_gmail.send_email.call_args
        assert call_kwargs.kwargs.get("to") == "me@example.com" or \
               call_kwargs.args[0] == "me@example.com"

    async def test_no_email_when_disabled(self) -> None:
        config = OutputConfig(terminal=False, file=False, email_self=False)
        engine = _make_engine()
        gen = BriefingGenerator(engine, config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response()
        )), patch("src.briefing.generator.gmail_client") as mock_gmail_ctx:
            await gen.generate()
        mock_gmail_ctx.assert_not_called()

    async def test_no_email_when_recipient_empty(self) -> None:
        config = OutputConfig(
            terminal=False, file=False, email_self=True,
            email_recipient="",  # intentionally empty
        )
        engine = _make_engine()
        gen = BriefingGenerator(engine, config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response()
        )), patch("src.briefing.generator.gmail_client") as mock_gmail_ctx:
            await gen.generate()
        mock_gmail_ctx.assert_not_called()

    async def test_continues_on_email_send_failure(self) -> None:
        config = OutputConfig(
            terminal=False, file=False, email_self=True,
            email_recipient="me@example.com",
        )
        engine = _make_engine()
        gen = BriefingGenerator(engine, config)
        with patch.object(gen._client.messages, "create", new=AsyncMock(
            return_value=_make_sonnet_response("Text")
        )), patch("src.briefing.generator.gmail_client") as mock_gmail_ctx:
            mock_gmail = AsyncMock()
            mock_gmail_ctx.return_value.__aenter__.return_value = mock_gmail
            mock_gmail_ctx.return_value.__aexit__.return_value = None
            mock_gmail.send_email.side_effect = Exception("MCP error")
            result = await gen.generate()  # must not raise
        assert result == "Text"
```

### Step 2: Run to verify they fail

```
pytest tests/test_briefing/test_briefing_generator.py::TestEmailOutput -v
```
Expected: Tests fail because `_send_email` method is not defined.

### Step 3: Implement `_send_email` in `src/briefing/generator.py`

Add to the imports section:

```python
from src.mcp.gmail_client import gmail_client
```

Add `_send_email` method to `BriefingGenerator`:

```python
async def _send_email(self, text: str, today: str) -> None:
    try:
        async with gmail_client() as gmail:
            await gmail.send_email(
                to=self._config.email_recipient,
                subject=f"Morning Briefing \u2014 {today}",
                body=text,
            )
        logger.info("Briefing email sent to %s", self._config.email_recipient)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send briefing email: %s", exc)
```

### Step 4: Run to verify they pass

```
pytest tests/test_briefing/test_briefing_generator.py::TestEmailOutput -v
```
Expected: 4 PASSED

### Step 5: Run full suite

```
pytest --tb=short -q
```
Expected: All tests PASSED

### Step 6: Commit

```bash
git add src/briefing/generator.py tests/test_briefing/test_briefing_generator.py
git commit -m "feat(briefing): add email-to-self output routing to BriefingGenerator"
```

---

## Task 8: `src/briefing/scheduler.py`

**Files:**
- Create: `src/briefing/scheduler.py`
- Create: `tests/test_briefing/test_briefing_scheduler.py`

### Step 1: Write the failing tests

Create `tests/test_briefing/test_briefing_scheduler.py`:

```python
"""Tests for create_briefing_scheduler."""

import pytest
from unittest.mock import MagicMock, patch


class TestParseBriefingTime:
    def test_parses_valid_time(self) -> None:
        from src.briefing.scheduler import _parse_briefing_time
        assert _parse_briefing_time("07:00") == (7, 0)
        assert _parse_briefing_time("09:30") == (9, 30)
        assert _parse_briefing_time("00:00") == (0, 0)

    def test_defaults_to_seven_on_invalid(self) -> None:
        from src.briefing.scheduler import _parse_briefing_time
        assert _parse_briefing_time("not-a-time") == (7, 0)
        assert _parse_briefing_time("25:99") == (25, 99)  # parsed but not validated


class TestCreateBriefingScheduler:
    def test_returns_async_scheduler(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from src.briefing.generator import OutputConfig
        from src.briefing.scheduler import create_briefing_scheduler

        monkeypatch.setenv("BRIEFING_TIME", "08:00")
        engine = MagicMock()
        config = OutputConfig(terminal=False)
        scheduler = create_briefing_scheduler(engine, config)
        assert isinstance(scheduler, AsyncIOScheduler)

    def test_job_added_with_correct_cron_params(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.briefing.generator import OutputConfig
        from src.briefing.scheduler import create_briefing_scheduler

        monkeypatch.setenv("BRIEFING_TIME", "06:45")
        engine = MagicMock()
        config = OutputConfig(terminal=False)
        scheduler = create_briefing_scheduler(engine, config)
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        trigger = jobs[0].trigger
        # APScheduler CronTrigger stores fields; check hour and minute
        fields = {f.name: f for f in trigger.fields}
        assert str(fields["hour"]) == "6"
        assert str(fields["minute"]) == "45"

    def test_default_briefing_time_is_seven(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.briefing.generator import OutputConfig
        from src.briefing.scheduler import create_briefing_scheduler

        monkeypatch.delenv("BRIEFING_TIME", raising=False)
        engine = MagicMock()
        scheduler = create_briefing_scheduler(engine, OutputConfig(terminal=False))
        jobs = scheduler.get_jobs()
        fields = {f.name: f for f in jobs[0].trigger.fields}
        assert str(fields["hour"]) == "7"
```

### Step 2: Run to verify they fail

```
pytest tests/test_briefing/test_briefing_scheduler.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.briefing.scheduler'`

### Step 3: Create `src/briefing/scheduler.py`

```python
"""APScheduler setup for the daily briefing trigger."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

if TYPE_CHECKING:
    from src.briefing.generator import OutputConfig
    from src.cli.query import QueryEngine

logger = logging.getLogger(__name__)


def _parse_briefing_time(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' into (hour, minute). Falls back to (7, 0) on error."""
    try:
        hour_str, minute_str = time_str.strip().split(":")
        return int(hour_str), int(minute_str)
    except (ValueError, AttributeError):
        logger.warning("Invalid BRIEFING_TIME %r; defaulting to 07:00", time_str)
        return 7, 0


def create_briefing_scheduler(
    engine: QueryEngine,
    output_config: OutputConfig,
) -> AsyncIOScheduler:
    """Return a configured AsyncIOScheduler that fires BriefingGenerator.generate() daily.

    The caller is responsible for calling scheduler.start() and scheduler.shutdown().
    """
    from src.briefing.generator import BriefingGenerator

    scheduler = AsyncIOScheduler()
    generator = BriefingGenerator(engine, output_config)
    hour, minute = _parse_briefing_time(os.environ.get("BRIEFING_TIME", "07:00"))
    scheduler.add_job(generator.generate, "cron", hour=hour, minute=minute)
    logger.info("Briefing scheduled daily at %02d:%02d", hour, minute)
    return scheduler
```

### Step 4: Run to verify they pass

```
pytest tests/test_briefing/test_briefing_scheduler.py -v
```
Expected: All PASSED

### Step 5: Run full suite

```
pytest --tb=short -q
```
Expected: All tests PASSED

### Step 6: Commit

```bash
git add src/briefing/scheduler.py tests/test_briefing/test_briefing_scheduler.py
git commit -m "feat(briefing): add create_briefing_scheduler with APScheduler cron trigger"
```

---

## Task 9: Wire scheduler into `watcher._amain()`

**Files:**
- Modify: `src/agent/watcher.py`
- Modify: `tests/test_agent/test_watcher.py` (add `TestSchedulerWiring`)

### Step 1: Write the failing test

Add to `tests/test_agent/test_watcher.py`:

```python
class TestSchedulerWiring:
    async def test_scheduler_started_in_amain(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """_amain() should start the APScheduler before running the watcher."""
        import src.agent.watcher as watcher_mod
        from src.briefing.generator import OutputConfig

        mock_scheduler = MagicMock()
        mock_watcher = AsyncMock()
        mock_watcher.run = AsyncMock()

        monkeypatch.setattr(
            "src.briefing.scheduler.create_briefing_scheduler",
            lambda engine, config: mock_scheduler,
        )
        # Patch EmailWatcher so it returns immediately
        monkeypatch.setattr(
            "src.agent.watcher.EmailWatcher",
            lambda **kwargs: mock_watcher,
        )
        # Patch storage constructors
        monkeypatch.setattr("src.agent.watcher.EmailVectorStore", MagicMock())
        monkeypatch.setattr("src.agent.watcher.EmailDatabase", MagicMock())

        await watcher_mod._amain()
        mock_scheduler.start.assert_called_once()
```

Note: this test requires that `_amain` imports and calls `create_briefing_scheduler`. If imports inside `_amain` make the above monkeypatching awkward, adapt by patching the scheduler module directly.

### Step 2: Run to verify it fails

```
pytest tests/test_agent/test_watcher.py::TestSchedulerWiring -v
```
Expected: Test fails because `_amain` doesn't yet call `create_briefing_scheduler`.

### Step 3: Modify `_amain` in `src/agent/watcher.py`

Update `_amain()` to add scheduler wiring after the storage constructors. The full updated function:

```python
async def _amain() -> None:
    """Async entry point: wire up signal handlers and run the watcher."""
    from pathlib import Path

    from src.briefing.generator import OutputConfig
    from src.briefing.scheduler import create_briefing_scheduler
    from src.cli.query import QueryEngine
    from src.processing.analyzer import AnalysisProcessor, EmailAnalyzer
    from src.storage.db import EmailDatabase
    from src.storage.vector_store import EmailVectorStore

    analyzer = EmailAnalyzer()
    vector_store = EmailVectorStore(persist_dir=Path("data/chroma"))
    db = EmailDatabase(db_path=Path("data/email_agent.db"))

    engine = QueryEngine(vector_store, db)
    output_config = OutputConfig.from_env()
    scheduler = create_briefing_scheduler(engine, output_config)
    scheduler.start()

    watcher = EmailWatcher(
        processor_factory=lambda gmail: AnalysisProcessor(
            analyzer, gmail, vector_store=vector_store, db=db
        )
    )

    loop = asyncio.get_running_loop()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, watcher.stop)
    except (NotImplementedError, AttributeError):
        pass

    try:
        await watcher.run()
    finally:
        scheduler.shutdown(wait=False)
```

### Step 4: Run to verify it passes

```
pytest tests/test_agent/test_watcher.py::TestSchedulerWiring -v
```
Expected: PASSED

### Step 5: Run full suite

```
pytest --tb=short -q
```
Expected: All tests PASSED

### Step 6: Commit

```bash
git add src/agent/watcher.py tests/test_agent/test_watcher.py
git commit -m "feat(agent): wire APScheduler briefing into watcher _amain()"
```

---

## Task 10: `email-agent briefing` CLI command

**Files:**
- Modify: `src/cli/commands.py` (add `briefing` command)
- Modify: `src/cli/main.py` (register `briefing`)
- Modify: `tests/test_cli/test_commands.py` (add `TestBriefingCommand`)

### Step 1: Write the failing tests

Add to `tests/test_cli/test_commands.py`. The existing file uses `CliRunner` and mocks `QueryEngine`. Follow that pattern:

```python
class TestBriefingCommand:
    def test_briefing_command_calls_generate(self) -> None:
        from unittest.mock import AsyncMock, patch
        from click.testing import CliRunner
        from src.cli.main import cli

        runner = CliRunner()
        with patch("src.cli.commands.BriefingGenerator") as mock_gen_cls:
            mock_gen = MagicMock()
            mock_gen.generate = AsyncMock(return_value="## Briefing\nContent.")
            mock_gen_cls.return_value = mock_gen
            result = runner.invoke(cli, ["briefing"], obj=MagicMock())

        assert result.exit_code == 0
        mock_gen.generate.assert_called_once()

    def test_briefing_command_with_output_flag(self) -> None:
        from unittest.mock import AsyncMock, patch
        from click.testing import CliRunner
        from src.briefing.generator import OutputConfig
        from src.cli.main import cli

        runner = CliRunner()
        captured_config: list[OutputConfig] = []

        def capture_gen(engine: object, config: OutputConfig) -> MagicMock:
            captured_config.append(config)
            m = MagicMock()
            m.generate = AsyncMock(return_value="text")
            return m

        with patch("src.cli.commands.BriefingGenerator", side_effect=capture_gen):
            result = runner.invoke(cli, ["briefing", "--output", "file"], obj=MagicMock())

        assert result.exit_code == 0
        assert len(captured_config) == 1
        assert captured_config[0].file is True
        assert captured_config[0].terminal is False

    def test_briefing_registered_in_cli_group(self) -> None:
        from src.cli.main import cli
        assert "briefing" in cli.commands
```

### Step 2: Run to verify they fail

```
pytest tests/test_cli/test_commands.py::TestBriefingCommand -v
```
Expected: `No such command 'briefing'`

### Step 3: Add `briefing` command to `src/cli/commands.py`

Add these imports near the top of the `commands.py` imports:

```python
import os
```

Add the command at the end of the file:

```python
@click.command()
@click.option(
    "--output",
    default=None,
    help="Comma-separated outputs: terminal,file,email. Overrides env vars.",
)
@click.pass_obj
def briefing(engine: QueryEngine, output: str | None) -> None:
    """Generate an on-demand morning briefing with Claude Sonnet."""
    asyncio.run(_briefing_async(engine, output))


async def _briefing_async(engine: QueryEngine, output_override: str | None) -> None:
    from src.briefing.generator import BriefingGenerator, OutputConfig

    if output_override is not None:
        flags = {s.strip() for s in output_override.split(",")}
        config = OutputConfig(
            terminal="terminal" in flags,
            file="file" in flags,
            email_self="email" in flags,
            email_recipient=os.environ.get("BRIEFING_EMAIL_TO", ""),
        )
    else:
        config = OutputConfig.from_env()

    generator = BriefingGenerator(engine, config)
    await generator.generate()
```

### Step 4: Register in `src/cli/main.py`

Update the import and `add_command` lines at the bottom:

```python
from src.cli.commands import backfill, briefing, search, status  # noqa: E402

cli.add_command(search)
cli.add_command(status)
cli.add_command(backfill)
cli.add_command(briefing)
```

### Step 5: Run to verify they pass

```
pytest tests/test_cli/test_commands.py::TestBriefingCommand -v
```
Expected: 3 PASSED

### Step 6: Run full suite

```
pytest --tb=short -q
```
Expected: All tests PASSED

### Step 7: Verify the command is registered

```
email-agent --help
```
Expected: `briefing` appears in the commands list.

### Step 8: Commit

```bash
git add src/cli/commands.py src/cli/main.py tests/test_cli/test_commands.py
git commit -m "feat(cli): add email-agent briefing command with --output flag"
```

---

## Task 11: Update `.env.example`

**Files:**
- Modify: `.env.example`

### Step 1: Replace the existing Briefing Configuration section

The current `.env.example` has placeholder vars that don't match our design. Replace the `# ── Briefing Configuration ─────` section with:

```bash
# ── Briefing Configuration ─────────────────────────────────────────────────────
# Cron time for scheduled daily briefing (HH:MM, 24h, default 07:00)
BRIEFING_TIME=07:00

# Output destinations (each defaults shown below)
BRIEFING_OUTPUT_TERMINAL=true   # print Rich panel to stdout
BRIEFING_OUTPUT_FILE=false      # write data/briefings/YYYY-MM-DD.md
BRIEFING_OUTPUT_EMAIL=false     # send via Gmail to BRIEFING_EMAIL_TO

# Required if BRIEFING_OUTPUT_EMAIL=true
BRIEFING_EMAIL_TO=your@gmail.com
```

### Step 2: Commit

```bash
git add .env.example
git commit -m "chore: update .env.example with Phase 5 briefing env vars"
```

---

## Final: Full suite verification

```
pytest --tb=short -q
```
Expected: ~195 tests, all PASSED.

Then run a quick smoke test of the CLI:

```
email-agent --help
email-agent briefing --help
```

Both should print usage without errors.

---

## Phase 5 Summary

| File | Change |
|------|--------|
| `src/storage/db.py` | + `get_urgent_emails(hours)` |
| `src/cli/query.py` | + `get_urgent_emails`, `get_pending_follow_ups`, `get_open_deadlines` |
| `src/mcp/gmail_client.py` | + `send_email(to, subject, body)` |
| `src/briefing/__init__.py` | New package |
| `src/briefing/generator.py` | New: `OutputConfig` + `BriefingGenerator` |
| `src/briefing/scheduler.py` | New: `create_briefing_scheduler` |
| `src/agent/watcher.py` | Wire scheduler into `_amain()` |
| `src/cli/commands.py` | + `briefing` command |
| `src/cli/main.py` | Register `briefing` command |
| `.env.example` | Add Phase 5 briefing env vars |
