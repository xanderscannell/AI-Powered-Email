"""Data types shared across MCP client modules."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RawEmail:
    """An email as returned by the Gmail MCP server, before Haiku analysis.

    Fields populated by search_gmail_messages (lightweight):
        id, thread_id, sender, subject, snippet, labels, web_link

    Fields populated by get_gmail_message_content (full):
        body, recipient, date  (plus all of the above)
    """

    id: str
    thread_id: str
    sender: str
    subject: str
    snippet: str
    labels: list[str] = field(default_factory=list)
    body: str | None = None
    recipient: str | None = None
    date: str | None = None
    web_link: str | None = None
