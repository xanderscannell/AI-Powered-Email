"""Gmail MCP client — wraps workspace-mcp Gmail tools behind a typed async API."""

import asyncio
import json
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters
from mcp.types import TextContent

from src.mcp.stdio_transport import stdio_client

from src.mcp.types import RawEmail

logger = logging.getLogger(__name__)

# Gmail system label IDs (not user-created; used directly without cache lookup)
_STARRED = "STARRED"
_UNREAD = "UNREAD"

# Full set of AI labels the agent creates on first run.
# Order matters: parents must be created before their children so Gmail
# nests them correctly in the sidebar.
AI_LABELS: list[str] = [
    # Level 0 — root parent; never applied to emails directly
    "AI",
    # Level 1 — type parents (inbox filter targets)
    "AI/Human",
    "AI/Automated",
    # Level 2 — Human sublabels
    "AI/Human/FollowUp",
    # Level 2 — Automated domain sublabels
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

# JSON-decoded value from an MCP tool response
_JsonValue = dict[str, Any] | list[Any] | str | None


class MCPError(Exception):
    """Raised when a workspace-mcp tool call returns an error."""


class GmailClient:
    """Thin async wrapper around the workspace-mcp Gmail tools.

    Holds a single long-lived MCP session so the polling loop avoids
    spawning a new subprocess on every poll.  Use the `gmail_client()`
    context manager to construct and tear down correctly.
    """

    def __init__(self, session: ClientSession, user_email: str) -> None:
        self._session = session
        self._user_email = user_email
        self._label_cache: dict[str, str] = {}  # label name → label ID

    # ── Public API ─────────────────────────────────────────────────────────────

    async def get_unread_email_ids(self, max_results: int = 500) -> list[str]:
        """Return only the IDs of unread emails — no content fetch.

        Used on startup to seed the processed-ID set without burning API calls.
        The default limit of 500 is intentionally higher than the polling limit
        to capture as much of the existing backlog as possible in one shot.
        """
        raw = await self._call(
            "search_gmail_messages",
            {"query": "is:unread", "page_size": max_results,
             "user_google_email": self._user_email},
        )
        return self._parse_search_ids(raw)

    async def get_unread_emails(self, max_results: int = 50) -> list[RawEmail]:
        """Return unread emails with full body content.

        Makes two MCP calls: a lightweight search, then a batch content fetch.
        """
        raw = await self._call(
            "search_gmail_messages",
            {"query": "is:unread", "page_size": max_results,
             "user_google_email": self._user_email},
        )
        ids = self._parse_search_ids(raw)
        if not ids:
            return []

        content = await self._call(
            "get_gmail_messages_content_batch",
            {"message_ids": ids, "user_google_email": self._user_email},
        )
        return self._parse_batch_emails(content)

    async def get_emails_since(self, days: int, max_results: int = 500) -> list[RawEmail]:
        """Return all emails (read and unread) received in the last N days.

        Uses Gmail's ``after:YYYY/MM/DD`` search operator. The max_results cap
        defaults to 500 — the same limit used for startup ID seeding.
        """
        since = (datetime.now() - timedelta(days=days)).strftime("%Y/%m/%d")
        raw = await self._call(
            "search_gmail_messages",
            {"query": f"after:{since}", "page_size": max_results,
             "user_google_email": self._user_email},
        )
        ids = self._parse_search_ids(raw)
        if not ids:
            return []

        content = await self._call(
            "get_gmail_messages_content_batch",
            {"message_ids": ids, "user_google_email": self._user_email},
        )
        return self._parse_batch_emails(content)

    async def get_email(self, email_id: str) -> RawEmail:
        """Return a single email with full body."""
        raw = await self._call(
            "get_gmail_message_content",
            {"message_id": email_id, "user_google_email": self._user_email},
        )
        if isinstance(raw, str):
            emails = self._parse_batch_emails(raw)
            if emails:
                return emails[0]
            raise MCPError(f"Could not parse message {email_id} from response")
        if isinstance(raw, dict):
            return self._parse_email_dict(raw)
        raise MCPError(f"Unexpected response type for message {email_id}: {type(raw)}")

    async def apply_label(self, email_id: str, label_name: str) -> None:
        """Add a label to an email, creating the label first if needed."""
        label_id = await self._get_or_create_label_id(label_name)
        await self._call(
            "modify_gmail_message_labels",
            {"message_id": email_id, "add_label_ids": [label_id],
             "user_google_email": self._user_email},
        )
        logger.debug("Applied label %r (id=%s) to message %s", label_name, label_id, email_id)

    async def remove_label(self, email_id: str, label_name: str) -> None:
        """Remove a label from an email. No-ops if the label doesn't exist."""
        label_id = self._label_cache.get(label_name)
        if label_id is None:
            await self._refresh_label_cache()
            label_id = self._label_cache.get(label_name)
        if label_id is None:
            logger.warning("Label %r not found in Gmail; skipping remove", label_name)
            return
        await self._call(
            "modify_gmail_message_labels",
            {"message_id": email_id, "remove_label_ids": [label_id],
             "user_google_email": self._user_email},
        )
        logger.debug("Removed label %r from message %s", label_name, email_id)

    async def star_email(self, email_id: str) -> None:
        """Star an email (applies the Gmail STARRED system label)."""
        await self._call(
            "modify_gmail_message_labels",
            {"message_id": email_id, "add_label_ids": [_STARRED],
             "user_google_email": self._user_email},
        )
        logger.debug("Starred message %s", email_id)

    async def create_label(self, label_name: str) -> str:
        """Create a Gmail label and return its ID.

        If the label already exists (found in cache), returns the cached ID
        without making an MCP call.
        """
        cached = self._label_cache.get(label_name)
        if cached:
            return cached

        await self._call("manage_gmail_label", {"name": label_name, "action": "create",
                                                "user_google_email": self._user_email})
        await self._refresh_label_cache()

        label_id = self._label_cache.get(label_name)
        if label_id is None:
            raise MCPError(
                f"Label {label_name!r} was created but is missing from Gmail label list"
            )
        logger.info("Created Gmail label: %s (id=%s)", label_name, label_id)
        return label_id

    async def ensure_ai_labels(self) -> None:
        """Idempotently create all AI/* labels required by the agent.

        Safe to call on every startup — skips labels that already exist.
        """
        await self._refresh_label_cache()
        for label_name in AI_LABELS:
            if label_name not in self._label_cache:
                await self.create_label(label_name)
            else:
                logger.debug("Label already exists: %s", label_name)

    async def send_email(self, to: str, subject: str, body: str) -> None:
        """Send an email via Gmail MCP.

        Used by BriefingGenerator to deliver the daily briefing to self.
        """
        await self._call(
            "send_gmail_message",
            {
                "to": to,
                "subject": subject,
                "body": body,
                "user_google_email": self._user_email,
            },
        )
        logger.info("Sent email to %s: %r", to, subject)

    # ── Internal helpers ───────────────────────────────────────────────────────

    async def _refresh_label_cache(self) -> None:
        """Rebuild the name → ID cache from the live Gmail label list."""
        raw = await self._call(
            "list_gmail_labels", {"user_google_email": self._user_email}
        )
        if isinstance(raw, list):
            # Legacy JSON list response
            self._label_cache = {
                str(lbl["name"]): str(lbl["id"])
                for lbl in raw
                if isinstance(lbl, dict) and "name" in lbl and "id" in lbl
            }
        elif isinstance(raw, str):
            # Current workspace-mcp returns formatted text:
            #   • LabelName (ID: label_id)
            self._label_cache = {}
            for match in re.finditer(r"•\s+(.+?)\s+\(ID:\s+(.+?)\)", raw):
                self._label_cache[match.group(1)] = match.group(2)
        else:
            logger.warning("Unexpected response from list_gmail_labels: %r", raw)
            return
        logger.debug("Label cache refreshed: %d labels", len(self._label_cache))

    async def _get_or_create_label_id(self, label_name: str) -> str:
        """Return the label ID, creating the label in Gmail if it doesn't exist."""
        if label_name not in self._label_cache:
            await self._refresh_label_cache()
        if label_name not in self._label_cache:
            return await self.create_label(label_name)
        return self._label_cache[label_name]

    async def _call(self, tool_name: str, arguments: dict[str, Any]) -> _JsonValue:
        """Call a workspace-mcp tool and return the parsed JSON result.

        Raises MCPError if the tool returns an error.  Plain-string responses
        (e.g. "Email sent!") are returned as-is.
        """
        logger.debug("MCP → %s %s", tool_name, arguments)
        result = await self._session.call_tool(tool_name, arguments)

        if result.isError:
            raise MCPError(f"Tool {tool_name!r} returned error: {result.content}")

        if not result.content:
            return None

        # Extract text from the first TextContent block
        text: str | None = None
        for item in result.content:
            if isinstance(item, TextContent):
                text = item.text
                break

        if text is None:
            return None

        try:
            parsed: _JsonValue = json.loads(text)
            return parsed
        except json.JSONDecodeError:
            return text  # some tools return plain confirmation strings

    @staticmethod
    def _parse_search_ids(raw: _JsonValue) -> list[str]:
        """Extract message IDs from a search response (text or JSON list)."""
        if isinstance(raw, list):
            return [
                str(m.get("message_id", ""))
                for m in raw
                if isinstance(m, dict) and m.get("message_id")
            ]
        if isinstance(raw, str):
            return re.findall(r"Message ID:\s*(\S+)", raw)
        return []

    @staticmethod
    def _parse_batch_emails(raw: _JsonValue) -> list[RawEmail]:
        """Parse one or more emails from a batch/single content response.

        workspace-mcp returns text blocks like::

            Message ID: abc123
            Subject: Hello
            From: alice@example.com
            Date: Mon, 1 Jan 2026 12:00:00 +0000
            To: <bob@example.com>
            Web Link: https://mail.google.com/...

            Body text follows after a blank line...
        """
        if isinstance(raw, list):
            return [
                GmailClient._parse_email_dict(m)
                for m in raw
                if isinstance(m, dict)
            ]
        if not isinstance(raw, str):
            return []

        emails: list[RawEmail] = []
        # Split into per-message blocks on "Message ID:" boundaries
        blocks = re.split(r"(?=^Message ID:)", raw, flags=re.MULTILINE)
        for block in blocks:
            block = block.strip()
            if not block.startswith("Message ID:"):
                continue

            def _header(name: str) -> str:
                m = re.search(rf"^{name}:\s*(.+)$", block, re.MULTILINE)
                return m.group(1).strip() if m else ""

            msg_id = _header("Message ID")
            subject = _header("Subject") or "(no subject)"
            sender = _header("From")
            date = _header("Date")
            to_raw = _header("To")
            web_link = _header("Web Link")

            # Body: everything after the header block (first blank line)
            body = ""
            header_end = re.search(r"\n\s*\n", block)
            if header_end:
                body = block[header_end.end():].strip()

            # Strip angle brackets from To: <email@example.com>
            recipient = re.sub(r"^<|>$", "", to_raw) if to_raw else None

            emails.append(RawEmail(
                id=msg_id,
                thread_id="",
                sender=sender,
                recipient=recipient,
                subject=subject,
                snippet=body[:200] if body else "",
                body=body or None,
                labels=[],
                date=date or None,
                web_link=web_link or None,
            ))
        return emails

    @staticmethod
    def _parse_email_dict(data: dict[str, Any]) -> RawEmail:
        """Map a raw MCP message dict to a RawEmail dataclass (legacy JSON)."""
        body_raw = data.get("body", "")
        recipient_raw = data.get("to", "")
        date_raw = data.get("date", "")
        link_raw = data.get("web_link", "")

        return RawEmail(
            id=str(data.get("message_id", data.get("id", ""))),
            thread_id=str(data.get("thread_id", "")),
            sender=str(data.get("from", "")),
            recipient=str(recipient_raw) if recipient_raw else None,
            subject=str(data.get("subject", "(no subject)")),
            snippet=str(data.get("snippet", "")),
            body=str(body_raw) if body_raw else None,
            labels=list(data.get("labels", [])),
            date=str(date_raw) if date_raw else None,
            web_link=str(link_raw) if link_raw else None,
        )


_MCP_CONNECT_RETRIES = 5
_MCP_RETRY_DELAY_SECONDS = 3


@asynccontextmanager
async def gmail_client(
    *,
    user_email: str | None = None,
    server_command: str | None = None,
) -> AsyncIterator[GmailClient]:
    """Async context manager that yields a connected, ready-to-use GmailClient.

    Spawns `workspace-mcp` as a subprocess via the MCP stdio transport,
    initialises the session, warms the label cache, and tears everything
    down cleanly on exit.

    Retries up to ``_MCP_CONNECT_RETRIES`` times on startup failure because
    ``workspace-mcp`` binds port 8000 for an internal OAuth server and will
    crash if a previous instance hasn't fully released it yet.

    Args:
        user_email: Google account email. Falls back to USER_GOOGLE_EMAIL env var.
        server_command: Command used to launch the MCP server.
                        Defaults to GMAIL_MCP_SERVER_PATH env var (or "uvx").

    Example::

        async with gmail_client() as client:
            emails = await client.get_unread_emails()
    """
    email = user_email or os.environ.get("USER_GOOGLE_EMAIL", "")
    if not email:
        raise ValueError(
            "user_email must be provided or USER_GOOGLE_EMAIL env var must be set"
        )

    cmd = server_command or os.environ.get("GMAIL_MCP_SERVER_PATH", "uvx")
    # Detect uvx by name or full path (e.g. C:\...\uvx.exe) and pass workspace-mcp args
    _cmd_basename = os.path.basename(cmd).lower().replace(".exe", "")
    args = ["workspace-mcp", "--tools", "gmail"] if _cmd_basename == "uvx" else []

    # Use a non-default port for workspace-mcp's internal OAuth server to avoid
    # conflicts with other services on port 8000. TIME_WAIT sockets from previous
    # runs can also block the port for up to 2 minutes on Windows.
    mcp_port = os.environ.get("WORKSPACE_MCP_PORT", "18741")

    server_params = StdioServerParameters(
        command=cmd,
        args=args,
        env={
            **os.environ,
            "GOOGLE_OAUTH_CLIENT_ID": os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""),
            "GOOGLE_OAUTH_CLIENT_SECRET": os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
            "USER_GOOGLE_EMAIL": email,
            "MCP_SINGLE_USER_MODE": "1",
            "WORKSPACE_MCP_PORT": mcp_port,
            # Force UTF-8 I/O in the workspace-mcp subprocess so that Unicode
            # characters in log messages (e.g. ✓) don't crash the logging handler
            # on Windows, where the default console encoding is cp1252.
            "PYTHONUTF8": "1",
        },
    )

    last_err: BaseException | None = None
    for attempt in range(1, _MCP_CONNECT_RETRIES + 1):
        try:
            async with stdio_client(server_params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    client = GmailClient(session, email)
                    await client._refresh_label_cache()
                    logger.info("Gmail MCP client connected (%s)", email)
                    yield client
                    return  # clean exit from the context manager
        except BaseExceptionGroup as exc:
            last_err = exc
            if attempt < _MCP_CONNECT_RETRIES:
                logger.warning(
                    "MCP server connection failed (attempt %d/%d) — "
                    "retrying in %ds (workspace-mcp port 8000 likely still held by a previous process)",
                    attempt,
                    _MCP_CONNECT_RETRIES,
                    _MCP_RETRY_DELAY_SECONDS,
                )
                await asyncio.sleep(_MCP_RETRY_DELAY_SECONDS)
            else:
                raise
        except Exception as exc:
            last_err = exc
            if attempt < _MCP_CONNECT_RETRIES:
                logger.warning(
                    "MCP server connection failed (attempt %d/%d) — retrying in %ds",
                    attempt,
                    _MCP_CONNECT_RETRIES,
                    _MCP_RETRY_DELAY_SECONDS,
                )
                await asyncio.sleep(_MCP_RETRY_DELAY_SECONDS)
            else:
                raise

    # Should be unreachable, but just in case
    raise MCPError(f"Failed to connect after {_MCP_CONNECT_RETRIES} attempts") from last_err
