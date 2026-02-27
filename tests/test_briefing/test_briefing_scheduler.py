"""Tests for create_briefing_scheduler and _parse_briefing_time."""

import pytest
from unittest.mock import MagicMock


class TestParseBriefingTime:
    def test_parses_valid_time(self) -> None:
        from src.briefing.scheduler import _parse_briefing_time
        assert _parse_briefing_time("07:00") == (7, 0)
        assert _parse_briefing_time("09:30") == (9, 30)
        assert _parse_briefing_time("00:00") == (0, 0)

    def test_defaults_to_seven_on_invalid(self) -> None:
        from src.briefing.scheduler import _parse_briefing_time
        assert _parse_briefing_time("not-a-time") == (7, 0)

    def test_handles_whitespace(self) -> None:
        from src.briefing.scheduler import _parse_briefing_time
        assert _parse_briefing_time("  08:15  ") == (8, 15)


class TestCreateBriefingScheduler:
    def test_returns_async_io_scheduler(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from src.briefing.generator import OutputConfig
        from src.briefing.scheduler import create_briefing_scheduler

        monkeypatch.setenv("BRIEFING_TIME", "08:00")
        engine = MagicMock()
        config = OutputConfig(terminal=False)
        scheduler = create_briefing_scheduler(engine, config)
        assert isinstance(scheduler, AsyncIOScheduler)

    def test_job_added_with_correct_cron_params(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.briefing.generator import OutputConfig
        from src.briefing.scheduler import create_briefing_scheduler

        monkeypatch.setenv("BRIEFING_TIME", "06:45")
        engine = MagicMock()
        config = OutputConfig(terminal=False)
        scheduler = create_briefing_scheduler(engine, config)
        jobs = scheduler.get_jobs()
        assert len(jobs) == 1
        trigger = jobs[0].trigger
        fields = {f.name: f for f in trigger.fields}
        assert str(fields["hour"]) == "6"
        assert str(fields["minute"]) == "45"

    def test_default_briefing_time_is_seven(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.briefing.generator import OutputConfig
        from src.briefing.scheduler import create_briefing_scheduler

        monkeypatch.delenv("BRIEFING_TIME", raising=False)
        engine = MagicMock()
        scheduler = create_briefing_scheduler(engine, OutputConfig(terminal=False))
        jobs = scheduler.get_jobs()
        fields = {f.name: f for f in jobs[0].trigger.fields}
        assert str(fields["hour"]) == "7"
