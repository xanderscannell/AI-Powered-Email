"""Core agent loop — polls Gmail for new emails and feeds them to a processor."""

import asyncio
import logging
import os
import signal
from typing import Protocol, runtime_checkable

from dotenv import load_dotenv

from src.mcp.gmail_client import GmailClient, MCPError, gmail_client
from src.mcp.types import RawEmail

logger = logging.getLogger(__name__)

# Backoff: 2^attempt seconds, capped at 5 minutes
_MAX_BACKOFF_SECONDS = 300


# ── Processor interface ────────────────────────────────────────────────────────


@runtime_checkable
class EmailProcessor(Protocol):
    """Interface for the email processing pipeline.

    Phase 2 will implement this with the Haiku analyser.  For now,
    NoOpProcessor is used as the placeholder.
    """

    async def process(self, email: RawEmail) -> None:
        """Process a single email (analyse, store, label).

        Implementations must not raise — log and swallow errors internally
        so the watcher loop stays alive.
        """
        ...


class NoOpProcessor:
    """Stub processor used until Phase 2 (Haiku analysis) is implemented.

    Logs each email so you can verify the watcher loop is working end-to-end
    without needing a real analyser in place.
    """

    async def process(self, email: RawEmail) -> None:
        logger.info(
            "[NoOp] email id=%s from=%r subject=%r",
            email.id,
            email.sender,
            email.subject,
        )


# ── Watcher ────────────────────────────────────────────────────────────────────


class EmailWatcher:
    """Polls Gmail for unread emails and feeds each new one to a processor.

    Reconnects automatically on MCP failures using exponential backoff so the
    agent can run unattended across transient network or subprocess issues.

    Processed email IDs are tracked in an in-memory set for this phase.
    Phase 3 will replace this with SQLite-backed persistence so IDs survive
    restarts.

    Usage::

        watcher = EmailWatcher(processor=NoOpProcessor())
        await watcher.run()          # blocks until stop() is called
    """

    def __init__(
        self,
        processor: EmailProcessor,
        poll_interval: int | None = None,
        max_results_per_poll: int = 50,
    ) -> None:
        self._processor = processor
        self._poll_interval = poll_interval or int(
            os.environ.get("POLL_INTERVAL_SECONDS", "60")
        )
        self._max_results = max_results_per_poll
        self._processed_ids: set[str] = set()  # Phase 3: replace with SQLite
        self._stop_event = asyncio.Event()

    def stop(self) -> None:
        """Signal the watcher to finish the current poll and shut down cleanly."""
        logger.info("Shutdown requested — finishing current poll then stopping")
        self._stop_event.set()

    async def run(self) -> None:
        """Run the watcher loop, reconnecting on MCP failures with backoff.

        Returns only after stop() is called or an unrecoverable error occurs.
        """
        attempt = 0
        while not self._stop_event.is_set():
            try:
                async with gmail_client() as gmail:
                    logger.info("Connected to Gmail MCP — running ensure_ai_labels")
                    await gmail.ensure_ai_labels()
                    attempt = 0  # reset backoff counter on successful connect
                    await self._loop(gmail)
            except MCPError as exc:
                if self._stop_event.is_set():
                    break
                attempt += 1
                delay = min(2**attempt, _MAX_BACKOFF_SECONDS)
                logger.error(
                    "MCP error (attempt %d): %s — reconnecting in %ds",
                    attempt,
                    exc,
                    delay,
                )
                await self._interruptible_sleep(delay)
            except Exception as exc:  # noqa: BLE001
                if self._stop_event.is_set():
                    break
                attempt += 1
                delay = min(2**attempt, _MAX_BACKOFF_SECONDS)
                logger.error(
                    "Unexpected error (attempt %d): %s — reconnecting in %ds",
                    attempt,
                    exc,
                    delay,
                    exc_info=True,
                )
                await self._interruptible_sleep(delay)

        logger.info("Watcher stopped")

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _loop(self, gmail: GmailClient) -> None:
        """Inner poll loop — runs until stop() is called or an exception escapes."""
        while not self._stop_event.is_set():
            await self._poll(gmail)
            await self._interruptible_sleep(self._poll_interval)

    async def _poll(self, gmail: GmailClient) -> None:
        """Fetch unread emails, skip already-seen IDs, and run the processor."""
        emails = await gmail.get_unread_emails(max_results=self._max_results)
        new = [e for e in emails if e.id not in self._processed_ids]

        if not new:
            logger.debug("Poll: 0 new emails (%d total unread)", len(emails))
            return

        logger.info("Poll: %d new email(s) to process", len(new))
        for email in new:
            try:
                await self._processor.process(email)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "Processor failed on email %s: %s",
                    email.id,
                    exc,
                    exc_info=True,
                )
            finally:
                # Always mark as seen — avoid re-processing on the next poll
                # even if the processor raised.
                self._processed_ids.add(email.id)

    async def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep for `seconds` but wake immediately if stop() is called."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass


# ── Entry point ────────────────────────────────────────────────────────────────


def main() -> None:
    """Start the email agent.  Called by `python -m src` and the CLI entry point."""
    load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        # Ctrl+C on Windows (no add_signal_handler) arrives here
        logger.info("Interrupted — goodbye")


async def _amain() -> None:
    """Async entry point: wire up signal handlers and run the watcher."""
    watcher = EmailWatcher(processor=NoOpProcessor())

    loop = asyncio.get_running_loop()
    try:
        # Unix: clean async signal handling
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, watcher.stop)
    except (NotImplementedError, AttributeError):
        # Windows: fall back to KeyboardInterrupt caught in main()
        pass

    await watcher.run()
