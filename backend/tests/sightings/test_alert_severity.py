"""``sightings.max_alert_severity`` through the accumulator (slice 038).

The column is slice 038's, but it lives on *this* slice's row, so it is applied
the way an enriched route is: onto the accumulator from another subsystem's
task, and written by the flush that writes the rest of the row. What that buys
is one transaction per fact and a retry that rewrites both the column and its
event — and what it costs is that the monotonicity and the exactly-once
event emission have to hold in memory, which is what this module checks.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker, SightingEventType
from flightsite.sightings.repository import OpenSightingRow, SightingIds
from flightsite.sightings.state import ActiveSighting

from .conftest import SimulatedTime, observe


def accumulator() -> ActiveSighting:
    return ActiveSighting(icao="ae1463", started_ms=1_000, last_seen_ms=1_000)


def test_a_new_sighting_has_no_alert_severity() -> None:
    """The ordinary case on a stock install: almost every sighting."""
    assert accumulator().max_alert_severity is None


def test_the_first_match_sets_the_severity_and_emits_alert_matched() -> None:
    active = accumulator()

    assert active.apply_alert_severity("info", "Rule: First ever", 2_000) is True

    assert active.max_alert_severity == "info"
    (event,) = active.pending_events
    assert event.type is SightingEventType.ALERT_MATCHED
    assert event.ts_ms == 2_000
    assert event.payload == {"severity": "info", "reason": "Rule: First ever"}


def test_a_higher_severity_raises_it_and_emits_an_upgrade() -> None:
    """SPEC §48's "a newly matched higher-priority condition may notify again",
    recorded on the timeline rather than left for the notification layer to
    re-derive."""
    active = accumulator()
    active.apply_alert_severity("info", "Rule: First ever", 2_000)

    assert active.apply_alert_severity("critical", "Emergency squawk 7700", 3_000) is True

    assert active.max_alert_severity == "critical"
    upgrade = active.pending_events[-1]
    assert upgrade.type is SightingEventType.ALERT_SEVERITY_UPGRADED
    assert upgrade.payload == {
        "from": "info",
        "to": "critical",
        "reason": "Emergency squawk 7700",
    }


@pytest.mark.parametrize("later", ["info", "high"])
def test_an_equal_or_lower_severity_changes_nothing(later: str) -> None:
    """``max_alert_severity`` is a maximum over the sighting: it really did
    reach the higher one, and a tie is not an upgrade."""
    active = accumulator()
    active.apply_alert_severity("high", "Rule: Military", 2_000)
    before = len(active.pending_events)

    assert active.apply_alert_severity(later, "Rule: Something else", 3_000) is False

    assert active.max_alert_severity == "high"
    assert len(active.pending_events) == before


def test_re_applying_the_same_severity_emits_nothing() -> None:
    """Idempotent under a replay, the same way :meth:`apply_route` is."""
    active = accumulator()
    active.apply_alert_severity("high", "Rule: Military", 2_000)

    assert active.apply_alert_severity("high", "Rule: Military", 2_000) is False
    assert len(active.pending_events) == 1


def test_applying_a_severity_marks_the_row_for_the_next_flush() -> None:
    """A user watching a live aircraft expects the sightings list to show it
    alerted, not to show it a flush interval later."""
    active = accumulator()
    active.mark_flushed(1_500)
    assert not active.dirty

    active.apply_alert_severity("high", "Rule: Military", 2_000)

    assert active.dirty
    assert active.flush_immediately


def test_an_unknown_severity_is_refused_rather_than_ordered() -> None:
    with pytest.raises(ValueError, match="unknown alert severity"):
        accumulator().apply_alert_severity("urgent", "Rule: Nonsense", 2_000)


def test_a_rehydrated_sighting_keeps_the_severity_it_already_reached() -> None:
    """A restart mid-sighting must not blank the column on the next flush, and
    must not emit a second ``alert_matched`` for an alert already recorded."""
    row = OpenSightingRow(
        ids=SightingIds(aircraft_id=1, sighting_id=2),
        icao24="ae1463",
        started_ms=1_000,
        last_known_ms=2_000,
        max_alert_severity="high",
    )

    active = row.to_accumulator()

    assert active.max_alert_severity == "high"
    assert active.apply_alert_severity("high", "Rule: Military", 3_000) is False
    assert active.pending_events == []
    assert active.apply_alert_severity("critical", "Emergency squawk 7700", 3_000) is True


async def test_the_worker_writes_the_severity_and_its_event_in_one_cycle(
    database: Database, live: LiveStore, clock: SimulatedTime, worker: PersistenceWorker
) -> None:
    """The apply seam end to end: one column and one timeline row, from one
    transaction."""
    observe(live, clock, "ae1463")
    await worker.process_pending()

    assert worker.apply_alert_severity("ae1463", "high", "Rule: Military", at_ms=2_000) is True
    await worker.process_pending()

    async with database.read_session() as session:
        severity = await session.scalar(text("SELECT max_alert_severity FROM sightings"))
        events = (await session.execute(text("SELECT type FROM sighting_events"))).all()

    assert severity == "high"
    assert [row[0] for row in events] == [SightingEventType.ALERT_MATCHED.value]


async def test_applying_to_an_aircraft_with_no_open_sighting_answers_false(
    worker: PersistenceWorker,
) -> None:
    """The aircraft's closure gap expired between the match and this call —
    an ordinary outcome, not an error."""
    assert worker.apply_alert_severity("000000", "high", "Rule: Military", at_ms=2_000) is False
    assert worker.max_alert_severity_for("000000") is None


async def test_the_worker_reports_the_standing_severity_from_memory(
    live: LiveStore, clock: SimulatedTime, worker: PersistenceWorker
) -> None:
    """Read on the alert engine's cycle, so it must be an in-memory lookup on
    the accumulator rather than a read of the row it is about to write."""
    observe(live, clock, "ae1463")
    await worker.process_pending()
    assert worker.max_alert_severity_for("ae1463") is None

    worker.apply_alert_severity("ae1463", "interesting", "Rule: Rare", at_ms=2_000)

    assert worker.max_alert_severity_for("ae1463") == "interesting"
