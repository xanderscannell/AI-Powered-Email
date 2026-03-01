# README Design

**Date**: 2026-03-01
**Status**: Approved

## Overview

A comprehensive project README targeting a technical developer audience. Leads
with a brief overview and architecture diagram, then devotes the bulk of the
document to step-by-step setup instructions (Anthropic API key, Google OAuth,
install/configure). Separate sections for the watcher and CLI. Closes with
troubleshooting and development reference.

## Audience

Technical developers who are comfortable with Python/CLI tooling but need
detailed guidance on the Google Cloud Console OAuth setup and `workspace-mcp`
integration.

## Structure

```
# AI-Powered Email Agent
  Overview (3 sentences + bullet features)
  Architecture diagram (ASCII)

## Prerequisites
  Python 3.13+, uv, Gmail account, Anthropic key, Google Cloud project

## Step 1: Get Your Anthropic API Key
  console.anthropic.com walkthrough → copy sk-ant-... key

## Step 2: Set Up Google OAuth Credentials
  2.1 Create a Google Cloud Project
  2.2 Enable the Gmail API
  2.3 Configure the OAuth Consent Screen (publish app to avoid 7-day token expiry)
  2.4 Create OAuth Credentials (Desktop app type → client ID + secret)
  2.5 Authorize workspace-mcp (first-time browser OAuth flow, "unverified app" note)

## Step 3: Install and Configure
  3.1 Clone and install (uv sync --extra dev)
  3.2 Configure .env (annotated copy of .env.example with callouts)
  3.3 Create data directories (mkdir -p data/chroma data/briefings)

## Step 4: First Run and Verify
  4.1 Backfill historical emails (email-agent backfill --days 30)
  4.2 Verify (email-agent status + sample search)

## Watcher: Real-Time Email Monitoring
  Start command, log output example, what it does to inbox, Gmail label tree,
  stopping, single-instance warning

## CLI: On-Demand Commands
  search (with results table example)
  status
  backfill (Batches API note, skip-already-processed note)
  reindex (when to use)

## Troubleshooting
  OAuth flow hangs (WORKSPACE_MCP_PORT)
  "App isn't verified" warning
  MCP server fails to connect (retry logic, TIME_WAIT note)
  Search scores all 0 (rm data/chroma + reindex)
  No labels in Gmail (email mismatch, expired token)
  SQLite locked (kill orphaned processes, platform-specific commands)
  Unicode errors on Windows (PYTHONUTF8)

## Development
  Tests (uv run pytest, known failures note)
  Linting/formatting (make targets)
  Project structure tree
```

## Key Decisions

- **Setup-first structure**: majority of document is the numbered setup guide;
  feature documentation comes after
- **Step-by-step with screenshot callouts**: OAuth section uses numbered steps
  for every Cloud Console click, with callout boxes for "unverified app" and
  first-time auth flow
- **Watcher and CLI as separate sections**: they serve different use cases
  (background monitoring vs. on-demand queries) and have different mental models
- **No architecture deep-dive**: brief ASCII diagram in the header; full
  architecture detail lives in `.context/ARCHITECTURE.md`
- **Batches API explained in backfill section**: cost/behaviour note helps
  users understand why backfill is different from real-time processing
- **Troubleshooting covers known Windows-specific issues**: MCP port conflicts,
  TIME_WAIT, Unicode/encoding
