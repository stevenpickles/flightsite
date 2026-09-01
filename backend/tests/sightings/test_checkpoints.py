"""Track checkpointing while a sighting is open (ADR-0005).

What these tests hold: the worker writes the *new* points of every open
sighting on its flush cycle and no others, the high-water mark advances only on
a committed transaction, the batches are thinned but never lose their tail, and
the ``seq`` numbering stays dense and monotonic across cycles and across a
restart. The bound this buys — "a power cut loses at most one checkpoint
interval" — is exactly the invariant a wrong high-water mark would break
silently.

Everything runs on the simulated clock of ``conftest.py``, driving one worker
cycle per simulated instant.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from flightsite.db import Database, SightingTrackCheckpoint
from flightsite.db.clock import to_epoch_ms
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker
from flightsite.sightings.vocabulary import PositionSourceCode

from .conftest import (
    FLUSH_INTERVAL_S,
    REMOVE_S,
    FailingOnceDatabase,
    SimulatedTime,
    checkpoints_of,
    fly,
    observe,
    only_sighting,
    straight_leg,
    worker_on,
)


async def sighting_id_of(database: Database) -> int:
    return (await only_sighting(database)).id


def rows_of(rows: Sequence[SightingTrackCheckpoint]) -> list[tuple[int, int, float]]:
    """Checkpoint rows as comparable values.

    ORM instances read through two different sessions are two objects, so the
    comparison has to be over what the rows say rather than over identity.
    """
    return [(row.seq, row.ts_ms, row.lat) for row in rows]


async def test_a_flush_cycle_checkpoints_the_points_seen_so_far(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # A curved climb, so thinning has no straight run to collapse and every
    # observed point is worth keeping.
    fly(live, clock, [(5.0 + index, index * index * 0.05) for index in range(6)])

    await worker.process_pending()

    rows = await checkpoints_of(database, await sighting_id_of(database))
    assert [row.seq for row in rows] == [0, 1, 2, 3, 4, 5]
    assert [row.ts_ms for row in rows] == sorted(row.ts_ms for row in rows)


async def test_checkpoint_rows_carry_the_whole_point(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # Every field playback will need (DATA_MODEL §11), including the integer
    # position-source code the hot table uses instead of the text enum.
    fly(
        live,
        clock,
        [(5.0, 0.0)],
        altitude_ft=12_500.0,
        ground_speed_kt=310.0,
        track_deg=42.5,
        position_source="mlat",
    )

    await worker.process_pending()

    (row,) = await checkpoints_of(database, await sighting_id_of(database))
    assert row.alt_ft == 12_500
    assert row.gs_kt == 310.0
    assert row.track_deg == 42.5
    assert row.pos_source == PositionSourceCode.MLAT


async def test_a_later_cycle_writes_only_the_new_points(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    """The high-water mark, which is what bounds the checkpoint table's size.

    Re-writing the whole track every cycle would still be correct and would
    still recover a power cut; it would also turn a thirty-second cadence into
    quadratic write amplification over an hour-long sighting.
    """
    fly(live, clock, [(5.0 + index, index * index * 0.05) for index in range(4)])
    await worker.process_pending()
    sighting_id = await sighting_id_of(database)
    first = await checkpoints_of(database, sighting_id)

    clock.advance(FLUSH_INTERVAL_S)
    fly(live, clock, [(20.0 + index, 5.0 + index * index * 0.05) for index in range(3)])
    await worker.process_pending()

    rows = await checkpoints_of(database, sighting_id)
    assert len(rows) == len(first) + 3
    assert [row.seq for row in rows] == list(range(len(rows)))
    assert [row.ts_ms for row in rows[: len(first)]] == [row.ts_ms for row in first]
    assert min(row.ts_ms for row in rows[len(first) :]) > max(row.ts_ms for row in first)


async def test_a_cycle_with_no_new_points_writes_no_checkpoints(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    fly(live, clock, straight_leg(3))
    await worker.process_pending()
    sighting_id = await sighting_id_of(database)
    before = await checkpoints_of(database, sighting_id)

    clock.advance(FLUSH_INTERVAL_S)
    observe(live, clock, callsign="ASA123")  # heard, but with no position
    result = await worker.process_pending()

    assert result.checkpointed == 0
    assert rows_of(await checkpoints_of(database, sighting_id)) == rows_of(before)


async def test_a_non_positioned_aircraft_checkpoints_nothing(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # Mode S-only trackfiles are first-class (SPEC §20) and simply have no path.
    for _ in range(3):
        clock.advance(5.0)
        observe(live, clock, altitude_ft=8_000.0)

    result = await worker.process_pending()

    assert result.checkpointed == 0
    assert await checkpoints_of(database, await sighting_id_of(database)) == []


async def test_checkpoint_batches_are_thinned(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    """ADR-0005's light thinning, measured on the case it exists for.

    Twenty evenly spaced points down a dead-straight level leg carry two
    points' worth of information, and the checkpoint table is the busiest one
    in the schema while sightings are open.
    """
    fly(live, clock, straight_leg(20), altitude_ft=30_000.0)

    result = await worker.process_pending()

    rows = await checkpoints_of(database, await sighting_id_of(database))
    assert result.checkpointed == len(rows)
    assert len(rows) < 20


async def test_thinning_never_loses_the_newest_point(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    # The tail is what defines the recovery bound: a batch that stopped short
    # of the newest point would quietly widen the window a power cut costs.
    fly(live, clock, straight_leg(20), altitude_ft=30_000.0)
    newest_observation_ms = to_epoch_ms(clock.now())

    await worker.process_pending()

    rows = await checkpoints_of(database, await sighting_id_of(database))
    assert rows[-1].ts_ms == newest_observation_ms
    assert rows[-1].lat > rows[0].lat  # ...and it is the far end of the leg


async def test_thinning_stays_continuous_across_cycles(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    """The anchor carried between batches, seen through the worker.

    Without it every cycle would re-keep its own first point, and a long cruise
    would cost one checkpoint row per flush interval forever rather than one
    per change of course.
    """
    for cycle in range(4):
        fly(live, clock, straight_leg(10, start_nm=5.0 + cycle * 5.0), altitude_ft=30_000.0)
        clock.advance(FLUSH_INTERVAL_S)
        await worker.process_pending()

    rows = await checkpoints_of(database, await sighting_id_of(database))
    # One end-of-batch point per cycle, plus the sighting's first point; a
    # dead-straight leg gives thinning nothing else to keep.
    assert len(rows) == 5


async def test_a_failed_cycle_leaves_the_points_pending(
    live: LiveStore, clock: SimulatedTime, db_path: Path
) -> None:
    """Checkpoint state advances only on a committed transaction.

    A high-water mark moved before the commit would turn a transient SD-card
    error into a permanent hole in the sighting's path.
    """
    database = FailingOnceDatabase(db_path)
    await database.upgrade_to("head")
    try:
        async with worker_on(database, live, clock) as worker:
            fly(live, clock, [(5.0 + index, index * index * 0.05) for index in range(4)])
            database.fail_next = True

            failed = await worker.process_pending()
            recovered = await worker.process_pending()

            assert failed.failed is True
            assert failed.checkpointed == 0
            assert recovered.failed is False
            rows = await checkpoints_of(database, await sighting_id_of(database))
            assert [row.seq for row in rows] == [0, 1, 2, 3]
    finally:
        await database.dispose()


async def test_a_restart_resumes_the_sequence_and_the_high_water_mark(
    worker: PersistenceWorker,
    live: LiveStore,
    clock: SimulatedTime,
    database: Database,
) -> None:
    """A second process must neither renumber nor re-checkpoint.

    Restarting inside the closure gap adopts the open sighting, and the
    checkpoint rows it already has are the evidence of what was written. The
    live track still holds those same points, so without the rehydrated
    high-water mark the new process would write every one of them again — under
    ``seq`` values that already exist.
    """
    fly(live, clock, [(5.0 + index, index * index * 0.05) for index in range(4)])
    await worker.process_pending()
    sighting_id = await sighting_id_of(database)
    before = await checkpoints_of(database, sighting_id)
    await worker.stop()

    async with worker_on(database, live, clock) as restarted:
        clock.advance(5.0)
        fly(live, clock, [(30.0, 9.0)])
        await restarted.process_pending()

        rows = await checkpoints_of(database, sighting_id)
        assert [row.seq for row in rows] == list(range(len(rows)))
        assert len(rows) == len(before) + 1
        assert rows_of(rows[: len(before)]) == rows_of(before)


async def test_an_aircraft_that_leaves_the_live_set_checkpoints_its_tail(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    """Removal arms the closure gap and flushes immediately (slice 009).

    That flush is what puts the last points on disk: the ten minutes before the
    sighting actually closes are exactly the window a power cut would otherwise
    lose them in.
    """
    fly(live, clock, [(5.0 + index, index * index * 0.05) for index in range(3)])
    clock.advance(REMOVE_S + 1.0)
    live.sweep()

    await worker.process_pending()

    rows = await checkpoints_of(database, await sighting_id_of(database))
    assert len(rows) == 3
    assert worker.pending_count == 1
