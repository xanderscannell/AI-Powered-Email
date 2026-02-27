"""Briefing generator — collects data, calls Sonnet, routes output."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from anthropic import AsyncAnthropic

from src.storage.models import DeadlineRecord, EmailRow, FollowUpRecord

if TYPE_CHECKING:
    from src.cli.query import QueryEngine

logger = logging.getLogger(__name__)

_BRIEFING_MODEL = "claude-sonnet-4-6"
_BRIEFING_MAX_TOKENS = 1500
_PRIORITY_LABEL: dict[int, str] = {1: "CRITICAL", 2: "HIGH", 3: "MEDIUM", 4: "LOW", 5: "FYI"}


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


class BriefingGenerator:
    """Generates a daily briefing: collects data, calls Sonnet, routes output."""

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
            Panel(
                text,
                title=f"[bold]Morning Briefing \u2014 {today}[/bold]",
                border_style="green",
            )
        )

    def _write_file(self, text: str, today: str) -> None:
        """Write briefing to data/briefings/YYYY-MM-DD.md with YAML front-matter."""
        from datetime import datetime

        self._config.briefing_dir.mkdir(parents=True, exist_ok=True)
        path = self._config.briefing_dir / f"{today}.md"
        header = (
            f"---\ndate: {today}\ngenerated_at: {datetime.utcnow().isoformat()}Z\n---\n\n"
        )
        path.write_text(header + text, encoding="utf-8")
        logger.info("Briefing written to %s", path)

    async def _send_email(self, text: str, today: str) -> None:  # pragma: no cover
        """Send briefing via Gmail MCP. Implemented in Task 7."""
        raise NotImplementedError
