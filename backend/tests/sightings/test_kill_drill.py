"""The real drills: a killed process, and a WAL that was never checkpointed.

``test_recovery.py`` proves what recovery *does* on simulated time, from
databases a worker was dropped mid-cycle. These two prove the premise underneath
it — that the state those drills construct is the state a real operating system
leaves when a real process stops existing:

* :func:`test_a_killed_app_recovers_on_the_next_start` runs the actual
  FastAPI application in a subprocess, in demo mode, with real ingestion and
  the real persistence worker, and terminates it without warning. No lifespan
  shutdown runs, no accumulator is flushed, no connection is closed.
* :func:`test_a_never_checkpointed_wal_is_replayed_and_then_recovered` leaves
  a write-ahead log that SQLite never folded back into the database file, which
  is what an unclean stop actually leaves on disk (SPEC §71's "SQLite WAL
  recovery"), and checks that the rows come back and recovery proceeds over
  them.

Both scripts end in ``os._exit`` or a ``TerminateProcess``/``SIGKILL``, never in
a return: an ``atexit`` hook, a ``finally`` block or a garbage-collected
connection would each quietly checkpoint the WAL and destroy the very state
under test.

The subprocess only ever *makes* the mess. Recovering it happens in-process,
where the assertions can see the report.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import select

from flightsite.db import Database, Sighting, SightingTrackCheckpoint, database_path
from flightsite.db.clock import utc_now_ms
from flightsite.db.engine import QUICK_CHECK_OK
from flightsite.live import LiveStore
from flightsite.sightings import ClosureReason, PersistenceWorker, SightingRepository

from .conftest import CLOSE_S, reading

#: Seconds to wait for a subprocess to reach its ready marker. Generous: it
#: pays for an interpreter start, the SQLAlchemy import graph and a migration
#: run on a cold filesystem, none of which this drill is measuring.
STARTUP_TIMEOUT_S = 40.0

#: Seconds to wait for the running app to have checkpointed enough of a track
#: to make the kill interesting.
TRAFFIC_TIMEOUT_S = 20.0

#: Checkpoint rows that must exist before the kill, so that recovery has a path
#: to repair rather than a set of empty sightings.
REQUIRED_CHECKPOINTS = 20

#: How often the parent polls the child's database while it fills.
POLL_INTERVAL_S = 0.2

#: Flush cadence forced on the app in the drill. The product's is 30 s, which
#: would put the whole drill's runtime inside a single checkpoint interval and
#: leave nothing on disk to recover; a quarter second gives the same shape --
#: repeated checkpoint batches, then a kill mid-interval -- in a few seconds.
DRILL_FLUSH_INTERVAL_S = 0.25


# ------------------------------------------------------------------- scripts


#: Runs the real application: real config load, real lifespan, real demo
#: ingestion, real persistence worker as the single writer. The one thing the
#: drill imposes is the worker's flush cadence, for the reason above.
APP_SCRIPT = """
import asyncio
import sys
from pathlib import Path

from flightsite.app import create_app
from flightsite.sightings import PersistenceWorker


async def main() -> None:
    ready = Path(sys.argv[1])
    app = create_app()
    app.state.persistence = PersistenceWorker(
        database=app.state.database,
        live=app.state.live,
        close_s=app.state.settings.sighting.close_s,
        flush_interval_s=float(sys.argv[2]),
    )
    async with app.router.lifespan_context(app):
        ready.write_text("ready")
        while True:
            await asyncio.sleep(0.1)


asyncio.run(main())
"""

#: Writes a sighting and its checkpoints through the real worker, then stops
#: existing. Nothing closes the connection, so the WAL is left unmerged.
WAL_SCRIPT = """
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from flightsite.db import Database, database_path
from flightsite.ingest import AircraftStateBatch, AircraftStateUpdate, Position
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker

ICAO = "ae1463"


async def main() -> None:
    data_dir = Path(sys.argv[1])
    database = Database(database_path(data_dir))
    await database.upgrade_to("head")
    live = LiveStore(
        stale_s=15.0,
        remove_s=60.0,
        receiver_location=Position(latitude=47.4502, longitude=-122.3088),
    )
    worker = PersistenceWorker(
        database=database, live=live, flush_interval_s=0.001, tick_interval_s=3600.0
    )
    await worker.start()
    base = datetime.now(UTC)
    for index in range(24):
        at = base + timedelta(seconds=index)
        live.apply(
            AircraftStateBatch(
                timestamp=at,
                updates=(
                    AircraftStateUpdate(
                        icao=ICAO,
                        timestamp=at,
                        position=Position(
                            latitude=47.4502 + index * 0.02,
                            longitude=-122.3088 + index * 0.005,
                        ),
                        position_source="adsb",
                        altitude_ft=30_000.0,
                    ),
                ),
            )
        )
        await worker.process_pending()
    Path(sys.argv[2]).write_text("ready")
    # Not `return`: an ordinary exit would close the connection and checkpoint
    # the WAL, which is precisely the state this drill must not reach.
    os._exit(0)


asyncio.run(main())
"""


# ------------------------------------------------------------------- harness


def spawn(script: str, data_dir: Path, *arguments: str) -> subprocess.Popen[bytes]:
    """Run ``script`` in a fresh interpreter against ``data_dir``.

    Output goes to a file rather than a pipe: a pipe nobody drains fills its
    buffer and blocks the child, which in this suite would look exactly like a
    hung drill.
    """
    environment = dict(os.environ)
    environment.update(FLIGHTSITE_DATA_DIR=str(data_dir), FLIGHTSITE_DEMO="1")
    log = (data_dir / "drill.log").open("wb")
    return subprocess.Popen(
        [sys.executable, "-c", script, *arguments],
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )


async def wait_for(marker: Path, process: subprocess.Popen[bytes], timeout_s: float) -> None:
    """Wait for the child to signal readiness, or explain why it never did."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _exists(marker):
            return
        if process.poll() is not None:
            raise AssertionError(f"drill subprocess exited early:\n{_log_of(marker.parent)}")
        await asyncio.sleep(POLL_INTERVAL_S)
    raise AssertionError(f"drill subprocess never became ready:\n{_log_of(marker.parent)}")


async def wait_for_checkpoints(path: Path, wanted: int, timeout_s: float) -> int:
    """Poll the child's database until it has checkpointed ``wanted`` points.

    Reading a database another process is writing is exactly what WAL is for,
    so this is a plain read connection; a lock collision simply means try again
    in a moment.
    """
    deadline = time.monotonic() + timeout_s
    found = 0
    while time.monotonic() < deadline:
        found = _count(path, "sighting_track_checkpoints")
        if found >= wanted:
            return found
        await asyncio.sleep(POLL_INTERVAL_S)
    raise AssertionError(f"only {found} checkpoint rows after {timeout_s}s")


def _count(path: Path, table: str) -> int:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        return int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    except sqlite3.OperationalError:  # pragma: no cover - momentary lock
        return 0
    finally:
        connection.close()


def _exists(path: Path) -> bool:
    """Filesystem probes live in sync helpers so the drills stay ASYNC-clean."""
    return path.exists()


def wal_bytes(path: Path) -> int:
    """Size of the write-ahead log beside ``path``, or zero if there is none."""
    wal = Path(f"{path}-wal")
    return wal.stat().st_size if wal.exists() else 0


def _log_of(data_dir: Path) -> str:
    log = data_dir / "drill.log"
    return log.read_text(errors="replace") if log.exists() else "(no output captured)"


def long_after_the_gap() -> int:
    """A clock reading past every closure deadline the child can have armed.

    The alternative — sleeping out a real ``close_s`` — would put ten minutes,
    or a fragile tiny configured gap, into a drill whose subject is recovery
    rather than the gap rule.
    """
    return utc_now_ms() + int((CLOSE_S + 60.0) * 1_000)


async def recover(path: Path) -> tuple[PersistenceWorker, Database]:
    """Start a worker over the wreckage, exactly as the next boot would."""
    database = Database(path)
    worker = PersistenceWorker(
        database=database,
        live=LiveStore(stale_s=15.0, remove_s=60.0),
        close_s=CLOSE_S,
        tick_interval_s=3_600.0,
        clock=long_after_the_gap,
    )
    await worker.start()
    return worker, database


async def open_sightings(database: Database) -> list[Sighting]:
    async with reading(database) as session:
        return list(
            (await session.scalars(select(Sighting).where(Sighting.ended_ms.is_(None)))).all()
        )


async def all_sightings(database: Database) -> list[Sighting]:
    async with reading(database) as session:
        return list((await session.scalars(select(Sighting))).all())


# --------------------------------------------------------------- the drills


@pytest.mark.drill
async def test_a_killed_app_recovers_on_the_next_start(isolated_data_dir: Path) -> None:
    """Terminate the running product mid-flight; restart; check the repair.

    This is the roadmap's acceptance criterion in its literal form: the app is
    killed while sightings are open, and the next start closes them sanely with
    ``shutdown_recovery`` and a bounded amount of track lost.
    """
    path = database_path(isolated_data_dir)
    marker = isolated_data_dir / "ready"
    process = spawn(APP_SCRIPT, isolated_data_dir, str(marker), str(DRILL_FLUSH_INTERVAL_S))
    try:
        await wait_for(marker, process, STARTUP_TIMEOUT_S)
        checkpointed = await wait_for_checkpoints(path, REQUIRED_CHECKPOINTS, TRAFFIC_TIMEOUT_S)
    finally:
        # SIGKILL on POSIX, TerminateProcess on Windows: no handler, no
        # lifespan shutdown, no final flush.
        process.kill()
        process.wait(timeout=30)

    assert checkpointed >= REQUIRED_CHECKPOINTS
    survivor = Database(path)
    try:
        assert list(await survivor.quick_check()) == [QUICK_CHECK_OK]
        left_open = await open_sightings(survivor)
        # Demo mode fills the sky, so a kill lands across many sightings at
        # once — the shape a power cut has in the field, not a single row.
        assert len(left_open) >= 5, f"the kill left only {len(left_open)} sightings open"
    finally:
        await survivor.dispose()

    worker, database = await recover(path)
    try:
        report = worker.recovery
        assert report.recovered == len(left_open)
        assert report.continued == 0
        assert report.failed == 0
        assert report.points_recovered > 0

        assert await open_sightings(database) == []
        closed = await all_sightings(database)
        assert {row.closure_reason for row in closed} == {ClosureReason.SHUTDOWN_RECOVERY.value}
        assert all(row.ended_ms is not None for row in closed)

        # The path moved from the checkpoint table into the packed rows, whole.
        async with reading(database) as session:
            assert (await session.scalars(select(SightingTrackCheckpoint))).first() is None
        repository = SightingRepository(database)
        packed = [await repository.load_track(row.id) for row in closed]
        assert sum(len(track) for track in packed) == report.points_recovered
        assert any(track for track in packed)
    finally:
        await worker.stop()
        await database.dispose()


async def test_a_never_checkpointed_wal_is_replayed_and_then_recovered(
    isolated_data_dir: Path,
) -> None:
    """SQLite hands the committed rows back; recovery takes it from there.

    Two distinct failures would both show up here and neither is ours to fix in
    code: a database opened without replaying its WAL would have lost the
    sighting entirely, and one whose WAL was corrupt would fail ``quick_check``.
    What the drill adds on top is that recovery then runs over the replayed
    rows like any other boot.
    """
    path = database_path(isolated_data_dir)
    marker = isolated_data_dir / "written"
    process = spawn(WAL_SCRIPT, isolated_data_dir, str(isolated_data_dir), str(marker))
    await wait_for(marker, process, STARTUP_TIMEOUT_S)
    assert process.wait(timeout=30) == 0

    assert wal_bytes(path) > 0, "the drill must leave an unmerged WAL"

    worker, database = await recover(path)
    try:
        assert worker.recovery.recovered == 1
        assert worker.recovery.points_recovered > 0

        closed = await all_sightings(database)
        assert len(closed) == 1
        assert closed[0].closure_reason == ClosureReason.SHUTDOWN_RECOVERY.value
        track = await SightingRepository(database).load_track(closed[0].id)
        assert len(track) > 1
        assert [sample.ts_ms for sample in track] == sorted(sample.ts_ms for sample in track)
    finally:
        await worker.stop()
        await database.dispose()
