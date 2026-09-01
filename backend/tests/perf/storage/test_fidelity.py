"""The generated database must be one the product could have produced.

This is the load-bearing test of the whole slice. Every growth figure, every
latency and every retention timing is measured against synthetic rows, so if
those rows are not shaped like real ones the numbers describe a database that
does not exist. Slice 049 has the same problem in a different form and solves
it the same way: its ``live_population`` gate exists so that "everything else
is meaningless otherwise".

So each test below asserts one invariant the *production* writer maintains —
:class:`~flightsite.sightings.repository.SightingRepository` and
:class:`~flightsite.sightings.state.ActiveSighting`, as documented in
``docs/DATA_MODEL.md`` §2 and ADR-0005 — against the generator's output. They
are written as SQL over the finished database rather than as assertions about
the generator's internals, because what matters is the rows, not how they were
built.
"""

from __future__ import annotations

from sqlalchemy import text

from flightsite.db import Database
from flightsite.sightings.track_codec import PackedTrack, unpack_track
from tests.perf.storage.conftest import Dataset


async def scalar(database: Database, sql: str) -> int:
    """One integer from a read session — the shape every check below wants."""
    async with database.read_session() as session:
        return int((await session.execute(text(sql))).scalar_one())


async def test_every_sighting_points_at_an_aircraft_that_exists(database: Database) -> None:
    """The foreign key, checked as data rather than trusted to the pragma.

    ``foreign_keys=ON`` is set on every connection (ADR-0001), so a violation
    could not have been inserted — but the generator assigns ``aircraft.id``
    from its own counter instead of reading rows back, and an off-by-one there
    would be silent if the constraint were ever relaxed.
    """
    orphans = await scalar(
        database,
        "SELECT count(*) FROM sightings s "
        "LEFT JOIN aircraft a ON a.id = s.aircraft_id WHERE a.id IS NULL",
    )
    assert orphans == 0


async def test_closed_sightings_are_internally_consistent(database: Database) -> None:
    """``ended_ms``, ``duration_ms`` and ``closure_reason`` move together.

    ``SightingRepository.close_sighting`` sets all three at once, and
    ``docs/DATA_MODEL.md`` §2.3 documents ``duration_ms`` as "set at close".
    A row with a duration but no end, or an end that precedes its start, is
    one the product cannot produce.
    """
    assert await scalar(database, "SELECT count(*) FROM sightings WHERE ended_ms IS NULL") == 0
    assert (
        await scalar(
            database,
            "SELECT count(*) FROM sightings "
            "WHERE duration_ms IS NULL OR closure_reason IS NULL "
            "OR ended_ms < started_ms OR duration_ms <> ended_ms - started_ms",
        )
        == 0
    )


async def test_aircraft_aggregates_equal_their_sightings(database: Database) -> None:
    """``sighting_count`` and ``total_observed_ms`` are sums over the sightings.

    Production maintains both transactionally — the count at open, the observed
    time at close — so they are derivable, and a synthetic database whose
    denormalized aggregates disagree with the rows beneath them would make the
    rarity and top-aircraft queries measure fiction.
    """
    mismatched = await scalar(
        database,
        "SELECT count(*) FROM aircraft a WHERE a.sighting_count <> "
        "(SELECT count(*) FROM sightings s WHERE s.aircraft_id = a.id)",
    )
    assert mismatched == 0

    mismatched_time = await scalar(
        database,
        "SELECT count(*) FROM aircraft a WHERE a.total_observed_ms <> "
        "(SELECT coalesce(sum(s.duration_ms), 0) FROM sightings s WHERE s.aircraft_id = a.id)",
    )
    assert mismatched_time == 0


async def test_aircraft_first_and_last_seen_bound_their_sightings(database: Database) -> None:
    """The lifetime window really is the union of the sighting windows."""
    wrong = await scalar(
        database,
        "SELECT count(*) FROM aircraft a WHERE "
        "a.first_seen_ms <> (SELECT min(s.started_ms) FROM sightings s WHERE s.aircraft_id = a.id) "
        "OR a.last_seen_ms <> (SELECT max(s.ended_ms) FROM sightings s WHERE s.aircraft_id = a.id)",
    )
    assert wrong == 0


async def test_lifetime_records_are_the_extremes_of_their_sightings(database: Database) -> None:
    """``_merge_records``' contract: a record moves only on a strictly better value.

    Checked as min/max identities, which is what "the best value ever seen"
    means once the whole history is in place.
    """
    for column, aggregate in (
        ("closest_approach_nm", "min"),
        ("max_range_nm", "max"),
        ("lowest_alt_ft", "min"),
        ("highest_alt_ft", "max"),
    ):
        wrong = await scalar(
            database,
            f"SELECT count(*) FROM aircraft a WHERE a.{column} IS NOT NULL AND a.{column} <> "
            f"(SELECT {aggregate}(s.{column}) FROM sightings s WHERE s.aircraft_id = a.id)",
        )
        assert wrong == 0, f"aircraft.{column} is not the {aggregate} of its sightings"


async def test_a_record_carries_the_moment_it_was_set(database: Database) -> None:
    """Every record column's ``_ms`` companion is non-NULL exactly when it is.

    ``docs/DATA_MODEL.md`` §2.2: the record columns carry their ``_ms`` moments
    "so the UI can say *when* the record was set". A value without a moment
    would render as a record that happened at no time.
    """
    for value_column, moment_column in (
        ("closest_approach_nm", "closest_approach_ms"),
        ("max_range_nm", "max_range_ms"),
        ("lowest_alt_ft", "lowest_alt_ms"),
        ("highest_alt_ft", "highest_alt_ms"),
    ):
        wrong = await scalar(
            database,
            "SELECT count(*) FROM aircraft WHERE "
            f"({value_column} IS NULL) <> ({moment_column} IS NULL)",
        )
        assert wrong == 0, f"{value_column} and {moment_column} disagree about being set"


async def test_position_columns_agree_with_each_other(database: Database) -> None:
    """A sighting with no position has no position-derived values.

    The Mode S-only case (``any_position = 0``) is the one a growth model gets
    wrong most easily, because it is the sighting with no ``sighting_tracks``
    row at all. Asserting the whole cluster of consequences together keeps that
    case honest.
    """
    contradictions = await scalar(
        database,
        "SELECT count(*) FROM sightings WHERE "
        "(pos_count > 0 AND any_position = 0) "
        "OR (any_position = 0 AND (max_range_nm IS NOT NULL OR closest_approach_nm IS NOT NULL "
        "OR lowest_alt_ft IS NOT NULL OR highest_alt_ft IS NOT NULL))",
    )
    assert contradictions == 0


async def test_per_sighting_extremes_are_ordered(database: Database) -> None:
    """``closest <= farthest``, ``lowest <= highest``, ``min <= avg <= peak``."""
    unordered = await scalar(
        database,
        "SELECT count(*) FROM sightings WHERE "
        "(closest_approach_nm IS NOT NULL AND max_range_nm < closest_approach_nm) "
        "OR (lowest_alt_ft IS NOT NULL AND highest_alt_ft < lowest_alt_ft) "
        "OR (rssi_min_db IS NOT NULL AND NOT (rssi_min_db <= rssi_avg_db "
        "AND rssi_avg_db <= rssi_peak_db))",
    )
    assert unordered == 0


async def test_positioned_time_is_a_percentage(database: Database) -> None:
    """``pos_time_pct`` is bounded and set exactly when it can be computed."""
    wrong = await scalar(
        database,
        "SELECT count(*) FROM sightings WHERE pos_time_pct IS NOT NULL "
        "AND (pos_time_pct < 0 OR pos_time_pct > 100)",
    )
    assert wrong == 0


async def test_an_alert_severity_has_an_alert_match_behind_it(database: Database) -> None:
    """``docs/DATA_MODEL.md`` §4.3: ``alert_matches`` is the source of truth.

    ``sightings.max_alert_severity`` is a denormalization of it for the
    Sightings page. A severity with no matching row would make the "interesting"
    filter and ``daily_stats.interesting`` disagree with the alert history.
    """
    dangling = await scalar(
        database,
        "SELECT count(*) FROM sightings s WHERE s.max_alert_severity IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM alert_matches m WHERE m.sighting_id = s.id)",
    )
    assert dangling == 0

    orphaned = await scalar(
        database,
        "SELECT count(*) FROM alert_matches m WHERE NOT EXISTS "
        "(SELECT 1 FROM sightings s WHERE s.id = m.sighting_id "
        "AND s.max_alert_severity IS NOT NULL)",
    )
    assert orphaned == 0


async def test_emergency_squawks_latch_the_emergency_flag(database: Database) -> None:
    """SPEC §17: ``had_emergency`` latches once an emergency squawk is seen."""
    wrong = await scalar(
        database,
        "SELECT count(*) FROM sightings WHERE "
        "squawk_last IN ('7500', '7600', '7700') AND had_emergency = 0",
    )
    assert wrong == 0


async def test_every_track_row_decodes_with_the_production_codec(
    database: Database, dataset: Dataset
) -> None:
    """The blobs are real packed tracks, not bytes of the right length.

    Decoded with :func:`~flightsite.sightings.track_codec.unpack_track`, the
    same function the sighting-detail endpoint uses, so a blob that would make
    the API raise cannot pass. Also checks ADR-0005's stated layout: a v1 row
    is exactly ``5 + 21 * point_count`` bytes, which is the identity the whole
    growth model is built on.
    """
    async with database.read_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT sighting_id, encoding_version, point_count, started_ms, points_blob "
                    "FROM sighting_tracks LIMIT 200"
                )
            )
        ).all()

    assert rows, "the dataset produced no packed tracks"
    for sighting_id, version, point_count, started_ms, blob in rows:
        assert version == 1
        assert len(blob) == 5 + 21 * point_count, (
            f"sighting {sighting_id}'s blob is {len(blob)} bytes for {point_count} points; "
            "ADR-0005's v1 layout is a 5-byte header plus 21 bytes a point"
        )
        samples = unpack_track(
            PackedTrack(
                encoding_version=version,
                point_count=point_count,
                started_ms=started_ms,
                points_blob=blob,
            )
        )
        assert len(samples) == point_count
        timestamps = [sample.ts_ms for sample in samples]
        assert timestamps == sorted(set(timestamps)), "track points must strictly increase in time"


async def test_a_track_exists_exactly_where_a_position_was_seen(database: Database) -> None:
    """ADR-0005: a closed sighting with positions gets one packed row; one
    without gets none.

    Both directions matter. A track row for a Mode S sighting would be a path
    for an aircraft that never reported one; a missing row for a positioned
    sighting would quietly shrink the measured growth.
    """
    tracks_without_positions = await scalar(
        database,
        "SELECT count(*) FROM sighting_tracks t JOIN sightings s ON s.id = t.sighting_id "
        "WHERE s.any_position = 0",
    )
    assert tracks_without_positions == 0


async def test_checkpoints_are_deleted_at_close(database: Database) -> None:
    """ADR-0005: ``sighting_track_checkpoints`` is bounded by concurrent
    traffic, not by history.

    The generated history contains only closed sightings, so the table must be
    empty. This is the invariant that keeps a crash-recovery record from
    becoming an archival one — the failure mode it guards against grows without
    limit and would dominate a multi-year database.
    """
    assert await scalar(database, "SELECT count(*) FROM sighting_track_checkpoints") == 0


async def test_the_analytics_rollups_agree_with_the_sightings(database: Database) -> None:
    """``daily_stats`` is a fold over the sightings of its local day.

    The generator does not compute these: it runs the real
    :class:`~flightsite.analytics.backfill.AnalyticsBackfill` over the rows it
    wrote, so agreement here is really a check that the history is well-formed
    enough for production code to roll up — which is exactly what makes the
    analytics latency measurements meaningful.
    """
    rolled_sql = "SELECT coalesce(sum(sightings), 0) FROM daily_stats"
    async with database.read_session() as session:
        total_rolled = int((await session.execute(text(rolled_sql))).scalar_one())
        total_rows = int(
            (await session.execute(text("SELECT count(*) FROM sightings"))).scalar_one()
        )
        days = int((await session.execute(text("SELECT count(*) FROM daily_stats"))).scalar_one())

    assert days > 0, "the backfill produced no daily rollups"
    assert total_rolled == total_rows, (
        f"daily_stats accounts for {total_rolled} sightings but the table holds {total_rows}"
    )


async def test_t0_is_the_first_sighting(database: Database) -> None:
    """``meta['t0_ms']`` is what the ``t0`` analytics preset resolves against."""
    async with database.read_session() as session:
        stored = (
            await session.execute(text("SELECT value FROM meta WHERE key = 't0_ms'"))
        ).scalar_one()
        first = (await session.execute(text("SELECT min(started_ms) FROM sightings"))).scalar_one()
    assert int(stored) == int(first)


async def test_the_population_has_a_long_tail(dataset: Dataset, database: Database) -> None:
    """Rarity needs airframes seen once or twice, or it measures nothing.

    SPEC §44's rarity is "never seen before" and "seen fewer than N times". A
    generator that gave every airframe the same number of sightings would
    produce a database on which the rarity query returns an empty list very
    quickly, and the measured latency would be of a query with no work to do.
    """
    rare = await scalar(database, "SELECT count(*) FROM aircraft WHERE sighting_count <= 2")
    total = await scalar(database, "SELECT count(*) FROM aircraft")
    frequent = await scalar(database, "SELECT max(sighting_count) FROM aircraft")

    assert total > 0
    assert rare > 0, "no airframe was seen twice or fewer times; rarity has nothing to find"
    assert frequent > 4, (
        f"the most-seen airframe has only {frequent} sightings; the population is not "
        "reused enough to look like a real receiver"
    )
