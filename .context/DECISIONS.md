# Architecture Decision Records

---

## ADR-001: Python as Orchestration Language

**Date**: 2026-02-27
**Status**: Accepted

**Context**:
The agent needs to coordinate MCP servers, call the Anthropic API, manage a local vector DB, schedule jobs, and expose a CLI. Multiple language options exist.

**Decision**:
Use Python 3.11+ as the single orchestration language.

**Rationale**:
- ChromaDB and LanceDB have first-class Python SDKs
- Anthropic's Python SDK is the most complete and well-documented
- APScheduler is Python-native; avoids system cron configuration
- MCP server integrations are Python-friendly
- Fastest path to a working prototype

**Consequences**:
- (+) Unified language across all layers — no polyglot complexity
- (+) Rich ecosystem for ML/AI tooling
- (-) Not as performant as Rust/Go for high-throughput, but email volume doesn't require it

**Alternatives considered**:
- TypeScript: Good MCP support, but ChromaDB Python SDK is more mature
- Claude Code agent: Could use Claude Code itself as the orchestrator, but a plain Python script gives more control and is easier to schedule

---

## ADR-002: ChromaDB for Vector Storage

**Date**: 2026-02-27
**Status**: Accepted (revisit before Phase 3 if benchmarks favor LanceDB)

**Context**:
Need local vector storage for semantic email search with no external server dependency.

**Decision**:
Use ChromaDB in local persistent mode.

**Rationale**:
- Runs fully locally with zero server process (embedded mode)
- Simple Python API with minimal boilerplate
- Good documentation and active community
- Supports metadata filtering alongside vector similarity

**Consequences**:
- (+) Zero-dependency local operation; DB files in `data/chroma/`
- (+) Fast enough for personal email volumes (tens of thousands of emails)
- (-) Less performant than LanceDB at very large scale, but acceptable here

**Alternatives considered**:
- LanceDB: Slightly better performance and Arrow-native, but less ergonomic Python API as of this decision
- Pinecone / Weaviate: Cloud-hosted — ruled out immediately (local-first requirement)
- FAISS: No built-in metadata filtering; would require a separate metadata store

---

## ADR-003: Claude Haiku for Email Intelligence

**Date**: 2026-02-27
**Status**: Accepted

**Context**:
Need an LLM to extract sentiment, intent, priority, entities, and summaries from every incoming email. Cost and latency matter because this runs on each email.

**Decision**:
Use Claude Haiku (claude-haiku-4-5-20251001) for all email analysis.

**Rationale**:
- Cheapest and fastest Claude model — practical to run on every email
- Sufficient intelligence for structured extraction tasks (sentiment, intent classification, entity extraction)
- Use Sonnet or Opus for complex synthesis tasks like draft generation or briefing summaries

**Consequences**:
- (+) Cost-effective at scale
- (+) Low latency per email
- (-) May miss nuance compared to Sonnet; acceptable for classification, compensate by using Sonnet for final briefing synthesis

**Alternatives considered**:
- Claude Sonnet for all tasks: Too expensive to run on every email
- GPT-4o-mini: Would work similarly, but staying within Anthropic ecosystem simplifies billing and API management
- Local model (Ollama/llama.cpp): No API cost, but quality gap is significant for nuanced intent/sentiment extraction

---

## ADR-004: SQLite for Structured Tracking Data

**Date**: 2026-02-27
**Status**: Accepted

**Context**:
Need structured storage for contacts, follow-up tracking, deadlines, and sentiment history — queryable by date, contact, and status.

**Decision**:
Use SQLite via Python's built-in `sqlite3` module (or SQLAlchemy for convenience).

**Rationale**:
- Zero configuration, zero dependencies beyond Python stdlib
- Perfect for the access patterns: contact history, follow-up lists, deadline queries
- File-based — consistent with local-first philosophy
- SQL queries are more expressive than vector similarity for structured lookups

**Consequences**:
- (+) No additional infrastructure
- (+) Durable, ACID-compliant
- (-) Not suitable for unstructured or semantic queries — ChromaDB handles those

**Alternatives considered**:
- PostgreSQL: Overkill for local personal tool; requires running a server
- DuckDB: Good analytical queries, but SQLite is sufficient and more universally familiar

---

## ADR-005: Gmail MCP for All Gmail I/O

**Date**: 2026-02-27
**Status**: Accepted

**Context**:
Need to read emails and write labels/stars back to Gmail.

**Decision**:
Use the Gmail MCP server for all Gmail interactions. No direct Gmail REST API calls.

**Rationale**:
- MCP provides a clean tool-calling interface compatible with the agent loop
- Avoids managing OAuth flows manually
- Consistent abstraction layer — same pattern used for Calendar

**Consequences**:
- (+) Simpler agent code — calls MCP tools rather than managing HTTP auth
- (+) Calendar access follows the same pattern
- (-) Depends on MCP server being configured and running

---

## ADR-006: APScheduler for Briefing Scheduling

**Date**: 2026-02-27
**Status**: Accepted

**Context**:
Need to run the daily briefing job at a configured time without requiring system cron configuration.

**Decision**:
Use APScheduler 3.x with a cron-style trigger embedded in the Python process.

**Rationale**:
- Python-native; no OS-level configuration
- Supports cron expressions for flexibility
- Can run as a long-running background process alongside the watcher

**Consequences**:
- (+) Single process manages both email watching and scheduled briefings
- (+) Configurable schedule without touching system cron
- (-) Briefings won't run if the process isn't running; document this clearly

**Alternatives considered**:
- System cron: Works, but requires user to configure OS-level jobs; less portable
- Celery + Redis: Overkill for a single-machine personal tool
