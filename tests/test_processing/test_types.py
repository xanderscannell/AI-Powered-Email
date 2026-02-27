"""Tests for processing type definitions, enums, and label mappings."""

import pytest

from src.processing.types import (
    EmailAnalysis,
    INTENT_LABEL,
    Intent,
    PRIORITY_LABEL,
    Priority,
)


# ── Priority ────────────────────────────────────────────────────────────────────


class TestPriority:
    def test_values_are_1_to_5(self) -> None:
        assert [p.value for p in Priority] == [1, 2, 3, 4, 5]

    def test_is_int_enum(self) -> None:
        assert isinstance(Priority.CRITICAL, int)
        assert Priority.CRITICAL == 1
        assert Priority.FYI == 5

    def test_names(self) -> None:
        assert Priority(1) is Priority.CRITICAL
        assert Priority(2) is Priority.HIGH
        assert Priority(3) is Priority.MEDIUM
        assert Priority(4) is Priority.LOW
        assert Priority(5) is Priority.FYI


# ── Intent ──────────────────────────────────────────────────────────────────────


class TestIntent:
    def test_string_values(self) -> None:
        assert Intent.ACTION_REQUIRED == "action_required"
        assert Intent.QUESTION == "question"
        assert Intent.FYI == "fyi"

    def test_is_str_enum(self) -> None:
        assert isinstance(Intent.ACTION_REQUIRED, str)

    def test_round_trip(self) -> None:
        for intent in Intent:
            assert Intent(intent.value) is intent


# ── PRIORITY_LABEL ──────────────────────────────────────────────────────────────


class TestPriorityLabel:
    def test_all_priorities_have_a_label(self) -> None:
        for p in Priority:
            assert p in PRIORITY_LABEL, f"Missing label for {p}"

    def test_label_names(self) -> None:
        assert PRIORITY_LABEL[Priority.CRITICAL] == "AI/Priority/Critical"
        assert PRIORITY_LABEL[Priority.HIGH] == "AI/Priority/High"
        assert PRIORITY_LABEL[Priority.MEDIUM] == "AI/Priority/Medium"
        assert PRIORITY_LABEL[Priority.LOW] == "AI/Priority/Low"
        assert PRIORITY_LABEL[Priority.FYI] == "AI/Priority/FYI"


# ── INTENT_LABEL ────────────────────────────────────────────────────────────────


class TestIntentLabel:
    def test_all_intents_have_a_label(self) -> None:
        for i in Intent:
            assert i in INTENT_LABEL, f"Missing label for {i}"

    def test_label_names(self) -> None:
        assert INTENT_LABEL[Intent.ACTION_REQUIRED] == "AI/Intent/ActionRequired"
        assert INTENT_LABEL[Intent.QUESTION] == "AI/Intent/Question"
        assert INTENT_LABEL[Intent.FYI] == "AI/Intent/FYI"


# ── EmailAnalysis ───────────────────────────────────────────────────────────────


class TestEmailAnalysis:
    def _make(self, **kwargs: object) -> EmailAnalysis:
        defaults: dict[str, object] = dict(
            email_id="msg_1",
            sentiment=0.0,
            intent=Intent.FYI,
            priority=Priority.MEDIUM,
        )
        return EmailAnalysis(**{**defaults, **kwargs})  # type: ignore[arg-type]

    def test_required_fields_are_stored(self) -> None:
        a = self._make(sentiment=0.7, intent=Intent.QUESTION, priority=Priority.HIGH)
        assert a.email_id == "msg_1"
        assert a.sentiment == 0.7
        assert a.intent == Intent.QUESTION
        assert a.priority == Priority.HIGH

    def test_defaults(self) -> None:
        a = self._make()
        assert a.entities == []
        assert a.summary == ""
        assert a.requires_reply is False
        assert a.deadline is None

    def test_optional_fields(self) -> None:
        a = self._make(
            entities=["Alice", "Project X"],
            summary="One sentence.",
            requires_reply=True,
            deadline="by Friday",
        )
        assert a.entities == ["Alice", "Project X"]
        assert a.summary == "One sentence."
        assert a.requires_reply is True
        assert a.deadline == "by Friday"

    def test_is_frozen(self) -> None:
        a = self._make()
        with pytest.raises((AttributeError, TypeError)):
            a.email_id = "other"  # type: ignore[misc]
