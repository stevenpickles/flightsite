"""Power-cut drills: what survives an unclean shutdown, and what it costs.

Every drill here starts from a database in the state a *killed* process leaves
behind, built by running the real pipeline and then dropping the worker without
letting it shut down (:func:`power_cut`). Constructing the rows by hand would
prove only that the recovery queries work; running the worker and then killing
it proves that the state recovery expects is the state the worker actually
produces.

What the drills pin down (SPEC §71, ADR-0005):

* an aircraft long gone is **recovered** — closed with ``shutdown_recovery``
  from its checkpoint rows, simplified and packed, checkpoints deleted;
* an aircraft still transmitting is **continued** — same sighting row, no
  spurious closure;
* the loss is **bounded**: everything checkpointed comes back, and what does
  not is at most one flush interval of path;
* recovery is **idempotent**: a crash between recovery transactions leaves a
  database the next attempt finishes correctly, and a third attempt finds
  nothing to do;
* impossible leftovers — checkpoints on a closed sighting, on a sighting that
  does not exist, or beside an already-packed track — are cleaned and counted.

The real ``kill -9`` against a real process is ``test_kill_drill.py``; these are
the fast, deterministic drills that run on simulated time.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sqlite3
from collections.abc import AsyncIterator, Sequence
from math import sin
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.db import Database, SightingTrack, SightingTrackCheckpoint
from flightsite.ingest import Position
from flightsite.live import LiveStore
from flightsite.logging import configure_logging
from flightsite.sightings import (
    ClosureReason,
    PersistenceWorker,
    ShutdownRecovery,
    SightingRepository,
    TrackSample,
    from_track_point,
    pack_track,
    simplify,
)

from .conftest import (
    CLOSE_S,
    FLUSH_INTERVAL_S,
    ICAO,
    REMOVE_S,
    SEATTLE,
    FailingOnceDatabase,
    SimulatedTime,
    checkpoints_of,
    existing_aircraft,
    observe,
    offset_from,
    only_sighting,
    packed_track_of,
    reading,
    sightings_of,
    worker_on,
)

#: Longitude/latitude tolerance for a round trip through the packed encoding,
#: whose scale is 1e-5 degrees.
COORD_TOLERANCE = 1e-5

#: Simulated seconds between observations in the drills — the product's 1 Hz.
STEP_S = 1.0


# --------------------------------------------------------------- the power cut


async def power_cut(worker: PersistenceWorker) -> None:
    """Drop a running worker the way a power cut does: no hooks, no flush.

    Deliberately not :meth:`PersistenceWorker.stop`. A clean stop force-flushes
    every accumulator, which would leave the database in exactly the state
    these drills must never start from — SPEC §71's premise is that no shutdown
    hook runs at all. Cancelling the task and dropping the subscription is the
    closest an in-process test gets to the plug being pulled; the version with
    a real ``TerminateProcess`` is ``test_kill_drill.py``.
    """
    task, worker._task = worker._task, None
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    subscription, worker._subscription = worker._subscription, None
    if subscription is not None:
        subscription.close()


@contextlib.asynccontextmanager
async def doomed_worker(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> AsyncIterator[PersistenceWorker]:
    """A worker that is killed on exit rather than stopped."""
    worker = PersistenceWorker(
        database=database,
        live=live,
        close_s=CLOSE_S,
        flush_interval_s=FLUSH_INTERVAL_S,
        tick_interval_s=3_600.0,
        clock=clock.epoch_ms,
    )
    await worker.start()
    try:
        yield worker
    finally:
        await power_cut(worker)


# ----------------------------------------------------------------- the flight


def arc(index: int) -> Position:
    """A gently curving track: enough shape that thinning keeps real points."""
    return offset_from(SEATTLE, 5.0 + index * 0.15, 3.0 * sin(index / 12.0))


async def fly_under(
    worker: PersistenceWorker,
    live: LiveStore,
    clock: SimulatedTime,
    seconds: int,
    *,
    icao: str = ICAO,
) -> None:
    """Observe ``icao`` once a second for ``seconds``, running a cycle each time.

    One cycle per observation is what the running product does (a 1 s tick), so
    the checkpoint cadence the drill cuts into is the real one.
    """
    for index in range(seconds):
        clock.advance(STEP_S)
        observe(live, clock, icao, position=arc(index), altitude_ft=30_000.0)
        await worker.process_pending()


def depart(live: LiveStore, clock: SimulatedTime) -> None:
    """Age every aircraft out of the live set, arming its closure gap.

    The ordinary closure path needs the removal event; only startup recovery
    reaches a sighting whose aircraft simply stopped existing.
    """
    clock.advance(REMOVE_S + 1.0)
    live.sweep()


def flown(live: LiveStore, icao: str = ICAO) -> tuple[TrackSample, ...]:
    """The full-resolution truth: every point the live track still holds."""
    for record in live.snapshot():
        if record.icao == icao:
            return tuple(from_track_point(point) for point in record.track.points_since(None))
    raise AssertionError(f"{icao} is not in the live set")


# ---------------------------------------------------------------- assertions


async def recovered_track(database: Database, sighting_id: int) -> tuple[TrackSample, ...]:
    """The decoded path of a sighting recovery packed."""
    return await SightingRepository(database).load_track(sighting_id)


def assert_matches_checkpoints(
    recovered: Sequence[TrackSample], checkpoints: Sequence[SightingTrackCheckpoint]
) -> None:
    """Every recovered point is a checkpointed fix, unmoved and in order."""
    by_ts = {row.ts_ms: row for row in checkpoints}
    assert recovered, "a positioned sighting must recover a path"
    assert [sample.ts_ms for sample in recovered] == sorted(sample.ts_ms for sample in recovered)
    for sample in recovered:
        # No invention: recovery packs points that were received, never a
        # curve fitted through them (ADR-0005).
        row = by_ts.get(sample.ts_ms)
        assert row is not None, f"recovered a point at {sample.ts_ms} that was never checkpointed"
        assert sample.latitude == pytest.approx(row.lat, abs=COORD_TOLERANCE)
        assert sample.longitude == pytest.approx(row.lon, abs=COORD_TOLERANCE)
        assert sample.altitude_ft == row.alt_ft


def execute_raw(path: Path, statement: str, parameters: tuple[object, ...] = ()) -> None:
    """Run one statement through plain ``sqlite3``, foreign keys off.

    The application's own connections enforce foreign keys (ADR-0001), which
    is exactly why the anomaly drills cannot use them: the states being forged
    are ones the schema refuses to create.
    """
    connection = sqlite3.connect(path)
    try:
        connection.execute(statement, parameters)
        connection.commit()
    finally:
        connection.close()


# ------------------------------------------------------------------- fixtures


@pytest.fixture
async def crashed(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> tuple[int, list[SightingTrackCheckpoint], tuple[TrackSample, ...]]:
    """A power cut 75 s into a flight, mid checkpoint interval.

    Returns the sighting's id, the checkpoint rows that reached the disk, and
    the full-resolution truth the dead process still had in memory.
    """
    async with doomed_worker(database, live, clock) as worker:
        await fly_under(worker, live, clock, 75)
        sighting_id = (await only_sighting(database)).id
        written = await checkpoints_of(database, sighting_id)
        truth = flown(live)
    return sighting_id, written, truth


# ------------------------------------------------------------------- recovery


async def test_a_power_cut_mid_flight_recovers_the_checkpointed_path(
    crashed: tuple[int, list[SightingTrackCheckpoint], tuple[TrackSample, ...]],
    database: Database,
    live: LiveStore,
    clock: SimulatedTime,
) -> None:
    sighting_id, written, _ = crashed
    assert written, "the drill is meaningless if nothing was checkpointed"

    clock.advance(CLOSE_S + 1.0)
    async with worker_on(database, live, clock) as restarted:
        assert restarted.recovery.recovered == 1
        assert restarted.recovery.continued == 0
        assert restarted.pending_count == 0

    sighting = await only_sighting(database)
    assert sighting.closure_reason == ClosureReason.SHUTDOWN_RECOVERY.value
    assert sighting.ended_ms is not None
    assert sighting.duration_ms == sighting.ended_ms - sighting.started_ms
    # The path exists in exactly one table, which is ADR-0005's invariant.
    assert await checkpoints_of(database, sighting_id) == []
    assert await packed_track_of(database, sighting_id) is not None
    assert_matches_checkpoints(await recovered_track(database, sighting_id), written)


async def test_recovery_ends_the_sighting_when_the_aircraft_was_last_heard(
    crashed: tuple[int, list[SightingTrackCheckpoint], tuple[TrackSample, ...]],
    database: Database,
    live: LiveStore,
    clock: SimulatedTime,
) -> None:
    """Not when the gap expired, and not when the process came back.

    The sighting is the observation period. The ten minutes of silence that
    made it a recovery candidate were not part of it, and neither were the
    hours the machine may have spent powered off.
    """
    _, written, _ = crashed
    clock.advance(CLOSE_S * 5)

    async with worker_on(database, live, clock):
        pass

    sighting = await only_sighting(database)
    assert sighting.ended_ms is not None
    assert sighting.ended_ms >= written[-1].ts_ms
    assert sighting.ended_ms < clock.epoch_ms() - int(CLOSE_S * 1_000)


async def test_recovery_credits_the_airframe_exactly_once(
    crashed: tuple[int, list[SightingTrackCheckpoint], tuple[TrackSample, ...]],
    database: Database,
    live: LiveStore,
    clock: SimulatedTime,
) -> None:
    clock.advance(CLOSE_S + 1.0)
    async with worker_on(database, live, clock):
        pass
    # A second boot must not add the duration again or open a second sighting.
    async with worker_on(database, live, clock) as second:
        assert second.recovery.acted is False

    sighting = await only_sighting(database)
    aircraft = await existing_aircraft(database)
    assert aircraft.sighting_count == 1
    assert aircraft.total_observed_ms == sighting.duration_ms


async def test_a_sighting_with_no_checkpoints_recovers_without_a_track(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    """A Mode S-only aircraft, killed seconds after it was first heard.

    No position ever arrived, so there is nothing to pack — and no row is the
    right answer, not a track of zero points (SPEC §20).
    """
    async with doomed_worker(database, live, clock) as worker:
        observe(live, clock, squawk="1200")
        await worker.process_pending()
        sighting_id = (await only_sighting(database)).id
        assert await checkpoints_of(database, sighting_id) == []

    clock.advance(CLOSE_S + 1.0)
    async with worker_on(database, live, clock) as restarted:
        assert restarted.recovery.recovered == 1
        assert restarted.recovery.points_recovered == 0

    sighting = await only_sighting(database)
    assert sighting.closure_reason == ClosureReason.SHUTDOWN_RECOVERY.value
    assert await packed_track_of(database, sighting_id) is None
    assert await recovered_track(database, sighting_id) == ()


async def test_a_thinned_cruise_leg_recovers_the_points_that_were_kept(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    """Checkpoint thinning is invisible in the recovered result (ADR-0005).

    A dead-straight leg is checkpointed as a handful of rows, and what recovery
    packs is the simplification of exactly those rows — no more, and nothing
    the receiver did not report.
    """
    async with doomed_worker(database, live, clock) as worker:
        for index in range(90):
            clock.advance(STEP_S)
            observe(
                live,
                clock,
                position=offset_from(SEATTLE, 5.0 + index * 0.1, 0.0),
                altitude_ft=30_000.0,
            )
            await worker.process_pending()
        sighting_id = (await only_sighting(database)).id
        written = await checkpoints_of(database, sighting_id)

    # Thinning collapses the straight legs: far fewer rows than observations.
    assert 0 < len(written) < 20

    clock.advance(CLOSE_S + 1.0)
    async with worker_on(database, live, clock):
        pass

    recovered = await recovered_track(database, sighting_id)
    expected = simplify(
        tuple(
            TrackSample(
                ts_ms=row.ts_ms,
                latitude=row.lat,
                longitude=row.lon,
                position_source="adsb",
                altitude_ft=row.alt_ft,
                ground_speed_kt=row.gs_kt,
                track_deg=row.track_deg,
            )
            for row in written
        )
    )
    assert [sample.ts_ms for sample in recovered] == [sample.ts_ms for sample in expected]
    assert_matches_checkpoints(recovered, written)


# --------------------------------------------------------------- bounded loss


async def test_a_power_cut_loses_at_most_one_flush_interval_of_track(
    crashed: tuple[int, list[SightingTrackCheckpoint], tuple[TrackSample, ...]],
    database: Database,
    live: LiveStore,
    clock: SimulatedTime,
) -> None:
    """The guarantee ADR-0005 makes, measured against the in-memory truth.

    Two halves, and both matter: nothing that reached a checkpoint is lost, and
    what never reached one spans less than a single flush interval.
    """
    sighting_id, written, truth = crashed
    last_checkpoint_ms = written[-1].ts_ms

    lost = [sample for sample in truth if sample.ts_ms > last_checkpoint_ms]
    assert lost, "the cut must land mid-interval or the drill proves nothing"
    assert lost[-1].ts_ms - last_checkpoint_ms <= int(FLUSH_INTERVAL_S * 1_000)

    clock.advance(CLOSE_S + 1.0)
    async with worker_on(database, live, clock):
        pass

    recovered = await recovered_track(database, sighting_id)
    # Douglas-Peucker keeps the endpoints, so the recovered path spans the
    # whole checkpointed record rather than a prefix of it.
    assert recovered[0].ts_ms == written[0].ts_ms
    assert recovered[-1].ts_ms == last_checkpoint_ms

    sighting = await only_sighting(database)
    assert sighting.ended_ms is not None
    assert truth[-1].ts_ms - sighting.ended_ms <= int(FLUSH_INTERVAL_S * 1_000)


# ----------------------------------------------------------------- continuity


async def test_an_aircraft_still_transmitting_keeps_its_sighting(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    """A restart inside the gap is not a closure (the continuity drill).

    The process died; the aircraft did not. Closing here would chop a flight in
    half and invent a second sighting for the same pass, so the sighting is
    handed back and the next observation continues it.
    """
    async with doomed_worker(database, live, clock) as worker:
        await fly_under(worker, live, clock, 40)
        original = await only_sighting(database)

    clock.advance(30.0)
    async with worker_on(database, live, clock) as restarted:
        assert restarted.recovery.recovered == 0
        assert restarted.recovery.continued == 1
        assert restarted.pending_count == 1

        clock.advance(STEP_S)
        observe(live, clock, position=arc(41), altitude_ft=31_000.0)
        await restarted.process_pending()

        continued = await only_sighting(database)
        assert continued.id == original.id
        assert continued.started_ms == original.started_ms
        assert continued.ended_ms is None

    assert (await existing_aircraft(database)).sighting_count == 1


async def test_a_continued_sighting_that_never_returns_closes_as_a_gap(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    """Because that closure *is* observed: this process watched the silence."""
    async with doomed_worker(database, live, clock) as worker:
        await fly_under(worker, live, clock, 20)

    clock.advance(30.0)
    async with worker_on(database, live, clock) as restarted:
        assert restarted.recovery.continued == 1
        clock.advance(CLOSE_S)
        assert (await restarted.process_pending()).closed == 1

    assert (await only_sighting(database)).closure_reason == ClosureReason.GAP_TIMEOUT.value


async def test_a_normally_closed_sighting_is_left_alone(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    async with worker_on(database, live, clock) as worker:
        await fly_under(worker, live, clock, 20)
        depart(live, clock)
        await worker.process_pending()
        clock.advance(CLOSE_S)
        assert (await worker.process_pending()).closed == 1

    async with worker_on(database, live, clock) as restarted:
        assert restarted.recovery.acted is False

    sighting = await only_sighting(database)
    assert sighting.closure_reason == ClosureReason.GAP_TIMEOUT.value


# --------------------------------------------------------------- double crash


class FailingAfterDatabase(Database):
    """A database whose writer transactions fail from the ``allow``-th onward.

    The injected fault stands in for the machine dying between two recovery
    transactions: everything committed before it stays committed, and
    everything after it never happened.
    """

    def __init__(self, path: Path, *, allow: int) -> None:
        super().__init__(path)
        self.allow = allow
        self.used = 0

    @contextlib.asynccontextmanager
    async def writer_session(self) -> AsyncIterator[AsyncSession]:
        used, self.used = self.used, self.used + 1
        if used >= self.allow:
            raise RuntimeError("simulated power cut mid-recovery")
        async with super().writer_session() as session:
            yield session


def recovery_over(database: Database, clock: SimulatedTime, *, batch_size: int) -> ShutdownRecovery:
    return ShutdownRecovery(
        database=database,
        repository=SightingRepository(database),
        close_ms=int(CLOSE_S * 1_000),
        clock=clock.epoch_ms,
        batch_size=batch_size,
    )


async def _five_stale_sightings(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> tuple[str, ...]:
    """Five aircraft mid-flight when the power went, all long gone by now."""
    icaos = tuple(f"ab00{index:02d}" for index in range(5))
    async with doomed_worker(database, live, clock) as worker:
        for index in range(20):
            clock.advance(STEP_S)
            for offset, icao in enumerate(icaos):
                observe(
                    live,
                    clock,
                    icao,
                    position=offset_from(SEATTLE, 5.0 + index * 0.2 + offset, offset * 0.5),
                    altitude_ft=30_000.0 + offset * 100,
                )
            await worker.process_pending()
    clock.advance(CLOSE_S + 1.0)
    return icaos


async def test_a_crash_during_recovery_converges_on_the_next_attempt(
    database: Database, live: LiveStore, clock: SimulatedTime, db_path: Path
) -> None:
    """The double-crash drill: interrupt recovery, re-run it, check convergence.

    Progress is the database itself — a sighting the first attempt closed is
    simply not open any more — so the second attempt needs no marker, no
    resume point and no special case.
    """
    icaos = await _five_stale_sightings(database, live, clock)

    interrupted = FailingAfterDatabase(db_path, allow=2)
    try:
        first = await recovery_over(interrupted, clock, batch_size=1).run()
    finally:
        await interrupted.dispose()

    assert first.report.recovered == 2
    assert first.report.failed == 3
    assert first.report.transactions == 5
    closed = [row for icao in icaos for row in await sightings_of(database, icao) if row.ended_ms]
    assert len(closed) == 2
    assert {row.closure_reason for row in closed} == {ClosureReason.SHUTDOWN_RECOVERY.value}
    # The three that did not commit are untouched, checkpoints and all.
    for icao in icaos:
        sighting = await only_sighting(database, icao)
        if sighting.ended_ms is None:
            assert await checkpoints_of(database, sighting.id)

    second = await recovery_over(database, clock, batch_size=1).run()
    assert second.report.recovered == 3
    assert second.report.failed == 0

    third = await recovery_over(database, clock, batch_size=1).run()
    assert third.report.acted is False
    assert third.pending == ()

    for icao in icaos:
        sighting = await only_sighting(database, icao)
        assert sighting.closure_reason == ClosureReason.SHUTDOWN_RECOVERY.value
        assert await checkpoints_of(database, sighting.id) == []
        assert await packed_track_of(database, sighting.id) is not None


async def test_a_failed_recovery_batch_is_retried_by_the_next_cycle(
    live: LiveStore, clock: SimulatedTime, db_path: Path
) -> None:
    """A quarantined sighting keeps its reason, and closes one cycle later.

    Handing it back as an already-expired pending closure means the retry runs
    through the ordinary close path — and carries ``shutdown_recovery``, not
    the ``gap_timeout`` the ordinary path would otherwise record for a gap this
    process never watched.
    """
    database = FailingOnceDatabase(db_path)
    await database.upgrade_to("head")
    try:
        async with doomed_worker(database, live, clock) as worker:
            await fly_under(worker, live, clock, 40)
        clock.advance(CLOSE_S + 1.0)

        database.fail_next = True
        async with worker_on(database, live, clock) as restarted:
            assert restarted.recovery.recovered == 0
            assert restarted.recovery.failed == 1
            assert restarted.recovery.anomalies == 1
            assert restarted.pending_count == 1
            assert (await only_sighting(database)).ended_ms is None

            assert (await restarted.process_pending()).closed == 1

        sighting = await only_sighting(database)
        assert sighting.closure_reason == ClosureReason.SHUTDOWN_RECOVERY.value
        assert await checkpoints_of(database, sighting.id) == []
    finally:
        await database.dispose()


async def test_a_quarantined_sighting_whose_aircraft_returns_is_not_recovered(
    live: LiveStore, clock: SimulatedTime, db_path: Path
) -> None:
    """Hearing the aircraft again makes any later closure an observed one."""
    database = FailingOnceDatabase(db_path)
    await database.upgrade_to("head")
    try:
        async with doomed_worker(database, live, clock) as worker:
            await fly_under(worker, live, clock, 20)
        clock.advance(CLOSE_S + 1.0)

        database.fail_next = True
        async with worker_on(database, live, clock) as restarted:
            assert restarted.recovery.failed == 1

            clock.advance(STEP_S)
            observe(live, clock, position=arc(21), altitude_ft=30_000.0)
            await restarted.process_pending()
            assert restarted.active_count == 1

            depart(live, clock)
            await restarted.process_pending()
            clock.advance(CLOSE_S)
            assert (await restarted.process_pending()).closed == 1

        assert (await only_sighting(database)).closure_reason == ClosureReason.GAP_TIMEOUT.value
    finally:
        await database.dispose()


# ------------------------------------------------------------------- anomalies


async def test_checkpoints_left_on_a_closed_sighting_are_cleaned(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    """A state the atomic close path cannot produce — repaired anyway.

    Nothing reads checkpoints of a closed sighting, so leaving them would be
    invisible rather than harmful. That is exactly why they are removed and
    counted: an anomaly nobody is told about is a corruption that grows.
    """
    async with worker_on(database, live, clock) as worker:
        await fly_under(worker, live, clock, 20)
        depart(live, clock)
        await worker.process_pending()
        clock.advance(CLOSE_S)
        assert (await worker.process_pending()).closed == 1
    sighting = await only_sighting(database)

    async with database.writer_session() as session:
        session.add_all(
            [
                SightingTrackCheckpoint(
                    sighting_id=sighting.id,
                    seq=seq,
                    ts_ms=sighting.started_ms + seq,
                    lat=47.0,
                    lon=-122.0,
                    alt_ft=30_000,
                    gs_kt=None,
                    track_deg=None,
                    pos_source=0,
                )
                for seq in range(3)
            ]
        )

    async with worker_on(database, live, clock) as restarted:
        assert restarted.recovery.orphan_sightings == 1
        assert restarted.recovery.orphan_checkpoints == 3
        assert restarted.recovery.recovered == 0

    assert await checkpoints_of(database, sighting.id) == []


async def test_checkpoints_for_a_sighting_that_does_not_exist_are_cleaned(
    database: Database, live: LiveStore, clock: SimulatedTime, db_path: Path
) -> None:
    """Foreign keys make this unreachable in-process, so it is forged in SQL.

    A restore from a mangled backup or a hand-edited database could still
    present it, and recovery must not leave rows pointing at nothing.
    """
    await database.dispose()
    execute_raw(
        db_path,
        "INSERT INTO sighting_track_checkpoints"
        " (sighting_id, seq, ts_ms, lat, lon, alt_ft, gs_kt, track_deg, pos_source)"
        " VALUES (424242, 0, 1, 47.0, -122.0, NULL, NULL, NULL, 0)",
    )
    reopened = Database(db_path)
    try:
        async with worker_on(reopened, live, clock) as restarted:
            assert restarted.recovery.orphan_sightings == 1
            assert restarted.recovery.orphan_checkpoints == 1
        async with reading(reopened) as session:
            assert (await session.get(SightingTrackCheckpoint, (424242, 0))) is None
    finally:
        await reopened.dispose()


async def test_an_open_sighting_that_already_has_a_packed_track_is_closed(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    """The path is archived, so the sighting is finished — window or not.

    Leaving it open would let the next close try to insert a second
    ``sighting_tracks`` row for the same sighting and fail every cycle
    thereafter. Closing it is the only repair that leaves the schema in a state
    a reader can trust.
    """
    async with doomed_worker(database, live, clock) as worker:
        await fly_under(worker, live, clock, 40)
        sighting_id = (await only_sighting(database)).id
        written = await checkpoints_of(database, sighting_id)

    packed = pack_track(
        simplify(
            tuple(
                TrackSample(
                    ts_ms=row.ts_ms,
                    latitude=row.lat,
                    longitude=row.lon,
                    position_source="adsb",
                    altitude_ft=row.alt_ft,
                    ground_speed_kt=row.gs_kt,
                    track_deg=row.track_deg,
                )
                for row in written
            )
        )
    )
    async with database.writer_session() as session:
        session.add(
            SightingTrack(
                sighting_id=sighting_id,
                encoding_version=packed.encoding_version,
                point_count=packed.point_count,
                started_ms=packed.started_ms,
                points_blob=packed.points_blob,
            )
        )

    # Well inside the closure gap: without the anomaly rule this sighting would
    # have been continued.
    clock.advance(10.0)
    async with worker_on(database, live, clock) as restarted:
        assert restarted.recovery.orphan_sightings == 1
        assert restarted.recovery.recovered == 1
        assert restarted.recovery.continued == 0

    sighting = await only_sighting(database)
    assert sighting.closure_reason == ClosureReason.SHUTDOWN_RECOVERY.value
    assert await checkpoints_of(database, sighting_id) == []
    assert (await recovered_track(database, sighting_id)) != ()


async def test_a_checkpoint_newer_than_the_airframe_still_ends_the_sighting(
    database: Database, live: LiveStore, clock: SimulatedTime, db_path: Path
) -> None:
    """A sighting cannot have ended before the last position it recorded.

    The airframe row is the ordinary evidence of when an aircraft was last
    heard, but a checkpoint is evidence too, and the newer of the two is what
    the window and ``ended_ms`` are measured against.
    """
    async with doomed_worker(database, live, clock) as worker:
        await fly_under(worker, live, clock, 40)
        sighting = await only_sighting(database)
        written = await checkpoints_of(database, sighting.id)

    await database.dispose()
    execute_raw(db_path, "UPDATE aircraft SET last_seen_ms = ?", (sighting.started_ms,))
    reopened = Database(db_path)
    try:
        clock.advance(CLOSE_S + 1.0)
        async with worker_on(reopened, live, clock) as restarted:
            assert restarted.recovery.recovered == 1
        assert (await only_sighting(reopened)).ended_ms == written[-1].ts_ms
    finally:
        await reopened.dispose()


# ----------------------------------------------------------------- diagnostics


async def test_a_clean_boot_recovers_nothing_and_says_nothing(
    database: Database, live: LiveStore, clock: SimulatedTime
) -> None:
    async with worker_on(database, live, clock) as worker:
        assert worker.recovery.acted is False
        assert worker.recovery.anomalies == 0
        assert worker.recovery.transactions == 0
        assert worker.recovery.recovered == 0


async def test_the_recovery_summary_reaches_the_structured_log(
    database: Database,
    live: LiveStore,
    clock: SimulatedTime,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """SPEC §71 asks for diagnostics when recovery happens, not for faith.

    The assertion reads the JSON line an operator (and, from slice 042, the
    diagnostics surface) actually sees, not a Python-level call record.
    """
    icaos = await _five_stale_sightings(database, live, clock)

    configure_logging(level="INFO")
    capsys.readouterr()
    async with worker_on(database, live, clock) as restarted:
        report = restarted.recovery

    events = [
        json.loads(line)
        for line in capsys.readouterr().err.splitlines()
        if line.startswith("{") and '"sighting_recovery_complete"' in line
    ]
    assert len(events) == 1
    summary: dict[str, Any] = events[0]
    assert summary["recovered"] == len(icaos)
    assert summary["continued"] == 0
    assert summary["failed"] == 0
    assert summary["orphan_sightings"] == 0
    assert summary["points_recovered"] == report.points_recovered > 0
    assert summary["transactions"] == report.transactions >= 1
