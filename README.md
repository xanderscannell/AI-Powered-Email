# AI-Powered Email Agent

A local Python agent that watches your Gmail, classifies every email with
Claude Haiku, and stores results in a local vector DB + SQLite for semantic
search and daily briefings. Everything runs on your machine — no cloud storage.

**What it does:**
- Auto-labels incoming emails as `AI/Human` or `AI/Automated/<Domain>`
  (Finance, Shopping, Newsletter, Travel, and more)
- Flags human emails that need a reply with `AI/Human/FollowUp`
- Stores embeddings locally for natural-language search across your full
  email history
- Backfills historical emails in bulk using the Anthropic Batches API (~50%
  cheaper than real-time processing)
- *(Coming soon — Phase 5)* Daily briefing with urgent items, follow-ups,
  and upcoming deadlines

```
              ┌──────────────────────┐
              │    Gmail (via MCP)   │
              └──────────┬───────────┘
                         │ new emails
                         ▼
              ┌──────────────────────┐
              │     Email Watcher    │
              │   (polls every 60s)  │
              └──────────┬───────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │   Claude Haiku API   │
              │   → email_type       │
              │   → domain           │
              │   → summary          │
              │   → requires_reply   │
              └──┬────┬─────┬────────┘
    ┌────────────┘    |     └────────────────┐
    │                 │                      │
    ▼                 ▼                      ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Gmail Labels │  │   ChromaDB   │  │    SQLite    │
│  (via MCP)   │  │  (vectors)   │  │  (metadata)  │
│  write-only  │  └──────┬───────┘  └───────┬──────┘
└──────────────┘         └─────────┬────────┘
                                   ▼
                    ┌──────────────────────────┐
                    │     CLI (email-agent)    │
                    │  search / backfill /     │
                    │  status / reindex        │
                    └──────────────────────────┘
```

## Prerequisites

- **Python 3.13+** — the project requires 3.13
- **uv** — package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))
- **A Gmail account** you want to monitor
- **Anthropic API key** — for Claude Haiku email analysis (Step 1)
- **Google Cloud project** with Gmail API enabled and OAuth credentials (Step 2)

> **Windows users**: the agent works on Windows via Git Bash or PowerShell.
> `PYTHONUTF8=1` is set automatically to handle Unicode characters in logs.

## Step 1: Get Your Anthropic API Key

1. Go to [console.anthropic.com](https://console.anthropic.com) and sign in
   (or create a free account).
2. In the left sidebar, click **API Keys**.
3. Click **Create Key**, give it a name (e.g. `email-agent`), and click **Create Key**.
4. **Copy the key immediately** — it will not be shown again. It starts with `sk-ant-api03-...`
5. You will paste this into your `.env` file in Step 3.

> **Cost**: The agent uses Claude Haiku for per-email analysis (~$0.001 per
> email) and the Anthropic Batches API for backfill (~50% cheaper than
> real-time calls). At typical personal inbox volume, expect a few cents per day.

## Step 2: Set Up Google OAuth Credentials

The agent uses [`workspace-mcp`](https://github.com/pydantic/workspace-mcp)
to read and label your Gmail. It needs OAuth credentials from Google Cloud
Console so it can request permission to access your account.

### 2.1 Create a Google Cloud Project

1. Go to [console.cloud.google.com](https://console.cloud.google.com).
2. Click the **project dropdown** at the top of the page → **New Project**.
3. Enter a name (e.g. `email-agent`) and click **Create**.
4. Wait a moment, then confirm the new project is selected in the dropdown
   before continuing.

### 2.2 Enable the Gmail API

1. In the left sidebar, go to **APIs & Services → Library**.
2. Search for **Gmail API** and click it.
3. Click **Enable**.

<p align="center">
  <img width="600" alt="Gmail API page showing the Enable button" src="https://github.com/user-attachments/assets/330cb41f-6bb6-4ca1-aabc-eaaefd4cff5b" />
  <br><sub>The Enable button changes to "Manage" once the API is active — that confirms it worked.</sub>
</p>

### 2.3 Configure the OAuth Consent Screen

> You only need to do this once. Google requires a consent screen before
> you can create OAuth credentials.

1. Go to **APIs & Services → OAuth consent screen**.
2. Select **External** and click **Create**.
3. Fill in the required fields:
   - **App name**: `Email Agent` (anything descriptive works)
   - **User support email**: your Gmail address
   - **Developer contact email**: your Gmail address
4. Click **Save and Continue** through the **Scopes** page (no changes needed).
5. On the **Test Users** page, click **Save and Continue** (no changes needed).
6. On the **Summary** page, click **Back to Dashboard**.
7. Click **Publish App** → **Confirm**.

> ⚠️ **Important**: publishing the app prevents the OAuth token from
> expiring after 7 days. If you skip this step, you will need to re-authorize
> every week.

### 2.4 Create OAuth Credentials

1. Go to **APIs & Services → Credentials**.
2. Click **+ Create Credentials → OAuth client ID**.
3. For **Application type**, select **Desktop app**.
4. Give it a name (e.g. `email-agent-desktop`) and click **Create**.
5. A dialog shows your credentials:
   - **Client ID** — ends in `.apps.googleusercontent.com`
   - **Client Secret** — a short alphanumeric string
6. Copy both values and click **OK**. You will paste them into `.env` in Step 3.

<p align="center">
  <img width="700" alt="Credentials page showing the newly created OAuth client" src="https://github.com/user-attachments/assets/d2e37ff0-78ed-4174-832a-79e4a2e4e106" />
  <br><sub>The OAuth client entry on the Credentials page. Click the pencil icon at any time to retrieve your Client ID and Secret.</sub>
</p>

<p align="center">
  <img width="480" alt="Dialog showing the OAuth Client ID and Client Secret" src="https://github.com/user-attachments/assets/770cff16-2afa-44e7-a006-ce2f193b7668" />
  <br><sub>This dialog appears immediately after clicking Create — copy both values now, it won't be shown again.</sub>
</p>

### 2.5 First-Time OAuth Authorization

The first time the agent starts, `workspace-mcp` opens a browser window to
request Gmail access. This only happens once — the token is cached locally
afterward.

> **Screenshot callout**: expect a browser tab titled "Sign in with Google".
> Select your account, then click **Allow** on the permissions screen.
> You should see "Authentication successful" in the browser tab when done.

> ⚠️ If you see **"This app isn't verified"**, click
> **Advanced → Go to Email Agent (unsafe)**. This warning is expected for
> personal OAuth apps that have not gone through Google's formal verification
> process. Your credentials only access your own account.

## Step 3: Install and Configure

### 3.1 Clone and Install

```bash
git clone <repo-url>
cd AI-Powered-Email

# Install all dependencies including dev tools (creates .venv automatically)
uv sync --extra dev
```

### 3.2 Configure Environment Variables

```bash
cp .env.example .env
```

Open `.env` in your editor and fill in your values:

```bash
# ── Anthropic API ──────────────────────────────────────────────────────
# From Step 1
ANTHROPIC_API_KEY=sk-ant-api03-...

# ── Google OAuth ───────────────────────────────────────────────────────
# From Step 2.4
GOOGLE_OAUTH_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_OAUTH_CLIENT_SECRET=GOCSPX-...
# The Gmail account to monitor
USER_GOOGLE_EMAIL=your@gmail.com

# ── MCP Server ─────────────────────────────────────────────────────────
# Leave as "uvx" — workspace-mcp runs via uvx, no separate install needed
GMAIL_MCP_SERVER_PATH=uvx
GCAL_MCP_SERVER_PATH=uvx

# ── Storage Paths ──────────────────────────────────────────────────────
# Leave as-is unless you want to store data elsewhere
CHROMA_PATH=data/chroma
SQLITE_PATH=data/email_agent.db

# ── Briefing (Phase 5 — not yet active) ────────────────────────────────
BRIEFING_TIME=07:00
BRIEFING_OUTPUT_TERMINAL=true
BRIEFING_OUTPUT_FILE=false
BRIEFING_OUTPUT_EMAIL=false
BRIEFING_EMAIL_TO=your@gmail.com

# ── Email Polling ──────────────────────────────────────────────────────
# How often the watcher checks for new emails (seconds)
POLL_INTERVAL_SECONDS=60
```

### 3.3 Create Data Directories

```bash
mkdir -p data/chroma data/briefings
```

> Both `data/chroma/` and `data/email_agent.db` are gitignored — your email
> data never leaves your machine.

## Step 4: First Run and Verify

### 4.1 Backfill Historical Emails

Before starting the watcher, populate the search index with your recent
email history:

```bash
uv run email-agent backfill --days 30
```

> **First run only**: `workspace-mcp` will open a browser window for the
> OAuth flow (see Step 2.5). After you click Allow, the token is cached and
> this will not happen again.

A live progress spinner shows real-time counts as the Anthropic Batches API
processes your emails. When complete, each email is stored in ChromaDB and
SQLite and labeled in Gmail.

### 4.2 Verify the Setup

```bash
# Show database and vector store stats
uv run email-agent status

# Try a semantic search
uv run email-agent search "invoice from last month"
```

Expected `status` output:

```
Emails in database:         142
Emails in vector store:     142
Human emails needing reply:   3
Pending follow-ups:           1
```

> If `status` shows 0 emails, the backfill may not have completed. Run
> `uv run email-agent backfill --days 30` again and check for errors in
> the output.

## Watcher: Real-Time Email Monitoring

The watcher is a long-running process that polls Gmail every 60 seconds
(configurable via `POLL_INTERVAL_SECONDS`), analyzes new emails with Claude
Haiku, and fans out results to Gmail labels, ChromaDB, and SQLite.

### Start the Watcher

```bash
uv run python -m src
```

Leave this running in a terminal. You will see log output as emails arrive:

```
INFO  Gmail MCP client connected (you@gmail.com)
INFO  Seeded 247 already-processed email IDs
INFO  Watching for new emails (poll interval: 60s)
INFO  Processing email abc123 — "Re: Q1 Budget Review"
INFO  Analysis: type=human domain=work requires_reply=True
INFO  Wrote to SQLite, ChromaDB, Gmail labels
```

### What It Does to Your Inbox

When a new email arrives, the watcher:

1. Fetches it via the Gmail MCP server
2. Strips HTML and sends the plain-text body to Claude Haiku for analysis
3. Writes results to three places simultaneously:
   - **Gmail**: applies `AI/Human` or `AI/Automated/<Domain>` label
     (plus `AI/Human/FollowUp` if the email requires a reply)
   - **ChromaDB**: stores an embedding for semantic search
   - **SQLite**: stores structured metadata (type, domain, summary, deadlines)

### Gmail Labels Created

On first run the watcher auto-creates these labels in your Gmail sidebar:

```
AI/
├── Human
│   └── FollowUp
└── Automated
    ├── Finance
    ├── Shopping
    ├── Travel
    ├── Health
    ├── Government
    ├── Work
    ├── Education
    ├── Newsletter
    ├── Marketing
    ├── Social
    ├── Alerts
    └── Other
```

### Stopping the Watcher

`Ctrl+C` — the agent handles shutdown cleanly.

> ⚠️ Run only one watcher instance at a time. Multiple instances will
> conflict on the SQLite database.

## CLI: On-Demand Commands

All CLI commands can run while the watcher is running or independently.

### Search

Semantic natural-language search across your full email history:

```bash
uv run email-agent search "invoice from Acme last quarter"
uv run email-agent search "flights to London"
uv run email-agent search "performance review feedback"
```

Results are ranked by semantic similarity and show sender, subject, date,
type/domain, and a one-line AI summary:

```
┌─────┬──────────────────────────┬───────────────────┬─────────┬──────────────────────────────────┐
│  #  │ Subject                  │ From              │ Domain  │ Summary                          │
├─────┼──────────────────────────┼───────────────────┼─────────┼──────────────────────────────────┤
│  1  │ Q3 Invoice #1042         │ billing@acme.com  │ Finance │ Invoice for $4,200 due Oct 1     │
│  2  │ Re: Q3 billing question  │ you@gmail.com     │ Work    │ Follow-up on outstanding invoice │
└─────┴──────────────────────────┴───────────────────┴─────────┴──────────────────────────────────┘
```

### Status

Show a summary of what is stored in the database and vector store:

```bash
uv run email-agent status
```

### Backfill

Process historical emails and populate the search index:

```bash
# Process the last 30 days (recommended for first run)
uv run email-agent backfill --days 30

# Process the last 90 days
uv run email-agent backfill --days 90
```

Backfill submits all new emails as a single Anthropic Batches API batch —
roughly 50% cheaper than processing them one at a time. A live spinner shows
progress while the batch runs.

> **Already-processed emails are skipped automatically.** It is safe to run
> backfill multiple times — only genuinely new emails are sent to the API.

### Reindex

Rebuild the ChromaDB vector store from SQLite without making any API calls:

```bash
uv run email-agent reindex
```

Run this after deleting `data/chroma/` or after upgrading from an older
version of the agent that used a different distance metric.

## Troubleshooting

### OAuth flow hangs or "Authentication successful" never appears

The OAuth flow opens a local callback server on port 18741 (configurable).
If something else is using that port, set a different one:

```bash
WORKSPACE_MCP_PORT=19000 uv run python -m src
```

### "This app isn't verified" warning in the browser

Expected for personal OAuth apps. Click **Advanced → Go to Email Agent (unsafe)**
to proceed. Your credentials only access your own Gmail account.

### MCP server fails to connect on startup

`workspace-mcp` binds an internal port on startup. If a previous run crashed
without releasing it, the next startup may fail. The agent retries up to 5
times automatically (3-second delay between attempts). If it still fails,
wait about 2 minutes for the OS to release the port (common on Windows due
to TIME_WAIT), then try again.

### Search returns 0 results or all similarity scores show as 0.00

Your `data/chroma/` directory may have been created with an older version of
the agent that used L2 distance instead of cosine. Delete it and reindex:

```bash
rm -rf data/chroma
uv run email-agent reindex
```

### Backfill completes but no labels appear in Gmail

1. Confirm `USER_GOOGLE_EMAIL` in `.env` exactly matches the account you
   authorized in the OAuth flow.
2. The OAuth token may have expired if you did not publish the app (Step 2.3).
   Delete the cached token and re-authorize:
   ```bash
   rm -rf ~/.workspace-mcp/
   uv run email-agent backfill --days 1
   ```
   This triggers a fresh OAuth flow in the browser.

### SQLite database is locked

Only one agent process should run at a time. Find and kill any orphaned
instances:

```bash
# macOS / Linux
pkill -f "python -m src"

# Windows (PowerShell)
Get-Process python | Where-Object { $_.CommandLine -like "*src*" } | Stop-Process
```

### Unicode errors in logs (Windows)

The agent sets `PYTHONUTF8=1` automatically inside the `workspace-mcp`
subprocess. If you see encoding errors in your own terminal output, add
this to your `.env`:

```bash
PYTHONUTF8=1
```

## Development

### Running Tests

```bash
# Run all tests
uv run pytest

# Run a specific module
uv run pytest tests/test_processing/

# Run with coverage report
uv run pytest --cov=src --cov-report=term-missing
```

> 13 tests in `test_watcher.py` and `test_briefing_scheduler.py` are
> currently expected to fail — they cover Phase 5 work that is not yet
> complete.

### Linting and Formatting

```bash
make format      # auto-format with Black + Ruff
make lint        # check without modifying
make typecheck   # run mypy
make check       # lint + typecheck + tests
```

### Project Structure

```
src/
├── agent/         # Email watcher — polling loop and startup seeding
├── mcp/           # Gmail MCP client wrapper (workspace-mcp)
├── processing/    # Claude Haiku analyzer, prompts, HTML stripping
├── storage/       # ChromaDB vector store + SQLite database
├── briefing/      # Briefing generator + APScheduler (Phase 5, in progress)
└── cli/           # Click CLI — search, status, backfill, reindex
data/
├── chroma/        # ChromaDB vector store files (gitignored)
├── briefings/     # Generated briefing markdown files (gitignored)
└── email_agent.db # SQLite database (gitignored)
docs/
└── plans/         # Design docs and implementation plans
.context/          # CDS session context (architecture, decisions, status)
```
