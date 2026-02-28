"""Tests for processing type definitions, enums, and label mappings."""

import pytest

from src.processing.types import (
    DOMAIN_LABEL,
    HUMAN_LABEL,
    HUMAN_FOLLOWUP_LABEL,
    Domain,
    EmailAnalysis,
    EmailType,
)


class TestEmailType:
    def test_values(self) -> None:
        assert EmailType.HUMAN == "human"
        assert EmailType.AUTOMATED == "automated"

    def test_is_str_enum(self) -> None:
        assert isinstance(EmailType.HUMAN, str)

    def test_round_trip(self) -> None:
        for t in EmailType:
            assert EmailType(t.value) is t


class TestDomain:
    def test_all_values_present(self) -> None:
        expected = {
            "finance", "shopping", "travel", "health", "government",
            "work", "education", "newsletter", "marketing", "social",
            "alerts", "other",
        }
        assert {d.value for d in Domain} == expected

    def test_is_str_enum(self) -> None:
        assert isinstance(Domain.FINANCE, str)

    def test_round_trip(self) -> None:
        for d in Domain:
            assert Domain(d.value) is d


class TestDomainLabel:
    def test_all_domains_have_a_label(self) -> None:
        for d in Domain:
            assert d in DOMAIN_LABEL, f"Missing label for {d}"

    def test_label_format(self) -> None:
        assert DOMAIN_LABEL[Domain.FINANCE] == "AI/Automated/Finance"
        assert DOMAIN_LABEL[Domain.SHOPPING] == "AI/Automated/Shopping"
        assert DOMAIN_LABEL[Domain.TRAVEL] == "AI/Automated/Travel"
        assert DOMAIN_LABEL[Domain.HEALTH] == "AI/Automated/Health"
        assert DOMAIN_LABEL[Domain.GOVERNMENT] == "AI/Automated/Government"
        assert DOMAIN_LABEL[Domain.WORK] == "AI/Automated/Work"
        assert DOMAIN_LABEL[Domain.EDUCATION] == "AI/Automated/Education"
        assert DOMAIN_LABEL[Domain.NEWSLETTER] == "AI/Automated/Newsletter"
        assert DOMAIN_LABEL[Domain.MARKETING] == "AI/Automated/Marketing"
        assert DOMAIN_LABEL[Domain.SOCIAL] == "AI/Automated/Social"
        assert DOMAIN_LABEL[Domain.ALERTS] == "AI/Automated/Alerts"
        assert DOMAIN_LABEL[Domain.OTHER] == "AI/Automated/Other"


class TestHumanLabels:
    def test_human_label(self) -> None:
        assert HUMAN_LABEL == "AI/Human"

    def test_followup_label(self) -> None:
        assert HUMAN_FOLLOWUP_LABEL == "AI/Human/FollowUp"


class TestEmailAnalysis:
    def _make(self, **kwargs: object) -> EmailAnalysis:
        defaults: dict[str, object] = dict(
            email_id="msg_1",
            email_type=EmailType.HUMAN,
            domain=None,
        )
        return EmailAnalysis(**{**defaults, **kwargs})  # type: ignore[arg-type]

    def test_required_fields_are_stored(self) -> None:
        a = self._make(email_type=EmailType.AUTOMATED, domain=Domain.FINANCE)
        assert a.email_id == "msg_1"
        assert a.email_type == EmailType.AUTOMATED
        assert a.domain == Domain.FINANCE

    def test_human_email_has_no_domain(self) -> None:
        a = self._make(email_type=EmailType.HUMAN, domain=None)
        assert a.domain is None

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
        assert a.requires_reply is True
        assert a.deadline == "by Friday"

    def test_is_frozen(self) -> None:
        a = self._make()
        with pytest.raises((AttributeError, TypeError)):
            a.email_id = "other"  # type: ignore[misc]
