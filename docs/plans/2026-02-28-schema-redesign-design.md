# Design: Email Classification Schema Redesign

**Date**: 2026-02-28
**Status**: Approved

## Problem

The current `Priority` (1–5) + `Intent` (action_required/question/fyi) + `sentiment` schema
is the wrong abstraction for a personal inbox that is dominated by automated email (newsletters,
receipts, notifications, marketing). Assigning a newsletter "Medium" priority or a receipt "Low"
priority is noise, not signal. The labels don't help organise the inbox.

## Core Insight

Human email and automated email are fundamentally different things and should not share a
classification axis. The primary split is: **is this from a real person, or a machine?**

- **Automated email** → classify by life domain (Finance, Shopping, Travel, etc.)
- **Human email** → goes to a clean inbox; no priority scoring yet; `requires_reply` is the
  only action signal needed

## Design

### New `EmailAnalysis` Schema

```python
@dataclass(frozen=True)
class EmailAnalysis:
    email_id: str
    email_type: EmailType      # human | automated  (primary split)
    domain: Domain | None      # domain category; None for human emails
    requires_reply: bool       # kept — most useful signal for human email
    deadline: str | None       # kept — applies to both types
    summary: str               # kept
    entities: list[str]        # kept

# Removed: sentiment (float), priority (Priority), intent (Intent)
```

### `EmailType` Enum

```python
class EmailType(str, Enum):
    HUMAN = "human"
    AUTOMATED = "automated"
```

### `Domain` Enum (automated email only)

```python
class Domain(str, Enum):
    # Transactional / Money
    FINANCE = "finance"          # bank statements, billing, invoices, utilities
    SHOPPING = "shopping"        # orders, shipping, delivery notifications

    # Life Admin
    TRAVEL = "travel"            # bookings, itineraries, flight/hotel confirmations
    HEALTH = "health"            # medical, pharmacy, insurance
    GOVERNMENT = "government"    # official, legal, tax correspondence

    # Work / Learning
    WORK = "work"                # HR systems, IT, internal tools
    EDUCATION = "education"      # courses, alumni, certifications, student loans

    # Inbox Noise
    NEWSLETTER = "newsletter"    # subscriptions, digests, editorial content
    MARKETING = "marketing"      # promotions, deals, product announcements
    SOCIAL = "social"            # social media notifications
    ALERTS = "alerts"            # app alerts, security notices, service updates

    # Catch-all
    OTHER = "other"
```

### Gmail Label Structure

Labels are created in strict top-down order so Gmail nests them properly:

```
AI                              ← root; never applied to emails
├── AI/Human                    ← all human email
│   └── AI/Human/FollowUp       ← human email where requires_reply=True
└── AI/Automated                ← parent for inbox filter rule
    ├── AI/Automated/Finance
    ├── AI/Automated/Shopping
    ├── AI/Automated/Travel
    ├── AI/Automated/Health
    ├── AI/Automated/Government
    ├── AI/Automated/Work
    ├── AI/Automated/Education
    ├── AI/Automated/Newsletter
    ├── AI/Automated/Marketing
    ├── AI/Automated/Social
    ├── AI/Automated/Alerts
    └── AI/Automated/Other
```

**Creation order** (parents before children):
```python
AI_LABELS = [
    "AI",
    "AI/Human",
    "AI/Automated",
    "AI/Human/FollowUp",
    "AI/Automated/Finance",
    "AI/Automated/Shopping",
    "AI/Automated/Travel",
    "AI/Automated/Health",
    "AI/Automated/Government",
    "AI/Automated/Work",
    "AI/Automated/Education",
    "AI/Automated/Newsletter",
    "AI/Automated/Marketing",
    "AI/Automated/Social",
    "AI/Automated/Alerts",
    "AI/Automated/Other",
]
```

**Label assignment per email:**
- Human → `AI/Human` + `AI/Human/FollowUp` (if `requires_reply=True`)
- Automated → `AI/Automated/<Domain>` (one label; parent filter covers it)

A single Gmail filter rule — "skip inbox if label is AI/Automated" — routes all automated mail
out of the inbox automatically.

### SQLite Schema Changes (`emails` table)

Remove:
- `sentiment REAL`
- `intent TEXT`
- `priority INTEGER`

Add:
- `email_type TEXT NOT NULL`  — `'human'` or `'automated'`
- `domain TEXT`               — nullable; NULL for human emails

`contacts` table: remove `avg_sentiment` (was a rolling average of `analysis.sentiment`).
Contacts now track `email_address`, `total_emails`, `last_contact` only.

`get_urgent_emails()` → renamed `get_human_emails_needing_reply(hours)`:
```sql
WHERE email_type = 'human' AND requires_reply = 1
  AND processed_at >= datetime('now', '-N hours')
```

### ChromaDB Metadata Changes

Remove from `_build_metadata()`: `priority`, `intent`, `sentiment`

Add: `email_type`, `domain` (empty string if None, as ChromaDB requires scalar values)

```python
{
    "sender": ...,
    "subject": ...,
    "thread_id": ...,
    "date": ...,
    "email_type": analysis.email_type.value,
    "domain": analysis.domain.value if analysis.domain else "",
    "requires_reply": analysis.requires_reply,
    "summary": ...,
}
```

`search_with_filter` can now filter by `{"email_type": "human"}` or `{"domain": "finance"}`.

### Briefing Generator Changes

The "URGENT EMAILS (priority CRITICAL or HIGH)" section becomes:

```
HUMAN EMAILS NEEDING REPLY (last 24h):
  - Re: Contract renewal (from alice@company.com): ...

PENDING FOLLOW-UPS:
  ...

OPEN DEADLINES:
  ...
```

Remove `_PRIORITY_LABEL` dict from `generator.py`.

### CLI `search` Command Changes

The "Priority" display column (with colour-coded urgency levels) is replaced with two columns:
- **Type** — `human` or `automated`
- **Domain** — domain value, or blank for human emails

## Files Affected

| File | Change |
|------|--------|
| `src/processing/types.py` | Replace `Priority`, `Intent`, `PRIORITY_LABEL`, `INTENT_LABEL` with `EmailType`, `Domain`, new label dicts |
| `src/processing/prompts.py` | Rewrite `ANALYSIS_TOOL` schema |
| `src/processing/analyzer.py` | Update `_parse_analysis()`, `_apply_labels()`, log line |
| `src/mcp/gmail_client.py` | Replace `AI_LABELS` list |
| `src/storage/models.py` | DDL: swap 3 old columns for 2 new; update `EmailRow`; remove `avg_sentiment` from contacts |
| `src/storage/db.py` | Update `_upsert_email()`, `_upsert_contact()`, rename `get_urgent_emails()` |
| `src/storage/vector_store.py` | Update `_build_metadata()` |
| `src/cli/commands.py` | Replace priority display columns in `search` |
| `src/briefing/generator.py` | Update prompt, remove `_PRIORITY_LABEL` |

## SQLite Migration Note

This is a breaking schema change. Since the project is in active development with no
production data to preserve, the database should be dropped and recreated on next run.
The `emails` table DDL change handles this automatically via `CREATE TABLE IF NOT EXISTS`
— existing databases will need to be deleted manually or a migration applied.
