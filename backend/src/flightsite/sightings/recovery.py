"""Unclean-shutdown recovery: repairing what a killed process left open.

SPEC §71 asks FlightSite to tolerate host power loss without assuming that any
shutdown hook ran. What a ``kill -9`` or a pulled plug actually leaves behind is
narrow and well defined, because the persistence worker only ever writes inside
short transactions (ADR-0008) on a WAL database:

* **committed rows**, which SQLite's own WAL recovery hands back intact on the
  next open — that recovery happens below this module, in the first connection
  :class:`~flightsite.db.engine.Database` opens;
* **sightings still open** (``ended_ms IS NULL``), with their path sitting in
  ``sighting_track_checkpoints`` up to the last flush cycle;
* **nothing else.** A half-written close is not a state this schema can be
  found in: close packs the track, writes the ``sighting_tracks`` row and
  deletes the checkpoints in one transaction (ADR-0005), so it either all
  happened or none of it did.

What recovery therefore has to decide is one question per open sighting: *is
this aircraft still there?*

Two outcomes, and why they differ
---------------------------------

**Continuing.** An aircraft last heard within ``close_s`` of now might simply
still be overhead — the process was down for a moment, not the aircraft. Its
sighting is handed back to the worker as a pending closure with the deadline it
would have had, so the next observation *continues* the same row (same id, same
``started_ms``) and a restart costs the history nothing. If the aircraft really
has gone, the deadline expires normally and the sighting closes with
``gap_timeout`` — the ordinary rule, applied to an ordinary absence.

**Recovered.** An aircraft whose last data is older than the closure gap is
closed here, through the *same* close path a live sighting uses
(:meth:`~flightsite.sightings.repository.SightingRepository.close_sighting`):
the checkpoint rows are read back, simplified, packed into one
``sighting_tracks`` row, and deleted. The reason recorded is
``shutdown_recovery`` rather than ``gap_timeout``, and the distinction is not
cosmetic: nobody observed that gap. The process was dead. The aircraft may have
flown on for another hour with a receiver that was not listening, and
``gap_timeout`` would assert an observation FlightSite never made.

Bounded loss
------------

The cost of a power cut to an open sighting is exactly the points harvested
since its last checkpoint batch — one flush interval, ~30 s (ADR-0005). Nothing
in this module reconstructs or interpolates anything: the recovered path is the
points that reached the disk, and the gap at its end is honest.

Idempotence, and crashing during recovery
-----------------------------------------

Recovery closes sightings in batches, each in its own committed transaction, so
a crash *during* recovery keeps every batch that had already committed. Re-run
on the next boot it converges without special handling: a sighting closed by the
previous attempt is no longer open, so it is not a candidate; its checkpoints
went with it in the same transaction. There is no recovery marker to keep in
sync, and no partially-recovered sighting to recognize — the database state
*is* the progress record.

A batch whose transaction fails (a full disk, a locked file) is not dropped:
those sightings are handed back to the worker as already-expired pending
closures carrying ``shutdown_recovery``, so the very next worker cycle retries
them through the same close path with the same honest reason.

Anomalies
---------

Three impossible states are checked for anyway, because SPEC §71 asks for
diagnostics when recovery finds problems rather than for faith:

* checkpoint rows for a sighting that is already closed,
* checkpoint rows for a sighting row that does not exist,
* an open sighting that already owns a packed ``sighting_tracks`` row.

None can arise from the atomic close path. All three are cleaned — the leftover
checkpoints are deleted, and an open sighting holding a packed track is closed
regardless of its window, since its path has already been archived — and all
three are counted and logged as anomalies.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Final

import structlog
from sqlalchemy import delete, func, or_, select

from flightsite.counters import CounterRegistry
from flightsite.counters import counters as default_counters
from flightsite.db.engine import Database
from flightsite.db.models import Sighting, SightingTrack, SightingTrackCheckpoint
from flightsite.db.startup import DB_ERRORS_COUNTER
from flightsite.sightings.repository import OpenSightingRow, SightingRepository
from flightsite.sightings.state import ActiveSighting
from flightsite.sightings.vocabulary import ClosureReason

logger = structlog.get_logger(__name__)

#: Sightings closed per recovery transaction. Small enough that a crash loses
#: little work and a failure quarantines few sightings; large enough that a sky
#: full of aircraft is a couple of dozen transactions rather than a thousand.
DEFAULT_RECOVERY_BATCH: Final = 16

#: Ids per ``DELETE ... WHERE sighting_id IN (...)``, well under SQLite's bound
#: on statement parameters. Only anomalous rows ever reach this path, but the
#: count is not something recovery gets to assume.
_DELETE_CHUNK: Final = 500

#: A source of UTC epoch milliseconds; a hand-driven fake in tests.
EpochClock = Callable[[], int]


@dataclass(frozen=True, slots=True)
class RecoveryReport:
    """What startup recovery did, for the summary log and diagnostics.

    Retained on the persistence worker after :meth:`ShutdownRecovery.run` so
    the diagnostics surface (slice 042) can report the last boot's recovery
    without re-deriving it.
    """

    #: Sightings closed here with ``shutdown_recovery``.
    recovered: int = 0
    #: Sightings handed back to the worker to continue.
    continued: int = 0
    #: Track points retained across every recovered sighting, after
    #: simplification — what the packed rows actually hold.
    points_recovered: int = 0
    #: Leftover ``sighting_track_checkpoints`` rows deleted.
    orphan_checkpoints: int = 0
    #: Sightings those leftover rows belonged to.
    orphan_sightings: int = 0
    #: Committed recovery transactions, including the orphan cleanup.
    transactions: int = 0
    #: Sightings whose recovery transaction failed and were handed to the
    #: worker to retry.
    failed: int = 0

    @property
    def anomalies(self) -> int:
        """States recovery had to repair that should not have existed."""
        return self.orphan_sightings + self.failed

    @property
    def acted(self) -> bool:
        """True when there was anything at all to recover, continue or clean."""
        return bool(self.recovered or self.continued or self.orphan_sightings or self.failed)


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    """The report, plus the sightings the worker should carry on holding."""

    report: RecoveryReport
    #: Accumulators to install as pending closures: the continuing sightings
    #: with the deadline they would have had, and any whose repair failed with
    #: an already-expired deadline so the next cycle retries it.
    pending: tuple[ActiveSighting, ...] = ()


@dataclass(frozen=True, slots=True)
class _Orphans:
    """Leftover checkpoint rows found by the anomaly scan."""

    sighting_ids: tuple[int, ...] = ()
    rows: int = 0

    def __bool__(self) -> bool:
        return bool(self.sighting_ids)


@dataclass(frozen=True, slots=True)
class ShutdownRecovery:
    """Startup repair of the sightings an unclean shutdown left open.

    Args:
        database: the application database; recovery writes through its single
            writer session like every other writer (ADR-0001).
        repository: the sighting repository, so recovery closes sightings by
            exactly the same code path a live closure uses.
        close_ms: the closure gap in milliseconds (``sighting.close_s``). An
            aircraft silent for longer than this is recovered rather than
            continued.
        clock: UTC epoch-millisecond source, injected for tests.
        batch_size: sightings per committed recovery transaction.
        counters: registry receiving ``db_errors`` when a batch fails.
    """

    database: Database
    repository: SightingRepository
    close_ms: int
    clock: EpochClock
    batch_size: int = DEFAULT_RECOVERY_BATCH
    counters: CounterRegistry = field(default=default_counters)

    async def run(self) -> RecoveryOutcome:
        """Clean anomalies, close what is gone, hand back what may return."""
        now_ms = self.clock()

        orphans = await self._scan_orphans()
        transactions = 0
        if orphans:
            await self._delete_orphans(orphans.sighting_ids)
            transactions += 1
            logger.warning(
                "recovery_orphan_checkpoints_cleaned",
                sightings=len(orphans.sighting_ids),
                rows=orphans.rows,
            )

        # After the cleanup, so the high-water marks a continuing sighting
        # rehydrates with describe rows that still exist.
        rows = await self.repository.load_open_sightings()
        packed = await self._packed_open_ids() if rows else frozenset()
        stale, continuing = self._partition(rows, now_ms=now_ms, packed=packed)

        recovered = 0
        points = 0
        failed: list[OpenSightingRow] = []
        for batch in _chunks(stale, self.batch_size):
            transactions += 1
            closed = await self._close_batch(batch)
            if closed is None:
                failed.extend(batch)
                continue
            recovered += len(batch)
            points += closed

        report = RecoveryReport(
            recovered=recovered,
            continued=len(continuing),
            points_recovered=points,
            orphan_checkpoints=orphans.rows,
            orphan_sightings=len(orphans.sighting_ids),
            transactions=transactions,
            failed=len(failed),
        )
        self._log(report)
        pending = tuple(
            [self._continuing(row) for row in continuing] + [self._retrying(row) for row in failed]
        )
        return RecoveryOutcome(report=report, pending=pending)

    # ------------------------------------------------------------- the choice

    def _partition(
        self,
        rows: Sequence[OpenSightingRow],
        *,
        now_ms: int,
        packed: frozenset[int],
    ) -> tuple[tuple[OpenSightingRow, ...], tuple[OpenSightingRow, ...]]:
        """Split open sightings into "the aircraft is gone" and "it may not be".

        The window is measured against the sighting's *last data* — the newer of
        the airframe's last-seen instant and its newest checkpointed point —
        because either one is evidence the aircraft was still being received.
        """
        stale: list[OpenSightingRow] = []
        continuing: list[OpenSightingRow] = []
        for row in rows:
            gone = _last_data_ms(row) + self.close_ms <= now_ms
            # An open sighting that already owns a packed track is an anomaly
            # whose path has nevertheless been archived; closing it is the only
            # repair that leaves the schema in a state a reader can trust.
            (stale if gone or row.ids.sighting_id in packed else continuing).append(row)
        return tuple(stale), tuple(continuing)

    def _continuing(self, row: OpenSightingRow) -> ActiveSighting:
        """Rehydrate a sighting whose aircraft may still be overhead."""
        adopted = _accumulator(row)
        adopted.close_deadline_ms = adopted.last_seen_ms + self.close_ms
        return adopted

    def _retrying(self, row: OpenSightingRow) -> ActiveSighting:
        """Rehydrate a sighting whose repair failed, for the next worker cycle.

        The deadline is already in the past — that is what made it a recovery
        candidate — so the next cycle closes it, and the accumulator carries
        ``shutdown_recovery`` so the retry records the same reason this attempt
        would have.
        """
        retried = _accumulator(row)
        retried.close_deadline_ms = retried.last_seen_ms + self.close_ms
        retried.closure_reason = ClosureReason.SHUTDOWN_RECOVERY
        return retried

    # -------------------------------------------------------------- the close

    async def _close_batch(self, batch: Sequence[OpenSightingRow]) -> int | None:
        """Close one batch in one transaction; ``None`` if it did not commit.

        Nothing in memory depends on the outcome, so a failure needs no
        unwinding: the sightings are still open in the database, which is
        precisely the state the next attempt looks for.
        """
        points = 0
        try:
            async with self.database.writer_session() as session:
                for row in batch:
                    track = await self.repository.close_sighting(
                        session,
                        row.ids,
                        _accumulator(row),
                        reason=ClosureReason.SHUTDOWN_RECOVERY,
                    )
                    points += track.point_count
        except Exception as exc:
            self.counters.increment(DB_ERRORS_COUNTER)
            logger.warning(
                "recovery_batch_failed",
                error=str(exc),
                error_type=type(exc).__name__,
                sightings=len(batch),
                remediation="sightings left open; the next worker cycle retries the close",
            )
            return None

        for row in batch:
            logger.debug(
                "sighting_recovered",
                icao=row.icao24,
                sighting_id=row.ids.sighting_id,
                ended_ms=_accumulator(row).last_seen_ms,
                checkpoints=row.checkpoint_seq,
            )
        return points

    # ------------------------------------------------------------- anomalies

    async def _scan_orphans(self) -> _Orphans:
        """Checkpoint rows that belong to no open, unpacked sighting.

        Three impossible shapes in one query: a closed sighting, a sighting row
        that is gone, and a sighting whose track has already been packed.
        """
        statement = (
            select(
                SightingTrackCheckpoint.sighting_id,
                func.count().label("rows"),
            )
            .outerjoin(Sighting, Sighting.id == SightingTrackCheckpoint.sighting_id)
            .outerjoin(
                SightingTrack, SightingTrack.sighting_id == SightingTrackCheckpoint.sighting_id
            )
            .where(
                or_(
                    Sighting.id.is_(None),
                    Sighting.ended_ms.is_not(None),
                    SightingTrack.sighting_id.is_not(None),
                )
            )
            .group_by(SightingTrackCheckpoint.sighting_id)
            .order_by(SightingTrackCheckpoint.sighting_id)
        )
        async with self.database.read_session() as session:
            found = (await session.execute(statement)).all()
        return _Orphans(
            sighting_ids=tuple(int(sighting_id) for sighting_id, _ in found),
            rows=sum(int(count) for _, count in found),
        )

    async def _delete_orphans(self, sighting_ids: Sequence[int]) -> None:
        """Remove the leftover checkpoint rows, in one transaction."""
        async with self.database.writer_session() as session:
            for chunk in _chunks(sighting_ids, _DELETE_CHUNK):
                await session.execute(
                    delete(SightingTrackCheckpoint).where(
                        SightingTrackCheckpoint.sighting_id.in_(chunk)
                    )
                )

    async def _packed_open_ids(self) -> frozenset[int]:
        """Open sightings that already own a ``sighting_tracks`` row."""
        statement = (
            select(Sighting.id)
            .join(SightingTrack, SightingTrack.sighting_id == Sighting.id)
            .where(Sighting.ended_ms.is_(None))
        )
        async with self.database.read_session() as session:
            return frozenset((await session.scalars(statement)).all())

    # ------------------------------------------------------------ diagnostics

    @staticmethod
    def _log(report: RecoveryReport) -> None:
        """One structured summary of the boot, or silence on a clean one."""
        if not report.acted:
            return
        logger.info(
            "sighting_recovery_complete",
            recovered=report.recovered,
            continued=report.continued,
            points_recovered=report.points_recovered,
            orphan_checkpoints=report.orphan_checkpoints,
            orphan_sightings=report.orphan_sightings,
            failed=report.failed,
            transactions=report.transactions,
        )


def _accumulator(row: OpenSightingRow) -> ActiveSighting:
    """The rehydrated accumulator for an open sighting row.

    One correction on top of
    :meth:`~flightsite.sightings.repository.OpenSightingRow.to_accumulator`: a
    sighting cannot have ended before the last position it recorded, so a
    checkpoint newer than the airframe's stored last-seen instant moves
    ``last_seen_ms`` — and therefore ``ended_ms`` — forward to meet it.
    """
    adopted = row.to_accumulator()
    adopted.last_seen_ms = _last_data_ms(row)
    return adopted


def _last_data_ms(row: OpenSightingRow) -> int:
    """The newest instant this sighting has any evidence of reception for."""
    if row.checkpoint_ms is None:
        return row.last_known_ms
    return max(row.last_known_ms, row.checkpoint_ms)


def _chunks[T](items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    """``items`` in slices of at most ``size``, in order."""
    for start in range(0, len(items), size):
        yield items[start : start + size]


__all__ = [
    "DEFAULT_RECOVERY_BATCH",
    "EpochClock",
    "RecoveryOutcome",
    "RecoveryReport",
    "ShutdownRecovery",
]
