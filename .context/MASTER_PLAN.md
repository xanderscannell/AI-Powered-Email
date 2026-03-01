# Master Implementation Plan

## Project: AI-Powered Email Agent

## Overview

A local Python agent that integrates with Gmail and Google Calendar via MCP, processes emails through Claude Haiku for structured intelligence (email type, domain, entities, summary, requires_reply, deadline), stores results in a local vector DB (ChromaDB) and SQLite, and provides daily briefings and an on-demand CLI interface. Everything runs on your machine with no external storage.

## Success Criteria

- [ ] New emails are automatically labeled in Gmail based on AI-detected type (human/automated) and domain
- [ ] Natural language search across entire email history works locally
- [ ] Daily briefing is generated automatically with urgent items, follow-ups, and sentiment shifts
- [ ] On-demand CLI lets you query, summarize, and draft email replies
- [ ] All data stays local — no cloud storage

---

## Phase 1: Foundation & Gmail MCP Integration

**Goal**: Get the core email watcher loop running — fetch emails via MCP and connect to Haiku for first-pass analysis.

### 1.1 Project Scaffolding
- [x] Initialize Python project with `pyproject.toml` (uv or pip)
- [x] Set up directory structure (`src/`, `tests/`, `data/`)
- [x] Configure Black, Ruff, mypy
- [x] Create `.env.example` with all required variables
- [x] Set up pytest with basic test runner

### 1.2 Gmail MCP Integration
- [x] Configure Gmail MCP server connection
- [x] Implement `src/mcp/gmail_client.py` — wrapper around MCP tools
  - `get_unread_emails()` → list of raw email objects
  - `get_email(email_id)` → single email with full body
  - `apply_label(email_id, label_name)` → add Gmail label
  - `create_label(label_name)` → ensure label exists
- [x] Create required AI labels in Gmail (`AI/Human`, `AI/Human/FollowUp`, `AI/Automated/<Domain>`)
- [x] Write tests for Gmail client (use mock MCP responses)

### 1.3 Core Agent Loop
- [x] Implement `src/agent/watcher.py` — polling loop
  - Poll for unread emails on configurable interval
  - Feed each email into the processing pipeline
  - Track processed email IDs to avoid re-processing
  - Startup seed: `_seed_processed_ids()` prevents re-processing historical emails
- [x] Wire up main entry point (`src/main.py` or `__main__.py`)

### Phase 1 Milestones
- [x] Agent starts, connects to Gmail MCP, and fetches unread emails
- [x] Gmail client can read and label emails without errors

---

## Phase 2: Processing Layer (Haiku Analysis)

**Goal**: Every incoming email is analyzed by Haiku and results are written back to Gmail as labels.

### 2.1 Email Analysis Types
- [x] Define `EmailAnalysis` dataclass in `src/processing/types.py`
  - Fields: email_type, domain, entities, summary, requires_reply, deadline
- [x] Define `EmailType` (human | automated) and `Domain` (12 values) enums

### 2.2 Haiku Analyzer
- [x] Implement `src/processing/analyzer.py`
  - `analyze_email(raw_email) → EmailAnalysis`
  - Single structured tool-use prompt → Haiku → parse JSON response
  - `process_with_analysis(email_id, analysis)` — fan-out from pre-computed result (used by backfill)
- [x] Implement `src/processing/prompts.py`
  - Email analysis prompt template
  - JSON schema for structured output (tool use)
  - HTML stripped from body before 4000-char truncation
- [x] Write tests for analyzer (mock Haiku responses)

### 2.3 Gmail Label Write-back
- [x] Connect `EmailAnalysis` results to `gmail_client.apply_label()`
- [x] FollowUp label correctly applied only to human emails

### Phase 2 Milestones
- [x] New email arrives → Haiku analyzes → Gmail labels applied within 30 seconds
- [x] Human emails land in `AI/Human`; automated emails land in `AI/Automated/<Domain>`

---

## Phase 3: Storage Layer (ChromaDB + SQLite)

**Goal**: All analyzed emails are stored locally for search and structured querying.

### 3.1 SQLite Storage
- [x] Implement `src/storage/models.py` — table schemas
- [x] Implement `src/storage/db.py`
  - `upsert_email(email, analysis)` — insert or update
  - `get_follow_ups(due_before=None)` → list of follow-up records
  - `get_upcoming_deadlines(days=7)` → deadline records
  - `get_human_emails_needing_reply(hours)` → human emails without reply
  - `get_all_emails()` → all emails (for reindex)
  - FK constraints enforced via `PRAGMA foreign_keys=ON`
- [x] Write tests for DB layer

### 3.2 ChromaDB Vector Store
- [x] Implement `src/storage/vector_store.py`
  - `add_email(email, analysis)` — embed and store
  - `search(query, n_results=10)` → ranked email results
  - `search_with_filter(query, metadata_filter)` → filtered semantic search
  - Cosine distance (`hnsw:space=cosine`) so scores in [0,1]
- [x] Write tests for vector store (WordHashEmbeddingFunction for meaningful ranking tests)

### 3.3 Fan-out Write Integration
- [x] `AnalysisProcessor._write_storage()` writes to all three targets after analysis:
  1. Gmail labels (MCP)
  2. ChromaDB (vector store)
  3. SQLite (structured DB)
- [x] Partial failures logged, don't crash

### Phase 3 Milestones
- [x] Every processed email appears in ChromaDB and SQLite
- [x] `vector_store.search("budget dispute vendor")` returns relevant results

---

## Phase 4: Search Layer (CLI Semantic Search)

**Goal**: Natural language search works from the command line.

### 4.1 CLI Scaffolding
- [x] Implement `src/cli/main.py` with click entry point
- [x] Implement `email-agent search "<query>"` command
  - Queries ChromaDB + SQLite via QueryEngine
  - Formats results with sender, subject, date, summary, similarity score, type/domain
- [x] Implement `email-agent status` command — DB + vector store stats

### 4.2 Backfill Historical Emails
- [x] Implement `email-agent backfill --days N` command
  - Submits all new emails as a single Batches API batch (~50% cost reduction)
  - Live spinner polling with real-time pass/skip/fail counts
  - Fan-out via `AnalysisProcessor.process_with_analysis()` after batch completes

### 4.3 Reindex
- [x] Implement `email-agent reindex` command
  - Rebuilds ChromaDB from SQLite with no API calls
  - Needed after deleting `data/chroma/` or changing distance metric

### Phase 4 Milestones
- [x] `email-agent search "budget dispute with Acme in Q2"` returns the right thread
- [x] Semantic search scores in [0,1] (cosine distance)

---

## Phase 5: Briefing Layer (Scheduled Digest)

**Goal**: A daily briefing is generated automatically each morning.

### 5.1 Briefing Generator
- [ ] Implement `src/briefing/generator.py` (skeleton exists)
  - Queries SQLite for: human emails needing reply (last 24h), follow-ups due today, upcoming deadlines
  - Queries ChromaDB for: overnight activity
  - Passes compiled context to Sonnet → structured briefing markdown
- [ ] Add `email briefing` CLI command for on-demand generation

### 5.2 Scheduler
- [ ] Implement `src/briefing/scheduler.py` with APScheduler
  - Cron trigger at configured time (default 7am)
  - Output to: markdown file, stdout, or email-to-self (configurable via .env)

### Phase 5 Milestones
- [ ] Briefing runs automatically at configured time
- [ ] Briefing covers: urgent items, follow-ups due today, sentiment shifts, overnight summary
- [ ] Output format is clean, readable markdown

---

## Phase 6: Interaction Layer (Full CLI)

**Goal**: Full on-demand query and draft generation from the CLI.

### 6.1 Full CLI Commands
- [ ] `email summarize-unread` — summarize all unread with priority sort
- [ ] `email draft-reply <email_id>` — generate reply draft, push to Gmail drafts
- [ ] `email contacts [email_address]` — show contact sentiment history
- [ ] `email follow-ups` — list pending follow-ups with due dates

### 6.2 Google Calendar Integration
- [ ] Configure Google Calendar MCP
- [ ] `email briefing` enriched with calendar context (meetings today, upcoming deadlines that have calendar events)

### Phase 6 Milestones
- [ ] Draft reply pushed to Gmail drafts folder successfully
- [ ] Calendar events referenced in morning briefing

---

## Phase 7: Polish & Optional Web UI

**Goal**: Production-quality local tool with optional browser-based UI.

### 7.1 Reliability & Error Recovery
- [ ] Retry logic for MCP connection failures
- [ ] Dead letter queue for emails that failed processing
- [ ] Health check command: `email health`

### 7.2 Optional Local Web UI
- [ ] Simple FastAPI + HTMX web UI at `localhost:8080`
  - Dashboard: today's briefing, unread summary, search bar
  - Not required for core functionality

### Phase 7 Milestones
- [ ] Agent runs for 7 days without manual intervention
- [ ] All Phase 1-6 success criteria verified end-to-end

---

## Timeline Dependencies

```
Phase 1 (Foundation)
    └──► Phase 2 (Haiku Processing)
              └──► Phase 3 (Storage)
                        ├──► Phase 4 (Search CLI)
                        └──► Phase 5 (Briefings)
                                   └──► Phase 6 (Full CLI + Calendar)
                                              └──► Phase 7 (Polish)
```

## Risk Areas

| Risk | Impact | Mitigation |
|------|--------|------------|
| Gmail MCP OAuth setup complexity | High | Document setup carefully; test early in Phase 1 |
| Haiku API costs if backfilling large inbox | Medium | Rate-limit backfill; process only last 90 days initially |
| ChromaDB vs LanceDB performance | Low | Swap is isolated to `vector_store.py`; decide by Phase 3 start |
| APScheduler missed runs if process restarts | Low | Document that agent must stay running; add startup recovery in Phase 7 |
| Email body parsing (HTML vs plain text) | Medium | Extract plain text early; handle multipart MIME in Phase 1 |
