"""Types for the email analysis pipeline."""

from dataclasses import dataclass, field
from enum import Enum


class EmailType(str, Enum):
    """Whether the email was sent by a real person or an automated system."""

    HUMAN = "human"
    AUTOMATED = "automated"


class Domain(str, Enum):
    """Life-domain category for automated email."""

    # Transactional / Money
    FINANCE = "finance"
    SHOPPING = "shopping"

    # Life Admin
    TRAVEL = "travel"
    HEALTH = "health"
    GOVERNMENT = "government"

    # Work / Learning
    WORK = "work"
    EDUCATION = "education"

    # Inbox Noise
    NEWSLETTER = "newsletter"
    MARKETING = "marketing"
    SOCIAL = "social"
    ALERTS = "alerts"

    # Catch-all
    OTHER = "other"


# ── Gmail label constants ───────────────────────────────────────────────────────

HUMAN_LABEL = "AI/Human"
HUMAN_FOLLOWUP_LABEL = "AI/Human/FollowUp"

DOMAIN_LABEL: dict[Domain, str] = {
    Domain.FINANCE: "AI/Automated/Finance",
    Domain.SHOPPING: "AI/Automated/Shopping",
    Domain.TRAVEL: "AI/Automated/Travel",
    Domain.HEALTH: "AI/Automated/Health",
    Domain.GOVERNMENT: "AI/Automated/Government",
    Domain.WORK: "AI/Automated/Work",
    Domain.EDUCATION: "AI/Automated/Education",
    Domain.NEWSLETTER: "AI/Automated/Newsletter",
    Domain.MARKETING: "AI/Automated/Marketing",
    Domain.SOCIAL: "AI/Automated/Social",
    Domain.ALERTS: "AI/Automated/Alerts",
    Domain.OTHER: "AI/Automated/Other",
}


# ── Analysis result ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EmailAnalysis:
    """Structured intelligence extracted from a single email by Haiku."""

    email_id: str
    email_type: EmailType
    domain: Domain | None          # None for human emails
    entities: list[str] = field(default_factory=list)
    summary: str = ""
    requires_reply: bool = False
    deadline: str | None = None
