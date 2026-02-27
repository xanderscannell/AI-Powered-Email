# Phase 5 — Briefing Generator: Design

**Date**: 2026-02-27
**Phase**: 5
**Status**: Approved

---

## Overview

Phase 5 adds a daily briefing generator that collects urgent emails, pending
follow-ups, and open deadlines from the existing storage layer, synthesises
them via Claude Sonnet into a readable morning briefing, and routes the output
to up to three destinations: rich terminal panel, markdown file, and
email-to-self via Gmail MCP.

The briefing fires automatically on a cron schedule (default 07:00) integrated
into the existing email watcher process, and is also available on demand via
`email-agent briefing`.

---

## Architecture

```
email-agent briefing (CLI)          APScheduler (daily cron)
        │                                    │
        └────────────────┬───────────────────┘
                         ▼
              BriefingGenerator.generate()
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
   QueryEngine     AsyncAnthropic   OutputConfig
  (data collect)   (Sonnet synth)  (env-driven)
     │  │  │                            │
     │  │  └─ get_urgent_emails()       ├─ terminal (Rich panel)
     │  └──── get_pending_follow_ups()  ├─ file (data/briefings/)
     └──────── get_open_deadlines()     └─ email-to-self (Gmail MCP)
```

### New files

| File | Purpose |
|------|---------|
| `src/briefing/__init__.py` | Package marker |
| `src/briefing/generator.py` | `BriefingGenerator` + `OutputConfig` |
| `src/briefing/scheduler.py` | APScheduler setup (`create_briefing_scheduler`) |

### Modified files

| File | Change |
|------|--------|
| `src/cli/query.py` | Add `get_urgent_emails()`, `get_pending_follow_ups()`, `get_open_deadlines()` |
| `src/storage/db.py` | Add `get_urgent_emails(hours)` SQL query |
| `src/cli/commands.py` | Add `briefing` click command |
| `src/agent/watcher.py` | Wire scheduler into `main()` |

---

## QueryEngine Extensions

Three new methods on `QueryEngine` in `src/cli/query.py`.

### `get_urgent_emails(hours: int = 24) -> list[EmailRow]`

Delegates to a new `EmailDatabase.get_urgent_emails(hours)` method:

```sql
SELECT * FROM emails
WHERE priority <= 2
  AND processed_at >= datetime('now', '-N hours')
ORDER BY priority, processed_at DESC
```

Priority threshold: ≤ 2 (CRITICAL + HIGH), matching the `_PRIORITY_LABEL` map
already used in `commands.py`.

### `get_pending_follow_ups() -> list[tuple[FollowUpRecord, EmailRow | None]]`

Calls `db.get_follow_ups(status="pending")` (already exists), then looks up
each `EmailRow` by `email_id` via `db.get_email_by_id()`. Returns enriched
pairs so the briefing has full context (subject, sender, date).

### `get_open_deadlines() -> list[tuple[DeadlineRecord, EmailRow | None]]`

Same pattern: calls `db.get_open_deadlines()` (already exists), enriches each
record with its `EmailRow`.

The tuple approach keeps QueryEngine as the single coordination layer, avoiding
SQL joins and matching the existing `get_emails_for_topic` pattern.

---

## BriefingGenerator

```python
# src/briefing/generator.py

@dataclass
class OutputConfig:
    terminal: bool = True
    file: bool = False
    email_self: bool = False
    briefing_dir: Path = Path("data/briefings")
    email_recipient: str = ""  # from BRIEFING_EMAIL_TO env var

    @classmethod
    def from_env(cls) -> "OutputConfig": ...

class BriefingGenerator:
    def __init__(self, engine: QueryEngine, output_config: OutputConfig) -> None: ...

    async def generate(self) -> str:
        # 1. Collect data via QueryEngine (urgent, follow-ups, deadlines)
        # 2. Build Sonnet prompt
        # 3. Call AsyncAnthropic → markdown briefing string
        # 4. Route to each enabled output
        # 5. Return briefing text
```

### Sonnet prompt structure

```
Today is {YYYY-MM-DD}. Generate a concise morning email briefing.

URGENT EMAILS (last 24h, priority CRITICAL or HIGH):
{subject | sender | summary for each}

PENDING FOLLOW-UPS:
{subject | sender | waiting since for each}

OPEN DEADLINES:
{description | email subject for each}

Format the briefing with clear labelled sections. Be specific — reference
actual names, dates, and action items from the data above. End with a
"Recommended focus" of 1–3 items for today.
```

**Model**: `claude-sonnet-4-6`
**max_tokens**: `1500`

---

## Output Routing

Three outputs, independently controlled via `.env`:

| Env var | Default | Effect |
|---------|---------|--------|
| `BRIEFING_OUTPUT_TERMINAL` | `true` | Print Rich panel to stdout |
| `BRIEFING_OUTPUT_FILE` | `false` | Write `data/briefings/YYYY-MM-DD.md` |
| `BRIEFING_OUTPUT_EMAIL` | `false` | Send via Gmail MCP to `BRIEFING_EMAIL_TO` |

**Terminal**: `console.print(Panel(text, title="Morning Briefing — {date}", border_style="green"))` — same Rich pattern as `email status`.

**File**: Writes markdown with a YAML front-matter header (`date`, `generated_at`). Creates `data/briefings/` if absent.

**Email-to-self**: Calls a new `GmailClient.send_email(to, subject, body)` method backed by the Gmail MCP `send_email` tool.

---

## Scheduler

```python
# src/briefing/scheduler.py

def create_briefing_scheduler(
    engine: QueryEngine,
    output_config: OutputConfig,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    generator = BriefingGenerator(engine, output_config)
    hour, minute = _parse_briefing_time(os.environ.get("BRIEFING_TIME", "07:00"))
    scheduler.add_job(generator.generate, "cron", hour=hour, minute=minute)
    return scheduler
```

Integrated into `src/agent/watcher.py` `main()`: after building `QueryEngine`,
call `create_briefing_scheduler(engine, output_config).start()`, then start the
watcher polling loop as before.

**`BRIEFING_TIME`** env var: `HH:MM` format, default `"07:00"`.

---

## CLI Command

```
email-agent briefing [--output terminal,file,email]
```

- Runs `asyncio.run(generator.generate())` directly (same pattern as `email status`).
- `--output` comma-separated flag overrides env vars for one-off runs (e.g. `--output file` to save without printing to terminal).
- Registered on the root click group alongside `search`, `status`, `backfill`.

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| Sonnet API error | Log + print `[red]Briefing failed: {exc}[/red]`, fall back to raw data display (matches `email status` fallback pattern) |
| Gmail MCP send failure | Log + skip email output; other outputs still complete |
| Empty data | Generate briefing anyway — Sonnet writes "No urgent items" message |
| APScheduler missed job | No recovery in Phase 5; noted in `.env.example` that process must stay running |

---

## Testing

Target: ~25 new tests, bringing the total to ~180.

| Test file | What it covers |
|-----------|---------------|
| `tests/cli/test_query_engine_extensions.py` | `get_urgent_emails`, `get_pending_follow_ups`, `get_open_deadlines` against in-memory SQLite |
| `tests/briefing/test_briefing_generator.py` | Mock `AsyncAnthropic`; assert prompt contains expected sections; assert each output path is invoked |
| `tests/briefing/test_briefing_scheduler.py` | Assert APScheduler job added with correct cron params |
| `tests/briefing/test_briefing_command.py` | Click test runner; assert `briefing` command calls `generator.generate()` |
| `tests/mcp/test_gmail_send.py` | Mock MCP `send_email` tool; assert `GmailClient.send_email` formats call correctly |

All tests follow the existing mock/fixture patterns in `conftest.py`.

---

## Environment Variables (additions to `.env.example`)

```bash
# Briefing output (comma-separated or individual vars)
BRIEFING_OUTPUT_TERMINAL=true
BRIEFING_OUTPUT_FILE=false
BRIEFING_OUTPUT_EMAIL=false
BRIEFING_EMAIL_TO=you@example.com   # required if BRIEFING_OUTPUT_EMAIL=true
BRIEFING_TIME=07:00                  # HH:MM, 24h format
```
