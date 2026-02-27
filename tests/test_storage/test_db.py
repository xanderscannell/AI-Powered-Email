"""Tests for EmailDatabase — all tests use a temporary SQLite file."""

from pathlib import Path

import pytest

from src.mcp.types import RawEmail
from src.processing.types import EmailAnalysis, Intent, Priority
from src.storage.db import EmailDatabase
from src.storage.models import ContactRecord, DeadlineRecord, EmailRow, FollowUpRecord


# ── Helpers ────────────────────────────────────────────────────────────────────


def make_email(
    id: str = "msg_1",
    sender: str = "alice@example.com",
    date: str | None = "2026-02-27T09:00:00Z",
) -> RawEmail:
    return RawEmail(
        id=id,
        thread_id=f"thread_{id}",
        sender=sender,
        subject="Test subject",
        snippet="snippet...",
        body="Full email body.",
        date=date,
    )


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


@pytest.fixture
def db(tmp_path: Path) -> EmailDatabase:
    return EmailDatabase(db_path=tmp_path / "test.db")


# ── emails table ───────────────────────────────────────────────────────────────


class TestEmailUpsert:
    def test_save_creates_email_row(self, db: EmailDatabase) -> None:
        email = make_email()
        db.save(email, make_analysis())

        rows = db._conn.execute("SELECT id, sender FROM emails").fetchall()
        assert len(rows) == 1
        assert rows[0]["id"] == "msg_1"
        assert rows[0]["sender"] == "alice@example.com"

    def test_save_stores_analysis_fields(self, db: EmailDatabase) -> None:
        analysis = make_analysis(
            sentiment=0.75,
            intent=Intent.ACTION_REQUIRED,
            priority=Priority.HIGH,
            requires_reply=True,
            deadline="by Friday",
        )
        db.save(make_email(), analysis)

        row = db._conn.execute("SELECT * FROM emails WHERE id = 'msg_1'").fetchone()
        assert row["sentiment"] == pytest.approx(0.75)
        assert row["intent"] == "action_required"
        assert row["priority"] == 2
        assert row["requires_reply"] == 1
        assert row["deadline"] == "by Friday"

    def test_upsert_updates_existing_row(self, db: EmailDatabase) -> None:
        db.save(make_email(), make_analysis(sentiment=0.1))
        db.save(make_email(), make_analysis(sentiment=0.9))

        rows = db._conn.execute("SELECT sentiment FROM emails").fetchall()
        assert len(rows) == 1
        assert rows[0]["sentiment"] == pytest.approx(0.9)

    def test_multiple_emails_stored_independently(self, db: EmailDatabase) -> None:
        db.save(make_email("a"), make_analysis("a"))
        db.save(make_email("b"), make_analysis("b"))

        count = db._conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        assert count == 2


# ── contacts table ─────────────────────────────────────────────────────────────


class TestContactUpsert:
    def test_creates_contact_on_first_email(self, db: EmailDatabase) -> None:
        db.save(make_email(sender="bob@example.com"), make_analysis(sentiment=0.6))

        contact = db.get_contact_history("bob@example.com")
        assert contact is not None
        assert isinstance(contact, ContactRecord)
        assert contact.total_emails == 1
        assert contact.avg_sentiment == pytest.approx(0.6)

    def test_increments_count_on_second_email(self, db: EmailDatabase) -> None:
        db.save(make_email("a", sender="carol@example.com"), make_analysis("a", sentiment=0.4))
        db.save(make_email("b", sender="carol@example.com"), make_analysis("b", sentiment=0.8))

        contact = db.get_contact_history("carol@example.com")
        assert contact is not None
        assert contact.total_emails == 2

    def test_recalculates_avg_sentiment(self, db: EmailDatabase) -> None:
        db.save(make_email("a", sender="dan@example.com"), make_analysis("a", sentiment=0.0))
        db.save(make_email("b", sender="dan@example.com"), make_analysis("b", sentiment=1.0))

        contact = db.get_contact_history("dan@example.com")
        assert contact is not None
        assert contact.avg_sentiment == pytest.approx(0.5)

    def test_three_emails_avg_sentiment(self, db: EmailDatabase) -> None:
        for i, s in enumerate([0.0, 0.6, 0.9]):
            db.save(
                make_email(f"msg_{i}", sender="eve@example.com"),
                make_analysis(f"msg_{i}", sentiment=s),
            )

        contact = db.get_contact_history("eve@example.com")
        assert contact is not None
        assert contact.avg_sentiment == pytest.approx(0.5)  # (0+0.6+0.9)/3

    def test_returns_none_for_unknown_contact(self, db: EmailDatabase) -> None:
        assert db.get_contact_history("nobody@example.com") is None

    def test_last_contact_updated(self, db: EmailDatabase) -> None:
        db.save(
            make_email("a", sender="frank@example.com", date="2026-01-01T00:00:00Z"),
            make_analysis("a"),
        )
        db.save(
            make_email("b", sender="frank@example.com", date="2026-03-01T00:00:00Z"),
            make_analysis("b"),
        )
        contact = db.get_contact_history("frank@example.com")
        assert contact is not None
        assert contact.last_contact == "2026-03-01T00:00:00Z"


# ── follow_ups table ───────────────────────────────────────────────────────────


class TestFollowUps:
    def test_inserts_follow_up_when_reply_required(self, db: EmailDatabase) -> None:
        db.save(make_email(), make_analysis(requires_reply=True))

        follow_ups = db.get_follow_ups()
        assert len(follow_ups) == 1
        assert isinstance(follow_ups[0], FollowUpRecord)
        assert follow_ups[0].email_id == "msg_1"
        assert follow_ups[0].status == "pending"

    def test_no_follow_up_when_reply_not_required(self, db: EmailDatabase) -> None:
        db.save(make_email(), make_analysis(requires_reply=False))
        assert db.get_follow_ups() == []

    def test_no_duplicate_follow_up_on_reprocess(self, db: EmailDatabase) -> None:
        """Re-saving the same email must not create a second follow_up row."""
        db.save(make_email(), make_analysis(requires_reply=True))
        db.save(make_email(), make_analysis(requires_reply=True))

        assert len(db.get_follow_ups()) == 1

    def test_get_follow_ups_filters_by_status(self, db: EmailDatabase) -> None:
        db.save(make_email("a"), make_analysis("a", requires_reply=True))
        db.save(make_email("b"), make_analysis("b", requires_reply=True))
        # Manually mark one as done
        db._conn.execute(
            "UPDATE follow_ups SET status = 'done' WHERE email_id = 'b'"
        )
        db._conn.commit()

        pending = db.get_follow_ups(status="pending")
        done = db.get_follow_ups(status="done")
        assert len(pending) == 1
        assert len(done) == 1


# ── deadlines table ────────────────────────────────────────────────────────────


class TestDeadlines:
    def test_inserts_deadline_when_set(self, db: EmailDatabase) -> None:
        db.save(make_email(), make_analysis(deadline="by Friday"))

        deadlines = db.get_open_deadlines()
        assert len(deadlines) == 1
        assert isinstance(deadlines[0], DeadlineRecord)
        assert deadlines[0].email_id == "msg_1"
        assert deadlines[0].description == "by Friday"
        assert deadlines[0].status == "open"

    def test_no_deadline_when_none(self, db: EmailDatabase) -> None:
        db.save(make_email(), make_analysis(deadline=None))
        assert db.get_open_deadlines() == []

    def test_no_duplicate_deadline_on_reprocess(self, db: EmailDatabase) -> None:
        db.save(make_email(), make_analysis(deadline="by Friday"))
        db.save(make_email(), make_analysis(deadline="by Friday"))

        assert len(db.get_open_deadlines()) == 1

    def test_only_open_deadlines_returned(self, db: EmailDatabase) -> None:
        db.save(make_email(), make_analysis(deadline="by Friday"))
        db._conn.execute("UPDATE deadlines SET status = 'done'")
        db._conn.commit()

        assert db.get_open_deadlines() == []


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
        assert row.entities == '["Alice"]'

    def test_returns_none_for_unknown_id(self, db: EmailDatabase) -> None:
        assert db.get_email_by_id("nonexistent") is None

    def test_requires_reply_is_bool(self, db: EmailDatabase) -> None:
        email = make_email()
        db.save(email, make_analysis(requires_reply=True))
        row = db.get_email_by_id(email.id)
        assert row is not None
        assert row.requires_reply is True
        assert isinstance(row.requires_reply, bool)

    def test_nullable_fields_returned_as_none(self, db: EmailDatabase) -> None:
        from src.mcp.types import RawEmail

        raw = RawEmail(
            id="msg_null",
            thread_id="thread_null",
            sender="x@example.com",
            subject="Nullable test",
            snippet="snip",
            body=None,
            date=None,
        )
        db.save(raw, make_analysis("msg_null"))
        row = db.get_email_by_id("msg_null")
        assert row is not None
        assert row.body is None
        assert row.date is None
        assert row.deadline is None
