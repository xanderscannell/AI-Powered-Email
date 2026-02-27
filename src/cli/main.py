"""CLI entry point for the AI-powered email agent."""

import logging
from pathlib import Path

import click
from dotenv import load_dotenv

from src.cli.query import QueryEngine
from src.storage.db import EmailDatabase
from src.storage.vector_store import EmailVectorStore

logger = logging.getLogger(__name__)


@click.group()
@click.pass_context
def cli(ctx: click.Context) -> None:
    """AI-powered email agent — search, status, and backfill commands."""
    load_dotenv()
    logging.basicConfig(
        level=logging.WARNING,  # keep CLI output clean; errors still surface
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    )
    ctx.ensure_object(dict)
    db = EmailDatabase(db_path=Path("data/email_agent.db"))
    vector_store = EmailVectorStore(persist_dir=Path("data/chroma"))
    ctx.obj = QueryEngine(vector_store, db)
    ctx.call_on_close(ctx.obj.close)


# Import and register commands after cli is defined to avoid circular imports.
from src.cli.commands import search, status  # noqa: E402

cli.add_command(search)
cli.add_command(status)
