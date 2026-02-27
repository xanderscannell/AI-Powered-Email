# Checkpoint - 2026-02-27

## Session Summary

Designed and fully implemented Phase 4 (Search CLI) via brainstorming → writing-plans → subagent-driven development. All 9 tasks completed with TDD throughout. Test count rose from 126 to 155, all green. The CLI is fully wired: `email search`, `email status`, and `email backfill` are all functional.

## Completed

- Phase 4 design doc (`docs/plans/2026-02-27-phase4-cli-design.md`) — approved after brainstorming
- Phase 4 implementation plan (`docs/plans/2026-02-27-phase4-cli-plan.md`) — 9 TDD tasks
- ADR-007 added to `.context/DECISIONS.md` — QueryEngine for cross-store coordination
- `src/storage/models.py` — added `EmailRow` frozen dataclass
- `src/storage/db.py` — added `get_email_by_id()` and `get_stored_ids_since()`
- `src/mcp/gmail_client.py` — added `get_emails_since()` + moved datetime import to module level
- `pyproject.toml` — added `rich>=13.0.0` dependency
- `src/cli/query.py` (NEW) — `QueryEngine` coordinating both stores; exposes `vector_store` and `db` publicly
- `src/cli/main.py` (NEW) — click group entry point; wires `QueryEngine` via `ctx.obj`
- `src/cli/commands.py` (NEW) — `search`, `status`, `backfill` commands with rich output
- `tests/test_storage/test_db.py` — 8 new tests for new DB methods
- `tests/test_mcp/test_gmail_client.py` — 3 new tests for `get_emails_since()`
- `tests/test_cli/test_query_engine.py` (NEW) — 8 tests
- `tests/test_cli/test_commands.py` (NEW) — 10 tests (CliRunner, mocked QueryEngine)

## Files Changed

| File | Change |
|------|--------|
| `src/storage/models.py` | Added `EmailRow` frozen dataclass |
| `src/storage/db.py` | Added `get_email_by_id()`, `get_stored_ids_since()` |
| `src/mcp/gmail_client.py` | Added `get_emails_since()`; moved datetime import to module level |
| `pyproject.toml` | Added `rich>=13.0.0` |
| `src/cli/__init__.py` | Created (new package) |
| `src/cli/query.py` | Created — `QueryEngine` |
| `src/cli/main.py` | Created — click entry point |
| `src/cli/commands.py` | Created — `search`, `status`, `backfill` |
| `tests/test_cli/__init__.py` | Created (new test package) |
| `tests/test_cli/test_query_engine.py` | Created — 8 tests |
| `tests/test_cli/test_commands.py` | Created — 10 tests |
| `tests/test_storage/test_db.py` | Added 8 tests |
| `tests/test_mcp/test_gmail_client.py` | Added 3 tests |
| `docs/plans/2026-02-27-phase4-cli-design.md` | Created — design doc |
| `docs/plans/2026-02-27-phase4-cli-plan.md` | Created — implementation plan |
| `.context/DECISIONS.md` | Added ADR-007 |
| `.context/CURRENT_STATUS.md` | Updated to Phase 4 complete |
| `CLAUDE.md` | Updated Current Focus to Phase 5 |

## Issues and Solutions

| Issue | Solution |
|-------|----------|
| `get_email_by_id()` missing nullable field test and `entities` assertion | Added `test_nullable_fields_returned_as_none` and `assert row.entities == '["Alice"]'` |
| `from datetime import datetime, timedelta` deferred inside method body | Moved to module-level per CONVENTIONS.md |
| Mock used `call_args[0][1]` inconsistently | Changed to `call_args.args[1]` to match rest of test file |
| `from pathlib import Path` deferred inside `cli()` function | Moved to module-level |
| `_invoke()` had `-> "CliRunner"` return type annotation | Fixed to `-> Result` with correct import |
| `CliRunner(mix_stderr=False)` — Click 8.2 removed that param | Removed the kwarg |
| Lazy imports in `main.py` prevented patching at `src.cli.main.*` | Moved imports to module level |
| `try/except ModuleNotFoundError` guard around `mcp` imports in backfill | Removed — `mcp` is a declared dep; guard destroyed type safety |
| `asyncio.sleep` fired after the last backfill item (unnecessary ~1s hang) | Used `enumerate`; skipped sleep when `i == len(new_emails) - 1` |
| `gmail_client()` raises `ValueError` when `USER_GOOGLE_EMAIL` unset — not caught | Added `except (MCPError, ValueError)` |
| Dead NULL guard on `requires_reply` (NOT NULL column) | Removed — field is always an int from SQLite |

## Decisions Made

- **QueryEngine for cross-store coordination** (ADR-007): Centralises vector+DB joins in one class; backfill reuses `engine.vector_store` and `engine.db` directly to avoid duplicate store instances; Phase 5 briefing layer extends the same class.
- **Sonnet for `email status` synthesis**: User-triggered, infrequent — cost acceptable; better reasoning than Haiku for multi-email thread analysis.
- **`asyncio.run()` in click commands**: Keeps command handlers synchronous and simple; only `status` (Sonnet) and `backfill` (MCP + Haiku) need async helpers.

## Next Session Should

1. Brainstorm Phase 5: Briefing Generator
   - `BriefingGenerator` using Sonnet — consumes `QueryEngine`
   - APScheduler cron trigger for daily briefing
   - `email briefing` CLI command for on-demand trigger
   - Extend `QueryEngine` with `get_urgent_emails()`, `get_pending_follow_ups()`, `get_open_deadlines()`
2. Design briefing output format (rich panel? markdown file? both?)
3. Design `BRIEFING_TIME` env var integration with APScheduler

## Open Questions

- Should briefings be output only to terminal, or also written to a local file (e.g. `data/briefings/YYYY-MM-DD.md`)?
- Should the watcher process and the briefing scheduler run as a single unified process or separate processes?
