# System Architecture

## High-Level Overview

A local Python agent that watches Gmail via MCP, processes each email through Claude Haiku, and distributes results across three storage targets. Scheduled briefings and on-demand CLI interaction layer on top.

```
                        ┌─────────────────────────────────┐
                        │         Gmail MCP Server         │
                        └───────────────┬─────────────────┘
                                        │ new emails
                                        ▼
                        ┌─────────────────────────────────┐
                        │         Email Watcher            │
                        │    (core agent loop / poller)    │
                        └───────────────┬─────────────────┘
                                        │ raw email
                                        ▼
                        ┌─────────────────────────────────┐
                        │       Processing Layer           │
                        │  Claude Haiku API                │
                        │  → email_type, domain            │
                        │  → entities, summary             │
                        └──────┬───────────┬──────────────┘
                               │           │           │
                  ┌────────────┘    ┌──────┘    ┌─────┘
                  ▼                 ▼           ▼
         ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
         │  Gmail Labels│  │  ChromaDB    │  │   SQLite     │
         │  & Stars     │  │  (vectors +  │  │  (contacts,  │
         │  (via MCP)   │  │   metadata)  │  │   follow-ups,│
         └──────────────┘  └──────┬───────┘  │   deadlines) │
                                  │           └──────┬───────┘
                                  └────────┬─────────┘
                                           │
                         ┌─────────────────┴──────────────┐
                         │          Query Layer             │
                         │  natural language search         │
                         └─────────────────┬──────────────┘
                                           │
          ┌────────────────────────────────┼───────────────────────────┐
          │                               │                            │
┌─────────┴──────────┐        ┌──────────┴─────────┐     ┌───────────┴──────────┐
│   Briefing Layer   │        │  Interaction Layer  │     │  MCP Server          │
│  (APScheduler)     │        │  (CLI / web UI)     │     │  (Claude Desktop)    │
│  daily digest      │        │  on-demand queries  │     │  7 read-only tools   │
└────────────────────┘        └────────────────────┘     └──────────────────────┘
```

## Components

### Email Watcher

**Purpose**: Polls Gmail via MCP for new/unread emails and feeds them into the processing pipeline.
**Tech stack**: Python, Gmail MCP server
**Key files**:
- `src/agent/watcher.py`
- `src/mcp/gmail_client.py`

**Interfaces**:
- Input: Gmail MCP events / polling result
- Output: Raw email objects (id, sender, subject, body, timestamp, thread_id)

**Notes**: Initial implementation can be polling-based; MCP push notifications can be added later.

---

### Processing Layer

**Purpose**: Analyzes each email through Claude Haiku to extract structured intelligence.
**Tech stack**: Python, Anthropic SDK (Haiku model)
**Key files**:
- `src/processing/analyzer.py`
- `src/processing/prompts.py`

**Interfaces**:
- Input: Raw email object
- Output: `EmailAnalysis` dataclass — email_type (human|automated), domain (12 values), entities, one-line summary, requires_reply (bool), deadline (optional date)

**Notes**: Haiku is used because it's fast and cheap enough to run on every incoming email. Backfill uses the Anthropic Batches API (single batch submission, polled until complete) for ~50% cost reduction. HTML is stripped from email bodies before the 4000-char truncation. `AnalysisProcessor.process_with_analysis(email_id, analysis)` handles fan-out from a pre-computed batch result without calling the API.

---

### Storage Layer — ChromaDB (Vector Store)

**Purpose**: Stores email embeddings + metadata for semantic (natural language) search.
**Tech stack**: Python, ChromaDB (local persistent mode)
**Key files**:
- `src/storage/vector_store.py`

**Interfaces**:
- Input: Raw email + `EmailAnalysis`
- Output: Queryable collection; returns (email_id, similarity_score, metadata) tuples

**Notes**: ChromaDB runs in local persistent mode — no server process. DB files live in `data/chroma/`. Uses `hnsw:space=cosine` distance so similarity scores always fall in [0,1]. Run `email-agent reindex` to rebuild from SQLite after deleting the chroma directory or changing the distance metric.

---

### Storage Layer — SQLite (Structured Data)

**Purpose**: Tracks contacts, follow-ups, deadlines, and sentiment history with structured queries.
**Tech stack**: Python, sqlite3 or SQLAlchemy
**Key files**:
- `src/storage/db.py`
- `src/storage/models.py`

**Tables**:
- `emails` — id, thread_id, sender, subject, timestamp, email_type, domain, summary, requires_reply, deadline
- `contacts` — email_address, name, last_contact, total_emails
- `follow_ups` — email_id, due_date, status, notes
- `deadlines` — email_id, deadline_date, description, status

**Key methods**: `get_human_emails_needing_reply(hours)`, `get_pending_follow_ups()`, `get_upcoming_deadlines()`, `get_all_emails()` (for reindex). FK constraints enforced via `PRAGMA foreign_keys=ON`.

---

### Gmail Labels (Write-back)

**Purpose**: Persists AI analysis results directly in Gmail as labels and stars so they're visible in the Gmail UI.
**Tech stack**: Python, Gmail MCP server
**Key files**:
- `src/mcp/gmail_client.py` (label write methods)

**Label scheme** (16 hierarchical labels):
- `AI/Human` — human-authored emails
- `AI/Human/FollowUp` — human emails that require a reply
- `AI/Automated/<Domain>` — automated emails by domain (e.g. `AI/Automated/Newsletters`, `AI/Automated/Receipts`, `AI/Automated/Notifications`, etc.)
- FollowUp label is reserved for human emails only; automated emails never receive it

---

### Briefing Layer

**Purpose**: Runs on a schedule (default: 7am daily) to generate a digest of urgent items, overnight activity, follow-ups due, and sentiment shifts.
**Tech stack**: Python, APScheduler
**Key files**:
- `src/briefing/scheduler.py`
- `src/briefing/generator.py`

**Output options** (configurable):
- Markdown file in `data/briefings/YYYY-MM-DD.md`
- Email to own inbox (via Gmail MCP)
- Printed to stdout

---

### MCP Server (Claude Desktop)

**Purpose**: Exposes processed email data to Claude Desktop as 7 read-only tools. Spawned by Claude Desktop over stdio; no Gmail dependency, no Anthropic API dependency — pure local SQLite + ChromaDB reads.
**Tech stack**: Python, `mcp.server.fastmcp.FastMCP`
**Key files**:
- `src/mcp/server.py`

**Tools exposed**:
- `search_emails(query, limit)` — semantic search via ChromaDB
- `get_emails_needing_reply(hours)` — human emails awaiting reply
- `get_pending_followups()` — follow-ups the agent is tracking
- `get_open_deadlines()` — deadlines extracted from emails
- `get_status()` — counts from SQLite + ChromaDB
- `get_email(email_id)` — full email record by ID
- `get_contact(email_address)` — contact history

**Entry point**: `email-agent-mcp` → `src.mcp.server:main` → `mcp.run(transport="stdio")`

**Notes**: Module-level singleton `_engine: QueryEngine | None` is built lazily on first tool call from `SQLITE_PATH` / `CHROMA_PATH` env vars. Requires the background agent to have run at least once (data files must exist). SQLite WAL mode ensures concurrent read access alongside the running watcher.

---

### Interaction Layer (CLI)

**Purpose**: On-demand natural language interface for querying emails and generating drafts.
**Tech stack**: Python, `click` or `argparse`
**Key files**:
- `src/cli/main.py`
- `src/cli/commands.py`

**Implemented commands**:
- `email-agent search "<query>"` — semantic search via ChromaDB + SQLite
- `email-agent status` — database + vector store stats summary
- `email-agent backfill --days N` — process historical emails via Batches API
- `email-agent reindex` — rebuild ChromaDB from SQLite (no API calls)

**Planned commands** (Phase 5-6):
- `email-agent briefing` — on-demand daily digest
- `email-agent draft-reply <email_id>` — generate a reply draft

---

## Data Flow

1. **Ingestion**: Watcher polls Gmail MCP → receives raw email objects
2. **Analysis**: Each email sent to Haiku → `EmailAnalysis` returned
3. **Fan-out write**: Results written simultaneously to:
   - Gmail (labels/stars via MCP)
   - ChromaDB (embedding + metadata)
   - SQLite (structured fields)
4. **Query**: CLI or Briefing layer queries ChromaDB (semantic) + SQLite (structured) → merged results → Haiku for synthesis → response
5. **Briefing**: APScheduler triggers → queries both stores → Haiku generates digest → output to configured destination

## External Dependencies

| Dependency | Purpose | Version |
|-----------|---------|---------|
| Anthropic SDK | Claude Haiku API calls | latest |
| Gmail MCP server | Read/write Gmail | latest |
| Google Calendar MCP | Calendar events for context | latest |
| ChromaDB | Local vector store | latest stable |
| APScheduler | Job scheduling | 3.x |
| click | CLI framework | 8.x |
| python-dotenv | Environment variable loading | latest |

## Key Design Patterns

- **Fan-out writes**: Every processed email writes to three targets atomically (best-effort; SQLite is source of truth for structured data)
- **Local-first**: No cloud storage; ChromaDB and SQLite files live in `data/` directory
- **Incremental layering**: Each subsystem (vector search, briefings, CLI) is independent and can be added without rearchitecting the core loop
- **MCP as the Gmail interface**: All Gmail reads and writes go through the MCP server; no direct Gmail API calls

## Technology Decisions

See [DECISIONS.md](DECISIONS.md) for rationale behind technology choices.
