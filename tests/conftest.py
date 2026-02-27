"""Shared pytest fixtures."""

import pytest


@pytest.fixture
def sample_raw_email() -> dict[str, str]:
    """A minimal raw email object for use in tests."""
    return {
        "id": "msg_001",
        "thread_id": "thread_001",
        "sender": "alice@example.com",
        "subject": "Q2 budget review — action required",
        "body": "Hi, please review the attached budget figures and respond by Friday.",
        "timestamp": "2026-02-27T09:00:00Z",
    }
