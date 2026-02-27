"""Briefing generator — collects data, calls Sonnet, routes output."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


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
