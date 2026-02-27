# Development Environment Setup

## Prerequisites

- Python 3.11+
- uv (recommended) or pip
- Gmail account with API access
- Google Cloud project with Gmail API and Google Calendar API enabled
- Anthropic API key (for Claude Haiku)
- Gmail MCP server configured
- Google Calendar MCP server configured

## Installation

```bash
# Navigate to project
cd AI-Powered-Email

# Install dependencies with uv
uv sync

# OR with pip
pip install -e ".[dev]"

# Set up environment variables
cp .env.example .env
# Edit .env with your values (see Environment Variables below)
```

## Environment Variables

```bash
# .env.example

# Anthropic API
ANTHROPIC_API_KEY=sk-ant-...

# MCP Server paths
GMAIL_MCP_SERVER_PATH=/path/to/gmail-mcp-server
GCAL_MCP_SERVER_PATH=/path/to/gcal-mcp-server

# Storage paths (relative to project root)
CHROMA_PATH=data/chroma
SQLITE_PATH=data/email_agent.db

# Briefing configuration
BRIEFING_OUTPUT=file          # Options: file | email | stdout
BRIEFING_SCHEDULE=0 7 * * *   # Cron expression (default: 7am daily)
BRIEFING_OUTPUT_DIR=data/briefings

# Email polling
POLL_INTERVAL_SECONDS=60

# Optional: self-email for briefing delivery
SELF_EMAIL=your@gmail.com
```

## Running Locally

```bash
# Start the agent (watches email + runs briefing scheduler)
python -m src.main

# OR with uv
uv run python -m src.main
```

## Running Tests

```bash
# All tests
pytest tests/

# Specific module
pytest tests/test_processing/

# With coverage
pytest --cov=src tests/

# With uv
uv run pytest tests/
```

## Building

No build step required — pure Python. The package is installed in editable mode with `pip install -e .`.

## Setting Up Gmail MCP

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or use existing)
3. Enable Gmail API and Google Calendar API
4. Create OAuth 2.0 credentials (Desktop app type)
5. Download credentials JSON
6. Follow the Gmail MCP server setup instructions to authorize with your credentials
7. Set `GMAIL_MCP_SERVER_PATH` in `.env`

## Gmail Labels Setup

The agent will auto-create required labels on first run:
- `AI/Priority/Critical`
- `AI/Priority/High`
- `AI/Priority/Medium`
- `AI/Priority/Low`
- `AI/Priority/FYI`
- `AI/Intent/ActionRequired`
- `AI/Intent/Question`
- `AI/Intent/FYI`
- `AI/FollowUp`

## Data Directory

```bash
mkdir -p data/chroma data/briefings
```

Both `data/chroma/` and `data/email_agent.db` are gitignored.

## Common Issues

### MCP server not connecting
**Fix**: Verify `GMAIL_MCP_SERVER_PATH` points to the correct executable and that OAuth credentials are authorized. Run the MCP server manually to check for auth errors.

### ChromaDB import error
**Fix**: `pip install chromadb` — it's not always pulled in transitively.

### Haiku API rate limit during backfill
**Fix**: Use `email backfill --days 30 --delay 2` to add a 2-second delay between calls.

### SQLite database locked
**Fix**: Only one agent process should run at a time. Kill any orphaned processes: `pkill -f "python -m src.main"`.
