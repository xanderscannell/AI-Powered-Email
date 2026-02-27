"""Tests for BriefingGenerator — data collection, Sonnet synthesis, terminal output."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.briefing.generator import BriefingGenerator, OutputConfig
from src.storage.models import DeadlineRecord, EmailRow, FollowUpRecord


# ── Helpers ─────────────────────────────────────────────────────────────────


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
        id=1,
        email_id=email_id,
        status="pending",
        notes=None,
        created_at="2026-02-26 08:00:00",
    )


def _make_deadline(email_id: str = "msg_1") -> DeadlineRecord:
    return DeadlineRecord(
        id=1,
        email_id=email_id,
        description="Submit Q2 report",
        status="open",
        created_at="2026-02-26 08:00:00",
    )


def _make_engine(
    urgent=None,
    follow_ups=None,
    deadlines=None,
) -> MagicMock:
    engine = MagicMock()
    engine.get_urgent_emails.return_value = urgent or []
    engine.get_pending_follow_ups.return_value = follow_ups or []
    engine.get_open_deadlines.return_value = deadlines or []
    return engine


def _make_sonnet_response(
    text: str = "## Morning Briefing\n\nFocus on the budget.",
) -> MagicMock:
    content = MagicMock()
    content.text = text
    response = MagicMock()
    response.content = [content]
    return response


@pytest.fixture
def terminal_only_config() -> OutputConfig:
    return OutputConfig(terminal=True, file=False, email_self=False)


# ── TestBuildPrompt ──────────────────────────────────────────────────────────


class TestBuildPrompt:
    def _gen(self) -> BriefingGenerator:
        return BriefingGenerator(
            engine=_make_engine(),
            output_config=OutputConfig(terminal=False, file=False, email_self=False),
            api_key="test-key",
        )

    def test_prompt_contains_urgent_subject(self) -> None:
        gen = self._gen()
        prompt = gen._build_prompt(
            "2026-02-27",
            urgent=[_make_row()],
            follow_ups=[],
            deadlines=[],
        )
        assert "Budget review" in prompt

    def test_prompt_contains_follow_up(self) -> None:
        gen = self._gen()
        prompt = gen._build_prompt(
            "2026-02-27",
            urgent=[],
            follow_ups=[(_make_follow_up(), _make_row())],
            deadlines=[],
        )
        assert "Budget review" in prompt

    def test_prompt_contains_deadline_description(self) -> None:
        gen = self._gen()
        prompt = gen._build_prompt(
            "2026-02-27",
            urgent=[],
            follow_ups=[],
            deadlines=[(_make_deadline(), _make_row())],
        )
        assert "Submit Q2 report" in prompt

    def test_prompt_includes_today_date(self) -> None:
        gen = self._gen()
        prompt = gen._build_prompt("2026-02-27", urgent=[], follow_ups=[], deadlines=[])
        assert "2026-02-27" in prompt

    def test_prompt_requests_recommended_focus(self) -> None:
        gen = self._gen()
        prompt = gen._build_prompt("2026-02-27", urgent=[], follow_ups=[], deadlines=[])
        assert "Recommended focus" in prompt


# ── TestGenerate ─────────────────────────────────────────────────────────────


class TestGenerate:
    @pytest.mark.asyncio
    async def test_returns_sonnet_text(self, terminal_only_config: OutputConfig) -> None:
        engine = _make_engine()
        gen = BriefingGenerator(engine=engine, output_config=terminal_only_config, api_key="test-key")
        mock_response = _make_sonnet_response("## Briefing\nFocus on budget.")
        with patch("rich.console.Console"):
            gen._client.messages.create = AsyncMock(return_value=mock_response)
            result = await gen.generate()
        assert "Briefing" in result

    @pytest.mark.asyncio
    async def test_calls_get_urgent_emails(self, terminal_only_config: OutputConfig) -> None:
        engine = _make_engine()
        gen = BriefingGenerator(engine=engine, output_config=terminal_only_config, api_key="test-key")
        gen._client.messages.create = AsyncMock(return_value=_make_sonnet_response())
        with patch("rich.console.Console"):
            await gen.generate()
        engine.get_urgent_emails.assert_called_once_with(24)

    @pytest.mark.asyncio
    async def test_calls_get_pending_follow_ups(self, terminal_only_config: OutputConfig) -> None:
        engine = _make_engine()
        gen = BriefingGenerator(engine=engine, output_config=terminal_only_config, api_key="test-key")
        gen._client.messages.create = AsyncMock(return_value=_make_sonnet_response())
        with patch("rich.console.Console"):
            await gen.generate()
        engine.get_pending_follow_ups.assert_called_once()

    @pytest.mark.asyncio
    async def test_calls_get_open_deadlines(self, terminal_only_config: OutputConfig) -> None:
        engine = _make_engine()
        gen = BriefingGenerator(engine=engine, output_config=terminal_only_config, api_key="test-key")
        gen._client.messages.create = AsyncMock(return_value=_make_sonnet_response())
        with patch("rich.console.Console"):
            await gen.generate()
        engine.get_open_deadlines.assert_called_once()


# ── TestSonnetFallback ───────────────────────────────────────────────────────


class TestSonnetFallback:
    @pytest.mark.asyncio
    async def test_returns_fallback_text_on_api_error(self) -> None:
        engine = _make_engine(
            urgent=[_make_row()],
            follow_ups=[(_make_follow_up(), _make_row())],
            deadlines=[(_make_deadline(), _make_row())],
        )
        config = OutputConfig(terminal=False, file=False, email_self=False)
        gen = BriefingGenerator(engine=engine, output_config=config, api_key="test-key")
        gen._client.messages.create = AsyncMock(side_effect=Exception("API error"))
        result = await gen.generate()
        assert len(result) > 0


# ── TestTerminalOutput ───────────────────────────────────────────────────────


class TestTerminalOutput:
    @pytest.mark.asyncio
    async def test_terminal_output_calls_console_print(self) -> None:
        engine = _make_engine()
        config = OutputConfig(terminal=True, file=False, email_self=False)
        gen = BriefingGenerator(engine=engine, output_config=config, api_key="test-key")
        gen._client.messages.create = AsyncMock(return_value=_make_sonnet_response())
        with patch("rich.console.Console") as mock_console_cls:
            mock_console = MagicMock()
            mock_console_cls.return_value = mock_console
            await gen.generate()
        mock_console.print.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_terminal_output_when_disabled(self) -> None:
        engine = _make_engine()
        config = OutputConfig(terminal=False, file=False, email_self=False)
        gen = BriefingGenerator(engine=engine, output_config=config, api_key="test-key")
        gen._client.messages.create = AsyncMock(return_value=_make_sonnet_response())
        with patch("rich.console.Console") as mock_console_cls:
            mock_console = MagicMock()
            mock_console_cls.return_value = mock_console
            await gen.generate()
        mock_console_cls.assert_not_called()


# ── TestFileOutput ───────────────────────────────────────────────────────────


class TestFileOutput:
    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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

    @pytest.mark.asyncio
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
