"""CLI command implementations — all commands delegate to QueryEngine."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import anthropic
import click
from anthropic import AsyncAnthropic
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from src.cli.query import QueryEngine

import json

from src.mcp.gmail_client import MCPError, gmail_client
from src.mcp.types import RawEmail
from src.processing.analyzer import (
    AnalysisProcessor,
    EmailAnalyzer,
    build_batch_request,
    parse_analysis_from_message,
)
from src.processing.types import Domain, EmailAnalysis, EmailType
from src.storage.models import EmailRow

logger = logging.getLogger(__name__)
console = Console(width=200)


@click.command()
@click.argument("query")
@click.option("--limit", default=10, show_default=True, help="Number of results.")
@click.pass_obj
def search(engine: QueryEngine, query: str, limit: int) -> None:
    """Semantic search over indexed emails."""
    results = engine.search(query, n=limit)

    if not results:
        console.print(
            "[yellow]No emails indexed yet. "
            "Run `email-agent backfill --days 30` to get started.[/yellow]"
        )
        return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Subject", max_width=38)
    table.add_column("From", max_width=26)
    table.add_column("Date", width=12)
    table.add_column("Type", width=10)
    table.add_column("Domain", width=12)
    table.add_column("Score", width=6)

    for i, result in enumerate(results, start=1):
        m = result.metadata
        email_type = str(m.get("email_type", ""))
        domain = str(m.get("domain", ""))
        type_style = "cyan" if email_type == "human" else "dim"
        score = f"{max(0.0, 1.0 - result.distance):.2f}"
        table.add_row(
            str(i),
            str(m.get("subject", "")),
            str(m.get("sender", "")),
            str(m.get("date", ""))[:10],
            f"[{type_style}]{email_type}[/{type_style}]",
            domain or "",
            score,
        )

    console.print(f"\nSearch results for [bold]{query!r}[/bold]\n")
    console.print(table)

    top = results[0].metadata
    if top.get("summary"):
        console.print(f"\n  [dim]Top result:[/dim] {top['summary']}")


_STATUS_MODEL = "claude-sonnet-4-6"
_STATUS_MAX_TOKENS = 1024


@click.command()
@click.argument("topic")
@click.option("--limit", default=10, show_default=True, help="Emails to include.")
@click.pass_obj
def status(engine: QueryEngine, topic: str, limit: int) -> None:
    """Synthesise a thread status for a topic using Claude Sonnet."""
    asyncio.run(_status_async(engine, topic, limit))


async def _status_async(engine: QueryEngine, topic: str, limit: int) -> None:
    console.print(f"Fetching emails related to [bold]{topic!r}[/bold]...")
    rows = engine.get_emails_for_topic(topic, n=limit)

    if not rows:
        console.print("[yellow]No emails found for that topic.[/yellow]")
        return

    console.print(f"Found {len(rows)} email(s). Generating summary with Sonnet...")

    email_context = "\n\n---\n\n".join(
        f"From: {r.sender}\nDate: {r.date or 'unknown'}\n"
        f"Subject: {r.subject}\n\n{r.body or r.snippet}"
        for r in rows
    )
    prompt = (
        f"Here are {len(rows)} emails related to the topic '{topic}':\n\n"
        f"{email_context}\n\n"
        "Provide a concise status summary covering: current state, last action taken, "
        "who needs to respond next (if anyone), and recommended next step. "
        "Be specific — reference actual names, dates, and details from the emails."
    )

    client = AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    try:
        response = await client.messages.create(
            model=_STATUS_MODEL,
            max_tokens=_STATUS_MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = response.content[0].text if response.content else "(no response)"
    except Exception as exc:  # noqa: BLE001
        logger.error("Sonnet synthesis failed: %s", exc)
        console.print(f"[red]Synthesis failed: {exc}[/red]")
        console.print("\n[dim]Raw emails found:[/dim]")
        for row in rows:
            console.print(f"  • {row.subject} — {row.sender} ({row.date})")
        return

    console.print(Panel(summary, title=f"[bold]{topic}[/bold]", border_style="blue"))


@click.command()
@click.option("--days", required=True, type=int, help="Days of history to process.")
@click.pass_obj
def backfill(engine: QueryEngine, days: int) -> None:
    """Process historical emails from the last N days via the Anthropic Batches API."""
    asyncio.run(_backfill_async(engine, days))


def _create_batch(requests: list, api_key: str) -> str:
    """Synchronous: submit a batch to Anthropic. Returns the batch ID."""
    client = anthropic.Anthropic(api_key=api_key)
    batch = client.messages.batches.create(requests=requests)
    return batch.id


def _retrieve_batch(batch_id: str, api_key: str) -> object:
    """Synchronous: retrieve current batch status."""
    client = anthropic.Anthropic(api_key=api_key)
    return client.messages.batches.retrieve(batch_id)


def _collect_batch_results(batch_id: str, api_key: str) -> list:
    """Synchronous: stream all batch results into a list."""
    client = anthropic.Anthropic(api_key=api_key)
    return list(client.messages.batches.results(batch_id))


async def _backfill_async(engine: QueryEngine, days: int) -> None:
    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

    stored_ids = engine.get_stored_ids_since(days)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")

    try:
        async with gmail_client() as gmail:
            console.print(f"Fetching all emails from the last {days} day(s)...")
            all_emails = await gmail.get_emails_since(days)

            new_emails = [e for e in all_emails if e.id not in stored_ids]
            console.print(
                f"Found {len(all_emails)} email(s). "
                f"[dim]{len(stored_ids)} already stored,[/dim] "
                f"[bold]{len(new_emails)} new.[/bold]"
            )

            if not new_emails:
                console.print("[green]Nothing to do.[/green]")
                return

            # ── Submit batch ────────────────────────────────────────────────
            requests = [build_batch_request(e) for e in new_emails]
            console.print(
                f"Submitting batch of [bold]{len(new_emails)}[/bold] email(s) "
                f"to Anthropic (50% off vs real-time)..."
            )
            batch_id = await asyncio.to_thread(_create_batch, requests, api_key)
            console.print(f"  Batch ID: [dim]{batch_id}[/dim]")

            # ── Poll with live status ────────────────────────────────────────
            with console.status("Waiting for Anthropic batch to complete...") as status:
                while True:
                    batch = await asyncio.to_thread(_retrieve_batch, batch_id, api_key)
                    if batch.processing_status == "ended":
                        break
                    c = batch.request_counts
                    status.update(
                        f"Processing batch — "
                        f"[green]{c.succeeded} done[/green], "
                        f"{c.processing} in progress"
                        + (f", [red]{c.errored} errored[/red]" if c.errored else "")
                        + "..."
                    )
                    await asyncio.sleep(5)

            counts = batch.request_counts
            console.print(
                f"Batch complete — "
                f"[green]{counts.succeeded} succeeded[/green]"
                + (f", [red]{counts.errored} errored[/red]" if counts.errored else "")
                + "."
            )

            # ── Collect results ─────────────────────────────────────────────
            results = await asyncio.to_thread(_collect_batch_results, batch_id, api_key)

            # ── Fan out: labels + storage ───────────────────────────────────
            email_map = {e.id: e for e in new_emails}
            processor = AnalysisProcessor(
                analyzer=EmailAnalyzer(),
                gmail=gmail,
                vector_store=engine.vector_store,
                db=engine.db,
            )
            processed = 0
            failed = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Applying labels & storing...", total=len(results))
                for result in results:
                    email = email_map.get(result.custom_id)
                    if result.result.type == "succeeded" and email is not None:
                        try:
                            analysis = parse_analysis_from_message(
                                result.custom_id, result.result.message
                            )
                            await processor.process_with_analysis(email, analysis)
                            processed += 1
                        except Exception as exc:  # noqa: BLE001
                            logger.error("Backfill: fan-out failed for %s: %s", result.custom_id, exc)
                            failed += 1
                    else:
                        logger.warning(
                            "Backfill: batch item %s — %s",
                            result.custom_id,
                            result.result.type,
                        )
                        failed += 1
                    progress.advance(task)

            console.print(
                f"[green]Done.[/green] {processed} processed"
                + (f", [red]{failed} failed[/red]" if failed else "")
                + "."
            )

    except (MCPError, ValueError) as exc:
        console.print(f"[red]Gmail error: {exc}[/red]")


@click.command()
@click.option(
    "--output",
    default=None,
    help="Comma-separated outputs to enable: terminal,file,email. Overrides env vars.",
)
@click.pass_obj
def briefing(engine: QueryEngine, output: str | None) -> None:
    """Generate an on-demand morning briefing with Claude Sonnet."""
    asyncio.run(_briefing_async(engine, output))


async def _briefing_async(engine: QueryEngine, output_override: str | None) -> None:
    from src.briefing.generator import BriefingGenerator, OutputConfig

    if output_override is not None:
        flags = {s.strip() for s in output_override.split(",")}
        config = OutputConfig(
            terminal="terminal" in flags,
            file="file" in flags,
            email_self="email" in flags,
            email_recipient=os.environ.get("BRIEFING_EMAIL_TO", ""),
        )
    else:
        config = OutputConfig.from_env()

    generator = BriefingGenerator(engine, config)
    await generator.generate()


# ── reindex ──────────────────────────────────────────────────────────────────


def _row_to_raw_email(row: EmailRow) -> RawEmail:
    return RawEmail(
        id=row.id,
        thread_id=row.thread_id,
        sender=row.sender,
        subject=row.subject,
        snippet=row.snippet,
        body=row.body,
        date=row.date,
    )


def _row_to_analysis(row: EmailRow) -> EmailAnalysis:
    return EmailAnalysis(
        email_id=row.id,
        email_type=EmailType(row.email_type),
        domain=Domain(row.domain) if row.domain else None,
        entities=json.loads(row.entities),
        summary=row.summary,
        requires_reply=row.requires_reply,
        deadline=row.deadline,
    )


@click.command()
@click.pass_obj
def reindex(engine: QueryEngine) -> None:
    """Re-populate the vector store from emails already in the database.

    Reads every email from SQLite and re-embeds it into ChromaDB.
    No API calls — use this after deleting data/chroma to rebuild the index.
    """
    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

    rows = engine.db.get_all_emails()
    if not rows:
        console.print("[yellow]No emails in database to reindex.[/yellow]")
        return

    console.print(f"Reindexing [bold]{len(rows)}[/bold] emails from database into vector store...")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Embedding...", total=len(rows))
        for row in rows:
            engine.vector_store.upsert(_row_to_raw_email(row), _row_to_analysis(row))
            progress.advance(task)

    console.print(f"[green]Done.[/green] {len(rows)} emails indexed.")
