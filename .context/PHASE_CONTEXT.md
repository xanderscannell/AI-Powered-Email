# Context Loading by Phase

## Phase 1: Foundation & Gmail MCP Integration

**Always read**:
- `CURRENT_STATUS.md`
- `CONVENTIONS.md` (Python style, file structure)

**Read if relevant**:
- `ARCHITECTURE.md` (sections: Email Watcher, Gmail Labels)
- `DECISIONS.md` (ADR-001 Python, ADR-005 Gmail MCP)

**Can skip**:
- `CONTEXT/` deep-dives (nothing written yet)
- ADRs 002-004 (storage decisions not relevant yet)

---

## Phase 2: Processing Layer

**Always read**:
- `CURRENT_STATUS.md`
- `CONVENTIONS.md` (dataclasses, async patterns, error handling)

**Read if relevant**:
- `ARCHITECTURE.md` (sections: Processing Layer)
- `DECISIONS.md` (ADR-003 Haiku, ADR-001 Python)

**Can skip**:
- Storage-related ADRs (002, 004) until Phase 3

---

## Phase 3: Storage Layer

**Always read**:
- `CURRENT_STATUS.md`
- `CONVENTIONS.md`
- `ARCHITECTURE.md` (sections: Storage Layer — ChromaDB, Storage Layer — SQLite, Data Flow)

**Read if relevant**:
- `DECISIONS.md` (ADR-002 ChromaDB, ADR-004 SQLite)
- `CONTEXT/` if any deep-dive docs have been written for storage

---

## Phase 4: Search Layer

**Always read**:
- `CURRENT_STATUS.md`
- `CONVENTIONS.md`
- `ARCHITECTURE.md` (sections: Query Layer, Interaction Layer)

**Read if relevant**:
- `DECISIONS.md` (ADR-002 ChromaDB)
- Phase 3 checkpoint if available

---

## Phase 5: Briefing Layer

**Always read**:
- `CURRENT_STATUS.md`
- `CONVENTIONS.md`
- `ARCHITECTURE.md` (sections: Briefing Layer, Data Flow)

**Read if relevant**:
- `DECISIONS.md` (ADR-006 APScheduler)
- `CONTEXT/` briefing design docs if created

---

## Phase 6: Interaction Layer & Calendar

**Always read**:
- `CURRENT_STATUS.md`
- `CONVENTIONS.md`
- `ARCHITECTURE.md` (full document)

**Read if relevant**:
- `DECISIONS.md` (all ADRs)
- Any CHECKPOINTS from Phases 1-5 to understand accumulated decisions

---

## Phase 7: Polish & Web UI

**Always read**:
- `CURRENT_STATUS.md`
- `CONVENTIONS.md`
- `ARCHITECTURE.md` (full)
- `DECISIONS.md` (all)

**Read if relevant**:
- All CHECKPOINTS for full history
- `CONTEXT/` for any area being refactored
