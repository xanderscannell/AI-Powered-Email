"""Types for the email analysis pipeline."""

from dataclasses import dataclass, field
from enum import Enum


class Priority(int, Enum):
    """Email priority, from most to least urgent.

    Integer values map directly to the Haiku tool schema so they can be
    round-tripped through JSON without a separate mapping step.
    """

    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4
    FYI = 5


class Intent(str, Enum):
    """Primary intent / action category of the email."""

    ACTION_REQUIRED = "action_required"
    QUESTION = "question"
    FYI = "fyi"


# ── Gmail label mappings ───────────────────────────────────────────────────────

PRIORITY_LABEL: dict[Priority, str] = {
    Priority.CRITICAL: "AI/Priority/Critical",
    Priority.HIGH: "AI/Priority/High",
    Priority.MEDIUM: "AI/Priority/Medium",
    Priority.LOW: "AI/Priority/Low",
    Priority.FYI: "AI/Priority/FYI",
}

INTENT_LABEL: dict[Intent, str] = {
    Intent.ACTION_REQUIRED: "AI/Intent/ActionRequired",
    Intent.QUESTION: "AI/Intent/Question",
    Intent.FYI: "AI/Intent/FYI",
}


# ── Analysis result ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EmailAnalysis:
    """Structured intelligence extracted from a single email by Haiku.

    Produced by EmailAnalyzer.analyze() and consumed by:
      - AnalysisProcessor  (Phase 2: Gmail label write-back)
      - VectorStore        (Phase 3: ChromaDB embedding)
      - Database           (Phase 3: SQLite structured storage)
    """

    email_id: str
    sentiment: float          # -1.0 (very negative) → 1.0 (very positive)
    intent: Intent
    priority: Priority
    entities: list[str] = field(default_factory=list)  # people, orgs, projects
    summary: str = ""                                   # one-sentence summary
    requires_reply: bool = False
    deadline: str | None = None                         # free-text, e.g. "by Friday"
