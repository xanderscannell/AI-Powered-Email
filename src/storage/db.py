"""SQLite structured storage — emails, contacts, follow-ups, and deadlines."""

import json
import logging
import sqlite3
from pathlib import Path

from src.mcp.types import RawEmail
from src.processing.types import EmailAnalysis
from src.storage.models import (
    ALL_TABLES,
    ContactRecord,
    DeadlineRecord,
    EmailRow,
    FollowUpRecord,
)

logger = logging.getLogger(__name__)

_DEFAULT_DB_PATH = Path("data/email_agent.db")


class EmailDatabase:
    """Wraps SQLite for structured storage of emails, contacts, and tracking data.

    Designed for single-threaded use from an async event loop — all calls are
    synchronous/blocking but fast enough for personal email volume.

    Usage::

        db = EmailDatabase()
        db.save(raw_email, analysis)
        follow_ups = db.get_follow_ups()
    """

    def __init__(self, db_path: str | Path = _DEFAULT_DB_PATH) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    # ── Write API ───────────────────────────────────────────────────────────────

    def save(self, email: RawEmail, analysis: EmailAnalysis) -> None:
        """Write email + analysis to all tables in a single transaction.

        Idempotent: re-processing an email updates the emails row and contact
        stats but does NOT create duplicate follow_up or deadline rows.
        """
        with self._conn:
            is_new = self._conn.execute(
                "SELECT 1 FROM emails WHERE id = ?", (email.id,)
            ).fetchone() is None

            self._upsert_email(email, analysis)
            self._upsert_contact(email, analysis)

            # Only insert follow_up / deadline rows on first processing.
            # This prevents duplicates if the same email is seen again after
            # a reconnect (processed_ids set survived, but save() could be
            # called again after future restarts when Phase 3 persists IDs).
            if is_new:
                if analysis.requires_reply:
                    self._insert_follow_up(analysis.email_id)
                if analysis.deadline:
                    self._insert_deadline(analysis.email_id, analysis.deadline)

    # ── Read API ────────────────────────────────────────────────────────────────

    def get_follow_ups(self, status: str = "pending") -> list[FollowUpRecord]:
        """Return follow_up rows matching the given status."""
        rows = self._conn.execute(
            "SELECT id, email_id, status, notes, created_at FROM follow_ups WHERE status = ?",
            (status,),
        ).fetchall()
        return [FollowUpRecord(**dict(r)) for r in rows]

    def get_open_deadlines(self) -> list[DeadlineRecord]:
        """Return all open deadline rows, oldest first."""
        rows = self._conn.execute(
            "SELECT id, email_id, description, status, created_at FROM deadlines "
            "WHERE status = 'open' ORDER BY created_at",
        ).fetchall()
        return [DeadlineRecord(**dict(r)) for r in rows]

    def get_contact_history(self, email_address: str) -> ContactRecord | None:
        """Return the contact record for an email address, or None if not found."""
        row = self._conn.execute(
            "SELECT email_address, total_emails, last_contact "
            "FROM contacts WHERE email_address = ?",
            (email_address,),
        ).fetchone()
        return ContactRecord(**dict(row)) if row else None

    def get_email_by_id(self, email_id: str) -> EmailRow | None:
        """Return the stored email row for email_id, or None if not found."""
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

    def get_stored_ids_since(self, days: int) -> set[str]:
        """Return IDs of emails processed within the last N days.

        Uses SQLite's own datetime arithmetic so there is no UTC/local-time mismatch.
        """
        rows = self._conn.execute(
            "SELECT id FROM emails WHERE processed_at >= datetime('now', ?)",
            (f"-{days} days",),
        ).fetchall()
        return {row["id"] for row in rows}

    # ── Private ─────────────────────────────────────────────────────────────────

    def _create_tables(self) -> None:
        with self._conn:
            for ddl in ALL_TABLES:
                self._conn.execute(ddl)

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

    def _upsert_contact(self, email: RawEmail, analysis: EmailAnalysis) -> None:
        self._conn.execute(
            """
            INSERT INTO contacts (email_address, total_emails, last_contact)
            VALUES (?, 1, ?)
            ON CONFLICT(email_address) DO UPDATE SET
                total_emails = total_emails + 1,
                last_contact = excluded.last_contact
            """,
            (email.sender, email.date),
        )

    def _insert_follow_up(self, email_id: str) -> None:
        self._conn.execute(
            "INSERT INTO follow_ups (email_id) VALUES (?)",
            (email_id,),
        )

    def _insert_deadline(self, email_id: str, description: str) -> None:
        self._conn.execute(
            "INSERT INTO deadlines (email_id, description) VALUES (?, ?)",
            (email_id, description),
        )
