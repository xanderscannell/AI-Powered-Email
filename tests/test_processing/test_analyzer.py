"""Tests for the email analysis pipeline (Haiku integration)."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from anthropic.types import ToolUseBlock

from src.mcp.types import RawEmail
from src.processing.analyzer import (
    AnalysisError,
    AnalysisProcessor,
    EmailAnalyzer,
    _parse_analysis,
)
from src.processing.prompts import BODY_CHAR_LIMIT, build_messages
from src.processing.types import EmailAnalysis, Intent, Priority


# ── Helpers ────────────────────────────────────────────────────────────────────


def make_email(**kwargs: object) -> RawEmail:
    defaults: dict[str, object] = dict(
        id="msg_1",
        thread_id="thread_1",
        sender="sender@example.com",
        subject="Test subject",
        snippet="snippet...",
        body="Email body text.",
    )
    return RawEmail(**{**defaults, **kwargs})  # type: ignore[arg-type]


def make_tool_block(data: dict[str, object]) -> ToolUseBlock:
    return ToolUseBlock(
        type="tool_use",
        id="toolu_test_123",
        name="record_email_analysis",
        input=data,
    )


VALID_DATA: dict[str, object] = {
    "sentiment": 0.5,
    "intent": "question",
    "priority": 3,
    "entities": ["Alice", "Project X"],
    "summary": "Alice asks about Project X.",
    "requires_reply": True,
    "deadline": "by Friday",
}


# ── build_messages ──────────────────────────────────────────────────────────────


class TestBuildMessages:
    def test_returns_single_user_message(self) -> None:
        msgs = build_messages(make_email())
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_contains_sender_and_subject(self) -> None:
        msgs = build_messages(make_email(sender="alice@example.com", subject="Hello"))
        content = msgs[0]["content"]
        assert "alice@example.com" in content
        assert "Hello" in content

    def test_includes_recipient_when_present(self) -> None:
        msgs = build_messages(make_email(recipient="bob@example.com"))
        assert "bob@example.com" in msgs[0]["content"]

    def test_no_recipient_header_when_absent(self) -> None:
        msgs = build_messages(make_email())  # recipient defaults to None
        assert "To:" not in msgs[0]["content"]

    def test_includes_date_when_present(self) -> None:
        msgs = build_messages(make_email(date="2024-01-15"))
        assert "2024-01-15" in msgs[0]["content"]

    def test_body_included_in_content(self) -> None:
        msgs = build_messages(make_email(body="The quick brown fox."))
        assert "The quick brown fox." in msgs[0]["content"]

    def test_body_truncated_at_limit(self) -> None:
        long_body = "x" * (BODY_CHAR_LIMIT + 100)
        msgs = build_messages(make_email(body=long_body))
        content = msgs[0]["content"]
        assert "x" * BODY_CHAR_LIMIT in content
        assert "truncated" in content

    def test_no_truncation_marker_under_limit(self) -> None:
        msgs = build_messages(make_email(body="x" * (BODY_CHAR_LIMIT - 1)))
        assert "truncated" not in msgs[0]["content"]

    def test_falls_back_to_snippet_when_no_body(self) -> None:
        msgs = build_messages(make_email(body=None, snippet="Just the snippet."))
        assert "Just the snippet." in msgs[0]["content"]

    def test_instruction_present(self) -> None:
        """The prompt must tell Haiku to call record_email_analysis."""
        msgs = build_messages(make_email())
        assert "record_email_analysis" in msgs[0]["content"]


# ── _parse_analysis ─────────────────────────────────────────────────────────────


class TestParseAnalysis:
    def test_parses_all_fields(self) -> None:
        a = _parse_analysis("msg_1", VALID_DATA)
        assert a.email_id == "msg_1"
        assert a.sentiment == 0.5
        assert a.intent == Intent.QUESTION
        assert a.priority == Priority.MEDIUM
        assert a.entities == ["Alice", "Project X"]
        assert a.summary == "Alice asks about Project X."
        assert a.requires_reply is True
        assert a.deadline == "by Friday"

    def test_null_deadline_maps_to_none(self) -> None:
        data = {**VALID_DATA, "deadline": None}
        a = _parse_analysis("msg_1", data)
        assert a.deadline is None

    def test_empty_entities_list(self) -> None:
        data = {**VALID_DATA, "entities": []}
        a = _parse_analysis("msg_1", data)
        assert a.entities == []

    def test_returns_email_analysis_instance(self) -> None:
        a = _parse_analysis("msg_1", VALID_DATA)
        assert isinstance(a, EmailAnalysis)

    def test_email_id_threaded_through(self) -> None:
        a = _parse_analysis("custom_id", VALID_DATA)
        assert a.email_id == "custom_id"


# ── EmailAnalyzer.analyze ───────────────────────────────────────────────────────


class TestEmailAnalyzerAnalyze:
    @pytest.fixture
    def analyzer(self) -> EmailAnalyzer:
        return EmailAnalyzer(api_key="test-key")

    def _mock_response(self, *blocks: object) -> MagicMock:
        r = MagicMock()
        r.content = list(blocks)
        r.stop_reason = "tool_use"
        return r

    async def test_returns_analysis_on_success(self, analyzer: EmailAnalyzer) -> None:
        block = make_tool_block(VALID_DATA)
        analyzer._client.messages.create = AsyncMock(
            return_value=self._mock_response(block)
        )

        result = await analyzer.analyze(make_email())

        assert isinstance(result, EmailAnalysis)
        assert result.sentiment == 0.5

    async def test_passes_email_id_through(self, analyzer: EmailAnalyzer) -> None:
        block = make_tool_block(VALID_DATA)
        analyzer._client.messages.create = AsyncMock(
            return_value=self._mock_response(block)
        )

        result = await analyzer.analyze(make_email(id="special_id"))

        assert result.email_id == "special_id"

    async def test_raises_analysis_error_on_empty_content(
        self, analyzer: EmailAnalyzer
    ) -> None:
        r = MagicMock()
        r.content = []
        r.stop_reason = "end_turn"
        analyzer._client.messages.create = AsyncMock(return_value=r)

        with pytest.raises(AnalysisError):
            await analyzer.analyze(make_email())

    async def test_raises_analysis_error_for_wrong_tool_name(
        self, analyzer: EmailAnalyzer
    ) -> None:
        wrong = ToolUseBlock(
            type="tool_use", id="toolu_x", name="some_other_tool", input={}
        )
        analyzer._client.messages.create = AsyncMock(
            return_value=self._mock_response(wrong)
        )

        with pytest.raises(AnalysisError):
            await analyzer.analyze(make_email())

    async def test_skips_non_tool_blocks(self, analyzer: EmailAnalyzer) -> None:
        """Non-ToolUseBlock content blocks must be ignored, not crash."""
        text_block = MagicMock()
        text_block.__class__ = object  # not a ToolUseBlock
        good_block = make_tool_block(VALID_DATA)
        analyzer._client.messages.create = AsyncMock(
            return_value=self._mock_response(text_block, good_block)
        )

        result = await analyzer.analyze(make_email())

        assert isinstance(result, EmailAnalysis)


# ── AnalysisProcessor.process ───────────────────────────────────────────────────


class TestAnalysisProcessorProcess:
    def _make_processor(self) -> tuple[AnalysisProcessor, MagicMock, MagicMock]:
        analyzer = MagicMock()
        gmail = MagicMock()
        gmail.apply_label = AsyncMock()
        gmail.star_email = AsyncMock()
        return AnalysisProcessor(analyzer=analyzer, gmail=gmail), analyzer, gmail

    def _analysis(self, **kwargs: object) -> EmailAnalysis:
        defaults: dict[str, object] = dict(
            email_id="msg_1",
            sentiment=0.0,
            intent=Intent.FYI,
            priority=Priority.MEDIUM,
        )
        return EmailAnalysis(**{**defaults, **kwargs})  # type: ignore[arg-type]

    async def test_calls_analyzer_with_email(self) -> None:
        proc, analyzer, _ = self._make_processor()
        analyzer.analyze = AsyncMock(return_value=self._analysis())

        email = make_email()
        await proc.process(email)

        analyzer.analyze.assert_called_once_with(email)

    async def test_applies_priority_label(self) -> None:
        proc, analyzer, gmail = self._make_processor()
        analyzer.analyze = AsyncMock(return_value=self._analysis(priority=Priority.HIGH))

        await proc.process(make_email())

        labels_applied = [c.args[1] for c in gmail.apply_label.call_args_list]
        assert "AI/Priority/High" in labels_applied

    async def test_applies_intent_label(self) -> None:
        proc, analyzer, gmail = self._make_processor()
        analyzer.analyze = AsyncMock(
            return_value=self._analysis(intent=Intent.ACTION_REQUIRED)
        )

        await proc.process(make_email())

        labels_applied = [c.args[1] for c in gmail.apply_label.call_args_list]
        assert "AI/Intent/ActionRequired" in labels_applied

    async def test_stars_critical_emails(self) -> None:
        proc, analyzer, gmail = self._make_processor()
        analyzer.analyze = AsyncMock(
            return_value=self._analysis(priority=Priority.CRITICAL)
        )

        await proc.process(make_email())

        gmail.star_email.assert_called_once()

    async def test_stars_high_priority_emails(self) -> None:
        proc, analyzer, gmail = self._make_processor()
        analyzer.analyze = AsyncMock(
            return_value=self._analysis(priority=Priority.HIGH)
        )

        await proc.process(make_email())

        gmail.star_email.assert_called_once()

    async def test_does_not_star_medium_priority(self) -> None:
        proc, analyzer, gmail = self._make_processor()
        analyzer.analyze = AsyncMock(
            return_value=self._analysis(priority=Priority.MEDIUM)
        )

        await proc.process(make_email())

        gmail.star_email.assert_not_called()

    async def test_applies_followup_label_when_reply_required(self) -> None:
        proc, analyzer, gmail = self._make_processor()
        analyzer.analyze = AsyncMock(
            return_value=self._analysis(requires_reply=True)
        )

        await proc.process(make_email())

        labels_applied = [c.args[1] for c in gmail.apply_label.call_args_list]
        assert "AI/FollowUp" in labels_applied

    async def test_no_followup_label_when_reply_not_required(self) -> None:
        proc, analyzer, gmail = self._make_processor()
        analyzer.analyze = AsyncMock(
            return_value=self._analysis(requires_reply=False)
        )

        await proc.process(make_email())

        labels_applied = [c.args[1] for c in gmail.apply_label.call_args_list]
        assert "AI/FollowUp" not in labels_applied

    async def test_swallows_analysis_error(self) -> None:
        """A failed analysis must not propagate — processor contract requires silence."""
        proc, analyzer, _ = self._make_processor()
        analyzer.analyze = AsyncMock(side_effect=AnalysisError("Haiku failed"))

        await proc.process(make_email())  # must not raise

    async def test_label_failure_does_not_raise(self) -> None:
        """Individual label write failures must be swallowed."""
        proc, analyzer, gmail = self._make_processor()
        analyzer.analyze = AsyncMock(return_value=self._analysis())
        gmail.apply_label = AsyncMock(side_effect=Exception("network error"))

        await proc.process(make_email())  # must not raise
