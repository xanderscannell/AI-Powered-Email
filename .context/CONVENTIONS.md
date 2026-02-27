# Project Conventions

## Language and Runtime

- **Language**: Python
- **Version**: Python 3.11+
- **Package manager**: uv (preferred) or pip with pyproject.toml

## Code Style

- **Formatter**: Black (line length 100)
- **Linter**: Ruff
- **Type checker**: mypy (strict mode)
- **All type annotations are required** — no `Any` unless truly unavoidable

## Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Classes | PascalCase | `EmailAnalyzer`, `VectorStore` |
| Functions/methods | snake_case | `process_email`, `get_unread` |
| Constants | UPPER_SNAKE_CASE | `MAX_RETRIES`, `DEFAULT_PRIORITY` |
| Private members | _leading_underscore | `_haiku_client`, `_db_conn` |
| Files | snake_case | `email_analyzer.py`, `vector_store.py` |
| Type aliases | PascalCase | `EmailId = str` |
| Dataclasses | PascalCase | `EmailAnalysis`, `ContactRecord` |

## File Organization

```
src/
  agent/
    __init__.py       # Public exports
    watcher.py        # Email polling / watch loop
  mcp/
    __init__.py
    gmail_client.py   # Gmail MCP read/write wrapper
    calendar_client.py
  processing/
    __init__.py
    analyzer.py       # Haiku analysis pipeline
    prompts.py        # Prompt templates
    types.py          # EmailAnalysis dataclass and enums
  storage/
    __init__.py
    vector_store.py   # ChromaDB interface
    db.py             # SQLite interface
    models.py         # SQLite table schemas
  briefing/
    __init__.py
    scheduler.py      # APScheduler setup
    generator.py      # Briefing generation logic
  cli/
    __init__.py
    main.py           # CLI entry point
    commands.py       # click command definitions
tests/
  test_processing/
    test_analyzer.py
  test_storage/
    test_vector_store.py
    test_db.py
  test_briefing/
    test_generator.py
data/
  chroma/             # ChromaDB persistent storage (gitignored)
  briefings/          # Generated briefing markdown files
  email_agent.db      # SQLite database (gitignored)
```

## Error Handling

Use typed exceptions; never swallow errors silently. Log errors with context before re-raising or handling.

```python
# Pattern: custom exception hierarchy
class EmailAgentError(Exception):
    """Base exception for all agent errors."""

class MCPConnectionError(EmailAgentError):
    """Raised when MCP server connection fails."""

class AnalysisError(EmailAgentError):
    """Raised when Haiku analysis fails."""

# Pattern: log and re-raise at boundaries
try:
    result = await gmail_client.fetch_unread()
except MCPConnectionError as e:
    logger.error("Failed to fetch emails: %s", e, exc_info=True)
    raise
```

## Async

- Use `asyncio` for the main agent loop and MCP calls
- Mark all I/O-bound functions as `async def`
- Use `asyncio.gather()` for concurrent fan-out writes to Gmail labels + ChromaDB + SQLite

## Logging

- Use the standard `logging` module
- Logger per module: `logger = logging.getLogger(__name__)`
- Log levels: DEBUG for internal state, INFO for key events, WARNING for recoverable issues, ERROR for failures

## Dataclasses

Prefer `@dataclass` or `dataclass(frozen=True)` for data transfer objects. Use Pydantic only if validation is needed at a system boundary.

```python
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

class Priority(int, Enum):
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4
    FYI = 5

@dataclass(frozen=True)
class EmailAnalysis:
    email_id: str
    sentiment: float          # -1.0 to 1.0
    intent: str               # "action_required", "fyi", "question", etc.
    priority: Priority
    entities: list[str]
    summary: str
    requires_reply: bool
    deadline: datetime | None = None
```

## Testing

- **Framework**: pytest
- **Coverage target**: 80%+ on processing and storage modules
- **Test naming**: `test_[function]_[scenario]_[expected_result]`
- **Run tests**: `pytest tests/`
- **With coverage**: `pytest --cov=src tests/`
- Use `pytest-asyncio` for async tests

## Environment Variables

All secrets and config go in `.env` (gitignored). Use `python-dotenv` to load them.

```bash
# .env
ANTHROPIC_API_KEY=sk-...
GMAIL_MCP_SERVER_PATH=/path/to/mcp/server
GCAL_MCP_SERVER_PATH=/path/to/mcp/server
BRIEFING_OUTPUT=file          # file | email | stdout
BRIEFING_SCHEDULE=0 7 * * *   # cron expression
CHROMA_PATH=data/chroma
SQLITE_PATH=data/email_agent.db
```

## Git Conventions

- **Commit format**: `<type>(<scope>): <description>`
- **Types**: feat, fix, docs, test, refactor, perf, chore
- **Branch naming**: `feature/description`, `fix/description`
- **Examples**: `feat(processing): add Haiku email analyzer`, `feat(storage): implement ChromaDB vector store`

## Import Order

1. Standard library (`asyncio`, `logging`, `dataclasses`, `sqlite3`)
2. Third-party packages (`anthropic`, `chromadb`, `click`, `apscheduler`)
3. Local modules (`from src.processing.types import EmailAnalysis`)
