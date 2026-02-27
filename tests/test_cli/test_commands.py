"""Tests for CLI commands — QueryEngine is mocked, CliRunner used throughout."""

import asyncio as _asyncio
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner, Result

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


def _invoke(engine: MagicMock, *args: str) -> Result:
    from src.cli.main import cli

    runner = CliRunner()
    with patch("src.cli.main.EmailDatabase"), patch(
        "src.cli.main.EmailVectorStore"
    ), patch("src.cli.main.QueryEngine", return_value=engine):
        return runner.invoke(cli, list(args), catch_exceptions=False)


def _async_return(value: object) -> object:
    """Return an awaitable that resolves to value."""
    async def _inner() -> object:
        return value
    return _inner()


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

        mock_client = MagicMock()
        mock_client.messages.create = MagicMock(
            return_value=_async_return(mock_response)
        )

        with patch("src.cli.commands.AsyncAnthropic", return_value=mock_client):
            result = _invoke(engine, "status", "invoice dispute")

        assert result.exit_code == 0
        assert "invoice dispute is unresolved" in result.output


# ── email backfill ───────────────────────────────────────────────────────────────


class TestBackfillCommand:
    def test_skips_already_stored_emails(self) -> None:
        engine = MagicMock()
        engine.get_stored_ids_since.return_value = {"msg_1"}
        engine.vector_store = MagicMock()
        engine.db = MagicMock()

        from src.mcp.types import RawEmail

        all_emails = [
            RawEmail(id="msg_1", thread_id="t1", sender="a@b.com", subject="Old", snippet="old"),
            RawEmail(id="msg_3", thread_id="t3", sender="c@d.com", subject="New", snippet="new", body="New body."),
        ]

        mock_gmail = MagicMock()
        mock_gmail.get_emails_since = MagicMock(return_value=_async_return(all_emails))
        mock_gmail.__aenter__ = MagicMock(return_value=_async_return(mock_gmail))
        mock_gmail.__aexit__ = MagicMock(return_value=_async_return(None))

        mock_processor = MagicMock()
        mock_processor.process = MagicMock(return_value=_async_return(None))

        with patch("src.cli.commands.gmail_client", return_value=mock_gmail), patch(
            "src.cli.commands.EmailAnalyzer"
        ), patch("src.cli.commands.AnalysisProcessor", return_value=mock_processor):
            result = _invoke(engine, "backfill", "--days", "30")

        assert result.exit_code == 0
        # processor.process should only be called once (for msg_3, not msg_1)
        assert mock_processor.process.call_count == 1

    def test_requires_days_option(self) -> None:
        engine = MagicMock()
        runner = CliRunner()
        from src.cli.main import cli
        with patch("src.cli.main.EmailDatabase"), patch(
            "src.cli.main.EmailVectorStore"
        ), patch("src.cli.main.QueryEngine", return_value=engine):
            result = runner.invoke(cli, ["backfill"], catch_exceptions=False)
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


# ── email briefing ───────────────────────────────────────────────────────────────


class TestBriefingCommand:
    def test_briefing_registered_in_cli_group(self) -> None:
        from src.cli.main import cli
        assert "briefing" in cli.commands

    def test_briefing_command_calls_generate(self) -> None:
        from unittest.mock import AsyncMock

        runner = CliRunner()
        with patch("src.briefing.generator.BriefingGenerator") as mock_gen_cls:
            mock_gen = MagicMock()
            mock_gen.generate = AsyncMock(return_value="## Briefing\nContent.")
            mock_gen_cls.return_value = mock_gen
            result = _invoke(MagicMock(), "briefing")

        assert result.exit_code == 0, result.output
        mock_gen.generate.assert_called_once()

    def test_briefing_output_flag_overrides_env(self) -> None:
        from unittest.mock import AsyncMock
        from src.briefing.generator import OutputConfig

        captured: list[OutputConfig] = []

        def capture(engine: object, config: OutputConfig) -> MagicMock:
            captured.append(config)
            m = MagicMock()
            m.generate = AsyncMock(return_value="text")
            return m

        with patch("src.briefing.generator.BriefingGenerator", side_effect=capture):
            result = _invoke(MagicMock(), "briefing", "--output", "file")

        assert result.exit_code == 0, result.output
        assert len(captured) == 1
        assert captured[0].file is True
        assert captured[0].terminal is False
        assert captured[0].email_self is False
