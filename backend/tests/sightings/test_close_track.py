"""Sighting close: simplify, pack, delete the checkpoints (ADR-0005).

The roadmap's acceptance criteria for this path, in order:

* "closed sighting stores a simplified, timestamped, ordered, decodable path";
* "packed track for a typical sighting is <= 2 KB; checkpoint rows are removed
  at close".

Each is asserted end to end here — from live observations through the worker's
cycle to the bytes in ``sighting_tracks`` and back out through the decoder the
repository ships with them — because the transactional sequence (pack, insert,
delete) is the part of this slice a unit test of the codec cannot reach.
"""

from __future__ import annotations

from itertools import pairwise

from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker, SightingRepository
from flightsite.sightings.track_codec import ENCODING_VERSION

from .conftest import (
    CLOSE_S,
    REMOVE_S,
    SimulatedTime,
    checkpoints_of,
    fly,
    observe,
    only_sighting,
    packed_track_of,
    straight_leg,
)


async def close_out(worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime) -> None:
    """Let the aircraft leave the live set and its closure gap expire."""
    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()
    clock.advance(CLOSE_S + 1.0)
    await worker.process_pending()


async def test_a_closed_sighting_stores_a_decodable_path(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    fly(live, clock, [(5.0 + index, index * index * 0.05) for index in range(8)])
    await worker.process_pending()

    await close_out(worker, live, clock)

    sighting = await only_sighting(database)
    row = await packed_track_of(database, sighting.id)
    assert row is not None
    assert row.encoding_version == ENCODING_VERSION
    assert row.point_count >= 2

    points = await SightingRepository(database).load_track(sighting.id)
    assert len(points) == row.point_count
    assert points[0].ts_ms == row.started_ms
    assert [point.ts_ms for point in points] == sorted(point.ts_ms for point in points)
    assert all(point.position_source == "adsb" for point in points)


async def test_the_stored_path_spans_the_whole_sighting(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # Simplification may drop the middle of a leg; it may never move the ends,
    # or the sighting's first and last positions would be inventions.
    fly(live, clock, straight_leg(40))
    await worker.process_pending()

    await close_out(worker, live, clock)

    sighting = await only_sighting(database)
    points = await SightingRepository(database).load_track(sighting.id)
    assert points[0].ts_ms == sighting.started_ms
    assert points[-1].ts_ms == sighting.ended_ms


async def test_the_checkpoint_rows_are_gone_after_close(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    """The delete-after-pack step ADR-0005 makes the writer's responsibility.

    Checkpoints are a crash-recovery record; leaving them behind would make the
    table grow with history rather than with concurrent traffic, and would give
    slice 053's recovery a second, stale copy of every closed path.
    """
    fly(live, clock, straight_leg(20))
    await worker.process_pending()
    sighting_id = (await only_sighting(database)).id
    assert await checkpoints_of(database, sighting_id) != []

    await close_out(worker, live, clock)

    assert await checkpoints_of(database, sighting_id) == []
    assert await packed_track_of(database, sighting_id) is not None


async def test_a_typical_sighting_packs_into_under_two_kilobytes(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    """The roadmap's size acceptance criterion, on a realistic transit.

    Twelve minutes of manoeuvring flight at the 5 s sample rate these tests
    use: a curving climb, a level cruise leg and a descending turn — the shape
    DATA_MODEL §2.4 sizes at 40-80 retained points.
    """
    climb = [(5.0 + index * 0.4, index * index * 0.02) for index in range(50)]
    cruise = [(25.0 + index * 0.5, 50.0) for index in range(50)]
    descent = [(50.0 - index * 0.3, 50.0 + index * index * 0.015) for index in range(50)]
    for leg, altitude in ((climb, 12_000.0), (cruise, 34_000.0), (descent, 9_000.0)):
        fly(live, clock, leg, altitude_ft=altitude)
        await worker.process_pending()

    await close_out(worker, live, clock)

    row = await packed_track_of(database, (await only_sighting(database)).id)
    assert row is not None
    assert len(row.points_blob) <= 2_048, f"{row.point_count} points, {len(row.points_blob)} bytes"
    assert row.point_count < 150


async def test_the_stored_path_is_simplified_not_merely_copied(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # A straight cruise leg is two points' worth of information however many
    # times the decoder reported it.
    fly(live, clock, straight_leg(60), altitude_ft=30_000.0)
    await worker.process_pending()

    await close_out(worker, live, clock)

    row = await packed_track_of(database, (await only_sighting(database)).id)
    assert row is not None
    assert row.point_count == 2


async def test_the_in_memory_tail_survives_a_close_with_no_flush_between(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    """Close reads checkpoints *and* whatever the accumulator still holds.

    A sighting that opened and closed without a checkpoint cycle in between has
    its whole path in memory; one interrupted mid-interval has its tail there.
    Both must reach the packed row.
    """
    fly(live, clock, [(5.0 + index, index * index * 0.05) for index in range(4)])

    # No cycle at all until after the aircraft has gone: the open, the
    # checkpoints and the close all land in the same handful of transactions.
    await close_out(worker, live, clock)

    points = await SightingRepository(database).load_track((await only_sighting(database)).id)
    assert len(points) >= 3
    assert await checkpoints_of(database, (await only_sighting(database)).id) == []


async def test_a_sighting_with_no_positions_stores_no_track_row(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # SPEC §20: a Mode S-only aircraft is a first-class sighting with no path.
    # An empty row would assert a track that does not exist.
    observe(live, clock, callsign="N400EX", altitude_ft=6_000.0)
    await worker.process_pending()

    await close_out(worker, live, clock)

    sighting = await only_sighting(database)
    assert sighting.ended_ms is not None
    assert await packed_track_of(database, sighting.id) is None
    assert await SightingRepository(database).load_track(sighting.id) == ()


async def test_the_close_reports_what_the_track_cost(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # The cycle result is what the close log and later diagnostics report.
    fly(live, clock, [(5.0 + index, index * index * 0.05) for index in range(6)])
    await worker.process_pending()

    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()
    clock.advance(CLOSE_S + 1.0)
    result = await worker.process_pending()

    row = await packed_track_of(database, (await only_sighting(database)).id)
    assert row is not None
    assert result.closed == 1
    assert result.track_points == row.point_count


async def test_a_continued_sighting_keeps_one_path_across_the_gap(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    """An aircraft heard again inside the closure gap has one track, not two.

    The sighting is the same row (SPEC §18), so its path has to be the same
    path: the points from before the silence and the points from after it, in
    one packed row, with the gap visible as a gap between timestamps rather
    than smoothed into a straight line.
    """
    fly(live, clock, [(5.0 + index, index * index * 0.05) for index in range(4)])
    await worker.process_pending()

    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()

    clock.advance(CLOSE_S / 2)
    fly(live, clock, [(40.0 + index, 10.0 + index * index * 0.05) for index in range(4)])
    await worker.process_pending()
    await close_out(worker, live, clock)

    sighting = await only_sighting(database)
    points = await SightingRepository(database).load_track(sighting.id)
    gaps = [after.ts_ms - before.ts_ms for before, after in pairwise(points)]
    assert sighting.ended_ms is not None
    assert max(gaps) > CLOSE_S / 2 * 1_000
    assert points[-1].ts_ms == sighting.ended_ms
