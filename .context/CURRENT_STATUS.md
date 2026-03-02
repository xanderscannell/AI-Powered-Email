# Project Status

**Last updated**: 2026-03-01

## Current Position

**Phase**: Phase 6 complete — ready for Phase 5 (Briefing Generator)
**Subphase**: N/A
**Progress**: 90% complete

## Recently Completed

- Defined project architecture and tech stack in plan.txt
- Initialized CDS prevention framework
- **Phase 1.1 complete**: pyproject.toml (uv, Python 3.13), full src/ directory structure, .env.example, .gitignore, Makefile, conftest.py
- **Phase 1.2 complete**: `src/mcp/types.py` (RawEmail), `src/mcp/gmail_client.py` (GmailClient + gmail_client() context manager), 22 tests
- **Phase 1.3 complete**: `src/agent/watcher.py` (EmailWatcher + EmailProcessor protocol + NoOpProcessor + main()), 17 tests
- **Startup seed**: `get_unread_email_ids()` + `_seed_processed_ids()` — prevents processing historical emails on first run
- **Phase 2 complete**: `src/processing/types.py`, `src/processing/prompts.py`, `src/processing/analyzer.py` (EmailAnalyzer + AnalysisProcessor). Processor factory pattern wires gmail_client lifecycle.
- **Phase 3 complete**: `src/storage/models.py` (DDL + result dataclasses), `src/storage/db.py` (EmailDatabase — emails/contacts/follow_ups/deadlines), `src/storage/vector_store.py` (EmailVectorStore — ChromaDB with metadata filtering). Fan-out writes in `AnalysisProcessor._write_storage()`. 126 tests total, all green.
- **Phase 4 complete**: `src/cli/query.py` (QueryEngine), `src/cli/main.py` (click entry point), `src/cli/commands.py` (search/status/backfill). Also added `EmailRow` dataclass, `EmailDatabase.get_email_by_id()`, `EmailDatabase.get_stored_ids_since()`, `GmailClient.get_emails_since()`, `rich>=13.0.0` dep. 155 tests total, all green.
  - Design doc: `docs/plans/2026-02-27-phase4-cli-design.md`
  - Implementation plan: `docs/plans/2026-02-27-phase4-cli-plan.md`
  - ADR-007: QueryEngine for cross-store CLI coordination
- **Schema redesign complete** (2026-02-28): Replaced Priority/Intent/sentiment system with human-vs-automated + Domain classification across all layers. 194 tests passing.
  - Design doc: `docs/plans/2026-02-28-schema-redesign-design.md`
  - Implementation plan: `docs/plans/2026-02-28-schema-redesign-plan.md`
  - Changes: `processing/types.py` (EmailType + Domain enums), `processing/prompts.py` (tool schema), `processing/analyzer.py` (parse + label logic), `mcp/gmail_client.py` (AI_LABELS — 16 hierarchical labels), `storage/models.py` (schema: email_type/domain columns), `storage/db.py` (upserts + `get_human_emails_needing_reply`), `storage/vector_store.py` (metadata), `cli/commands.py` (Type/Domain columns in search table), `cli/query.py` (renamed method), `briefing/generator.py` (prompt + method call)
- **Analyzer bug fix** (2026-02-28): `AI/Human/FollowUp` label was being incorrectly applied to automated emails. Fixed `_apply_labels` so only human emails ever receive the FollowUp label. Regression test added.
- **Windows MCP fix** (2026-02-28): `PYTHONUTF8=1` added to workspace-mcp subprocess env to suppress Unicode logging errors on Windows.
- **Batches API backfill** (2026-02-28): Replaced per-email rate-limited loop with Anthropic Batches API submission. ~50% cost reduction, no per-call rate limiting needed.
  - New `AnalysisProcessor.process_with_analysis(email_id, analysis)` method for batch result fan-out
  - Live spinner during batch polling with real-time pass/skip/fail counts
  - HTML stripped from email bodies before 4000-char truncation
  - ANALYSIS_TOOL descriptions trimmed to reduce fixed token overhead
  - `src.*` modules now surface at INFO level; third-party noise stays at WARNING
  - 204 tests passing (13 pre-existing failures in `test_watcher.py` and `test_briefing_scheduler.py`)
- **Cosine distance + reindex** (2026-03-01): Vector store now uses `hnsw:space=cosine` so similarity scores fall in [0,1]. Added `email-agent reindex` command to rebuild ChromaDB from SQLite with no API calls.
  - `EmailDatabase.get_all_emails()` added to support reindex
  - `PRAGMA foreign_keys=ON` now enforced
  - Test embeddings upgraded to `WordHashEmbeddingFunction` (bag-of-words hashing) for meaningful semantic ranking tests
  - 9 new tests in `TestSemanticRanking` and `TestScaleAndIntegrity`
- **Phase 6 complete** (2026-03-01): Claude Desktop MCP Server — 7 read-only tools over stdio.
  - `src/mcp/server.py` — FastMCP server with tools: search_emails, get_emails_needing_reply, get_pending_followups, get_open_deadlines, get_status, get_email, get_contact
  - `tests/test_mcp/test_server.py` — 31 tests, real tmp databases, no API calls
  - `EmailDatabase.get_email_count()` and `EmailVectorStore.count()` helper methods added
  - `email-agent-mcp` script entry point registered in pyproject.toml
  - MASTER_PLAN.md: Phase 6 inserted; old Phase 6 → 7, Phase 7 → 8
  - ARCHITECTURE.md: MCP server added as third consumer of the storage layer
  - 198 tests passing total (31 pre-existing failures in watcher + briefing scheduler)

## In Progress

None — Phase 6 complete.

## Next Up

1. Phase 5: Briefing Generator
   - `src/briefing/generator.py` — BriefingGenerator skeleton exists; finalize with new schema
   - `src/briefing/scheduler.py` — APScheduler cron-based daily briefing runner
   - `src/cli/commands.py` — add `email briefing` command (on-demand trigger)
   - QueryEngine already has: `get_human_emails_needing_reply()`, `get_pending_follow_ups()`, `get_open_deadlines()`
   - Output: rich terminal panel (same style as `email status`)
   - Schedule config: `BRIEFING_TIME` env var (e.g. `"08:00"`)

## Active Files and Modules

```
src/
├── agent/          [status: done — watcher.py]
├── mcp/            [status: done — types.py, gmail_client.py, server.py (Phase 6)]
├── processing/     [status: done — types.py, prompts.py, analyzer.py]
├── storage/        [status: done — models.py, db.py, vector_store.py]
├── briefing/       [status: skeleton exists — generator.py, scheduler.py]
└── cli/            [status: done — query.py, main.py, commands.py (search/status/backfill/reindex)]
```

## Recent Decisions

- **2026-02-27**: Use Python as orchestration language (see DECISIONS.md #ADR-001)
- **2026-02-27**: Use ChromaDB for local vector storage (see DECISIONS.md #ADR-002)
- **2026-02-27**: Use Claude Haiku for email intelligence (see DECISIONS.md #ADR-003)
- **2026-02-27**: Use SQLite for structured tracking data (see DECISIONS.md #ADR-004)
- **2026-02-27**: Use Gmail MCP for all Gmail I/O (see DECISIONS.md #ADR-005)
- **2026-02-27**: Use APScheduler for briefing scheduling (see DECISIONS.md #ADR-006)
- **2026-02-27**: Use QueryEngine for cross-store CLI coordination (see DECISIONS.md #ADR-007)
- **2026-02-28**: Replace Priority/Intent/sentiment with EmailType + Domain classification (schema redesign)

## Open Questions

- **Q**: CLI interface vs local web UI?
  - Leaning toward: CLI first, web UI as optional Phase 6 add-on
  - Blocked by: Nothing; can start Phase 5

- **Q**: APScheduler vs cron for briefing scheduling?
  - Leaning toward: APScheduler (Python-native, no system config required) — ADR-006 accepted
  - Blocked by: Nothing

## Blockers

None currently.

## Notes for Claude

- Everything must stay local — no external storage, no cloud DBs
- Gmail MCP and Google Calendar MCP are the only external integrations besides the Haiku/Sonnet API
- The processing pipeline is write-to-three-places: Gmail labels, ChromaDB, SQLite
- `QueryEngine` exposes public `vector_store` and `db` attributes — backfill passes these to `AnalysisProcessor` to avoid duplicate store instances
- CLI entry point: `email-agent` (declared in pyproject.toml `[project.scripts]`)
- **Schema**: EmailType (human | automated) + Domain (12 values). Human → `AI/Human` label (+ `AI/Human/FollowUp`). Automated → `AI/Automated/<Domain>` label.
- **Key methods**: `db.get_human_emails_needing_reply(hours)` — NOT `get_urgent_emails` (renamed in schema redesign)
- Phase 5 QueryEngine extensions already implemented: `get_human_emails_needing_reply()`, `get_pending_follow_ups()`, `get_open_deadlines()`
- `AnalysisProcessor.process_with_analysis(email_id, analysis)` — used by backfill to fan out a pre-computed batch result; does NOT call the API
- `email-agent reindex` — rebuilds ChromaDB from SQLite with no API calls; run after deleting `data/chroma/` or changing distance metric
- Vector store uses cosine distance (`hnsw:space=cosine`); similarity scores always in [0,1]
- HTML is stripped from email bodies before the 4000-char truncation in the processing prompt
- 198 tests passing (13 pre-existing failures in `test_watcher.py` and `test_briefing_scheduler.py`)
- **Phase 6 MCP server**: `src/mcp/server.py` — module-level `_engine: QueryEngine | None = None` singleton; override in tests with `server_module._engine = my_engine`
- `EmailDatabase.get_email_count()` — returns `SELECT COUNT(*) FROM emails`
- `EmailVectorStore.count()` — returns `self._collection.count()`
- `email-agent-mcp` entry point in pyproject.toml → `src.mcp.server:main` → `mcp.run(transport="stdio")`
