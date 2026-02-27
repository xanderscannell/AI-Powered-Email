"""CLI command implementations — all commands delegate to QueryEngine."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import click
from rich import box
from rich.console import Console
from rich.table import Table

if TYPE_CHECKING:
    from src.cli.query import QueryEngine

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
