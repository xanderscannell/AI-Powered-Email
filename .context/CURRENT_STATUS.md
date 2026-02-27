# Project Status

**Last updated**: 2026-02-27

## Current Position

**Phase**: Phase 1 — Foundation & Gmail MCP Integration
**Subphase**: Phase 2 — Processing Layer
**Progress**: 35% complete (Phase 1 complete)

## Recently Completed

- Defined project architecture and tech stack in plan.txt
- Initialized CDS prevention framework
- **Phase 1.1 complete**: pyproject.toml (uv, Python 3.13), full src/ directory structure, .env.example, .gitignore, Makefile, conftest.py
- **Phase 1.2 complete**: `src/mcp/types.py` (RawEmail), `src/mcp/gmail_client.py` (GmailClient + gmail_client() context manager), 18 tests passing
- **Phase 1.3 complete**: `src/agent/watcher.py` (EmailWatcher + EmailProcessor protocol + NoOpProcessor + main()), 14 tests passing. 32 total tests green.

## In Progress

- [ ] Phase 2.1: EmailAnalysis types (`src/processing/types.py`)

## Next Up

1. Create Python project structure with pyproject.toml and uv/pip setup
2. Configure Gmail MCP server connection
3. Implement basic email watcher loop (fetch new emails via Gmail MCP)
4. Wire up Haiku API for first-pass email analysis (sentiment, intent, priority, entities, summary)
5. Write analyzed results back to Gmail as labels/stars

## Active Files and Modules

```
src/
├── agent/          [status: not started]
├── mcp/            [status: not started]
├── processing/     [status: not started]
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
