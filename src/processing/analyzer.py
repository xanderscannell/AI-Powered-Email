"""Email analysis pipeline — Haiku-powered structured extraction."""

import logging
import os

from anthropic import AsyncAnthropic
from anthropic.types import ToolUseBlock

from src.mcp.gmail_client import GmailClient
from src.mcp.types import RawEmail
from src.processing.prompts import ANALYSIS_TOOL, build_messages
from src.processing.types import (
    EmailAnalysis,
    Intent,
    INTENT_LABEL,
    Priority,
    PRIORITY_LABEL,
)

logger = logging.getLogger(__name__)

# Haiku: fast and cheap enough to run on every incoming email.
# Use Sonnet/Opus for synthesis tasks (briefings, draft replies) in later phases.
_MODEL = "claude-haiku-4-5-20251001"
_MAX_TOKENS = 1024


class AnalysisError(Exception):
    """Raised when Haiku fails to return a valid analysis tool call."""


# ── Analyser ───────────────────────────────────────────────────────────────────


class EmailAnalyzer:
    """Sends a single email to Claude Haiku and returns structured analysis.

    Uses Anthropic's tool_use with a forced tool_choice so the response is
    always machine-readable — no JSON parsing, no markdown fences.

    Usage::

        analyzer = EmailAnalyzer()
        analysis = await analyzer.analyze(email)
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._client = AsyncAnthropic(
            api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        )

    async def analyze(self, email: RawEmail) -> EmailAnalysis:
        """Analyse a single email and return structured EmailAnalysis.

        Raises:
            AnalysisError: if Haiku does not return the expected tool_use block.
        """
        response = await self._client.messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            tools=[ANALYSIS_TOOL],  # type: ignore[list-item]
            tool_choice={"type": "tool", "name": "record_email_analysis"},
            messages=build_messages(email),  # type: ignore[arg-type]
        )

        for block in response.content:
            if isinstance(block, ToolUseBlock) and block.name == "record_email_analysis":
                data = block.input
                return _parse_analysis(email.id, data)  # type: ignore[arg-type]

        raise AnalysisError(
            f"Haiku did not return a record_email_analysis tool call "
            f"for email {email.id!r} (stop_reason={response.stop_reason!r})"
        )


def _parse_analysis(email_id: str, data: dict[str, object]) -> EmailAnalysis:
    """Convert the raw tool-call input dict into a typed EmailAnalysis."""
    return EmailAnalysis(
        email_id=email_id,
        sentiment=float(data["sentiment"]),  # type: ignore[arg-type]
        intent=Intent(data["intent"]),
        priority=Priority(int(data["priority"])),  # type: ignore[arg-type]
        entities=[str(e) for e in data.get("entities", [])],  # type: ignore[union-attr]
        summary=str(data.get("summary", "")),
        requires_reply=bool(data.get("requires_reply", False)),
        deadline=str(data["deadline"]) if data.get("deadline") else None,
    )


# ── Processor ──────────────────────────────────────────────────────────────────


class AnalysisProcessor:
    """EmailProcessor that analyses each email and writes results back to Gmail.

    Implements the EmailProcessor protocol from src.agent.watcher.

    On each email it:
      1. Calls Haiku via EmailAnalyzer → EmailAnalysis
      2. Applies the priority label  (AI/Priority/*)
      3. Applies the intent label    (AI/Intent/*)
      4. Stars the email             (priority CRITICAL or HIGH)
      5. Applies AI/FollowUp label   (if requires_reply)

    Phase 3 will extend this to also write to ChromaDB and SQLite.
    """

    def __init__(self, analyzer: EmailAnalyzer, gmail: GmailClient) -> None:
        self._analyzer = analyzer
        self._gmail = gmail

    async def process(self, email: RawEmail) -> None:
        """Analyse email and apply Gmail labels. Never raises — logs on failure."""
        try:
            analysis = await self._analyzer.analyze(email)
        except AnalysisError as exc:
            logger.error("Analysis failed for email %s: %s", email.id, exc)
            return

        await self._apply_labels(email.id, analysis)

        logger.info(
            "email=%s priority=%s intent=%s sentiment=%+.2f reply=%s deadline=%r",
            email.id,
            analysis.priority.name,
            analysis.intent.value,
            analysis.sentiment,
            analysis.requires_reply,
            analysis.deadline,
        )

    async def _apply_labels(self, email_id: str, analysis: EmailAnalysis) -> None:
        """Fan out label writes; log individual failures rather than raising."""
        ops: list[tuple[str, object]] = [
            ("priority label", self._gmail.apply_label(email_id, PRIORITY_LABEL[analysis.priority])),
            ("intent label", self._gmail.apply_label(email_id, INTENT_LABEL[analysis.intent])),
        ]
        if analysis.priority in (Priority.CRITICAL, Priority.HIGH):
            ops.append(("star", self._gmail.star_email(email_id)))
        if analysis.requires_reply:
            ops.append(("follow-up label", self._gmail.apply_label(email_id, "AI/FollowUp")))

        for name, coro in ops:
            try:
                await coro  # type: ignore[misc]
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to apply %s to email %s: %s", name, email_id, exc)
