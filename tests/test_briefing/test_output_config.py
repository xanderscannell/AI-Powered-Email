"""Tests for OutputConfig — env var parsing."""

import pytest

from src.briefing.generator import OutputConfig


class TestOutputConfigDefaults:
    def test_terminal_on_by_default(self) -> None:
        assert OutputConfig().terminal is True

    def test_file_off_by_default(self) -> None:
        assert OutputConfig().file is False

    def test_email_off_by_default(self) -> None:
        assert OutputConfig().email_self is False

    def test_briefing_dir_default(self) -> None:
        from pathlib import Path
        assert OutputConfig().briefing_dir == Path("data/briefings")


class TestOutputConfigFromEnv:
    def test_reads_terminal_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRIEFING_OUTPUT_TERMINAL", "false")
        assert OutputConfig.from_env().terminal is False

    def test_reads_file_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRIEFING_OUTPUT_FILE", "true")
        assert OutputConfig.from_env().file is True

    def test_reads_email_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRIEFING_OUTPUT_EMAIL", "true")
        assert OutputConfig.from_env().email_self is True

    def test_reads_email_recipient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRIEFING_EMAIL_TO", "me@example.com")
        assert OutputConfig.from_env().email_recipient == "me@example.com"

    def test_case_insensitive_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BRIEFING_OUTPUT_FILE", "TRUE")
        assert OutputConfig.from_env().file is True

    def test_defaults_when_env_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for key in ("BRIEFING_OUTPUT_TERMINAL", "BRIEFING_OUTPUT_FILE", "BRIEFING_OUTPUT_EMAIL"):
            monkeypatch.delenv(key, raising=False)
        config = OutputConfig.from_env()
        assert config.terminal is True
        assert config.file is False
        assert config.email_self is False
