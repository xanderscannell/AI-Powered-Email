# Prompt: Implement Module

Read for context before implementing:
1. `.context/CURRENT_STATUS.md` — what we're working on and what's done
2. `.context/CONVENTIONS.md` — Python style, naming, async patterns, error handling
3. `.context/ARCHITECTURE.md` — where this module fits in the data flow

## Instructions

Implement the following module: **[MODULE_NAME]**

### Requirements
- [Requirement 1]
- [Requirement 2]

### Steps
1. Show the public interface (function/class signatures + docstrings) first for approval before writing implementation
2. Implement with full type annotations per CONVENTIONS.md
3. Use `async def` for all I/O-bound operations
4. Follow error handling patterns from CONVENTIONS.md (custom exceptions, logger.error before re-raise)
5. Create tests in `tests/test_[module_name].py` with pytest-asyncio for async tests

### Files to create/modify
- `src/[path]/[name].py`
- `tests/test_[path]/test_[name].py`

### Constraints
- All storage writes must go to all three targets (Gmail labels, ChromaDB, SQLite) unless this module handles only one layer
- No hardcoded API keys or paths — read from environment variables
- Must integrate with existing components per ARCHITECTURE.md data flow diagram

### Integration points
- Uses: [list what this module calls — e.g., `GmailClient`, `EmailAnalyzer`]
- Called by: [list what calls this module — e.g., `agent/watcher.py`]
