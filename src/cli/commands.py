"""CLI command implementations — all commands delegate to QueryEngine."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

import click
from anthropic import AsyncAnthropic
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from src.cli.query import QueryEngine

try:
    from src.mcp.gmail_client import MCPError, gmail_client
    from src.processing.analyzer import AnalysisProcessor, EmailAnalyzer
except ModuleNotFoundError:  # mcp package not installed in test environment
    gmail_client = None  # type: ignore[assignment]
    MCPError = Exception  # type: ignore[assignment,misc]
    AnalysisProcessor = None  # type: ignore[assignment,misc]
    EmailAnalyzer = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)
console = Console(width=200)

_PRIORITY_LABEL: dict[int, str] = {
    1: "CRITICAL",
    2: "HIGH",
    3: "MEDIUM",
    4: "LOW",
    5: "FYI",
}
_PRIORITY_STYLE: dict[int, str] = {
    1: "red bold",
    2: "orange3",
    3: "yellow",
    4: "white",
    5: "dim",
}


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
    table.add_column("Priority", width=10)
    table.add_column("Score", width=6)

    for i, result in enumerate(results, start=1):
        m = result.metadata
        pri = int(m.get("priority", 3))
        pri_label = _PRIORITY_LABEL.get(pri, str(pri))
        pri_style = _PRIORITY_STYLE.get(pri, "white")
        score = f"{max(0.0, 1.0 - result.distance):.2f}"
        table.add_row(
            str(i),
            str(m.get("subject", "")),
            str(m.get("sender", "")),
            str(m.get("date", ""))[:10],
            f"[{pri_style}]{pri_label}[/{pri_style}]",
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
@click.option(
    "--rate-limit",
    default=1.0,
    show_default=True,
    help="Max Haiku API calls per second.",
)
@click.pass_obj
def backfill(engine: QueryEngine, days: int, rate_limit: float) -> None:
    """Process historical emails from the last N days."""
    asyncio.run(_backfill_async(engine, days, rate_limit))


async def _backfill_async(engine: QueryEngine, days: int, rate_limit: float) -> None:
    import asyncio as _asyncio

    from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

    stored_ids = engine.get_stored_ids_since(days)

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

            delay = 1.0 / rate_limit
            processed = 0
            failed = 0

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Processing...", total=len(new_emails))
                analyzer = EmailAnalyzer()
                processor = AnalysisProcessor(
                    analyzer=analyzer,
                    gmail=gmail,
                    vector_store=engine.vector_store,
                    db=engine.db,
                )
                for email in new_emails:
                    try:
                        await processor.process(email)
                        processed += 1
                    except Exception as exc:  # noqa: BLE001
                        logger.error("Backfill: failed on email %s: %s", email.id, exc)
                        failed += 1
                    finally:
                        progress.advance(task)
                        await _asyncio.sleep(delay)

            console.print(
                f"[green]Done.[/green] {processed} processed"
                + (f", [red]{failed} failed[/red]" if failed else "")
                + "."
            )

    except MCPError as exc:
        console.print(f"[red]Gmail MCP error: {exc}[/red]")
