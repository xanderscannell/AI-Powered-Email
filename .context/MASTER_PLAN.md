# Master Implementation Plan

## Project: AI-Powered Email Agent

## Overview

A local Python agent that integrates with Gmail and Google Calendar via MCP, processes emails through Claude Haiku for structured intelligence (sentiment, intent, priority, entities, summary), stores results in a local vector DB (ChromaDB) and SQLite, and provides daily briefings and an on-demand CLI interface. Everything runs on your machine with no external storage.

## Success Criteria

- [ ] New emails are automatically labeled in Gmail based on AI-detected priority and intent
- [ ] Natural language search across entire email history works locally
- [ ] Daily briefing is generated automatically with urgent items, follow-ups, and sentiment shifts
- [ ] On-demand CLI lets you query, summarize, and draft email replies
- [ ] All data stays local — no cloud storage

---

## Phase 1: Foundation & Gmail MCP Integration

**Goal**: Get the core email watcher loop running — fetch emails via MCP and connect to Haiku for first-pass analysis.

### 1.1 Project Scaffolding
- [ ] Initialize Python project with `pyproject.toml` (uv or pip)
- [ ] Set up directory structure (`src/`, `tests/`, `data/`)
- [ ] Configure Black, Ruff, mypy
- [ ] Create `.env.example` with all required variables
- [ ] Set up pytest with basic test runner

### 1.2 Gmail MCP Integration
- [ ] Configure Gmail MCP server connection
- [ ] Implement `src/mcp/gmail_client.py` — wrapper around MCP tools
  - `get_unread_emails()` → list of raw email objects
  - `get_email(email_id)` → single email with full body
  - `apply_label(email_id, label_name)` → add Gmail label
  - `star_email(email_id)` → star an email
  - `create_label(label_name)` → ensure label exists
- [ ] Create required AI labels in Gmail (`AI/Priority/*`, `AI/Intent/*`, `AI/FollowUp`)
- [ ] Write tests for Gmail client (use mock MCP responses)

### 1.3 Core Agent Loop
- [ ] Implement `src/agent/watcher.py` — polling loop
  - Poll for unread emails on configurable interval
  - Feed each email into the processing pipeline
  - Track processed email IDs to avoid re-processing
- [ ] Wire up main entry point (`src/main.py` or `__main__.py`)

### Phase 1 Milestones
- [ ] Agent starts, connects to Gmail MCP, and fetches unread emails
- [ ] Gmail client can read and label emails without errors

---

## Phase 2: Processing Layer (Haiku Analysis)

**Goal**: Every incoming email is analyzed by Haiku and results are written back to Gmail as labels.

### 2.1 Email Analysis Types
- [ ] Define `EmailAnalysis` dataclass in `src/processing/types.py`
  - Fields: sentiment, intent, priority, entities, summary, requires_reply, deadline
- [ ] Define `Priority` and `Intent` enums

### 2.2 Haiku Analyzer
- [ ] Implement `src/processing/analyzer.py`
  - `analyze_email(raw_email) → EmailAnalysis`
  - Single structured prompt → Haiku → parse JSON response
- [ ] Implement `src/processing/prompts.py`
  - Email analysis prompt template
  - JSON schema for structured output
- [ ] Write tests for analyzer (mock Haiku responses)

### 2.3 Gmail Label Write-back
- [ ] Connect `EmailAnalysis` results to `gmail_client.apply_label()` and `star_email()`
- [ ] Verify labels appear correctly in Gmail UI

### Phase 2 Milestones
- [ ] New email arrives → Haiku analyzes → Gmail labels applied within 30 seconds
- [ ] Priority-1 emails are starred automatically

---

## Phase 3: Storage Layer (ChromaDB + SQLite)

**Goal**: All analyzed emails are stored locally for search and structured querying.

### 3.1 SQLite Storage
- [ ] Implement `src/storage/models.py` — table schemas
- [ ] Implement `src/storage/db.py`
  - `upsert_email(email, analysis)` — insert or update
  - `get_follow_ups(due_before=None)` → list of follow-up records
  - `get_contact_history(email_address)` → contact record with sentiment trend
  - `get_upcoming_deadlines(days=7)` → deadline records
- [ ] Write tests for DB layer

### 3.2 ChromaDB Vector Store
- [ ] Implement `src/storage/vector_store.py`
  - `add_email(email, analysis)` — embed and store
  - `search(query, n_results=10)` → ranked email results
  - `search_with_filter(query, metadata_filter)` → filtered semantic search
- [ ] Decide on embedding strategy: use ChromaDB's default embedding function or Haiku-generated embeddings
- [ ] Write tests for vector store

### 3.3 Fan-out Write Integration
- [ ] Update agent watcher to write to all three targets after analysis:
  1. Gmail labels (MCP)
  2. ChromaDB (vector store)
  3. SQLite (structured DB)
- [ ] Handle partial failures gracefully (log, don't crash)

### Phase 3 Milestones
- [ ] Every processed email appears in ChromaDB and SQLite
- [ ] `vector_store.search("budget dispute vendor")` returns relevant results

---

## Phase 4: Search Layer (CLI Semantic Search)

**Goal**: Natural language search works from the command line.

### 4.1 CLI Scaffolding
- [ ] Implement `src/cli/main.py` with click entry point
- [ ] Implement `email search "<query>"` command
  - Queries ChromaDB
  - Formats results with sender, subject, date, summary, similarity score
- [ ] Implement `email status "<topic>"` command
  - Finds all thread emails related to a topic
  - Passes through Haiku for a status summary

### 4.2 Backfill Historical Emails
- [ ] Implement `email backfill --days N` command to process historical emails
- [ ] Rate-limit Haiku calls during backfill to avoid API throttling

### Phase 4 Milestones
- [ ] `email search "budget dispute with Acme in Q2"` returns the right thread
- [ ] Semantic search beats Gmail keyword search on 5 manual test queries

---

## Phase 5: Briefing Layer (Scheduled Digest)

**Goal**: A daily briefing is generated automatically each morning.

### 5.1 Briefing Generator
- [ ] Implement `src/briefing/generator.py`
  - Queries SQLite for: urgent emails (priority ≤ 2), follow-ups due today, upcoming deadlines
  - Queries ChromaDB for: overnight activity, sentiment shifts
  - Passes compiled context to Haiku (or Sonnet) → structured briefing markdown
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
