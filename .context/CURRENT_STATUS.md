# Project Status

**Last updated**: 2026-02-27

## Current Position

**Phase**: Phase 2 — Processing Layer
**Subphase**: Complete — ready for Phase 3
**Progress**: 50% complete

## Recently Completed

- Defined project architecture and tech stack in plan.txt
- Initialized CDS prevention framework
- **Phase 1.1 complete**: pyproject.toml (uv, Python 3.13), full src/ directory structure, .env.example, .gitignore, Makefile, conftest.py
- **Phase 1.2 complete**: `src/mcp/types.py` (RawEmail), `src/mcp/gmail_client.py` (GmailClient + gmail_client() context manager), 22 tests
- **Phase 1.3 complete**: `src/agent/watcher.py` (EmailWatcher + EmailProcessor protocol + NoOpProcessor + main()), 17 tests
- **Startup seed**: `get_unread_email_ids()` + `_seed_processed_ids()` — prevents processing historical emails on first run
- **Phase 2 complete**: `src/processing/types.py` (Priority, Intent, EmailAnalysis), `src/processing/prompts.py` (ANALYSIS_TOOL schema, build_messages), `src/processing/analyzer.py` (EmailAnalyzer + AnalysisProcessor). Processor factory pattern wires gmail_client lifecycle. 83 tests total, all green.

## In Progress

None — Phase 2 complete.

## Next Up

1. Phase 3: Storage Layer
   - `src/storage/vector_store.py` — ChromaDB, embed email body+summary, store with email_id+metadata
   - `src/storage/database.py` — SQLite, store EmailAnalysis rows (email_id, priority, intent, sentiment, requires_reply, deadline, entities, summary, timestamp)
   - Fan-out writes in `AnalysisProcessor.process()`: Gmail labels + ChromaDB + SQLite simultaneously

## Active Files and Modules

```
src/
├── agent/          [status: done — watcher.py]
├── mcp/            [status: done — types.py, gmail_client.py]
├── processing/     [status: done — types.py, prompts.py, analyzer.py]
├── storage/        [status: not started]
├── briefing/       [status: not started]
└── cli/            [status: not started]
```

## Recent Decisions

- **2026-02-27**: Use Python as orchestration language (see DECISIONS.md #ADR-001)
- **2026-02-27**: Use ChromaDB for local vector storage (see DECISIONS.md #ADR-002)
- **2026-02-27**: Use Claude Haiku for email intelligence (see DECISIONS.md #ADR-003)
- **2026-02-27**: Use SQLite for structured tracking data (see DECISIONS.md #ADR-004)

## Open Questions

- **Q**: ChromaDB vs LanceDB — which vector store to use?
  - Leaning toward: ChromaDB (better Python ergonomics, widely documented)
  - Blocked by: Benchmarking not done yet; can decide before Phase 3

- **Q**: CLI interface vs local web UI?
  - Leaning toward: CLI first, web UI as optional Phase 6 add-on
  - Blocked by: Nothing; can start CLI in Phase 5

- **Q**: APScheduler vs cron for briefing scheduling?
  - Leaning toward: APScheduler (Python-native, no system config required)
  - Blocked by: Nothing

## Blockers

None currently.

## Notes for Claude

- Everything must stay local — no external storage, no cloud DBs
- Gmail MCP and Google Calendar MCP are the only external integrations besides the Haiku API
- The processing pipeline is write-to-three-places: Gmail labels, ChromaDB, SQLite
- Start simple: get the MCP + Haiku labeling loop working before adding vector search or briefings
