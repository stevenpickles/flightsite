"""``flightsite.api.receiver_stats`` — pure helpers and the query layer.

Two kinds of assertion: the pure functions (:func:`ever_ranges`,
:func:`signal_histogram`, :func:`next_local_day`) are checked against
brute-force recomputation and hand-picked fixtures with no database involved;
:class:`ReceiverStatsRepository` is checked against a migrated database
seeded the same way the Sightings/Aircraft page tests seed one
(``tests.api.aircraft_history_fixtures``, ``tests.api.sighting_fixtures``).

Unique-aircraft counting (today/since T0/per-day) is deliberately *not*
covered here — it is read from roadmap slice 031's
:class:`~flightsite.analytics.queries.AnalyticsQueries` (see
``tests/api/test_receiver_stats_api.py`` for the endpoint-level assertions,
and ``tests/analytics/`` for that query layer's own coverage).
"""

from __future__ import annotations

import random
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from flightsite.api.receiver_stats import (
    ReceiverStatsRepository,
    ever_ranges,
    next_local_day,
    signal_histogram,
)
from flightsite.db import Database, database_path
from flightsite.receiver_metrics.model import RangeRecord

from .aircraft_history_fixtures import SeedAircraft, seed_aircraft
from .sighting_fixtures import SeedSighting, seed_sightings

BASE_MS = 1_756_000_000_000
DAY_MS = 86_400_000


# ------------------------------------------------------------------ fixtures


@pytest.fixture
def db_path(isolated_data_dir: Path) -> Path:
    return database_path(isolated_data_dir)


@pytest.fixture
async def database(db_path: Path) -> AsyncIterator[Database]:
    instance = Database(db_path)
    try:
        await instance.upgrade_to("head")
        yield instance
    finally:
        await instance.dispose()


@pytest.fixture
def stats(database: Database) -> ReceiverStatsRepository:
    return ReceiverStatsRepository(database)


def record(nm: float, *, bucket: int, day_offset: int, at_ms: int = 1) -> tuple[str, RangeRecord]:
    """A ``(day, RangeRecord)`` pair, ``day_offset`` days after a fixed origin."""
    day = f"2026-09-{1 + day_offset:02d}"
    return day, RangeRecord(bearing_deg=bucket * 5.0 + 2.5, max_range_nm=nm, at_ms=at_ms)


# --------------------------------------------------------------- ever_ranges


def test_ever_ranges_keeps_the_larger_of_two_days_in_the_same_sector() -> None:
    rows = [record(90.0, bucket=8, day_offset=0), record(180.0, bucket=8, day_offset=1)]

    result = ever_ranges(rows)

    assert result[8].max_range_nm == 180.0


def test_ever_ranges_keeps_the_earlier_day_on_a_tie() -> None:
    """Mirrors :func:`~flightsite.receiver_metrics.model.better_range`: a tie
    keeps ``current``, so processing oldest-first answers "when did the
    receiver first reach this far"."""
    rows = [
        record(180.0, bucket=8, day_offset=0, at_ms=100),
        record(180.0, bucket=8, day_offset=1, at_ms=200),
    ]

    result = ever_ranges(rows)

    assert result[8].at_ms == 100


def test_ever_ranges_is_independent_per_sector() -> None:
    rows = [record(90.0, bucket=8, day_offset=0), record(40.0, bucket=9, day_offset=0)]

    result = ever_ranges(rows)

    assert result[8].max_range_nm == 90.0
    assert result[9].max_range_nm == 40.0


def test_ever_ranges_of_nothing_is_empty() -> None:
    assert ever_ranges([]) == {}


# ---------------------------------------------------------------- histogram


def _brute_force_histogram(values: list[float], bucket_width_db: float) -> list[tuple[float, int]]:
    """Recompute the same histogram by the most naive possible method: for
    each bucket boundary in range, count values that fall in ``[lo, hi)``."""
    import math

    if not values:
        return []
    low = min(values)
    high = max(values)
    start = math.floor(low / bucket_width_db) * bucket_width_db
    count = max(1, math.ceil((high - start) / bucket_width_db))
    counts = [0] * count
    for value in values:
        for index in range(count):
            lo = start + index * bucket_width_db
            hi = start + (index + 1) * bucket_width_db
            if lo <= value < hi or (index == count - 1 and value == hi):
                counts[index] += 1
                break
    return [(start + index * bucket_width_db, counts[index]) for index in range(count)]


@pytest.mark.parametrize("bucket_width_db", [1.0, 3.0, 5.0])
def test_signal_histogram_matches_brute_force_recomputation(bucket_width_db: float) -> None:
    rng = random.Random(42)
    values = [rng.uniform(-35.0, -5.0) for _ in range(200)]

    result = signal_histogram(values, bucket_width_db=bucket_width_db)
    expected = _brute_force_histogram(values, bucket_width_db)

    assert [(bucket.min_db, bucket.count) for bucket in result.buckets] == expected
    assert result.sample_count == len(values)
    assert sum(bucket.count for bucket in result.buckets) == len(values)
    assert result.min_db == min(values)
    assert result.max_db == max(values)
    assert result.avg_db == pytest.approx(sum(values) / len(values))


def test_signal_histogram_of_no_values_is_the_never_data_state() -> None:
    result = signal_histogram([])

    assert result.buckets == ()
    assert result.sample_count == 0
    assert result.min_db is None
    assert result.max_db is None
    assert result.avg_db is None


def test_signal_histogram_of_one_value_is_one_bucket() -> None:
    result = signal_histogram([-14.2], bucket_width_db=3.0)

    assert len(result.buckets) == 1
    assert result.buckets[0].count == 1


def test_signal_histogram_rejects_a_nonpositive_bucket_width() -> None:
    with pytest.raises(ValueError, match="bucket_width_db"):
        signal_histogram([-14.2], bucket_width_db=0.0)


# ------------------------------------------------------------- next_local_day


@pytest.mark.parametrize(
    ("day", "expected"),
    [
        ("2026-01-01", "2026-01-02"),
        ("2026-02-28", "2026-03-01"),  # not a leap year
        ("2024-02-28", "2024-02-29"),  # a leap year
        ("2026-12-31", "2027-01-01"),
    ],
)
def test_next_local_day(day: str, expected: str) -> None:
    assert next_local_day(day) == expected


# ----------------------------------------------------- ReceiverStatsRepository

AIRCRAFT = [
    SeedAircraft(
        icao24="ae1463",
        first_seen_ms=BASE_MS,
        last_seen_ms=BASE_MS,
        sighting_count=5,
        registration="N302DN",
        type_code="B738",
        model="Boeing 737-800",
        operator_name="Delta Air Lines",
    ),
    SeedAircraft(
        icao24="bbb222",
        first_seen_ms=BASE_MS,
        last_seen_ms=BASE_MS,
        sighting_count=12,
        registration="N999UA",
        type_code="B738",
        model="Boeing 737-800",
        operator_name="United Airlines",
    ),
    SeedAircraft(
        icao24="ccc333",
        first_seen_ms=BASE_MS,
        last_seen_ms=BASE_MS,
        sighting_count=1,
    ),
]


async def test_total_sightings_counts_every_sighting_row(
    database: Database, stats: ReceiverStatsRepository
) -> None:
    await seed_sightings(
        database,
        AIRCRAFT[:1],
        [
            SeedSighting(icao24="ae1463", started_ms=BASE_MS, ended_ms=BASE_MS + 60_000),
            SeedSighting(icao24="ae1463", started_ms=BASE_MS + 120_000),
        ],
    )

    assert await stats.total_sightings() == 2


async def test_signal_values_reads_only_non_null_rssi_within_the_window(
    database: Database, stats: ReceiverStatsRepository
) -> None:
    await seed_sightings(
        database,
        AIRCRAFT[:1],
        [
            SeedSighting(icao24="ae1463", started_ms=BASE_MS, rssi_avg_db=-14.0),
            SeedSighting(icao24="ae1463", started_ms=BASE_MS + DAY_MS, rssi_avg_db=-20.0),
            SeedSighting(icao24="ae1463", started_ms=BASE_MS + 2 * DAY_MS, rssi_avg_db=None),
        ],
    )

    unbounded = await stats.signal_values(from_ms=None, to_ms=None)
    assert sorted(unbounded) == [-20.0, -14.0]

    windowed = await stats.signal_values(from_ms=BASE_MS, to_ms=BASE_MS)
    assert windowed == (-14.0,)


async def test_most_frequent_aircraft_is_ranked_by_sighting_count(
    database: Database, stats: ReceiverStatsRepository
) -> None:
    await seed_aircraft(database, AIRCRAFT)

    result = await stats.most_frequent_aircraft()

    assert result is not None
    assert result.icao24 == "bbb222"
    assert result.registration == "N999UA"
    assert result.sighting_count == 12


async def test_most_frequent_aircraft_of_an_empty_install_is_none(
    stats: ReceiverStatsRepository,
) -> None:
    assert await stats.most_frequent_aircraft() is None


async def test_common_type_is_restricted_to_aircraft_this_receiver_has_sighted(
    database: Database, stats: ReceiverStatsRepository
) -> None:
    """A type in the imported metadata registry that this receiver has never
    sighted must not win "most common type" — SPEC §63 is a lifetime
    statistic about *this receiver*, not about the whole metadata database."""
    await seed_aircraft(
        database,
        AIRCRAFT
        + [
            # Never sighted by this receiver (no `aircraft` row), but with an
            # extremely common type in the metadata registry.
            SeedAircraft(
                icao24=f"never{index:03x}",
                first_seen_ms=BASE_MS,
                last_seen_ms=BASE_MS,
                type_code="A320",
            )
            for index in range(50)
        ],
    )
    # The 50 "never sighted" rows above still went through `seed_aircraft`,
    # which always writes an `aircraft` row too — delete those 50 so the
    # metadata-only population this test needs actually exists.
    from sqlalchemy import delete

    from flightsite.db.models import Aircraft

    async with database.writer_session() as session:
        await session.execute(delete(Aircraft).where(Aircraft.icao24.like("never%")))

    result = await stats.common_type()

    assert result is not None
    assert result.value == "B738"
    assert result.aircraft_count == 2


async def test_common_model_and_operator(
    database: Database, stats: ReceiverStatsRepository
) -> None:
    await seed_aircraft(database, AIRCRAFT)

    model = await stats.common_model()
    operator = await stats.common_operator()

    assert model is not None
    assert model.value == "Boeing 737-800"
    assert model.aircraft_count == 2
    assert operator is not None
    assert operator.value in {"Delta Air Lines", "United Airlines"}
    assert operator.aircraft_count == 1


async def test_common_type_of_an_empty_install_is_none(stats: ReceiverStatsRepository) -> None:
    assert await stats.common_type() is None
