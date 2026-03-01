"""Anthropic tool definition and prompt builder for email analysis."""

from html.parser import HTMLParser
from typing import Any

from src.mcp.types import RawEmail

# Maximum characters of email body sent to Haiku — applied after HTML stripping,
# so this represents actual text content rather than raw markup.
BODY_CHAR_LIMIT = 4_000


# ── HTML stripper ───────────────────────────────────────────────────────────────


class _HTMLStripper(HTMLParser):
    """Minimal HTMLParser subclass that collects visible text nodes."""

    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self._parts.append(text)

    def get_text(self) -> str:
        return " ".join(self._parts)


def strip_html(text: str) -> str:
    """Return plain text from an HTML string.

    If the input doesn't look like HTML, or stripping produces nothing useful,
    the original string is returned unchanged.
    """
    if "<" not in text:
        return text
    stripper = _HTMLStripper()
    try:
        stripper.feed(text)
        result = stripper.get_text()
        # Sanity check: if we stripped away >90% of the content something went
        # wrong (e.g. the input was not really HTML), so return the original.
        return result if len(result) > len(text) * 0.1 else text
    except Exception:  # noqa: BLE001
        return text


# ── Tool definition ────────────────────────────────────────────────────────────

#: Anthropic tool schema for structured email analysis.
#: Descriptions are intentionally terse to minimise input tokens per call.
ANALYSIS_TOOL: dict[str, Any] = {
    "name": "record_email_analysis",
    "description": "Record structured analysis of an email.",
    "input_schema": {
        "type": "object",
        "properties": {
            "email_type": {
                "type": "string",
                "enum": ["human", "automated"],
                "description": "'human' if written by a real person; 'automated' if system-generated.",
            },
            "domain": {
                "type": ["string", "null"],
                "enum": [
                    "finance", "shopping", "travel", "health", "government",
                    "work", "education", "newsletter", "marketing", "social",
                    "alerts", "other", None,
                ],
                "description": "Category for automated emails only; null for human emails.",
            },
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Named people, organisations, products, or key topics.",
            },
            "summary": {
                "type": "string",
                "description": "One sentence summary of the email.",
            },
            "requires_reply": {
                "type": "boolean",
                "description": "True if the sender expects a reply.",
            },
            "deadline": {
                "type": ["string", "null"],
                "description": "Any deadline or time constraint mentioned; null if none.",
            },
        },
        "required": [
            "email_type",
            "domain",
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

    HTML is stripped from the body before truncation so the character limit
    applies to actual text content, not markup.  If no body is available
    (e.g. headers-only from a lightweight search result) the snippet is used
    as a fallback.
    """
    raw_body = email.body or email.snippet or ""
    plain_body = strip_html(raw_body)
    body_preview = plain_body[:BODY_CHAR_LIMIT]
    truncated = len(plain_body) > BODY_CHAR_LIMIT

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
