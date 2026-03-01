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
