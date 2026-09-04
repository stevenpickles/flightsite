"""``alert_triggered`` / ``emergency_squawk`` events (slice 038, SPEC §55).

The producer is pure, so what it justifies is checked as arithmetic — the same
bargain :mod:`tests.activity.test_producers` makes for the rest of the feed.
Two properties carry the module: the two event types are genuinely distinct
(SPEC §47 wants an emergency prominent rather than one row among the alerts),
and the dedupe key names the *match* rather than the moment, which is what
makes the feed inherit SPEC §48's once-per-sighting-per-rule guarantee instead
of restating it.
"""

from __future__ import annotations

import pytest

from flightsite.activity.facts import AlertMatchFact
from flightsite.activity.model import ActivityEventType, Severity
from flightsite.activity.producers import alert_events, merge

RULE_MATCH = AlertMatchFact(
    match_id=1,
    matched_ms=1_756_600_000_000,
    severity="high",
    reason="Rule: Military aircraft",
    aircraft_id=7,
    sighting_id=11,
    icao24="ae1463",
    rule_id=3,
    rule_name="Military aircraft",
    callsign="RCH492",
    registration="05-8153",
    type_code="C17",
    model="Boeing C-17A Globemaster III",
    operator="United States Air Force",
    distance_nm=18.4,
    altitude_ft=24_975.0,
    military=True,
)

EMERGENCY_MATCH = AlertMatchFact(
    match_id=2,
    matched_ms=1_756_600_001_000,
    severity="critical",
    reason="Emergency squawk 7700 (general emergency)",
    aircraft_id=7,
    sighting_id=11,
    icao24="ae1463",
    builtin_key="emergency_7700",
    squawk="7700",
)


def test_a_rule_match_becomes_an_alert_triggered_event() -> None:
    (event,) = alert_events([RULE_MATCH]).events

    assert event.type is ActivityEventType.ALERT_TRIGGERED
    assert event.severity is Severity.HIGH
    assert event.ts_ms == RULE_MATCH.matched_ms
    assert event.aircraft_id == 7
    assert event.sighting_id == 11


def test_a_builtin_match_becomes_an_emergency_squawk_event() -> None:
    """SPEC §55 lists the two separately, and a feed filtered to
    ``emergency_squawk`` is a question a user genuinely asks."""
    (event,) = alert_events([EMERGENCY_MATCH]).events

    assert event.type is ActivityEventType.EMERGENCY_SQUAWK
    assert event.severity is Severity.CRITICAL


def test_the_event_carries_the_severity_the_match_actually_fired_at() -> None:
    """Flattening these to a fixed severity would throw away the only field the
    feed and slice 040's notifications sort on."""
    events = alert_events([RULE_MATCH, EMERGENCY_MATCH]).events

    assert [event.severity for event in events] == [Severity.HIGH, Severity.CRITICAL]


def test_a_rule_events_payload_carries_everything_a_notification_needs() -> None:
    """SPEC §48: callsign/tail, type, classification, altitude, distance, reason."""
    (event,) = alert_events([RULE_MATCH]).events

    assert event.payload == {
        "match_id": 1,
        "icao": "ae1463",
        "callsign": "RCH492",
        "registration": "05-8153",
        "type_code": "C17",
        "model": "Boeing C-17A Globemaster III",
        "operator": "United States Air Force",
        "reason": "Rule: Military aircraft",
        "severity": "high",
        "distance_nm": 18.4,
        "altitude_ft": 24_975.0,
        "military": True,
        "government": False,
        "law_enforcement": False,
        "rule_id": 3,
        "rule_name": "Military aircraft",
    }


def test_an_emergency_events_payload_names_the_code_rather_than_a_rule() -> None:
    (event,) = alert_events([EMERGENCY_MATCH]).events

    assert event.payload["squawk"] == "7700"
    assert event.payload["builtin_key"] == "emergency_7700"
    assert "rule_id" not in event.payload


def test_both_event_types_name_the_alert_match_row_they_are_about() -> None:
    """Issue #104: a client holding a live event has to be able to name the
    match, or it cannot report that it showed a notification for it. Carried on
    both types, because both become notifications."""
    events = alert_events([RULE_MATCH, EMERGENCY_MATCH]).events

    assert [event.payload["match_id"] for event in events] == [1, 2]


@pytest.mark.parametrize(
    ("fact", "expected"),
    [
        (RULE_MATCH, "alert_triggered:3:11"),
        (EMERGENCY_MATCH, "emergency_squawk:emergency_7700:11"),
    ],
)
def test_the_dedupe_key_names_the_match_not_the_moment(fact: AlertMatchFact, expected: str) -> None:
    """Derived from stored state, so re-examining the same match recomputes the
    same string and the ``UNIQUE`` index refuses the second insert."""
    (event,) = alert_events([fact]).events

    assert event.dedupe_key == expected


def test_two_matches_on_one_sighting_get_different_keys() -> None:
    """A second rule, or a second emergency code, is a different event — which
    is SPEC §48's documented exception inherited rather than restated."""
    events = alert_events([RULE_MATCH, EMERGENCY_MATCH]).events

    assert len({event.dedupe_key for event in events}) == 2


def test_the_same_match_twice_collapses_in_a_merged_batch() -> None:
    """Two producers reaching the same conclusion in one pass is legitimate;
    the batch reports what it actually wrote."""
    merged = merge([alert_events([RULE_MATCH]), alert_events([RULE_MATCH])])

    assert len(merged.events) == 1


def test_no_matches_produce_no_events() -> None:
    assert alert_events([]).empty


def test_alert_events_claim_no_milestones() -> None:
    """An alert is a recurring fact about a sighting, not an achievement that
    can happen only once for this receiver (``docs/DATA_MODEL.md`` §5)."""
    assert alert_events([RULE_MATCH, EMERGENCY_MATCH]).milestones == ()
