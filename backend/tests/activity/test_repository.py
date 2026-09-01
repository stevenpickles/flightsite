"""The SQL half: the facts a pass reads, and the rows it writes.

Split from :mod:`tests.activity.test_producers` along the same seam the code
is: everything here needs a database and none of it needs a judgement about
what an event means.

The write tests are the storage half of the roadmap's *"no duplicates on
restart/replay"* criterion — asserting not just that a repeat insert leaves one
row, but that :meth:`ActivityRepository.record` *reports* it as nothing new, so
the WebSocket stays as quiet as the table does.
"""

from __future__ import annotations

from sqlalchemy import text

from flightsite.activity import (
    ActivityBatch,
    ActivityEventType,
    ActivityRepository,
    NewActivityEvent,
    NewMilestone,
    Severity,
)
from flightsite.db import Database
from flightsite.receiver_metrics.model import (
    LIFETIME_BUSIEST_DAY,
    LIFETIME_BUSIEST_DAY_COUNT,
    LIFETIME_MAX_RANGE_AT_MS,
    LIFETIME_MAX_RANGE_BEARING,
    LIFETIME_MAX_RANGE_ICAO24,
    LIFETIME_MAX_RANGE_NM,
    LIFETIME_MAX_SIMULTANEOUS,
)

from .conftest import BASE_MS, MS_PER_MINUTE, airframe, seed, set_lifetime, sighting

MS_PER_HOUR = 60 * MS_PER_MINUTE


def event(
    dedupe: str,
    *,
    ts_ms: int = BASE_MS,
    kind: ActivityEventType = ActivityEventType.MILESTONE,
    **kwargs: object,
) -> NewActivityEvent:
    return NewActivityEvent(
        type=kind,
        ts_ms=ts_ms,
        dedupe_key=dedupe,
        **kwargs,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------- the writes


async def test_recording_a_batch_returns_the_rows_it_created(
    repository: ActivityRepository,
) -> None:
    created = await repository.record(
        ActivityBatch(events=(event("a"), event("b", ts_ms=BASE_MS + 1)))
    )

    assert [row.id for row in created] == [1, 2]
    assert [row.type for row in created] == ["milestone", "milestone"]


async def test_recording_the_same_batch_twice_creates_and_reports_nothing_new(
    repository: ActivityRepository,
) -> None:
    """A restart re-derives; the database and the return value both say "old news".

    Returning the created rows rather than the proposed ones is what lets the
    WebSocket inherit the table's exactly-once guarantee instead of needing one
    of its own.
    """
    batch = ActivityBatch(events=(event("a"),))

    first = await repository.record(batch)
    second = await repository.record(batch)

    assert len(first) == 1
    assert second == ()
    assert len(await repository.list_events(limit=10)) == 1


async def test_a_milestone_is_claimed_once_and_the_first_claim_wins(
    repository: ActivityRepository,
) -> None:
    """SPEC §54's fire-once, and the moment it names is the moment it happened."""
    await repository.record(
        ActivityBatch(milestones=(NewMilestone(key="first_military", achieved_ms=BASE_MS),))
    )
    await repository.record(
        ActivityBatch(
            milestones=(NewMilestone(key="first_military", achieved_ms=BASE_MS + MS_PER_HOUR),)
        )
    )

    assert await repository.milestone_keys() == frozenset({"first_military"})


async def test_an_empty_batch_opens_no_transaction(repository: ActivityRepository) -> None:
    """An idle receiver's pass must cost nothing — this is most of them."""
    assert await repository.record(ActivityBatch()) == ()


async def test_a_batch_of_only_repeats_returns_nothing(repository: ActivityRepository) -> None:
    await repository.record(ActivityBatch(events=(event("a"),)))

    assert await repository.record(ActivityBatch(events=(event("a"), event("a")))) == ()


async def test_a_recorded_event_carries_the_airframe_address_from_the_aircraft_row(
    database: Database, repository: ActivityRepository
) -> None:
    """The feed and the aircraft page must never name different addresses.

    The payload happens to carry an ``icao`` too, but the *event's* address is
    read back from ``aircraft`` through the foreign key, so the link a feed row
    opens is the row it opens.
    """
    ids = await seed(database, [airframe("ae1463")], [sighting("ae1463")])

    created = await repository.record(
        ActivityBatch(
            events=(
                event(
                    "first",
                    kind=ActivityEventType.FIRST_EVER_AIRCRAFT,
                    aircraft_id=1,
                    sighting_id=ids[0],
                    payload={"icao": "ae1463"},
                ),
            )
        )
    )

    assert created[0].icao24 == "ae1463"
    assert created[0].sighting_id == ids[0]


async def test_a_receiver_wide_event_names_no_aircraft(repository: ActivityRepository) -> None:
    """A decoder outage is about no airframe at all, and says so with nulls."""
    created = await repository.record(
        ActivityBatch(
            events=(event("down", kind=ActivityEventType.RECEIVER_OFFLINE, severity=Severity.HIGH),)
        )
    )

    assert created[0].icao24 is None
    assert created[0].aircraft_id is None
    assert created[0].sighting_id is None
    assert created[0].severity == "high"


async def test_an_empty_payload_round_trips_as_an_empty_mapping(
    repository: ActivityRepository,
) -> None:
    """Stored as ``NULL``, read back as ``{}`` — one shape for a client."""
    created = await repository.record(ActivityBatch(events=(event("a"),)))

    assert created[0].payload == {}


async def test_a_payload_round_trips_exactly(repository: ActivityRepository) -> None:
    payload = {"range_nm": 241.5, "icao": "ae1463", "previous_nm": None}

    created = await repository.record(ActivityBatch(events=(event("a", payload=payload),)))

    assert created[0].payload == payload


async def test_an_unreadable_payload_does_not_hide_the_event(
    database: Database, repository: ActivityRepository
) -> None:
    """A payload is presentation; the event is history.

    Dropping a row whose JSON cannot be parsed would hide something that
    happened in order to protect a rendering nicety.
    """
    await repository.record(ActivityBatch(events=(event("a"),)))
    async with database.writer_session() as session:
        await session.execute(text("UPDATE activity_events SET payload_json = 'not json'"))

    rows = await repository.list_events(limit=10)

    assert len(rows) == 1
    assert rows[0].payload == {}


# ---------------------------------------------------------------- the facts


async def test_a_watermark_scan_walks_forward_by_id(
    database: Database, repository: ActivityRepository
) -> None:
    """ "What has happened since I last looked" is a primary-key seek."""
    ids = await seed(
        database,
        [airframe("ae1463"), airframe("a9c2f0")],
        [sighting("ae1463"), sighting("a9c2f0")],
    )

    assert await repository.sighting_ids_after(0, limit=10) == tuple(ids)
    assert await repository.sighting_ids_after(ids[0], limit=10) == (ids[1],)
    assert await repository.sighting_ids_after(ids[-1], limit=10) == ()


async def test_the_scan_is_bounded_so_a_long_catch_up_arrives_in_pieces(
    database: Database, repository: ActivityRepository
) -> None:
    """A service stopped for a week must not come back to one huge transaction."""
    await seed(
        database,
        [airframe(f"aa00{index:02d}") for index in range(5)],
        [sighting(f"aa00{index:02d}") for index in range(5)],
    )

    assert len(await repository.sighting_ids_after(0, limit=2)) == 2


async def test_the_maximum_sighting_id_is_zero_on_a_database_with_no_history(
    repository: ActivityRepository,
) -> None:
    """The first-boot watermark: an install with nothing to catch up on."""
    assert await repository.max_sighting_id() == 0


async def test_an_airframes_first_sighting_is_flagged_and_its_later_ones_are_not(
    database: Database, repository: ActivityRepository
) -> None:
    ids = await seed(
        database,
        [airframe("ae1463")],
        [sighting("ae1463"), sighting("ae1463", started_ms=BASE_MS + MS_PER_HOUR)],
    )

    observations = await repository.observations(ids)

    assert [row.first_ever for row in observations] == [True, False]


async def test_rank_counts_every_airframe_ever_heard_up_to_this_one(
    database: Database, repository: ActivityRepository
) -> None:
    """Ranked by ``aircraft.id`` — the row is created when the airframe is first heard.

    A surrogate key cannot drift the way a ``first_seen_ms`` corrected by a
    later import could, and it is dense in first-heard order by construction.
    """
    icaos = ["ae1463", "a9c2f0", "43c6db"]
    ids = await seed(
        database,
        [airframe(icao, first_seen_ms=BASE_MS + index) for index, icao in enumerate(icaos)],
        [sighting(icao, started_ms=BASE_MS + index) for index, icao in enumerate(icaos)],
    )

    observations = await repository.observations(ids)

    assert [row.rank for row in observations] == [1, 2, 3]


async def test_only_the_earliest_heard_airframe_of_a_type_is_the_first_of_that_type(
    database: Database, repository: ActivityRepository
) -> None:
    ids = await seed(
        database,
        [
            airframe("ae1463", first_seen_ms=BASE_MS, type_code="B52"),
            airframe("a9c2f0", first_seen_ms=BASE_MS + MS_PER_HOUR, type_code="B52"),
        ],
        [sighting("ae1463"), sighting("a9c2f0", started_ms=BASE_MS + MS_PER_HOUR)],
    )

    observations = await repository.observations(ids)

    assert [row.first_of_type for row in observations] == [True, False]


async def test_an_airframe_with_no_resolved_metadata_reads_as_unknown_not_as_missing(
    database: Database, repository: ActivityRepository
) -> None:
    """The LEFT JOINs are load-bearing: an unresolved airframe still has sightings."""
    ids = await seed(database, [airframe("ae1463")], [sighting("ae1463")])

    (observed,) = await repository.observations(ids)

    assert observed.type_code is None
    assert observed.registration is None
    assert observed.military is False
    assert observed.first_ever is True


async def test_an_observation_carries_the_close_only_once_the_sighting_has_ended(
    database: Database, repository: ActivityRepository
) -> None:
    ids = await seed(
        database,
        [airframe("ae1463"), airframe("a9c2f0")],
        [sighting("ae1463"), sighting("a9c2f0", duration_ms=900_000)],
    )

    observations = await repository.observations(ids)

    assert observations[0].duration_ms is None
    assert observations[1].duration_ms == 900_000
    assert observations[1].ended_ms == BASE_MS + 900_000


async def test_asking_about_no_sightings_asks_the_database_nothing(
    repository: ActivityRepository,
) -> None:
    assert await repository.observations([]) == ()


async def test_asking_about_sightings_that_do_not_exist_answers_nothing(
    repository: ActivityRepository,
) -> None:
    """A close reported for a row a data reset removed is an ordinary outcome."""
    assert await repository.observations([41, 42]) == ()


async def test_a_batch_of_only_repeat_sightings_needs_no_ranks(
    database: Database, repository: ActivityRepository
) -> None:
    """Rank is only asked for airframes being heard for the first time.

    An hour of a busy sky is almost entirely airframes already known, so the
    common case must not pay for a count over ``aircraft`` per row.
    """
    ids = await seed(
        database,
        [airframe("ae1463")],
        [sighting("ae1463"), sighting("ae1463", started_ms=BASE_MS + MS_PER_HOUR)],
    )

    observations = await repository.observations(ids[1:])

    assert [row.rank for row in observations] == [None]


async def test_the_first_military_sighting_is_the_earliest_one_ever_not_the_latest(
    database: Database, repository: ActivityRepository
) -> None:
    """Classification lands with a metadata import, hours or days after the sighting.

    The first military aircraft a receiver ever heard is therefore very often
    one it heard before it could tell — so the milestone is attributed by a
    query over history, not by whichever pass happened to notice.
    """
    await seed(
        database,
        [
            airframe("43c6db", first_seen_ms=BASE_MS, military=True, type_code="A400"),
            airframe("43c6dc", first_seen_ms=BASE_MS + MS_PER_HOUR, military=True),
        ],
        [
            sighting("43c6dc", started_ms=BASE_MS + MS_PER_HOUR),
            sighting("43c6db", started_ms=BASE_MS),
        ],
    )

    first = await repository.military_first()

    assert first is not None
    assert first.icao24 == "43c6db"
    assert first.started_ms == BASE_MS
    assert first.type_code == "A400"


async def test_a_receiver_that_has_never_heard_a_military_aircraft_has_no_first(
    database: Database, repository: ActivityRepository
) -> None:
    await seed(database, [airframe("ae1463")], [sighting("ae1463")])

    assert await repository.military_first() is None


async def test_the_rolling_records_are_read_from_lifetime_stats(
    database: Database, repository: ActivityRepository
) -> None:
    """Slice 033 owns these values; this slice only watches them change.

    Reading them rather than recomputing them is what makes a record
    announcement agree with the Receiver page by construction.
    """
    await set_lifetime(
        database,
        {
            LIFETIME_MAX_RANGE_NM: 241.5,
            LIFETIME_MAX_RANGE_AT_MS: float(BASE_MS),
            LIFETIME_MAX_RANGE_ICAO24: "ae1463",
            LIFETIME_MAX_RANGE_BEARING: 93.25,
            LIFETIME_BUSIEST_DAY: "2026-06-02",
            LIFETIME_BUSIEST_DAY_COUNT: 120_000.0,
            LIFETIME_MAX_SIMULTANEOUS: 87.0,
        },
    )

    records = await repository.receiver_records()

    assert records.max_range_nm == 241.5
    assert records.max_range_at_ms == BASE_MS
    assert records.max_range_icao24 == "ae1463"
    assert records.max_range_bearing_deg == 93.25
    assert records.busiest_day == "2026-06-02"
    assert records.busiest_day_count == 120_000.0
    assert records.max_simultaneous == 87.0


async def test_an_install_with_no_receiver_metrics_has_no_records(
    repository: ActivityRepository,
) -> None:
    """A first run has an empty ``lifetime_stats``, and that is not an error."""
    records = await repository.receiver_records()

    assert records.max_range_nm is None
    assert records.busiest_day is None


async def test_the_longest_sighting_seed_is_the_longest_closed_one(
    database: Database, repository: ActivityRepository
) -> None:
    ids = await seed(
        database,
        [airframe("ae1463"), airframe("a9c2f0"), airframe("43c6db")],
        [
            sighting("ae1463", duration_ms=600_000),
            sighting("a9c2f0", duration_ms=1_800_000),
            # Open: no duration yet, so not a candidate.
            sighting("43c6db"),
        ],
    )

    longest = await repository.longest_sighting()

    assert longest is not None
    assert longest.sighting_id == ids[1]
    assert longest.duration_ms == 1_800_000


async def test_a_receiver_with_no_closed_sighting_has_no_longest(
    database: Database, repository: ActivityRepository
) -> None:
    await seed(database, [airframe("ae1463")], [sighting("ae1463")])

    assert await repository.longest_sighting() is None


# ----------------------------------------------------------------- the feed


async def test_the_feed_is_newest_first_with_the_id_as_tie_break(
    repository: ActivityRepository,
) -> None:
    """A burst written by one pass shares a moment; paging must still be stable."""
    await repository.record(
        ActivityBatch(
            events=(
                event("a", ts_ms=BASE_MS),
                event("b", ts_ms=BASE_MS),
                event("c", ts_ms=BASE_MS + 1),
            )
        )
    )

    rows = await repository.list_events(limit=10)

    assert [row.id for row in rows] == [3, 2, 1]


async def test_the_feed_pages_without_repeating_or_skipping(
    repository: ActivityRepository,
) -> None:
    await repository.record(
        ActivityBatch(events=tuple(event(str(index), ts_ms=BASE_MS) for index in range(5)))
    )

    first = await repository.list_events(limit=2, offset=0)
    second = await repository.list_events(limit=2, offset=2)
    third = await repository.list_events(limit=2, offset=4)

    assert [row.id for row in first] == [5, 4]
    assert [row.id for row in second] == [3, 2]
    assert [row.id for row in third] == [1]


async def test_the_feed_filters_by_type(repository: ActivityRepository) -> None:
    await repository.record(
        ActivityBatch(
            events=(
                event("a", kind=ActivityEventType.FIRST_EVER_AIRCRAFT),
                event("b", kind=ActivityEventType.NEW_TYPE),
                event("c", kind=ActivityEventType.MILESTONE),
            )
        )
    )

    rows = await repository.list_events(limit=10, types=["new_type", "milestone"])

    assert {row.type for row in rows} == {"new_type", "milestone"}


async def test_the_feed_filters_by_an_inclusive_time_window(
    repository: ActivityRepository,
) -> None:
    await repository.record(
        ActivityBatch(
            events=(
                event("a", ts_ms=BASE_MS),
                event("b", ts_ms=BASE_MS + MS_PER_HOUR),
                event("c", ts_ms=BASE_MS + 2 * MS_PER_HOUR),
            )
        )
    )

    rows = await repository.list_events(limit=10, from_ms=BASE_MS, to_ms=BASE_MS + MS_PER_HOUR)

    assert [row.ts_ms for row in rows] == [BASE_MS + MS_PER_HOUR, BASE_MS]


async def test_an_empty_feed_is_an_empty_page_not_an_error(
    repository: ActivityRepository,
) -> None:
    assert await repository.list_events(limit=10) == ()
