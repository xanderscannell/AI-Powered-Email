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
              └──┬──────────┬────────┘
    ┌────────────┘          └────────────────┐
    │                 │                      │
    ▼                 ▼                      ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ Gmail Labels │  │   ChromaDB   │  │    SQLite    │
│  (via MCP)   │  │  (vectors)   │  │  (metadata)  │
│  write-only  │  └──────┬───────┘  └──────┬───────┘
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

> **Screenshot callout**: the Enable button turns to "Manage" once the API
> is active — that confirms it worked.

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

> **Screenshot callout**: the dialog that shows the Client ID and Client
> Secret appears immediately after clicking Create. If you close it, you can
> retrieve the values by clicking the pencil (edit) icon next to the
> credential on the Credentials page.

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
