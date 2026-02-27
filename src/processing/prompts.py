"""Anthropic tool definition and prompt builder for email analysis."""

from typing import Any

from src.mcp.types import RawEmail

# Maximum characters of email body sent to Haiku.
# Keeps token costs low while capturing the full content of most emails.
BODY_CHAR_LIMIT = 4_000

# ── Tool definition ────────────────────────────────────────────────────────────

#: Anthropic tool schema for structured email analysis.
#: Haiku is forced to call this tool via tool_choice, guaranteeing
#: a machine-readable response with no JSON parsing fragility.
ANALYSIS_TOOL: dict[str, Any] = {
    "name": "record_email_analysis",
    "description": (
        "Record the structured analysis of an email. "
        "Call this tool with your findings after reading the email."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "sentiment": {
                "type": "number",
                "description": (
                    "Sentiment score: -1.0 = very negative, 0.0 = neutral, "
                    "1.0 = very positive."
                ),
            },
            "intent": {
                "type": "string",
                "enum": ["action_required", "question", "fyi"],
                "description": (
                    "Primary intent. "
                    "'action_required': sender wants something done. "
                    "'question': sender is asking something. "
                    "'fyi': informational, no response expected."
                ),
            },
            "priority": {
                "type": "integer",
                "enum": [1, 2, 3, 4, 5],
                "description": (
                    "Urgency: 1=Critical (needs immediate attention), "
                    "2=High, 3=Medium, 4=Low, 5=FYI (no urgency)."
                ),
            },
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Notable named entities: people, organisations, projects, "
                    "products, or key topics mentioned in the email."
                ),
            },
            "summary": {
                "type": "string",
                "description": "One concise sentence summarising the email.",
            },
            "requires_reply": {
                "type": "boolean",
                "description": "True if the sender expects a reply or response.",
            },
            "deadline": {
                "type": ["string", "null"],
                "description": (
                    "Any deadline or time constraint mentioned, e.g. 'by Friday' "
                    "or 'before the 3pm meeting'. null if none."
                ),
            },
        },
        "required": [
            "sentiment",
            "intent",
            "priority",
            "entities",
            "summary",
            "requires_reply",
            "deadline",
        ],
    },
}


# ── Prompt builder ─────────────────────────────────────────────────────────────


def build_messages(email: RawEmail) -> list[dict[str, str]]:
    """Build the Anthropic messages list for analysing a single email.

    The body is truncated to BODY_CHAR_LIMIT characters.  If no body is
    available (e.g. headers-only from a lightweight search result) the
    snippet is used as a fallback.
    """
    raw_body = email.body or email.snippet or ""
    body_preview = raw_body[:BODY_CHAR_LIMIT]
    truncated = len(raw_body) > BODY_CHAR_LIMIT

    content_lines = [
        f"From: {email.sender}",
        f"Subject: {email.subject}",
    ]
    if email.recipient:
        content_lines.append(f"To: {email.recipient}")
    if email.date:
        content_lines.append(f"Date: {email.date}")

    content_lines.append("")  # blank line before body
    content_lines.append(body_preview)
    if truncated:
        content_lines.append("\n[… email truncated …]")

    return [
        {
            "role": "user",
            "content": (
                "Analyse the following email and call record_email_analysis "
                "with your findings.\n\n" + "\n".join(content_lines)
            ),
        }
    ]
