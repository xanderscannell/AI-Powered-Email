"""Tests for launcher.py — watcher process state management."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def reset_watcher_proc():
    """Reset module-level watcher_proc between tests."""
    import launcher

    launcher.watcher_proc = None
    yield
    launcher.watcher_proc = None


def test_check_watcher_false_when_no_proc():
    import launcher

    assert launcher.check_watcher() is False


def test_check_watcher_true_when_proc_running():
    import launcher

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None  # still running
    launcher.watcher_proc = mock_proc

    assert launcher.check_watcher() is True


def test_check_watcher_clears_exited_proc():
    import launcher

    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0  # exited
    launcher.watcher_proc = mock_proc

    assert launcher.check_watcher() is False
    assert launcher.watcher_proc is None


def test_stop_watcher_terminates_proc():
    import launcher

    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    launcher.watcher_proc = mock_proc

    launcher.stop_watcher()

    mock_proc.terminate.assert_called_once()
    assert launcher.watcher_proc is None


def test_prompt_with_default_uses_default_on_empty(monkeypatch):
    import launcher

    monkeypatch.setattr("builtins.input", lambda _: "")
    result = launcher.prompt_with_default("Label", "30")
    assert result == "30"


def test_prompt_with_default_uses_user_value(monkeypatch):
    import launcher

    monkeypatch.setattr("builtins.input", lambda _: "7")
    result = launcher.prompt_with_default("Label", "30")
    assert result == "7"
