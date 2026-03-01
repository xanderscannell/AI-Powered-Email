# Schema Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the Priority/Intent/sentiment classification system with a human-vs-automated split plus domain categorisation, updating every layer from the analysis schema through to the CLI and briefing output.

**Architecture:** The primary split is `EmailType` (human | automated). Automated emails get a `Domain` label (`AI/Automated/<Domain>`). Human emails land in `AI/Human` with an optional `AI/Human/FollowUp` sub-label. Sentiment, priority, and intent fields are removed from all layers.

**Tech Stack:** Python 3.13, uv, pytest, Anthropic SDK (tool_use), ChromaDB, SQLite, click, rich

**Design doc:** `docs/plans/2026-02-28-schema-redesign-design.md`

---

### Task 1: Replace enums and EmailAnalysis in `processing/types.py`

**Files:**
- Modify: `src/processing/types.py`
- Modify: `tests/test_processing/test_types.py`

**Step 1: Rewrite the test file**

Replace the entire contents of `tests/test_processing/test_types.py` with:

```python
"""Tests for processing type definitions, enums, and label mappings."""

import pytest

from src.processing.types import (
    DOMAIN_LABEL,
    HUMAN_LABEL,
    HUMAN_FOLLOWUP_LABEL,
    Domain,
    EmailAnalysis,
    EmailType,
)


# ── EmailType ────────────────────────────────────────────────────────────────────


class TestEmailType:
    def test_values(self) -> None:
        assert EmailType.HUMAN == "human"
        assert EmailType.AUTOMATED == "automated"

    def test_is_str_enum(self) -> None:
        assert isinstance(EmailType.HUMAN, str)

    def test_round_trip(self) -> None:
        for t in EmailType:
            assert EmailType(t.value) is t


# ── Domain ───────────────────────────────────────────────────────────────────────


class TestDomain:
    def test_all_values_present(self) -> None:
        expected = {
            "finance", "shopping", "travel", "health", "government",
            "work", "education", "newsletter", "marketing", "social",
            "alerts", "other",
        }
        assert {d.value for d in Domain} == expected

    def test_is_str_enum(self) -> None:
        assert isinstance(Domain.FINANCE, str)

    def test_round_trip(self) -> None:
        for d in Domain:
            assert Domain(d.value) is d


# ── Label mappings ───────────────────────────────────────────────────────────────


class TestDomainLabel:
    def test_all_domains_have_a_label(self) -> None:
        for d in Domain:
            assert d in DOMAIN_LABEL, f"Missing label for {d}"

    def test_label_format(self) -> None:
        assert DOMAIN_LABEL[Domain.FINANCE] == "AI/Automated/Finance"
        assert DOMAIN_LABEL[Domain.SHOPPING] == "AI/Automated/Shopping"
        assert DOMAIN_LABEL[Domain.TRAVEL] == "AI/Automated/Travel"
        assert DOMAIN_LABEL[Domain.HEALTH] == "AI/Automated/Health"
        assert DOMAIN_LABEL[Domain.GOVERNMENT] == "AI/Automated/Government"
        assert DOMAIN_LABEL[Domain.WORK] == "AI/Automated/Work"
        assert DOMAIN_LABEL[Domain.EDUCATION] == "AI/Automated/Education"
        assert DOMAIN_LABEL[Domain.NEWSLETTER] == "AI/Automated/Newsletter"
        assert DOMAIN_LABEL[Domain.MARKETING] == "AI/Automated/Marketing"
        assert DOMAIN_LABEL[Domain.SOCIAL] == "AI/Automated/Social"
        assert DOMAIN_LABEL[Domain.ALERTS] == "AI/Automated/Alerts"
        assert DOMAIN_LABEL[Domain.OTHER] == "AI/Automated/Other"


class TestHumanLabels:
    def test_human_label(self) -> None:
        assert HUMAN_LABEL == "AI/Human"

    def test_followup_label(self) -> None:
        assert HUMAN_FOLLOWUP_LABEL == "AI/Human/FollowUp"


# ── EmailAnalysis ────────────────────────────────────────────────────────────────


class TestEmailAnalysis:
    def _make(self, **kwargs: object) -> EmailAnalysis:
        defaults: dict[str, object] = dict(
            email_id="msg_1",
            email_type=EmailType.HUMAN,
            domain=None,
        )
        return EmailAnalysis(**{**defaults, **kwargs})  # type: ignore[arg-type]

    def test_required_fields_are_stored(self) -> None:
        a = self._make(email_type=EmailType.AUTOMATED, domain=Domain.FINANCE)
        assert a.email_id == "msg_1"
        assert a.email_type == EmailType.AUTOMATED
        assert a.domain == Domain.FINANCE

    def test_human_email_has_no_domain(self) -> None:
        a = self._make(email_type=EmailType.HUMAN, domain=None)
        assert a.domain is None

    def test_defaults(self) -> None:
        a = self._make()
        assert a.entities == []
        assert a.summary == ""
        assert a.requires_reply is False
        assert a.deadline is None

    def test_optional_fields(self) -> None:
        a = self._make(
            entities=["Alice", "Project X"],
            summary="One sentence.",
            requires_reply=True,
            deadline="by Friday",
        )
        assert a.entities == ["Alice", "Project X"]
        assert a.requires_reply is True
        assert a.deadline == "by Friday"

    def test_is_frozen(self) -> None:
        a = self._make()
        with pytest.raises((AttributeError, TypeError)):
            a.email_id = "other"  # type: ignore[misc]
```

**Step 2: Run to confirm failure**

```bash
cd /c/Users/xande/Documents/Code/AI-Powered-Email
uv run pytest tests/test_processing/test_types.py -v
```

Expected: `ImportError` — `EmailType`, `Domain`, etc. don't exist yet.

**Step 3: Rewrite `src/processing/types.py`**

Replace the entire file:

```python
"""Types for the email analysis pipeline."""

from dataclasses import dataclass, field
from enum import Enum


class EmailType(str, Enum):
    """Whether the email was sent by a real person or an automated system."""

    HUMAN = "human"
    AUTOMATED = "automated"


class Domain(str, Enum):
    """Life-domain category for automated email."""

    # Transactional / Money
    FINANCE = "finance"
    SHOPPING = "shopping"

    # Life Admin
    TRAVEL = "travel"
    HEALTH = "health"
    GOVERNMENT = "government"

    # Work / Learning
    WORK = "work"
    EDUCATION = "education"

    # Inbox Noise
    NEWSLETTER = "newsletter"
    MARKETING = "marketing"
    SOCIAL = "social"
    ALERTS = "alerts"

    # Catch-all
    OTHER = "other"


# ── Gmail label constants ───────────────────────────────────────────────────────

HUMAN_LABEL = "AI/Human"
HUMAN_FOLLOWUP_LABEL = "AI/Human/FollowUp"

DOMAIN_LABEL: dict[Domain, str] = {
    Domain.FINANCE: "AI/Automated/Finance",
    Domain.SHOPPING: "AI/Automated/Shopping",
    Domain.TRAVEL: "AI/Automated/Travel",
    Domain.HEALTH: "AI/Automated/Health",
    Domain.GOVERNMENT: "AI/Automated/Government",
    Domain.WORK: "AI/Automated/Work",
    Domain.EDUCATION: "AI/Automated/Education",
    Domain.NEWSLETTER: "AI/Automated/Newsletter",
    Domain.MARKETING: "AI/Automated/Marketing",
    Domain.SOCIAL: "AI/Automated/Social",
    Domain.ALERTS: "AI/Automated/Alerts",
    Domain.OTHER: "AI/Automated/Other",
}


# ── Analysis result ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EmailAnalysis:
    """Structured intelligence extracted from a single email by Haiku."""

    email_id: str
    email_type: EmailType
    domain: Domain | None          # None for human emails
    entities: list[str] = field(default_factory=list)
    summary: str = ""
    requires_reply: bool = False
    deadline: str | None = None
```

**Step 4: Run to confirm tests pass**

```bash
uv run pytest tests/test_processing/test_types.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/processing/types.py tests/test_processing/test_types.py
git commit -m "refactor(types): replace Priority/Intent/sentiment with EmailType/Domain"
```

---

### Task 2: Update the Haiku tool schema in `processing/prompts.py`

**Files:**
- Modify: `src/processing/prompts.py`
- Modify: `tests/test_processing/test_analyzer.py` (VALID_DATA and TestParseAnalysis only)

**Step 1: Update VALID_DATA in the test file**

In `tests/test_processing/test_analyzer.py`, change the imports at the top:

```python
# Old imports to remove:
from src.processing.types import EmailAnalysis, Intent, Priority

# New imports:
from src.processing.types import Domain, EmailAnalysis, EmailType
```

Replace `VALID_DATA`:

```python
VALID_DATA: dict[str, object] = {
    "email_type": "automated",
    "domain": "finance",
    "entities": ["Alice", "Project X"],
    "summary": "Alice asks about Project X.",
    "requires_reply": True,
    "deadline": "by Friday",
}
```

Update `TestParseAnalysis.test_parses_all_fields`:

```python
def test_parses_all_fields(self) -> None:
    a = _parse_analysis("msg_1", VALID_DATA)
    assert a.email_id == "msg_1"
    assert a.email_type == EmailType.AUTOMATED
    assert a.domain == Domain.FINANCE
    assert a.entities == ["Alice", "Project X"]
    assert a.summary == "Alice asks about Project X."
    assert a.requires_reply is True
    assert a.deadline == "by Friday"
```

Update `TestParseAnalysis.test_null_deadline_maps_to_none` — no change needed, just verify it still passes.

Update all `_analysis()` helper methods in `TestAnalysisProcessorProcess` and `TestWriteStorage` to use the new fields:

```python
def _analysis(self, **kwargs: object) -> EmailAnalysis:
    defaults: dict[str, object] = dict(
        email_id="msg_1",
        email_type=EmailType.HUMAN,
        domain=None,
    )
    return EmailAnalysis(**{**defaults, **kwargs})  # type: ignore[arg-type]
```

Remove these tests (they test behaviour being deleted):
- `test_applies_priority_label`
- `test_applies_intent_label`
- `test_stars_critical_emails`
- `test_stars_high_priority_emails`
- `test_does_not_star_medium_priority`

Add these new tests in `TestAnalysisProcessorProcess`:

```python
async def test_applies_human_label_for_human_email(self) -> None:
    proc, analyzer, gmail = self._make_processor()
    analyzer.analyze = AsyncMock(
        return_value=self._analysis(email_type=EmailType.HUMAN)
    )
    await proc.process(make_email())
    labels_applied = [c.args[1] for c in gmail.apply_label.call_args_list]
    assert "AI/Human" in labels_applied

async def test_applies_domain_label_for_automated_email(self) -> None:
    proc, analyzer, gmail = self._make_processor()
    analyzer.analyze = AsyncMock(
        return_value=self._analysis(email_type=EmailType.AUTOMATED, domain=Domain.FINANCE)
    )
    await proc.process(make_email())
    labels_applied = [c.args[1] for c in gmail.apply_label.call_args_list]
    assert "AI/Automated/Finance" in labels_applied
    assert "AI/Human" not in labels_applied

async def test_does_not_apply_domain_label_for_human_email(self) -> None:
    proc, analyzer, gmail = self._make_processor()
    analyzer.analyze = AsyncMock(
        return_value=self._analysis(email_type=EmailType.HUMAN, domain=None)
    )
    await proc.process(make_email())
    labels_applied = [c.args[1] for c in gmail.apply_label.call_args_list]
    assert not any("AI/Automated" in l for l in labels_applied)
```

Update the `_analysis()` in `TestWriteStorage` to use new fields (same pattern as above). The `test_no_storage_calls_without_dependencies` at the bottom of the file also constructs an `EmailAnalysis` directly — update it:

```python
# Old:
return EmailAnalysis(
    email_id="x", sentiment=0.0,
    intent=Intent.FYI, priority=Priority.MEDIUM,
)
# New:
return EmailAnalysis(email_id="x", email_type=EmailType.HUMAN, domain=None)
```

**Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_processing/test_analyzer.py -v
```

Expected: Multiple FAILs — `VALID_DATA` uses fields that `_parse_analysis` doesn't know yet.

**Step 3: Rewrite `src/processing/prompts.py`**

Replace the `ANALYSIS_TOOL` dict:

```python
ANALYSIS_TOOL: dict[str, Any] = {
    "name": "record_email_analysis",
    "description": (
        "Record the structured analysis of an email. "
        "Call this tool with your findings after reading the email."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "email_type": {
                "type": "string",
                "enum": ["human", "automated"],
                "description": (
                    "'human': sent by a real person (even a business contact). "
                    "'automated': newsletters, receipts, notifications, marketing, "
                    "alerts, or any message generated by a system rather than a person."
                ),
            },
            "domain": {
                "type": ["string", "null"],
                "enum": [
                    "finance", "shopping", "travel", "health", "government",
                    "work", "education", "newsletter", "marketing", "social",
                    "alerts", "other", None,
                ],
                "description": (
                    "Life-domain category for automated email only. null for human email. "
                    "finance: bills, receipts, bank statements, utilities. "
                    "shopping: orders, shipping, delivery. "
                    "travel: bookings, itineraries, confirmations. "
                    "health: medical, pharmacy, insurance. "
                    "government: official, legal, tax. "
                    "work: HR, IT, internal tools. "
                    "education: courses, certifications, alumni. "
                    "newsletter: subscriptions, digests, editorial. "
                    "marketing: promotions, deals, product announcements. "
                    "social: social media notifications. "
                    "alerts: app alerts, security notices, service updates. "
                    "other: automated but doesn't fit above."
                ),
            },
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Notable named entities: people, organisations, projects, "
                    "products, or key topics mentioned in the email."
                ),
            },
            "summary": {
                "type": "string",
                "description": "One concise sentence summarising the email.",
            },
            "requires_reply": {
                "type": "boolean",
                "description": "True if the sender expects a reply or response.",
            },
            "deadline": {
                "type": ["string", "null"],
                "description": (
                    "Any deadline or time constraint mentioned, e.g. 'by Friday'. "
                    "null if none."
                ),
            },
        },
        "required": [
            "email_type",
            "domain",
            "entities",
            "summary",
            "requires_reply",
            "deadline",
        ],
    },
}
```

Leave `build_messages()` unchanged — it doesn't reference the schema fields.

**Step 4: Run to confirm tests pass**

```bash
uv run pytest tests/test_processing/test_analyzer.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/processing/prompts.py tests/test_processing/test_analyzer.py
git commit -m "refactor(prompts): update ANALYSIS_TOOL schema for EmailType/Domain"
```

---

### Task 3: Update `processing/analyzer.py` — parse and label logic

**Files:**
- Modify: `src/processing/analyzer.py`

No new tests needed — the existing `test_analyzer.py` already covers the new behaviour after Task 2's changes. This task is purely implementation to make those tests pass.

**Step 1: Update imports at the top of `analyzer.py`**

```python
# Old:
from src.processing.types import (
    EmailAnalysis,
    Intent,
    INTENT_LABEL,
    Priority,
    PRIORITY_LABEL,
)

# New:
from src.processing.types import (
    DOMAIN_LABEL,
    HUMAN_FOLLOWUP_LABEL,
    HUMAN_LABEL,
    Domain,
    EmailAnalysis,
    EmailType,
)
```

**Step 2: Replace `_parse_analysis()`**

```python
def _parse_analysis(email_id: str, data: dict[str, object]) -> EmailAnalysis:
    """Convert the raw tool-call input dict into a typed EmailAnalysis."""
    email_type = EmailType(str(data["email_type"]))
    raw_domain = data.get("domain")
    domain = Domain(str(raw_domain)) if raw_domain else None
    return EmailAnalysis(
        email_id=email_id,
        email_type=email_type,
        domain=domain,
        entities=[str(e) for e in data.get("entities", [])],  # type: ignore[union-attr]
        summary=str(data.get("summary", "")),
        requires_reply=bool(data.get("requires_reply", False)),
        deadline=str(data["deadline"]) if data.get("deadline") else None,
    )
```

**Step 3: Replace `_apply_labels()` in `AnalysisProcessor`**

```python
async def _apply_labels(self, email_id: str, analysis: EmailAnalysis) -> None:
    """Fan out label writes; log individual failures rather than raising."""
    if analysis.email_type == EmailType.HUMAN:
        ops: list[tuple[str, object]] = [
            ("human label", self._gmail.apply_label(email_id, HUMAN_LABEL)),
        ]
        if analysis.requires_reply:
            ops.append(("follow-up label", self._gmail.apply_label(email_id, HUMAN_FOLLOWUP_LABEL)))
    else:
        domain_label = DOMAIN_LABEL.get(analysis.domain or Domain.OTHER, DOMAIN_LABEL[Domain.OTHER])
        ops = [
            ("domain label", self._gmail.apply_label(email_id, domain_label)),
        ]
        if analysis.requires_reply:
            ops.append(("follow-up label", self._gmail.apply_label(email_id, HUMAN_FOLLOWUP_LABEL)))

    for name, coro in ops:
        try:
            await coro  # type: ignore[misc]
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to apply %s to email %s: %s", name, email_id, exc)
```

**Step 4: Update the log line in `process()`**

```python
# Old:
logger.info(
    "email=%s priority=%s intent=%s sentiment=%+.2f reply=%s deadline=%r",
    email.id,
    analysis.priority.name,
    analysis.intent.value,
    analysis.sentiment,
    analysis.requires_reply,
    analysis.deadline,
)

# New:
logger.info(
    "email=%s type=%s domain=%s reply=%s deadline=%r",
    email.id,
    analysis.email_type.value,
    analysis.domain.value if analysis.domain else "n/a",
    analysis.requires_reply,
    analysis.deadline,
)
```

**Step 5: Run full processing test suite**

```bash
uv run pytest tests/test_processing/ -v
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add src/processing/analyzer.py
git commit -m "refactor(analyzer): parse EmailType/Domain, apply human/automated labels"
```

---

### Task 4: Update `AI_LABELS` in `mcp/gmail_client.py`

**Files:**
- Modify: `src/mcp/gmail_client.py`
- Modify: `tests/test_mcp/test_gmail_client.py`

**Step 1: Update the test fixture's label cache**

In `tests/test_mcp/test_gmail_client.py`, find the `client` fixture and update `_label_cache` to use the new labels:

```python
@pytest.fixture
def client(session: MagicMock) -> GmailClient:
    c = GmailClient(session, "test@example.com")
    c._label_cache = {
        "AI/Human": "lbl_human",
        "AI/Human/FollowUp": "lbl_followup",
        "AI/Automated/Finance": "lbl_finance",
        "ExistingLabel": "lbl_existing",
    }
    return c
```

Find any test that checks `AI_LABELS` directly and update the expected values. Search for `AI_LABELS` in the test file:

```bash
grep -n "AI_LABELS\|Priority\|Intent" tests/test_mcp/test_gmail_client.py
```

Update any assertion that references old label names to use the new structure.

**Step 2: Run to confirm failure (if any tests reference old labels)**

```bash
uv run pytest tests/test_mcp/test_gmail_client.py -v
```

**Step 3: Replace `AI_LABELS` in `gmail_client.py`**

```python
AI_LABELS: list[str] = [
    # Level 0 — root parent
    "AI",
    # Level 1 — type parents (also used as inbox filter targets)
    "AI/Human",
    "AI/Automated",
    # Level 2 — Human sublabels
    "AI/Human/FollowUp",
    # Level 2 — Automated domain sublabels
    "AI/Automated/Finance",
    "AI/Automated/Shopping",
    "AI/Automated/Travel",
    "AI/Automated/Health",
    "AI/Automated/Government",
    "AI/Automated/Work",
    "AI/Automated/Education",
    "AI/Automated/Newsletter",
    "AI/Automated/Marketing",
    "AI/Automated/Social",
    "AI/Automated/Alerts",
    "AI/Automated/Other",
]
```

**Step 4: Run to confirm tests pass**

```bash
uv run pytest tests/test_mcp/test_gmail_client.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add src/mcp/gmail_client.py tests/test_mcp/test_gmail_client.py
git commit -m "refactor(gmail): update AI_LABELS to Human/Automated hierarchy"
```

---

### Task 5: Update SQLite schema in `storage/models.py`

**Files:**
- Modify: `src/storage/models.py`
- Modify: `tests/test_storage/test_db.py` (helpers only — full test updates in Task 6)

**Step 1: Update the `make_analysis` helper in `test_db.py`**

```python
# Old imports:
from src.processing.types import EmailAnalysis, Intent, Priority

# New imports:
from src.processing.types import Domain, EmailAnalysis, EmailType

# Old make_analysis:
def make_analysis(
    email_id: str = "msg_1",
    sentiment: float = 0.0,
    intent: Intent = Intent.FYI,
    priority: Priority = Priority.MEDIUM,
    requires_reply: bool = False,
    deadline: str | None = None,
) -> EmailAnalysis:
    return EmailAnalysis(
        email_id=email_id,
        sentiment=sentiment,
        intent=intent,
        priority=priority,
        entities=["Alice"],
        summary="A test email.",
        requires_reply=requires_reply,
        deadline=deadline,
    )

# New make_analysis:
def make_analysis(
    email_id: str = "msg_1",
    email_type: EmailType = EmailType.HUMAN,
    domain: Domain | None = None,
    requires_reply: bool = False,
    deadline: str | None = None,
) -> EmailAnalysis:
    return EmailAnalysis(
        email_id=email_id,
        email_type=email_type,
        domain=domain,
        entities=["Alice"],
        summary="A test email.",
        requires_reply=requires_reply,
        deadline=deadline,
    )
```

**Step 2: Run to confirm failure**

```bash
uv run pytest tests/test_storage/test_db.py -v
```

Expected: Multiple FAILs — `make_analysis()` calls pass wrong kwargs, and DB schema still has old columns.

**Step 3: Rewrite `src/storage/models.py`**

Replace `_CREATE_EMAILS` DDL:

```python
_CREATE_EMAILS = """
CREATE TABLE IF NOT EXISTS emails (
    id            TEXT PRIMARY KEY,
    thread_id     TEXT NOT NULL,
    sender        TEXT NOT NULL,
    subject       TEXT NOT NULL,
    snippet       TEXT NOT NULL,
    body          TEXT,
    date          TEXT,
    email_type    TEXT NOT NULL,
    domain        TEXT,
    summary       TEXT NOT NULL,
    requires_reply INTEGER NOT NULL DEFAULT 0,
    deadline      TEXT,
    entities      TEXT NOT NULL DEFAULT '[]',
    processed_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""
```

Replace `_CREATE_CONTACTS` DDL (remove `avg_sentiment`):

```python
_CREATE_CONTACTS = """
CREATE TABLE IF NOT EXISTS contacts (
    email_address  TEXT PRIMARY KEY,
    total_emails   INTEGER NOT NULL DEFAULT 0,
    last_contact   TEXT
)
"""
```

Update `EmailRow` dataclass:

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
    email_type: str
    domain: str | None
    summary: str
    requires_reply: bool
    deadline: str | None
    entities: str  # JSON-encoded list[str]
    processed_at: str
```

Update `ContactRecord` dataclass:

```python
@dataclass(frozen=True)
class ContactRecord:
    """A row from the contacts table."""

    email_address: str
    total_emails: int
    last_contact: str | None
```

**Step 4: Run tests (expect some failures — Task 6 will fix the DB method bodies)**

```bash
uv run pytest tests/test_storage/test_db.py -v
```

**Step 5: Commit the schema changes**

```bash
git add src/storage/models.py tests/test_storage/test_db.py
git commit -m "refactor(models): swap priority/intent/sentiment columns for email_type/domain"
```

---

### Task 6: Update `storage/db.py` — upsert and queries

**Files:**
- Modify: `src/storage/db.py`
- Modify: `tests/test_storage/test_db.py`

**Step 1: Update `test_db.py` tests that check stored fields**

Find `test_save_stores_analysis_fields` and update it:

```python
def test_save_stores_analysis_fields(self, db: EmailDatabase) -> None:
    analysis = make_analysis(
        email_type=EmailType.AUTOMATED,
        domain=Domain.FINANCE,
        requires_reply=True,
        deadline="by Friday",
    )
    db.save(make_email(), analysis)

    row = db._conn.execute("SELECT * FROM emails WHERE id = 'msg_1'").fetchone()
    assert row["email_type"] == "automated"
    assert row["domain"] == "finance"
    assert row["requires_reply"] == 1
    assert row["deadline"] == "by Friday"
```

Find any test that checks `row["sentiment"]`, `row["intent"]`, `row["priority"]`, or `row["avg_sentiment"]` — remove or update those assertions.

Find `test_get_urgent_emails` (or similar) in the test file and replace with:

```python
class TestGetHumanEmailsNeedingReply:
    def test_returns_human_emails_with_reply_required(self, db: EmailDatabase) -> None:
        db.save(
            make_email(id="human_reply"),
            make_analysis(email_id="human_reply", email_type=EmailType.HUMAN, requires_reply=True),
        )
        db.save(
            make_email(id="human_no_reply"),
            make_analysis(email_id="human_no_reply", email_type=EmailType.HUMAN, requires_reply=False),
        )
        db.save(
            make_email(id="automated"),
            make_analysis(email_id="automated", email_type=EmailType.AUTOMATED, domain=Domain.NEWSLETTER, requires_reply=False),
        )

        results = db.get_human_emails_needing_reply(hours=24)
        ids = [r.id for r in results]
        assert "human_reply" in ids
        assert "human_no_reply" not in ids
        assert "automated" not in ids

    def test_respects_hours_window(self, db: EmailDatabase) -> None:
        db.save(
            make_email(id="recent"),
            make_analysis(email_id="recent", email_type=EmailType.HUMAN, requires_reply=True),
        )
        results = db.get_human_emails_needing_reply(hours=1)
        assert any(r.id == "recent" for r in results)
```

Find `TestGetContactHistory` — remove the `avg_sentiment` assertion:

```python
# Remove any line like:
assert record.avg_sentiment == ...
# ContactRecord no longer has avg_sentiment
```

**Step 2: Run to confirm failures**

```bash
uv run pytest tests/test_storage/test_db.py -v
```

**Step 3: Update `_upsert_email()` in `db.py`**

```python
def _upsert_email(self, email: RawEmail, analysis: EmailAnalysis) -> None:
    self._conn.execute(
        """
        INSERT INTO emails
            (id, thread_id, sender, subject, snippet, body, date,
             email_type, domain, summary,
             requires_reply, deadline, entities)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            email_type     = excluded.email_type,
            domain         = excluded.domain,
            summary        = excluded.summary,
            requires_reply = excluded.requires_reply,
            deadline       = excluded.deadline,
            entities       = excluded.entities
        """,
        (
            email.id,
            email.thread_id,
            email.sender,
            email.subject,
            email.snippet,
            email.body,
            email.date,
            analysis.email_type.value,
            analysis.domain.value if analysis.domain else None,
            analysis.summary,
            int(analysis.requires_reply),
            analysis.deadline,
            json.dumps(analysis.entities),
        ),
    )
```

**Step 4: Update `_upsert_contact()` — remove sentiment tracking**

```python
def _upsert_contact(self, email: RawEmail, analysis: EmailAnalysis) -> None:
    existing = self._conn.execute(
        "SELECT total_emails FROM contacts WHERE email_address = ?",
        (email.sender,),
    ).fetchone()

    if existing:
        self._conn.execute(
            """UPDATE contacts
               SET total_emails = ?, last_contact = ?
               WHERE email_address = ?""",
            (existing["total_emails"] + 1, email.date, email.sender),
        )
    else:
        self._conn.execute(
            """INSERT INTO contacts (email_address, total_emails, last_contact)
               VALUES (?, 1, ?)""",
            (email.sender, email.date),
        )
```

**Step 5: Update `get_email_by_id()` SELECT**

```python
def get_email_by_id(self, email_id: str) -> EmailRow | None:
    row = self._conn.execute(
        """SELECT id, thread_id, sender, subject, snippet, body, date,
                  email_type, domain, summary, requires_reply,
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

**Step 6: Rename and rewrite `get_urgent_emails()` → `get_human_emails_needing_reply()`**

```python
def get_human_emails_needing_reply(self, hours: int = 24) -> list[EmailRow]:
    """Return human emails that require a reply, processed within the last N hours."""
    rows = self._conn.execute(
        """SELECT id, thread_id, sender, subject, snippet, body, date,
                  email_type, domain, summary, requires_reply,
                  deadline, entities, processed_at
           FROM emails
           WHERE email_type = 'human'
             AND requires_reply = 1
             AND processed_at >= datetime('now', ?)
           ORDER BY processed_at DESC""",
        (f"-{hours} hours",),
    ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["requires_reply"] = bool(d["requires_reply"])
        result.append(EmailRow(**d))
    return result
```

Also update `get_contact_history()` — remove `avg_sentiment` from the SELECT:

```python
def get_contact_history(self, email_address: str) -> ContactRecord | None:
    row = self._conn.execute(
        "SELECT email_address, total_emails, last_contact "
        "FROM contacts WHERE email_address = ?",
        (email_address,),
    ).fetchone()
    return ContactRecord(**dict(row)) if row else None
```

**Step 7: Run to confirm all storage tests pass**

```bash
uv run pytest tests/test_storage/test_db.py -v
```

Expected: All tests PASS.

**Step 8: Commit**

```bash
git add src/storage/db.py tests/test_storage/test_db.py
git commit -m "refactor(db): update upsert/queries for email_type/domain schema"
```

---

### Task 7: Update ChromaDB metadata in `storage/vector_store.py`

**Files:**
- Modify: `src/storage/vector_store.py`
- Modify: `tests/test_storage/test_vector_store.py`

**Step 1: Find and update the metadata assertions in the test file**

```bash
grep -n "priority\|intent\|sentiment" tests/test_storage/test_vector_store.py
```

Update the `make_analysis` import and any helper that constructs an `EmailAnalysis` using the old fields (same pattern as Tasks 5–6). Update any test asserting `metadata["priority"]` etc. to assert `metadata["email_type"]` and `metadata["domain"]` instead.

**Step 2: Run to confirm failures**

```bash
uv run pytest tests/test_storage/test_vector_store.py -v
```

**Step 3: Replace `_build_metadata()` in `vector_store.py`**

```python
def _build_metadata(email: RawEmail, analysis: EmailAnalysis) -> dict[str, Any]:
    """Build the flat metadata dict stored alongside the vector."""
    return {
        "sender": email.sender,
        "subject": email.subject,
        "thread_id": email.thread_id,
        "date": email.date or "",
        "email_type": analysis.email_type.value,
        "domain": analysis.domain.value if analysis.domain else "",
        "requires_reply": analysis.requires_reply,
        "summary": analysis.summary,
    }
```

Also update the docstring on `search_with_filter` to reference new fields:

```python
def search_with_filter(
    self,
    query: str,
    where: dict[str, Any],
    n_results: int = 10,
) -> list[SearchResult]:
    """Semantic search filtered by metadata.

    ``where`` uses ChromaDB's filter syntax, e.g.::

        {"email_type": "human"}
        {"domain": "finance"}
        {"sender": "alice@example.com"}
    """
```

**Step 4: Run to confirm tests pass**

```bash
uv run pytest tests/test_storage/test_vector_store.py -v
```

**Step 5: Commit**

```bash
git add src/storage/vector_store.py tests/test_storage/test_vector_store.py
git commit -m "refactor(vector_store): update metadata to email_type/domain"
```

---

### Task 8: Update CLI search display in `commands.py`

**Files:**
- Modify: `src/cli/commands.py`
- Modify: `tests/test_cli/test_commands.py`

**Step 1: Update test fixtures that construct `EmailAnalysis` or check display output**

```bash
grep -n "priority\|intent\|sentiment\|Priority\|Intent" tests/test_cli/test_commands.py
```

Update `make_analysis` helpers and any mock `SearchResult` metadata dicts:

```python
# Old metadata mock:
{"priority": 2, "intent": "action_required", ...}

# New metadata mock:
{"email_type": "human", "domain": "", ...}
```

**Step 2: Run to confirm failures**

```bash
uv run pytest tests/test_cli/test_commands.py -v
```

**Step 3: Update `commands.py`**

Remove at the top of the file:

```python
# Remove these entirely:
_PRIORITY_LABEL: dict[int, str] = { ... }
_PRIORITY_STYLE: dict[int, str] = { ... }
```

Update the `search` command's table definition — replace the `Priority` column with `Type` and `Domain`:

```python
table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
table.add_column("#", style="dim", width=3)
table.add_column("Subject", max_width=38)
table.add_column("From", max_width=26)
table.add_column("Date", width=12)
table.add_column("Type", width=10)
table.add_column("Domain", width=12)
table.add_column("Score", width=6)
```

Update the row-building loop:

```python
for i, result in enumerate(results, start=1):
    m = result.metadata
    email_type = str(m.get("email_type", ""))
    domain = str(m.get("domain", ""))
    type_style = "cyan" if email_type == "human" else "dim"
    score = f"{max(0.0, 1.0 - result.distance):.2f}"
    table.add_row(
        str(i),
        str(m.get("subject", "")),
        str(m.get("sender", "")),
        str(m.get("date", ""))[:10],
        f"[{type_style}]{email_type}[/{type_style}]",
        domain or "",
        score,
    )
```

**Step 4: Run to confirm tests pass**

```bash
uv run pytest tests/test_cli/ -v
```

**Step 5: Commit**

```bash
git add src/cli/commands.py tests/test_cli/test_commands.py
git commit -m "refactor(cli): replace priority display with email_type/domain columns"
```

---

### Task 9: Update `briefing/generator.py`

**Files:**
- Modify: `src/briefing/generator.py`
- Modify: `tests/test_briefing/test_briefing_generator.py`

**Step 1: Update test fixtures**

```bash
grep -n "priority\|intent\|sentiment\|Priority\|Intent\|_PRIORITY_LABEL\|get_urgent" tests/test_briefing/test_briefing_generator.py
```

Update any mock `QueryEngine` that returns `get_urgent_emails()` to return `get_human_emails_needing_reply()` instead.

Update any `EmailRow` construction to use `email_type`/`domain` instead of `priority`/`intent`/`sentiment`.

**Step 2: Run to confirm failures**

```bash
uv run pytest tests/test_briefing/ -v
```

**Step 3: Update `generator.py`**

Remove:

```python
# Delete this line:
_PRIORITY_LABEL: dict[int, str] = {1: "CRITICAL", 2: "HIGH", 3: "MEDIUM", 4: "LOW", 5: "FYI"}
```

In `generate()`, update the call:

```python
# Old:
urgent = self._engine.get_urgent_emails(24)

# New:
human_needing_reply = self._engine.get_human_emails_needing_reply(24)
```

Update `_build_prompt()` signature and body:

```python
def _build_prompt(
    self,
    today: str,
    human_needing_reply: list[EmailRow],
    follow_ups: list[tuple[FollowUpRecord, EmailRow | None]],
    deadlines: list[tuple[DeadlineRecord, EmailRow | None]],
) -> str:
    reply_lines = "\n".join(
        f"  - {r.subject} (from {r.sender}): {r.summary}"
        for r in human_needing_reply
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
        f"HUMAN EMAILS NEEDING REPLY (last 24h):\n{reply_lines}\n\n"
        f"PENDING FOLLOW-UPS:\n{follow_up_lines}\n\n"
        f"OPEN DEADLINES:\n{deadline_lines}\n\n"
        "Format the briefing with clear labelled sections. Be specific — reference "
        "actual names, dates, and action items from the data above. End with a "
        '"Recommended focus" of 1\u20133 items for today.'
    )
```

Update `_fallback_text()` the same way — replace `urgent` parameter with `human_needing_reply` and update the section header.

**Step 4: Run to confirm tests pass**

```bash
uv run pytest tests/test_briefing/ -v
```

**Step 5: Commit**

```bash
git add src/briefing/generator.py tests/test_briefing/test_briefing_generator.py
git commit -m "refactor(briefing): replace urgent/priority with human emails needing reply"
```

---

### Task 10: Update `QueryEngine` and run full test suite

**Files:**
- Modify: `src/cli/query.py`
- Modify: `tests/test_cli/test_query_engine.py`

**Step 1: Check what `QueryEngine` exposes**

```bash
grep -n "urgent\|priority\|intent\|sentiment" src/cli/query.py
```

Update `get_urgent_emails()` call in `QueryEngine` to delegate to `get_human_emails_needing_reply()`. Update any associated test in `test_query_engine.py`.

**Step 2: Run the full test suite**

```bash
uv run pytest -v
```

Expected: All 155+ tests PASS. If any failures remain, fix them before committing.

**Step 3: Delete the old SQLite database**

The schema has changed. Any existing `data/email_agent.db` is incompatible:

```bash
rm -f data/email_agent.db
```

**Step 4: Final commit**

```bash
git add src/cli/query.py tests/test_cli/test_query_engine.py
git commit -m "refactor(query): rename get_urgent_emails to get_human_emails_needing_reply"
```

---

### Task 11: Update context files

**Files:**
- Modify: `.context/CURRENT_STATUS.md`
- Modify: `.context/MASTER_PLAN.md`

**Step 1: Update `CURRENT_STATUS.md`**

- Mark the schema redesign as complete
- Note that `data/email_agent.db` must be deleted before first run with new schema
- Update "Next Up" to reflect Phase 5 briefing work can now proceed with the correct schema

**Step 2: Update `MASTER_PLAN.md`**

In the Phase 2 section, update the label list to reflect the new hierarchy. Update Phase 5 to reference `get_human_emails_needing_reply()` instead of `get_urgent_emails()`.

**Step 3: Commit context updates**

```bash
git add .context/CURRENT_STATUS.md .context/MASTER_PLAN.md
git commit -m "docs(context): update status and plan for schema redesign"
```
