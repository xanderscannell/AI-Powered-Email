# Phase 4 Design: Search CLI

**Date**: 2026-02-27
**Status**: Approved
**Phase**: 4 — Search Layer

---

## Overview

Add a `click`-based CLI with three commands: `email search`, `email status`, and `email backfill`. A new `QueryEngine` class coordinates `EmailVectorStore` and `EmailDatabase` behind a single interface, keeping command handlers thin and giving Phase 5's briefing layer a foundation to build on.

---

## Architecture

Three new files plus additions to the storage layer:

```
src/
  cli/
    __init__.py
    main.py        # click group, entry point, initialises QueryEngine
    commands.py    # click command handlers — thin, delegate to QueryEngine
    query.py       # QueryEngine — coordinates EmailVectorStore + EmailDatabase
  storage/
    db.py          # + get_email_by_id() and get_stored_ids_since() (new methods)
tests/
  test_cli/
    test_query_engine.py
    test_commands.py
  test_storage/
    test_db.py     # additions for two new EmailDatabase methods
```

`QueryEngine` is constructed once at CLI startup in `main.py` with both stores wired in, then passed to commands via click's `Context.obj`. Commands stay thin: parse args → call QueryEngine → format and print.

---

## QueryEngine API

```python
class QueryEngine:
    def search(self, query: str, n: int = 10) -> list[SearchResult]:
        """Semantic search. Returns vector store results — metadata sufficient for display."""

    def get_emails_for_topic(self, topic: str, n: int = 10) -> list[EmailRow]:
        """vector_store.search() for IDs, then db.get_email_by_id() for bodies.
        Used by `status` to assemble a Sonnet synthesis prompt."""

    def get_stored_ids_since(self, days: int) -> set[str]:
        """IDs of emails already in the DB from the last N days.
        Used by `backfill` to skip already-processed emails."""
```

Phase 5 will add `get_urgent_emails()`, `get_pending_follow_ups()`, and `get_open_deadlines()` to this class for the briefing generator.

Two new `EmailDatabase` methods required:
- `get_email_by_id(email_id: str) -> EmailRow | None`
- `get_stored_ids_since(days: int) -> set[str]`

---

## Commands

### `email search "<query>"`

Performs a semantic search and displays results in a rich table.

```
email search "budget dispute Acme Q2"

┌───┬──────────────────────────┬──────────────────┬────────────┬────────┐
│ # │ Subject                  │ From             │ Date       │ Score  │
├───┼──────────────────────────┼──────────────────┼────────────┼────────┤
│ 1 │ Re: Invoice discrepancy  │ alice@acme.com   │ 2026-01-15 │  0.91  │
│ 2 │ Q2 budget reconciliation │ bob@acme.com     │ 2026-01-20 │  0.87  │
└───┴──────────────────────────┴──────────────────┴────────────┴────────┘
  [HIGH] Sentiment: -0.42  |  Intent: action_required  |  Requires reply: yes
  Summary: Alice flagged a $3k discrepancy on invoice #441...
```

Options: `--limit N` (default 10), `--min-priority N` (filter by priority ≤ N).

### `email status "<topic>"`

Finds related emails via semantic search, then passes full content to Claude Sonnet for a synthesised status summary.

```
email status "Acme invoice dispute"

Fetching related emails... found 5
Generating summary with Sonnet...

Status: UNRESOLVED DISPUTE (Jan 15 – Jan 20)

Background: Acme raised a $3,200 discrepancy on invoice #441 (ref: Q2-2026-A)...
Last action: Bob sent a breakdown request Jan 18. Alice replied Jan 20 with partial data.

Recommended next step: Reply to Alice clarifying the surcharge policy.
```

Options: `--limit N` (number of emails to include in synthesis, default 10).

### `email backfill --days N`

Fetches all emails from the last N days via Gmail MCP, skips any already stored, processes new ones through the full analysis pipeline with rate limiting.

```
email backfill --days 30

Fetching all emails from the last 30 days...
Found 312 emails. 189 already stored, 123 new.

Processing: ████████████████████ 123/123

Done. 123 emails processed in 10m 38s.
```

Options: `--days N` (required), `--rate-limit N` (Haiku calls per second, default 1).

---

## Data Flow

**search**
```
click → QueryEngine.search(query)
      → vector_store.search(query)
      → list[SearchResult]
      → rich table
```

**status**
```
click → QueryEngine.get_emails_for_topic(topic)
      → vector_store.search(topic) → IDs
      → db.get_email_by_id(id) × N → EmailRows
      → build Sonnet prompt
      → asyncio.run(AsyncAnthropic.messages.create())
      → rich panel
```

**backfill**
```
click → QueryEngine.get_stored_ids_since(days) → stored ID set
      → gmail_client.get_emails_since(days)    → all emails via MCP
      → diff: new = fetched - stored
      → rich progress bar
      → for each new email (rate-limited):
            EmailAnalyzer.analyze(email)
            vector_store.upsert(email, analysis)
            db.save(email, analysis)
            gmail_client.apply_label(...) [best-effort]
      → summary panel
```

---

## Error Handling

| Command | Failure | Behaviour |
|---------|---------|-----------|
| `search` | Empty DB / no results | "No emails indexed yet. Run `email backfill --days 30` to get started." |
| `status` | No results for topic | "No emails found for topic." exit 0 |
| `status` | Sonnet API failure | Print raw email list as fallback; surface error |
| `backfill` | MCP connection failure | Exit early with clear message |
| `backfill` | Per-email analysis failure | Log and skip; never abort the batch |
| Any | Stores not initialised | Helpful message, not a stack trace |

---

## Testing

**`test_cli/test_query_engine.py`** — unit tests with mocked stores:
- `search` returns results from vector store
- `get_emails_for_topic` correctly joins vector IDs with DB rows
- `get_emails_for_topic` with zero vector results returns `[]` without calling DB
- `get_stored_ids_since` returns the correct ID set

**`test_cli/test_commands.py`** — click `CliRunner` tests with mocked `QueryEngine`:
- `search` with results renders correct output
- `search` with no results prints "no emails indexed" message
- `status` calls `get_emails_for_topic` + mocked Sonnet response
- `backfill` skips stored IDs, processes new ones, shows correct counts

**`test_storage/test_db.py`** additions:
- `get_email_by_id` returns correct row
- `get_email_by_id` returns `None` for unknown ID
- `get_stored_ids_since` returns IDs within window, excludes older ones

Target: ~25–30 new tests on top of the existing 126.

---

## Output Style

Rich terminal formatting throughout: tables for search results, panels for status synthesis, progress bars for backfill. Uses the `rich` library (already a transitive dependency via ChromaDB; add explicitly to `pyproject.toml`).

---

## Design Decisions

- **QueryEngine over thin wrappers**: Chosen to centralise cross-store coordination. Pays off immediately in `status` (joins two stores) and gives Phase 5's briefing generator a clean foundation. See ADR-007.
- **Sonnet for `status` synthesis**: More capable reasoning for multi-email thread analysis; `status` is user-triggered and infrequent so cost is acceptable.
- **Haiku for `backfill` analysis**: Consistent with the watcher pipeline; cost matters at batch scale.
- **`asyncio.run()` in CLI commands**: Storage ops are synchronous; only `status` (Sonnet) and `backfill` (MCP + Haiku) need async. Wrapping with `asyncio.run()` keeps the click commands synchronous and simple.
