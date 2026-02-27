"""SQLite table schemas and typed query result types for the storage layer."""

from dataclasses import dataclass


# ── DDL ────────────────────────────────────────────────────────────────────────

_CREATE_EMAILS = """
CREATE TABLE IF NOT EXISTS emails (
    id            TEXT PRIMARY KEY,
    thread_id     TEXT NOT NULL,
    sender        TEXT NOT NULL,
    subject       TEXT NOT NULL,
    snippet       TEXT NOT NULL,
    body          TEXT,
    date          TEXT,
    sentiment     REAL NOT NULL,
    intent        TEXT NOT NULL,
    priority      INTEGER NOT NULL,
    summary       TEXT NOT NULL,
    requires_reply INTEGER NOT NULL DEFAULT 0,
    deadline      TEXT,
    entities      TEXT NOT NULL DEFAULT '[]',
    processed_at  TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

_CREATE_CONTACTS = """
CREATE TABLE IF NOT EXISTS contacts (
    email_address  TEXT PRIMARY KEY,
    total_emails   INTEGER NOT NULL DEFAULT 0,
    avg_sentiment  REAL NOT NULL DEFAULT 0.0,
    last_contact   TEXT
)
"""

_CREATE_FOLLOW_UPS = """
CREATE TABLE IF NOT EXISTS follow_ups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (email_id) REFERENCES emails(id)
)
"""

_CREATE_DEADLINES = """
CREATE TABLE IF NOT EXISTS deadlines (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id    TEXT NOT NULL,
    description TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'open',
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (email_id) REFERENCES emails(id)
)
"""

#: All DDL statements in creation order (respects FK dependencies).
ALL_TABLES: list[str] = [
    _CREATE_EMAILS,
    _CREATE_CONTACTS,
    _CREATE_FOLLOW_UPS,
    _CREATE_DEADLINES,
]


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


# ── Query result types ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FollowUpRecord:
    """A row from the follow_ups table."""

    id: int
    email_id: str
    status: str
    notes: str | None
    created_at: str


@dataclass(frozen=True)
class DeadlineRecord:
    """A row from the deadlines table."""

    id: int
    email_id: str
    description: str
    status: str
    created_at: str


@dataclass(frozen=True)
class ContactRecord:
    """A row from the contacts table."""

    email_address: str
    total_emails: int
    avg_sentiment: float
    last_contact: str | None
