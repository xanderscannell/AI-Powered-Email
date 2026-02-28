"""Tests for GmailClient — all MCP calls are mocked."""

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.mcp.gmail_client import AI_LABELS, GmailClient, MCPError
from src.mcp.types import RawEmail


# ── Helpers ────────────────────────────────────────────────────────────────────


def _tool_result(data: Any, *, is_error: bool = False) -> MagicMock:
    """Build a mock MCP CallToolResult whose first content block contains data."""
    content_block = MagicMock()
    # Simulate a TextContent block
    from mcp.types import TextContent

    content_block.__class__ = TextContent
    content_block.text = json.dumps(data) if not isinstance(data, str) else data

    result = MagicMock()
    result.isError = is_error
    result.content = [content_block]
    return result


def _error_result(message: str) -> MagicMock:
    return _tool_result(message, is_error=True)


# ── Fixtures ───────────────────────────────────────────────────────────────────


@pytest.fixture
def session() -> MagicMock:
    s = MagicMock()
    s.call_tool = AsyncMock()
    return s


@pytest.fixture
def client(session: MagicMock) -> GmailClient:
    """GmailClient with a pre-populated label cache (no live MCP calls needed)."""
    c = GmailClient(session, "test@example.com")
    c._label_cache = {
        "AI/Priority/High": "lbl_priority_high",
        "AI/Priority/Critical": "lbl_priority_critical",
        "AI/Intent/ActionRequired": "lbl_intent_action",
        "AI/FollowUp": "lbl_followup",
        "ExistingLabel": "lbl_existing",
    }
    return c


# ── _parse_email ───────────────────────────────────────────────────────────────


class TestParseEmail:
    def test_full_message_response(self) -> None:
        data = {
            "message_id": "msg_001",
            "thread_id": "thread_001",
            "from": "alice@example.com",
            "to": "bob@example.com",
            "subject": "Budget review",
            "snippet": "Please review...",
            "body": "Please review the attached budget.",
            "labels": ["INBOX", "UNREAD"],
            "date": "2026-02-27T09:00:00Z",
            "web_link": "https://mail.google.com/...",
        }
        email = GmailClient._parse_email_dict(data)
        assert email.id == "msg_001"
        assert email.thread_id == "thread_001"
        assert email.sender == "alice@example.com"
        assert email.recipient == "bob@example.com"
        assert email.subject == "Budget review"
        assert email.body == "Please review the attached budget."
        assert email.labels == ["INBOX", "UNREAD"]
        assert email.date == "2026-02-27T09:00:00Z"

    def test_search_result_without_body(self) -> None:
        data = {
            "message_id": "msg_002",
            "thread_id": "thread_002",
            "from": "carol@example.com",
            "subject": "Quick question",
            "snippet": "Hey, do you...",
        }
        email = GmailClient._parse_email_dict(data)
        assert email.body is None
        assert email.recipient is None
        assert email.date is None
        assert email.labels == []

    def test_missing_subject_uses_default(self) -> None:
        email = GmailClient._parse_email_dict({"message_id": "x", "thread_id": "y", "from": "z"})
        assert email.subject == "(no subject)"

    def test_empty_body_maps_to_none(self) -> None:
        email = GmailClient._parse_email_dict({"message_id": "x", "thread_id": "y", "from": "z", "body": ""})
        assert email.body is None


# ── get_unread_email_ids ───────────────────────────────────────────────────────


class TestGetUnreadEmailIds:
    async def test_returns_list_of_ids(self, client: GmailClient, session: MagicMock) -> None:
        session.call_tool.return_value = _tool_result([
            {"message_id": "id_1", "subject": "A"},
            {"message_id": "id_2", "subject": "B"},
        ])
        ids = await client.get_unread_email_ids()
        assert ids == ["id_1", "id_2"]

    async def test_empty_inbox_returns_empty_list(self, client: GmailClient, session: MagicMock) -> None:
        session.call_tool.return_value = _tool_result([])
        ids = await client.get_unread_email_ids()
        assert ids == []

    async def test_drops_entries_without_message_id(self, client: GmailClient, session: MagicMock) -> None:
        session.call_tool.return_value = _tool_result([
            {"message_id": "id_1"},
            {"subject": "no id here"},
            {"message_id": "id_3"},
        ])
        ids = await client.get_unread_email_ids()
        assert ids == ["id_1", "id_3"]

    async def test_passes_max_results_to_search(self, client: GmailClient, session: MagicMock) -> None:
        session.call_tool.return_value = _tool_result([])
        await client.get_unread_email_ids(max_results=123)
        call_args = session.call_tool.call_args
        assert call_args.args[1]["page_size"] == 123


# ── get_unread_emails ──────────────────────────────────────────────────────────


class TestGetUnreadEmails:
    async def test_returns_emails_with_body(self, client: GmailClient, session: MagicMock) -> None:
        search_response = [
            {"message_id": "msg_1", "thread_id": "t1", "from": "a@b.com", "subject": "Hello", "snippet": "Hi"},
            {"message_id": "msg_2", "thread_id": "t2", "from": "c@d.com", "subject": "World", "snippet": "Hey"},
        ]
        batch_response = [
            {"message_id": "msg_1", "thread_id": "t1", "from": "a@b.com", "subject": "Hello",
             "snippet": "Hi", "body": "Full body 1", "labels": ["INBOX"]},
            {"message_id": "msg_2", "thread_id": "t2", "from": "c@d.com", "subject": "World",
             "snippet": "Hey", "body": "Full body 2", "labels": ["INBOX"]},
        ]
        session.call_tool.side_effect = [
            _tool_result(search_response),
            _tool_result(batch_response),
        ]

        emails = await client.get_unread_emails()

        assert len(emails) == 2
        assert emails[0].id == "msg_1"
        assert emails[0].body == "Full body 1"
        assert emails[1].id == "msg_2"

    async def test_empty_inbox_returns_empty_list(self, client: GmailClient, session: MagicMock) -> None:
        session.call_tool.return_value = _tool_result([])
        emails = await client.get_unread_emails()
        assert emails == []

    async def test_search_passes_max_results(self, client: GmailClient, session: MagicMock) -> None:
        session.call_tool.side_effect = [_tool_result([]), _tool_result([])]
        await client.get_unread_emails(max_results=10)
        first_call = session.call_tool.call_args_list[0]
        assert first_call.args[1]["page_size"] == 10


# ── get_email ──────────────────────────────────────────────────────────────────


class TestGetEmail:
    async def test_returns_full_email(self, client: GmailClient, session: MagicMock) -> None:
        session.call_tool.return_value = _tool_result({
            "message_id": "msg_abc",
            "thread_id": "thread_abc",
            "from": "sender@example.com",
            "subject": "Test subject",
            "snippet": "Test snippet",
            "body": "Test body content",
            "labels": ["INBOX"],
        })
        email = await client.get_email("msg_abc")
        assert isinstance(email, RawEmail)
        assert email.id == "msg_abc"
        assert email.body == "Test body content"

    async def test_raises_mcp_error_on_tool_error(self, client: GmailClient, session: MagicMock) -> None:
        session.call_tool.return_value = _error_result("Message not found")
        with pytest.raises(MCPError, match="returned error"):
            await client.get_email("nonexistent")


# ── apply_label ────────────────────────────────────────────────────────────────


class TestApplyLabel:
    async def test_applies_cached_label(self, client: GmailClient, session: MagicMock) -> None:
        session.call_tool.return_value = _tool_result("OK")
        await client.apply_label("msg_1", "AI/Priority/High")

        session.call_tool.assert_called_once_with(
            "modify_gmail_message_labels",
            {"message_id": "msg_1", "add_label_ids": ["lbl_priority_high"],
             "user_google_email": "test@example.com"},
        )

    async def test_creates_missing_label_then_applies(
        self, client: GmailClient, session: MagicMock
    ) -> None:
        # Label not in cache → refresh (returns it) → apply
        client._label_cache.pop("AI/Priority/High")
        refreshed_labels = [
            {"id": "lbl_priority_high", "name": "AI/Priority/High"},
        ]
        session.call_tool.side_effect = [
            _tool_result(refreshed_labels),   # _refresh_label_cache
            _tool_result("OK"),                # modify_gmail_message_labels
        ]
        await client.apply_label("msg_1", "AI/Priority/High")
        assert session.call_tool.call_count == 2


# ── remove_label ───────────────────────────────────────────────────────────────


class TestRemoveLabel:
    async def test_removes_cached_label(self, client: GmailClient, session: MagicMock) -> None:
        session.call_tool.return_value = _tool_result("OK")
        await client.remove_label("msg_1", "ExistingLabel")

        session.call_tool.assert_called_once_with(
            "modify_gmail_message_labels",
            {"message_id": "msg_1", "remove_label_ids": ["lbl_existing"],
             "user_google_email": "test@example.com"},
        )

    async def test_no_op_when_label_not_found(self, client: GmailClient, session: MagicMock) -> None:
        # Refresh returns nothing new either
        session.call_tool.return_value = _tool_result([{"id": "lbl_existing", "name": "ExistingLabel"}])
        await client.remove_label("msg_1", "NonExistentLabel")
        # Only the refresh call should be made, not a modify call
        assert session.call_tool.call_count == 1


# ── star_email ─────────────────────────────────────────────────────────────────


class TestStarEmail:
    async def test_applies_starred_system_label(self, client: GmailClient, session: MagicMock) -> None:
        session.call_tool.return_value = _tool_result("OK")
        await client.star_email("msg_1")

        session.call_tool.assert_called_once_with(
            "modify_gmail_message_labels",
            {"message_id": "msg_1", "add_label_ids": ["STARRED"],
             "user_google_email": "test@example.com"},
        )


# ── create_label ───────────────────────────────────────────────────────────────


class TestCreateLabel:
    async def test_returns_cached_id_without_mcp_call(
        self, client: GmailClient, session: MagicMock
    ) -> None:
        label_id = await client.create_label("ExistingLabel")
        assert label_id == "lbl_existing"
        session.call_tool.assert_not_called()

    async def test_creates_new_label_and_returns_id(
        self, client: GmailClient, session: MagicMock
    ) -> None:
        new_label_list = [
            {"id": "lbl_new", "name": "NewLabel"},
            {"id": "lbl_existing", "name": "ExistingLabel"},
        ]
        session.call_tool.side_effect = [
            _tool_result("Created"),       # manage_gmail_label
            _tool_result(new_label_list),  # _refresh_label_cache
        ]
        label_id = await client.create_label("NewLabel")
        assert label_id == "lbl_new"
        assert client._label_cache["NewLabel"] == "lbl_new"

    async def test_raises_if_label_missing_after_create(
        self, client: GmailClient, session: MagicMock
    ) -> None:
        session.call_tool.side_effect = [
            _tool_result("Created"),   # manage_gmail_label
            _tool_result([]),          # _refresh_label_cache returns empty
        ]
        with pytest.raises(MCPError, match="missing from Gmail label list"):
            await client.create_label("GhostLabel")


# ── ensure_ai_labels ───────────────────────────────────────────────────────────


class TestEnsureAiLabels:
    async def test_creates_only_missing_labels(
        self, client: GmailClient, session: MagicMock
    ) -> None:
        # Simulate: cache already has all AI labels except two
        existing = {name: f"id_{i}" for i, name in enumerate(AI_LABELS[2:])}
        client._label_cache = existing

        # For each missing label: manage_gmail_label + list_gmail_labels (refresh)
        missing = AI_LABELS[:2]

        def side_effects() -> list[MagicMock]:
            results = []
            # refresh at start
            results.append(_tool_result([{"id": f"id_{i}", "name": n} for i, n in enumerate(AI_LABELS[2:])]))
            for i, name in enumerate(missing):
                results.append(_tool_result("Created"))  # manage_gmail_label
                all_labels = [{"id": f"id_{j}", "name": n} for j, n in enumerate(AI_LABELS[2:])]
                all_labels.append({"id": f"new_id_{i}", "name": name})
                results.append(_tool_result(all_labels))  # refresh after create
            return results

        session.call_tool.side_effect = side_effects()
        await client.ensure_ai_labels()

        # manage_gmail_label should be called exactly twice (for the two missing labels)
        manage_calls = [
            c for c in session.call_tool.call_args_list
            if c.args[0] == "manage_gmail_label"
        ]
        assert len(manage_calls) == len(missing)
        created_names = {c.args[1]["name"] for c in manage_calls}
        assert created_names == set(missing)


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
        arguments = call_args.args[1]
        assert "after:" in arguments["query"]


# ── send_email ──────────────────────────────────────────────────────────────────


class TestSendEmail:
    async def test_calls_send_gmail_message_tool(
        self, client: GmailClient, session: MagicMock
    ) -> None:
        session.call_tool.return_value = _tool_result("Email sent!")
        await client.send_email(
            "me@example.com",
            "Morning Briefing \u2014 2026-02-27",
            "# Briefing\n\nNo urgent items.",
        )
        session.call_tool.assert_called_once_with(
            "send_gmail_message",
            {
                "to": "me@example.com",
                "subject": "Morning Briefing \u2014 2026-02-27",
                "body": "# Briefing\n\nNo urgent items.",
                "user_google_email": "test@example.com",
            },
        )

    async def test_raises_mcp_error_on_failure(
        self, client: GmailClient, session: MagicMock
    ) -> None:
        session.call_tool.return_value = _error_result("Failed to send email")
        with pytest.raises(MCPError):
            await client.send_email(
                "me@example.com",
                "Morning Briefing \u2014 2026-02-27",
                "# Briefing\n\nNo urgent items.",
            )
