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

---

## ADR-007: QueryEngine for Cross-Store Coordination in the CLI

**Date**: 2026-02-27
**Status**: Accepted

**Context**:
Phase 4 introduces a CLI with three commands. Two of them (`status`, and eventually `briefing`) need to coordinate both `EmailVectorStore` and `EmailDatabase`. The question was whether to call the stores directly from command handlers or introduce a coordination layer.

**Decision**:
Introduce a `QueryEngine` class (`src/cli/query.py`) that wraps both stores and exposes higher-level query methods. CLI command handlers stay thin — they parse args, call `QueryEngine`, and format output.

**Rationale**:
- `status` joins vector search results with SQLite email bodies — that coordination logic belongs in one place, not scattered across command handlers
- Phase 5's `BriefingGenerator` needs the same cross-store access patterns; `QueryEngine` gives it a clean foundation
- Independently testable: mock both stores once in `QueryEngine` tests rather than in every command test

**Consequences**:
- (+) Thin command handlers — easy to read, easy to test
- (+) Cross-store logic centralised and reusable across CLI + briefing layers
- (+) Phase 5 can extend `QueryEngine` with `get_urgent_emails()`, `get_pending_follow_ups()`, etc.
- (-) One extra file and class for Phase 4's 3 commands; justified by Phase 5 reuse

**Alternatives considered**:
- Direct store calls from command handlers: Simpler for Phase 4 alone, but duplicates coordination logic across commands and makes Phase 5 harder
- Separate `BriefingQueryEngine` in Phase 5: Would duplicate `QueryEngine` logic; better to extend one class

---

## ADR-008: Anthropic Batches API for Backfill

**Date**: 2026-02-28
**Status**: Accepted

**Context**:
The original `backfill` command processed emails one at a time with a rate-limiting delay between API calls. This was slow and incurred full per-call overhead for every email.

**Decision**:
Submit all backfill emails as a single Anthropic Batches API batch, poll until complete, then fan out results.

**Rationale**:
- Batches API offers ~50% cost reduction with no per-call rate limiting
- Single submission + polling is simpler than managing a rate-limited loop
- `AnalysisProcessor.process_with_analysis(email_id, analysis)` decouples fan-out from API calls, enabling batch + real-time paths to share the same write logic

**Consequences**:
- (+) ~50% cost reduction on backfill runs
- (+) No per-call rate limiting needed
- (+) Fan-out logic is now reusable across real-time and batch paths
- (-) Batch results arrive asynchronously; must poll until complete (currently blocking with spinner)
- (-) Requires internet connectivity for the full batch to process; no partial resumption

**Alternatives considered**:
- Per-email loop with rate limiting: Simpler but 2× the cost and slower
- Async parallel calls: More complex to implement and still subject to rate limits

---

## ADR-009: Cosine Distance for ChromaDB Vector Store

**Date**: 2026-03-01
**Status**: Accepted

**Context**:
ChromaDB's default distance metric is L2 (Euclidean). With L2, distances can exceed 1.0, causing `similarity_score = 1 - distance` to go negative. The CLI was clamping all scores to 0, making similarity output meaningless.

**Decision**:
Configure the ChromaDB collection with `hnsw:space=cosine` so similarity scores always fall in [0,1].

**Rationale**:
- Cosine similarity is the standard metric for semantic search with embedding models
- Scores in [0,1] are directly interpretable by users and easier to threshold
- The existing collection must be rebuilt when changing the metric; `email-agent reindex` handles this

**Consequences**:
- (+) Similarity scores in [0,1] — meaningful and directly displayable
- (+) Standard metric for NLP embedding search
- (-) Existing `data/chroma/` directories built with L2 must be reindexed; one-time migration
- (-) Cosine distance is slightly more expensive to compute than L2 (negligible at email scale)

**Alternatives considered**:
- L2 (default): Works but produces > 1.0 distances for non-unit vectors
- Inner product: Requires unit-normalized embeddings; adds preprocessing complexity
