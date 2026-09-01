"""Producer exactness: these facts justify these events, and no others.

The roadmap's first acceptance criterion for this slice is *"fixture scenarios
emit exactly the expected events (no duplicates on restart/replay)"*. Half of
that is enforced by the schema and drilled in :mod:`tests.activity.test_service`;
the other half is here, and it is the harder half — a producer that proposes an
event the facts do not support would be recorded exactly once and still be
wrong.

Every assertion is on the *whole* batch rather than on a membership check.
``assert dedupe_keys(batch) == [...]`` fails when a producer emits something
extra, which is the failure a ``in`` assertion cannot see and the one this
criterion is actually about.
"""

from __future__ import annotations

import pytest

from flightsite.activity import (
    MILESTONE_FIRST_MILITARY,
    UNIQUE_AIRCRAFT_THRESHOLDS,
    ActivityBatch,
    ActivityEventType,
    RecordKind,
    Severity,
)
from flightsite.activity.facts import (
    HealthEpisode,
    ImportOutcome,
    LongestSighting,
    MilitaryFirst,
    ReceiverRecords,
    SightingObservation,
)
from flightsite.activity.model import crossed_threshold, dedupe_key
from flightsite.activity.producers import (
    best_closed,
    first_ever_events,
    health_events,
    import_events,
    longest_sighting_event,
    merge,
    military_milestone,
    new_type_events,
    record_events,
)

NOW_MS = 1_780_000_000_000


def keys(batch: ActivityBatch) -> list[str]:
    """Every event the batch proposes, by dedupe key, in order."""
    return [event.dedupe_key for event in batch.events]


def observation(
    sighting_id: int = 1,
    *,
    icao24: str = "ae1463",
    aircraft_id: int = 1,
    started_ms: int = NOW_MS,
    **kwargs: object,
) -> SightingObservation:
    return SightingObservation(
        sighting_id=sighting_id,
        aircraft_id=aircraft_id,
        icao24=icao24,
        started_ms=started_ms,
        **kwargs,  # type: ignore[arg-type]
    )


# --------------------------------------------------------- first-ever aircraft


def test_a_first_ever_sighting_emits_one_event_keyed_on_the_address() -> None:
    batch = first_ever_events([observation(first_ever=True)])

    assert keys(batch) == ["first_ever_aircraft:ae1463"]
    assert batch.milestones == ()
    assert batch.events[0].type is ActivityEventType.FIRST_EVER_AIRCRAFT
    assert batch.events[0].sighting_id == 1


def test_a_repeat_sighting_of_a_known_airframe_emits_nothing() -> None:
    """The producer's own guard, before the dedupe key ever gets involved."""
    assert first_ever_events([observation(first_ever=False)]) == ActivityBatch()


def test_the_same_airframe_examined_twice_yields_one_key() -> None:
    """Two passes over the same fact compute the same string, so one row survives.

    This is the property that makes a catch-up scan safe to re-run: the key is
    derived from the address, not from the moment the producer ran.
    """
    first = first_ever_events([observation(first_ever=True)])
    again = first_ever_events([observation(first_ever=True)])

    assert keys(first) == keys(again)


def test_the_payload_carries_the_whole_airframe_block_including_its_unknowns() -> None:
    """§2.7: unknown is ``null``, present, and the same five keys every time."""
    batch = first_ever_events([observation(first_ever=True, registration="G-ABCD")])

    assert batch.events[0].payload == {
        "icao": "ae1463",
        "registration": "G-ABCD",
        "type_code": None,
        "model": None,
        "operator": None,
    }


# ------------------------------------------------------ unique-aircraft counts


@pytest.mark.parametrize("threshold", UNIQUE_AIRCRAFT_THRESHOLDS)
def test_each_round_number_of_airframes_is_a_milestone(threshold: int) -> None:
    """SPEC §54's 1,000th airframe, and the same idea at the other scales."""
    batch = first_ever_events([observation(first_ever=True, rank=threshold)])

    assert [milestone.key for milestone in batch.milestones] == [f"unique_aircraft_{threshold}"]
    assert keys(batch) == [
        "first_ever_aircraft:ae1463",
        f"milestone:unique_aircraft_{threshold}",
    ]


def test_an_ordinary_rank_is_not_a_milestone() -> None:
    batch = first_ever_events([observation(first_ever=True, rank=999)])

    assert batch.milestones == ()
    assert keys(batch) == ["first_ever_aircraft:ae1463"]


def test_a_repeat_sighting_cannot_reach_a_threshold() -> None:
    """Rank only means anything for an airframe being heard for the first time."""
    assert first_ever_events([observation(rank=1_000)]) == ActivityBatch()


def test_crossed_threshold_names_only_an_exact_round_number() -> None:
    assert crossed_threshold(1_000) == 1_000
    assert crossed_threshold(1_001) is None


# ------------------------------------------------------------------- new types


def test_the_first_example_of_a_type_is_a_milestone_and_a_new_type_event() -> None:
    """§5 lists ``first_type_B52`` as a milestone; §3.9 gives the event its own word.

    So it is both, and the *specific* word wins for the event — a client sees
    ``new_type``, not a generic ``milestone`` it would have to open to read.
    """
    batch = new_type_events([observation(first_of_type=True, type_code="B52")])

    assert [milestone.key for milestone in batch.milestones] == ["first_type_B52"]
    assert keys(batch) == ["new_type:B52"]
    assert batch.events[0].type is ActivityEventType.NEW_TYPE
    assert batch.events[0].payload["milestone_key"] == "first_type_B52"


def test_an_airframe_of_a_type_already_heard_emits_nothing() -> None:
    assert new_type_events([observation(type_code="B738")]) == ActivityBatch()


def test_an_airframe_with_no_resolved_type_cannot_be_a_new_type() -> None:
    """Unknown is unknown, not a bucket (``docs/API.md`` §2.7).

    An airframe nobody has metadata for is genuinely typeless here, and
    announcing "a new type" for it would invent a designator.
    """
    assert new_type_events([observation(first_of_type=True, type_code=None)]) == ActivityBatch()


# --------------------------------------------------------------- first military


def test_the_first_military_airframe_ever_is_a_milestone() -> None:
    batch = military_milestone(
        MilitaryFirst(
            sighting_id=7,
            aircraft_id=3,
            icao24="43c6db",
            started_ms=NOW_MS,
            type_code="A400",
        )
    )

    assert [milestone.key for milestone in batch.milestones] == [MILESTONE_FIRST_MILITARY]
    assert keys(batch) == ["milestone:first_military"]
    assert batch.events[0].ts_ms == NOW_MS
    assert batch.events[0].payload["kind"] == "first_military"


def test_no_military_sighting_means_no_milestone() -> None:
    assert military_milestone(None) == ActivityBatch()


# ------------------------------------------------------------ longest sighting


def test_a_sighting_that_beats_the_record_is_announced_once() -> None:
    previous = LongestSighting(sighting_id=1, duration_ms=600_000, ended_ms=NOW_MS)
    batch = longest_sighting_event(
        previous, [observation(2, duration_ms=900_000, ended_ms=NOW_MS + 1)]
    )

    assert keys(batch) == ["receiver_record:longest_sighting:2"]
    assert batch.events[0].payload == {
        "record": RecordKind.LONGEST_SIGHTING.value,
        "duration_s": 900.0,
        "previous_s": 600.0,
    }
    assert batch.events[0].ts_ms == NOW_MS + 1


def test_a_shorter_sighting_is_not_a_record() -> None:
    previous = LongestSighting(sighting_id=1, duration_ms=900_000, ended_ms=NOW_MS)

    assert longest_sighting_event(previous, [observation(2, duration_ms=60_000)]) == ActivityBatch()


def test_equalling_the_record_does_not_displace_it() -> None:
    """A record should keep naming the first time it was reached."""
    previous = LongestSighting(sighting_id=1, duration_ms=900_000, ended_ms=NOW_MS)
    same = observation(2, duration_ms=900_000, ended_ms=NOW_MS + 1)

    assert longest_sighting_event(previous, [same]) == ActivityBatch()


def test_the_very_first_closed_sighting_seeds_the_record_silently() -> None:
    """On a virgin receiver the first sighting is trivially the longest ever.

    Announcing that would be an event about nothing — so a record with no
    predecessor seeds and stays quiet, and the *second* one onwards is
    measured against it.
    """
    batch = longest_sighting_event(None, [observation(1, duration_ms=900_000, ended_ms=NOW_MS)])

    assert batch == ActivityBatch()


def test_only_the_best_of_several_closes_is_the_record() -> None:
    """Two long sightings closing together held one record between them.

    Announcing the runner-up as well would announce a record that was never
    held — the better one was already in the same batch.
    """
    previous = LongestSighting(sighting_id=1, duration_ms=60_000, ended_ms=NOW_MS)
    batch = longest_sighting_event(
        previous,
        [
            observation(2, duration_ms=120_000, ended_ms=NOW_MS + 1),
            observation(3, duration_ms=900_000, ended_ms=NOW_MS + 2),
        ],
    )

    assert keys(batch) == ["receiver_record:longest_sighting:3"]


def test_best_closed_carries_the_record_forward_and_ignores_open_sightings() -> None:
    """The service's baseline and the producer share one comparison.

    An open sighting has no duration yet; treating its absence as zero — or as
    anything — would let a record be set by a sighting that has not ended.
    """
    previous = LongestSighting(sighting_id=1, duration_ms=600_000, ended_ms=NOW_MS)
    record = best_closed(previous, [observation(2), observation(3, duration_ms=60_000)])

    assert record == previous


# ----------------------------------------------------------- rolling records


def test_a_further_detection_than_ever_before_is_a_range_record() -> None:
    previous = ReceiverRecords(max_range_nm=180.0)
    current = ReceiverRecords(
        max_range_nm=241.5,
        max_range_at_ms=NOW_MS,
        max_range_icao24="ae1463",
        max_range_bearing_deg=93.25,
    )

    batch = record_events(previous, current, now_ms=NOW_MS + 5_000)

    assert keys(batch) == ["range_record:241.500"]
    assert batch.events[0].type is ActivityEventType.RANGE_RECORD
    # Stamped with when the aircraft was out there, not when a pass noticed.
    assert batch.events[0].ts_ms == NOW_MS
    assert batch.events[0].payload["previous_nm"] == 180.0


def test_a_standing_range_record_re_read_announces_nothing() -> None:
    """Every pass reads ``lifetime_stats``; only a change is news."""
    records = ReceiverRecords(max_range_nm=241.5, max_range_at_ms=NOW_MS)

    assert record_events(records, records, now_ms=NOW_MS) == ActivityBatch()


def test_the_first_record_ever_observed_seeds_silently() -> None:
    """An install upgrading into this slice must not narrate its own history."""
    current = ReceiverRecords(max_range_nm=241.5, max_simultaneous=87.0, busiest_day="2026-06-02")

    assert record_events(ReceiverRecords(), current, now_ms=NOW_MS) == ActivityBatch()


def test_a_higher_simultaneous_count_is_a_receiver_record() -> None:
    batch = record_events(
        ReceiverRecords(max_simultaneous=42.0),
        ReceiverRecords(max_simultaneous=87.0),
        now_ms=NOW_MS,
    )

    assert keys(batch) == ["receiver_record:max_simultaneous:87"]
    assert batch.events[0].payload == {
        "record": RecordKind.MAX_SIMULTANEOUS.value,
        "value": 87,
        "previous": 42,
    }


def test_a_busier_day_than_ever_before_names_the_day_and_the_count() -> None:
    batch = record_events(
        ReceiverRecords(busiest_day="2026-05-01", busiest_day_count=90_000.0),
        ReceiverRecords(busiest_day="2026-06-02", busiest_day_count=120_000.0),
        now_ms=NOW_MS,
    )

    assert keys(batch) == ["receiver_record:busiest_day:2026-06-02:120000"]
    assert batch.events[0].payload["previous_day"] == "2026-05-01"


def test_a_busiest_day_recomputed_downwards_is_not_a_record() -> None:
    """A rollup repair that lowers the standing day's total is a correction.

    ``lifetime_stats`` moves the busiest day up *or* down when the day it names
    is rebuilt (:func:`flightsite.receiver_metrics.lifetime.merged_busiest_day`),
    and a correction is not an achievement.
    """
    batch = record_events(
        ReceiverRecords(busiest_day="2026-06-02", busiest_day_count=120_000.0),
        ReceiverRecords(busiest_day="2026-06-02", busiest_day_count=90_000.0),
        now_ms=NOW_MS,
    )

    assert batch == ActivityBatch()


def test_every_record_that_moved_in_one_pass_is_announced() -> None:
    """A pass is not limited to one piece of news."""
    batch = record_events(
        ReceiverRecords(max_range_nm=180.0, max_simultaneous=42.0),
        ReceiverRecords(max_range_nm=241.5, max_range_at_ms=NOW_MS, max_simultaneous=87.0),
        now_ms=NOW_MS,
    )

    assert keys(batch) == ["range_record:241.500", "receiver_record:max_simultaneous:87"]


# ------------------------------------------------------------ decoder health


def test_an_outage_is_high_severity_and_stamped_when_it_began() -> None:
    batch = health_events(
        [
            HealthEpisode(
                offline=True,
                at_ms=NOW_MS,
                previous_duration_ms=3_600_000,
                error="ConnectError",
            )
        ]
    )

    assert keys(batch) == [f"receiver_offline:{NOW_MS}"]
    assert batch.events[0].severity is Severity.HIGH
    assert batch.events[0].ts_ms == NOW_MS
    assert batch.events[0].payload == {"error": "ConnectError", "uptime_s": 3600.0}


def test_a_restore_is_ordinary_news_and_reports_how_long_it_was_gone() -> None:
    """By the time it is read the problem is over, so it is ``info``."""
    batch = health_events([HealthEpisode(offline=False, at_ms=NOW_MS, previous_duration_ms=90_000)])

    assert keys(batch) == [f"receiver_restored:{NOW_MS}"]
    assert batch.events[0].severity is Severity.INFO
    assert batch.events[0].payload == {"outage_s": 90.0}


def test_an_episode_with_no_measured_predecessor_still_reports() -> None:
    batch = health_events([HealthEpisode(offline=False, at_ms=NOW_MS)])

    assert batch.events[0].payload == {}


# ---------------------------------------------------------- metadata updates


def test_each_source_of_a_run_gets_its_own_event() -> None:
    """SPEC §27: the user needs to see *which* sources worked.

    A run in which the registry imported and the airport dataset failed is two
    different pieces of news, so it is two events with two severities.
    """
    batch = import_events(
        [
            ImportOutcome(source="mictronics", ok=True, finished_ms=NOW_MS, rows_imported=430_000),
            ImportOutcome(
                source="airports", ok=False, finished_ms=NOW_MS, error="ConnectError: timed out"
            ),
        ]
    )

    assert keys(batch) == [
        f"metadata_updated:mictronics:{NOW_MS}",
        f"metadata_updated:airports:{NOW_MS}",
    ]
    assert [event.severity for event in batch.events] == [Severity.INFO, Severity.INTERESTING]
    assert batch.events[1].payload["error"] == "ConnectError: timed out"


def test_two_runs_of_the_same_source_are_two_events() -> None:
    """Updating metadata twice is two results, and the key says so."""
    first = import_events([ImportOutcome(source="faa", ok=True, finished_ms=NOW_MS)])
    second = import_events([ImportOutcome(source="faa", ok=True, finished_ms=NOW_MS + 86_400_000)])

    assert keys(first) != keys(second)


# ------------------------------------------------------------------- merging


def test_merge_keeps_order_and_collapses_a_repeated_conclusion() -> None:
    """Two producers can reach the same conclusion in one pass.

    The database would refuse the second insert anyway; collapsing it here
    means the pass reports what it actually wrote rather than what it proposed.
    """
    one = first_ever_events([observation(1, first_ever=True)])
    same_again = first_ever_events([observation(1, first_ever=True)])
    other = new_type_events([observation(1, first_of_type=True, type_code="B52")])

    merged = merge([one, same_again, other])

    assert keys(merged) == ["first_ever_aircraft:ae1463", "new_type:B52"]
    assert [milestone.key for milestone in merged.milestones] == ["first_type_B52"]


def test_merge_collapses_a_milestone_two_producers_both_claim() -> None:
    """A milestone claimed twice in one pass is one claim.

    The primary key would refuse the second insert anyway; collapsing it here
    keeps the pass's own report of what it wrote honest.
    """
    batch = new_type_events([observation(1, first_of_type=True, type_code="B52")])

    merged = merge([batch, batch])

    assert [milestone.key for milestone in merged.milestones] == ["first_type_B52"]


def test_merge_of_nothing_is_nothing() -> None:
    assert merge([ActivityBatch(), ActivityBatch()]) == ActivityBatch()


def test_a_dedupe_key_formats_floats_at_fixed_precision() -> None:
    """A key must depend on the value, not on a repr — and to a stated precision.

    Three decimals of a nautical mile is about two metres. A record beaten by
    less than that computes the same key and is not announced again, which is
    the right answer twice over: two metres is inside the noise of a position
    report, and a feed reporting it would be reporting rounding.
    """
    assert dedupe_key("range_record", 241.5) == "range_record:241.500"
    assert dedupe_key("range_record", 241.5) == dedupe_key("range_record", 241.50)
    assert dedupe_key("range_record", 241.5001) == dedupe_key("range_record", 241.5)
    assert dedupe_key("range_record", 241.502) != dedupe_key("range_record", 241.5)
