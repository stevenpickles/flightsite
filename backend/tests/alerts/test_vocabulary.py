"""The severity ladder is one ladder, wherever it is spelled.

Four layers know these four strings and none of them may import another's
spelling without inverting a dependency: the alert domain
(:class:`~flightsite.alerts.vocabulary.AlertSeverity`), the activity feed's
column (:class:`~flightsite.activity.model.Severity`), the sighting
accumulator's ordering
(:data:`~flightsite.sightings.vocabulary.ALERT_SEVERITIES`), and the three SQL
``CHECK`` predicates. This module is what makes that safe — the same answer
``tests/sightings/test_vocabulary.py`` gives for the closure reasons.
"""

from __future__ import annotations

import pytest

from flightsite.activity.model import Severity
from flightsite.alerts.vocabulary import (
    EMERGENCY_BUILTIN_KEYS,
    EMERGENCY_MEANINGS,
    EMERGENCY_SEVERITY,
    AlertSeverity,
    emergency_builtin_key,
)
from flightsite.api.schemas import AlertSeverityLiteral
from flightsite.db.models import (
    ALERT_ROW_SEVERITY_CHECK,
    ALERT_SEVERITY_CHECK,
)
from flightsite.sightings.vocabulary import (
    ALERT_SEVERITIES,
    EMERGENCY_SQUAWKS,
    alert_severity_rank,
    outranks_severity,
)


def test_the_alert_enum_and_the_activity_enum_are_the_same_ladder() -> None:
    assert {member.value for member in AlertSeverity} == {member.value for member in Severity}


def test_the_sightings_ordering_lists_the_same_values_lowest_first() -> None:
    assert tuple(member.value for member in AlertSeverity) == ALERT_SEVERITIES


def test_the_two_orderings_agree_rank_for_rank() -> None:
    """The one property that matters: the accumulator and the engine must not
    disagree about which of two severities is higher."""
    for member in AlertSeverity:
        assert alert_severity_rank(member.value) == member.rank


def test_the_sql_checks_constrain_exactly_the_ladder() -> None:
    for predicate in (ALERT_ROW_SEVERITY_CHECK, ALERT_SEVERITY_CHECK):
        assert all(f"'{member.value}'" in predicate for member in AlertSeverity)
        assert predicate.count("'") == 2 * len(AlertSeverity)


def test_the_published_literal_spells_the_same_four_values() -> None:
    published = set(AlertSeverityLiteral.__args__)  # type: ignore[attr-defined]
    assert published == {member.value for member in AlertSeverity}


def test_the_ladder_is_ordered_info_through_critical() -> None:
    assert [member.value for member in sorted(AlertSeverity, key=lambda s: s.rank)] == [
        "info",
        "interesting",
        "high",
        "critical",
    ]


@pytest.mark.parametrize(
    ("candidate", "current", "expected"),
    [
        (AlertSeverity.INFO, None, True),
        (AlertSeverity.CRITICAL, AlertSeverity.HIGH, True),
        (AlertSeverity.HIGH, AlertSeverity.CRITICAL, False),
        (AlertSeverity.HIGH, AlertSeverity.HIGH, False),
    ],
)
def test_outranks_is_strict_and_treats_none_as_nothing_standing(
    candidate: AlertSeverity, current: AlertSeverity | None, expected: bool
) -> None:
    """A tie is not an upgrade: SPEC §48 allows another notification for a
    *higher*-priority condition, and equal severities must not read as one."""
    assert candidate.outranks(current) is expected
    assert (
        outranks_severity(candidate.value, None if current is None else current.value) is expected
    )


def test_a_string_comparison_would_get_the_order_wrong() -> None:
    """The reason :attr:`AlertSeverity.rank` exists at all: these are a
    ``StrEnum``, so ``max`` over them without a key answers alphabetically."""
    assert max(AlertSeverity.CRITICAL, AlertSeverity.INFO) is AlertSeverity.INFO
    assert AlertSeverity.CRITICAL.outranks(AlertSeverity.INFO)


def test_an_unknown_severity_is_refused_rather_than_ordered() -> None:
    with pytest.raises(ValueError, match="unknown alert severity"):
        alert_severity_rank("urgent")


# ------------------------------------------------------------ emergency squawks


def test_the_emergency_codes_match_the_set_the_sighting_record_already_uses() -> None:
    """Slice 009 records these on the sighting; this slice alerts on them. One
    list, or an aircraft could have ``had_emergency`` with no alert."""
    assert set(EMERGENCY_MEANINGS) == EMERGENCY_SQUAWKS


def test_every_code_gets_its_own_builtin_key() -> None:
    """One key per code, so 7600 then 7700 is two matches — ``docs/DATA_MODEL.md``
    §4.3 names that as the allowed re-notification path."""
    assert EMERGENCY_BUILTIN_KEYS == ("emergency_7500", "emergency_7600", "emergency_7700")
    assert len(set(EMERGENCY_BUILTIN_KEYS)) == len(EMERGENCY_MEANINGS)


def test_the_builtin_key_names_its_code() -> None:
    assert emergency_builtin_key("7700") == "emergency_7700"


def test_emergency_severity_is_critical() -> None:
    """SPEC §46 fixes it, and nothing may lower it."""
    assert EMERGENCY_SEVERITY is AlertSeverity.CRITICAL
