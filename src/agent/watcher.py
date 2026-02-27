"""Core agent loop — polls Gmail for new emails and feeds them to a processor."""

import asyncio
import logging
import os
import signal
from collections.abc import Callable
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
    """Interface for the email processing pipeline."""

    async def process(self, email: RawEmail) -> None:
        """Process a single email (analyse, store, label).

        Implementations must not raise — log and swallow errors internally
        so the watcher loop stays alive.
        """
        ...


#: Factory that creates a fresh processor bound to a live GmailClient.
#: Called once per (re)connection so the processor always holds a valid client.
ProcessorFactory = Callable[[GmailClient], EmailProcessor]


class NoOpProcessor:
    """Stub processor — logs each email without calling Haiku or touching Gmail.

    Useful for end-to-end wiring tests before Phase 2 analysis is active.
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

    The processor is created via a factory on each (re)connection so it always
    holds a reference to the live GmailClient.  Processed email IDs survive
    reconnects in the in-memory set (Phase 3 will persist them to SQLite).

    Usage::

        analyzer = EmailAnalyzer()
        watcher = EmailWatcher(
            processor_factory=lambda gmail: AnalysisProcessor(analyzer, gmail)
        )
        await watcher.run()
    """

    def __init__(
        self,
        processor_factory: ProcessorFactory,
        poll_interval: int | None = None,
        max_results_per_poll: int = 50,
    ) -> None:
        self._processor_factory = processor_factory
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

    async def _seed_processed_ids(self, gmail: GmailClient) -> None:
        """Mark all currently-unread emails as seen without processing them.

        Called once at startup so the agent doesn't immediately hammer the
        Haiku API with years of backlogged emails.  Only emails that arrive
        *after* this seed call will be processed.

        Note: workspace-mcp caps search results at 500.  Inboxes with more
        than 500 unread emails will have the oldest ones fall through to the
        first poll, where they'll be processed normally.  For intentional
        historical processing use `email backfill --days N` (Phase 4).
        """
        ids = await gmail.get_unread_email_ids()
        self._processed_ids.update(ids)
        logger.info(
            "Startup: seeded %d pre-existing unread ID(s) — they will not be processed",
            len(ids),
        )

    async def _loop(self, gmail: GmailClient) -> None:
        """Create a fresh processor, seed processed IDs, then poll until stopped."""
        processor = self._processor_factory(gmail)
        await self._seed_processed_ids(gmail)
        while not self._stop_event.is_set():
            await self._poll(gmail, processor)
            await self._interruptible_sleep(self._poll_interval)

    async def _poll(self, gmail: GmailClient, processor: EmailProcessor) -> None:
        """Fetch unread emails, skip already-seen IDs, and run the processor."""
        emails = await gmail.get_unread_emails(max_results=self._max_results)
        new = [e for e in emails if e.id not in self._processed_ids]

        if not new:
            logger.debug("Poll: 0 new emails (%d total unread)", len(emails))
            return

        logger.info("Poll: %d new email(s) to process", len(new))
        for email in new:
            try:
                await processor.process(email)
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
    from pathlib import Path

    from src.briefing.generator import OutputConfig
    from src.briefing.scheduler import create_briefing_scheduler
    from src.cli.query import QueryEngine
    from src.processing.analyzer import AnalysisProcessor, EmailAnalyzer
    from src.storage.db import EmailDatabase
    from src.storage.vector_store import EmailVectorStore

    analyzer = EmailAnalyzer()
    vector_store = EmailVectorStore(persist_dir=Path("data/chroma"))
    db = EmailDatabase(db_path=Path("data/email_agent.db"))

    engine = QueryEngine(vector_store, db)
    output_config = OutputConfig.from_env()
    scheduler = create_briefing_scheduler(engine, output_config)
    scheduler.start()

    watcher = EmailWatcher(
        processor_factory=lambda gmail: AnalysisProcessor(
            analyzer, gmail, vector_store=vector_store, db=db
        )
    )

    loop = asyncio.get_running_loop()
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, watcher.stop)
    except (NotImplementedError, AttributeError):
        pass

    try:
        await watcher.run()
    finally:
        scheduler.shutdown(wait=False)
