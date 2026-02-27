"""Tests for EmailWatcher — GmailClient and processor are fully mocked."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.agent.watcher import EmailProcessor, EmailWatcher, NoOpProcessor
from src.mcp.types import RawEmail


# ── Helpers ────────────────────────────────────────────────────────────────────


def make_email(id: str, subject: str = "Test subject") -> RawEmail:
    return RawEmail(
        id=id,
        thread_id=f"thread_{id}",
        sender="sender@example.com",
        subject=subject,
        snippet="snippet...",
        body="Full email body.",
    )


def make_processor() -> MagicMock:
    p = MagicMock()
    p.process = AsyncMock()
    return p


def make_gmail_mock(*email_batches: list[RawEmail]) -> MagicMock:
    """Mock GmailClient whose get_unread_emails() returns successive batches."""
    gmail = MagicMock()
    gmail.ensure_ai_labels = AsyncMock()
    gmail.get_unread_email_ids = AsyncMock(return_value=[])
    gmail.get_unread_emails = AsyncMock(side_effect=list(email_batches))
    return gmail


def make_watcher(processor: MagicMock | None = None, **kwargs: object) -> tuple[EmailWatcher, MagicMock]:
    """Return (watcher, processor) with a factory that always returns the same processor."""
    proc = processor or make_processor()
    watcher = EmailWatcher(processor_factory=lambda _: proc, **kwargs)  # type: ignore[arg-type]
    return watcher, proc


# ── Protocol conformance ───────────────────────────────────────────────────────


class TestEmailProcessorProtocol:
    def test_noop_processor_satisfies_protocol(self) -> None:
        assert isinstance(NoOpProcessor(), EmailProcessor)

    def test_custom_processor_satisfies_protocol(self) -> None:
        class MyProcessor:
            async def process(self, email: RawEmail) -> None:
                pass

        assert isinstance(MyProcessor(), EmailProcessor)


# ── NoOpProcessor ──────────────────────────────────────────────────────────────


class TestNoOpProcessor:
    async def test_process_does_not_raise(self) -> None:
        proc = NoOpProcessor()
        await proc.process(make_email("msg_1"))  # should not raise


# ── EmailWatcher._poll ─────────────────────────────────────────────────────────


class TestPoll:
    async def test_new_emails_are_passed_to_processor(self) -> None:
        watcher, processor = make_watcher(poll_interval=1)
        emails = [make_email("a"), make_email("b")]
        gmail = make_gmail_mock(emails)

        await watcher._poll(gmail, processor)

        assert processor.process.call_count == 2
        calls = {c.args[0].id for c in processor.process.call_args_list}
        assert calls == {"a", "b"}

    async def test_already_processed_ids_are_skipped(self) -> None:
        watcher, processor = make_watcher(poll_interval=1)
        watcher._processed_ids = {"a", "b"}
        gmail = make_gmail_mock([make_email("a"), make_email("b"), make_email("c")])

        await watcher._poll(gmail, processor)

        processor.process.assert_called_once()
        assert processor.process.call_args.args[0].id == "c"

    async def test_empty_inbox_calls_no_processor(self) -> None:
        watcher, processor = make_watcher(poll_interval=1)
        gmail = make_gmail_mock([])

        await watcher._poll(gmail, processor)

        processor.process.assert_not_called()

    async def test_processed_ids_accumulate_after_poll(self) -> None:
        watcher, processor = make_watcher(poll_interval=1)
        gmail = make_gmail_mock([make_email("x"), make_email("y")])

        await watcher._poll(gmail, processor)

        assert "x" in watcher._processed_ids
        assert "y" in watcher._processed_ids

    async def test_processor_failure_still_marks_email_as_seen(self) -> None:
        """A crashing processor must not cause infinite retries."""
        processor = make_processor()
        processor.process = AsyncMock(side_effect=RuntimeError("boom"))
        watcher, _ = make_watcher(processor=processor, poll_interval=1)
        gmail = make_gmail_mock([make_email("bad")])

        await watcher._poll(gmail, processor)  # must not raise

        assert "bad" in watcher._processed_ids

    async def test_second_poll_skips_first_batch(self) -> None:
        watcher, processor = make_watcher(poll_interval=1)
        batch1 = [make_email("a"), make_email("b")]
        batch2 = [make_email("a"), make_email("b"), make_email("c")]
        gmail = make_gmail_mock(batch1, batch2)

        await watcher._poll(gmail, processor)
        await watcher._poll(gmail, processor)

        # 2 from first poll + 1 new from second poll = 3 total calls
        assert processor.process.call_count == 3


# ── EmailWatcher._seed_processed_ids ──────────────────────────────────────────


class TestSeedProcessedIds:
    async def test_seeds_all_returned_ids(self) -> None:
        watcher, _ = make_watcher(poll_interval=1)
        gmail = MagicMock()
        gmail.get_unread_email_ids = AsyncMock(return_value=["a", "b", "c"])

        await watcher._seed_processed_ids(gmail)

        assert watcher._processed_ids == {"a", "b", "c"}

    async def test_empty_inbox_seeds_nothing(self) -> None:
        watcher, _ = make_watcher(poll_interval=1)
        gmail = MagicMock()
        gmail.get_unread_email_ids = AsyncMock(return_value=[])

        await watcher._seed_processed_ids(gmail)

        assert watcher._processed_ids == set()

    async def test_seeded_ids_are_skipped_on_first_poll(self) -> None:
        """Emails that existed before startup must never reach the processor."""
        watcher, processor = make_watcher(poll_interval=1)
        pre_existing = [make_email("old_1"), make_email("old_2")]
        new_arrival = make_email("new_1")

        gmail = MagicMock()
        gmail.get_unread_email_ids = AsyncMock(return_value=["old_1", "old_2"])
        gmail.get_unread_emails = AsyncMock(return_value=[*pre_existing, new_arrival])

        await watcher._seed_processed_ids(gmail)
        await watcher._poll(gmail, processor)

        processor.process.assert_called_once()
        assert processor.process.call_args.args[0].id == "new_1"


# ── EmailWatcher._interruptible_sleep ─────────────────────────────────────────


class TestInterruptibleSleep:
    async def test_returns_early_when_stopped(self) -> None:
        watcher, _ = make_watcher(poll_interval=60)
        watcher._stop_event.set()
        await asyncio.wait_for(watcher._interruptible_sleep(60), timeout=1.0)

    async def test_waits_full_duration_when_not_stopped(self) -> None:
        watcher, _ = make_watcher(poll_interval=1)
        await asyncio.wait_for(watcher._interruptible_sleep(0.05), timeout=1.0)


# ── EmailWatcher.stop ──────────────────────────────────────────────────────────


class TestStop:
    def test_stop_sets_event(self) -> None:
        watcher, _ = make_watcher(poll_interval=1)
        assert not watcher._stop_event.is_set()
        watcher.stop()
        assert watcher._stop_event.is_set()


# ── EmailWatcher.run (reconnection behaviour) ──────────────────────────────────


class TestRun:
    async def test_run_exits_cleanly_after_stop(self) -> None:
        watcher, _ = make_watcher(poll_interval=60)

        gmail_mock = MagicMock()
        gmail_mock.ensure_ai_labels = AsyncMock()
        gmail_mock.get_unread_email_ids = AsyncMock(return_value=[])
        gmail_mock.get_unread_emails = AsyncMock(return_value=[])

        with patch("src.agent.watcher.gmail_client") as mock_ctx:
            mock_ctx.return_value.__aenter__ = AsyncMock(
                side_effect=lambda *_: (watcher.stop(), gmail_mock)[1]
            )
            mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await asyncio.wait_for(watcher.run(), timeout=2.0)

    async def test_run_reconnects_after_mcp_error(self) -> None:
        """Verifies gmail_client() is called again after an MCPError."""
        from src.mcp.gmail_client import MCPError

        watcher, _ = make_watcher(poll_interval=60)
        call_count = 0

        class FakeContext:
            async def __aenter__(self) -> MagicMock:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    raise MCPError("connection refused")
                watcher.stop()
                m = MagicMock()
                m.ensure_ai_labels = AsyncMock()
                m.get_unread_email_ids = AsyncMock(return_value=[])
                m.get_unread_emails = AsyncMock(return_value=[])
                return m

            async def __aexit__(self, *_: object) -> bool:
                return False

        with patch("src.agent.watcher.gmail_client", return_value=FakeContext()):
            with patch("src.agent.watcher._MAX_BACKOFF_SECONDS", 0):
                await asyncio.wait_for(watcher.run(), timeout=3.0)

        assert call_count == 2, "expected two connection attempts"
