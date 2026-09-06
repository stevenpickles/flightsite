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

Every wait on a subprocess here is bounded by *progress*, never by a fixed
window — see :data:`STALL_TIMEOUT_S` for why, and for the flake (issue #100)
that a fixed window caused.
"""

from __future__ import annotations

import asyncio
import functools
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import select

from flightsite.db import Database, Sighting, SightingTrackCheckpoint, database_path
from flightsite.db.clock import utc_now_ms
from flightsite.db.engine import QUICK_CHECK_OK
from flightsite.live import LiveStore
from flightsite.sightings import ClosureReason, PersistenceWorker, SightingRepository

from .conftest import CLOSE_S, reading

#: Seconds a drill subprocess may go without any sign of progress before the
#: drill declares it wedged.
#:
#: This is a **stall** deadline, not a budget for the work — issue #100. The
#: drill used to give the child one fixed 40 s window to reach its ready
#: marker, and that window was a budget for an interpreter start, the
#: SQLAlchemy import graph, a fifteen-step migration run and two dozen write
#: cycles. None of those has a bounded duration: they are set by how loaded the
#: machine is. Idle, the WAL drill reaches ready in about a second; under a
#: whole-machine CPU burn it took 25 s to 45 s and blew the window outright.
#: What *is* bounded, however loaded the machine, is the gap between two signs
#: of life from a subprocess that is still working, so that is what is measured
#: instead. A child that is merely slow keeps the drill waiting; one that has
#: genuinely stopped fails it, and fails it faster than the old budget did.
STALL_TIMEOUT_S = 60.0

#: How often the child touches its heartbeat file. Written from a daemon thread
#: started before the ``flightsite`` import graph, so neither a blocking
#: migration nor a busy event loop can silence it.
HEARTBEAT_INTERVAL_S = 0.5

#: Absolute ceiling on one wait, purely so a child that heartbeats forever
#: without ever reaching its goal cannot hang a suite. It is a hang guard, not
#: a performance expectation, and nothing should ever come close to it.
HANG_CEILING_S = 600.0

#: Seconds to wait for a subprocess to stop existing. It bounds no work: by the
#: time it is used the child has either called ``os._exit`` or been killed, and
#: all that remains is the operating system reaping it.
EXIT_TIMEOUT_S = 120.0

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


#: Prepended to every drill script, ahead of its ``flightsite`` imports.
#:
#: The pulse is the child's own answer to "are you still working?" (issue
#: #100). It runs on a daemon thread rather than the event loop because the
#: slowest thing the child does — an Alembic migration run driven through
#: SQLAlchemy's greenlet bridge — never yields to the loop, so a loop-based
#: heartbeat would go silent for exactly the stretch the parent most needs to
#: hear about. The thread is started at import time, before the import graph
#: the parent is waiting through. It writes a counter rather than touching an
#: mtime, so the parent compares *values* and never two machines' clocks; a
#: half-written file simply is not new progress, which is the safe reading.
#:
#: Daemon, so ``os._exit`` and ``TerminateProcess`` still leave the WAL and the
#: process state exactly as the drills require.
HEARTBEAT_PREAMBLE = """
import os as _os
import threading as _threading
import time as _time
from pathlib import Path as _Path

_BEAT = _Path(_os.environ["FLIGHTSITE_DATA_DIR"]) / "heartbeat"


def _pulse() -> None:
    count = 0
    while True:
        count += 1
        try:
            _BEAT.write_text(str(count))
        except OSError:  # the data directory went away with the fixture
            return
        _time.sleep({interval})


_BEAT.write_text("0")
_threading.Thread(target=_pulse, daemon=True).start()
"""


def with_heartbeat(script: str) -> str:
    """One drill script, prefixed with the progress pulse the parent waits on."""
    return HEARTBEAT_PREAMBLE.format(interval=HEARTBEAT_INTERVAL_S) + script


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
        [sys.executable, "-c", with_heartbeat(script), *arguments],
        env=environment,
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )


async def wait_while_progressing(
    process: subprocess.Popen[bytes],
    data_dir: Path,
    *,
    reached: Callable[[], bool],
    progress: Callable[[], object],
    goal: str,
) -> None:
    """Wait for ``reached()`` for as long as ``progress()`` keeps changing.

    The drill's one honest bound (issue #100). ``reached`` is the condition
    being waited for; ``progress`` returns a token that changes whenever the
    child does anything at all. A child that is slow because the machine is
    busy keeps changing the token and keeps its wait; a child that has stopped
    — deadlocked, or blocked on something no amount of patience will finish —
    stops changing it and fails the drill within :data:`STALL_TIMEOUT_S`.

    An early exit is reported as itself rather than as a timeout, and the
    child's captured output comes with every failure: a drill that fails
    because the product broke must not read like a drill that fails because
    the machine was busy.
    """
    ceiling = time.monotonic() + HANG_CEILING_S
    token = progress()
    last_change = time.monotonic()
    while True:
        # Before the liveness checks: a child that reached its goal and then
        # exited on purpose — which is exactly what the WAL script does — has
        # succeeded, not died.
        if reached():
            return
        if process.poll() is not None:
            raise AssertionError(f"drill subprocess exited before {goal}:\n{_log_of(data_dir)}")
        await asyncio.sleep(POLL_INTERVAL_S)
        now = time.monotonic()
        current = progress()
        if current != token:
            token, last_change = current, now
        elif now - last_change > STALL_TIMEOUT_S:
            raise AssertionError(
                f"drill subprocess showed no progress for {STALL_TIMEOUT_S:.0f}s "
                f"before {goal}:\n{_log_of(data_dir)}"
            )
        if now > ceiling:  # pragma: no cover - the hang guard, never reached
            raise AssertionError(
                f"drill subprocess kept signalling but never reached {goal} within "
                f"the {HANG_CEILING_S:.0f}s hang guard:\n{_log_of(data_dir)}"
            )


async def wait_for(marker: Path, process: subprocess.Popen[bytes], data_dir: Path) -> None:
    """Wait for the child to signal readiness, or explain why it never did."""
    await wait_while_progressing(
        process,
        data_dir,
        reached=lambda: _exists(marker),
        progress=lambda: _heartbeat(data_dir),
        goal="signalling ready",
    )


async def wait_for_checkpoints(
    path: Path, process: subprocess.Popen[bytes], data_dir: Path, wanted: int
) -> int:
    """Poll the child's database until it has checkpointed ``wanted`` points.

    Reading a database another process is writing is exactly what WAL is for,
    so this is a plain read connection; a lock collision simply means try again
    in a moment.

    The row count is its own progress signal, and a better one than the
    heartbeat here: an app that is alive but has stopped persisting is the
    failure this wait exists to catch, so "still breathing" must not be allowed
    to stand in for "still writing".
    """
    counted = functools.partial(_count, path, "sighting_track_checkpoints")
    await wait_while_progressing(
        process,
        data_dir,
        reached=lambda: counted() >= wanted,
        progress=counted,
        goal=f"checkpointing {wanted} track points",
    )
    return counted()


def _heartbeat(data_dir: Path) -> str:
    """The child's progress pulse, or ``""`` if it has not written one yet.

    A read that races the child's write returns whatever was there; it is not
    new progress, and the next poll will see the real value.
    """
    try:
        return (data_dir / "heartbeat").read_text()
    except OSError:  # pragma: no cover - only before the first pulse lands
        return ""


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


# ------------------------------------------------------- the harness's rule
#
# The drills below are expensive and rare; the property that makes them
# *reliable* is cheap and worth stating on its own. Issue #100's flake was a
# fixed window, so these three say exactly what replaced it: patience is
# unlimited while the child works, and is withdrawn when it stops.


class _Alive:
    """A stand-in for a subprocess that is running and stays running."""

    def poll(self) -> int | None:
        return None


def _running() -> subprocess.Popen[bytes]:
    return cast(subprocess.Popen[bytes], _Alive())


async def test_the_wait_outlasts_any_amount_of_slowness(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child that keeps signalling keeps its wait, past any fixed window.

    The stall window is shrunk to a fraction of the time the "child" takes, so
    a passing run is only possible if the wait is bounded by progress rather
    than by elapsed time — which is the whole of the #100 fix.
    """
    monkeypatch.setattr("tests.sightings.test_kill_drill.STALL_TIMEOUT_S", 0.05)
    monkeypatch.setattr("tests.sightings.test_kill_drill.POLL_INTERVAL_S", 0.01)
    ticks = 0

    def progress() -> int:
        nonlocal ticks
        ticks += 1
        return ticks

    await wait_while_progressing(
        _running(),
        isolated_data_dir,
        reached=lambda: ticks >= 30,
        progress=progress,
        goal="a goal reached slowly",
    )

    assert ticks >= 30


async def test_the_wait_gives_up_on_a_child_that_stops_signalling(
    isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Patience is for slowness, not for a wedge: silence still fails."""
    monkeypatch.setattr("tests.sightings.test_kill_drill.STALL_TIMEOUT_S", 0.05)
    monkeypatch.setattr("tests.sightings.test_kill_drill.POLL_INTERVAL_S", 0.01)

    with pytest.raises(AssertionError, match="no progress"):
        await wait_while_progressing(
            _running(),
            isolated_data_dir,
            reached=lambda: False,
            progress=lambda: "wedged",
            goal="a goal never reached",
        )


async def test_the_wait_reports_a_dead_child_as_dead(isolated_data_dir: Path) -> None:
    """A subprocess that died must not be reported as a slow machine."""

    class _Dead:
        def poll(self) -> int | None:
            return 1

    with pytest.raises(AssertionError, match="exited before"):
        await wait_while_progressing(
            cast(subprocess.Popen[bytes], _Dead()),
            isolated_data_dir,
            reached=lambda: False,
            progress=lambda: "irrelevant",
            goal="a goal it never lived to reach",
        )


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
        await wait_for(marker, process, isolated_data_dir)
        checkpointed = await wait_for_checkpoints(
            path, process, isolated_data_dir, REQUIRED_CHECKPOINTS
        )
    finally:
        # SIGKILL on POSIX, TerminateProcess on Windows: no handler, no
        # lifespan shutdown, no final flush.
        process.kill()
        process.wait(timeout=EXIT_TIMEOUT_S)

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
    await wait_for(marker, process, isolated_data_dir)
    assert process.wait(timeout=EXIT_TIMEOUT_S) == 0

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
