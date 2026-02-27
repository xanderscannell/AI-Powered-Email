"""APScheduler setup for the daily briefing trigger."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from apscheduler.schedulers.asyncio import AsyncIOScheduler

if TYPE_CHECKING:
    from src.briefing.generator import OutputConfig
    from src.cli.query import QueryEngine

logger = logging.getLogger(__name__)


def _parse_briefing_time(time_str: str) -> tuple[int, int]:
    """Parse 'HH:MM' into (hour, minute). Falls back to (7, 0) on parse error."""
    try:
        hour_str, minute_str = time_str.strip().split(":")
        return int(hour_str), int(minute_str)
    except (ValueError, AttributeError):
        logger.warning("Invalid BRIEFING_TIME %r; defaulting to 07:00", time_str)
        return 7, 0


def create_briefing_scheduler(
    engine: QueryEngine,
    output_config: OutputConfig,
) -> AsyncIOScheduler:
    """Return a configured AsyncIOScheduler that fires BriefingGenerator.generate() daily.

    The caller is responsible for calling scheduler.start() and scheduler.shutdown().
    """
    from src.briefing.generator import BriefingGenerator

    scheduler = AsyncIOScheduler()
    generator = BriefingGenerator(engine, output_config)
    hour, minute = _parse_briefing_time(os.environ.get("BRIEFING_TIME", "07:00"))
    scheduler.add_job(generator.generate, "cron", hour=hour, minute=minute)
    logger.info("Briefing scheduled daily at %02d:%02d", hour, minute)
    return scheduler
