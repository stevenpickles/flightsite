"""When maintenance is allowed to touch the database, and when it is not.

SPEC §70 asks for maintenance that is *conservative*, that runs ``VACUUM``
*only when justified and safe*, and that needs *no routine user babysitting*.
Those three phrases are the whole of this module: every threshold is a module
constant with a stated reason, none of them is a configuration key, and the two
decisions are pure functions over measured statistics so the guard matrix is
testable without a database.

The WAL checkpoint
------------------

WAL mode means committed pages accumulate in a ``-wal`` sidecar until a
checkpoint folds them back into the main file. SQLite checkpoints
automatically at :data:`~sqlite3.SQLITE_DEFAULT_WAL_AUTOCHECKPOINT`-sized
intervals, but a *passive* automatic checkpoint cannot shrink the sidecar while
any reader is using it, so on a busy receiver the file can grow and stay grown.
:data:`WAL_CHECKPOINT_THRESHOLD_BYTES` is the point at which FlightSite asks
for a ``TRUNCATE`` checkpoint, which does reset the file.

**Interplay with the writer lock.** ``PRAGMA wal_checkpoint(TRUNCATE)`` needs
every reader to be finished with the WAL, and it blocks new writers while it
runs. The maintenance service therefore issues it through
:meth:`~flightsite.db.engine.Database.maintenance_connection`, which takes the
process's single writer lock: the persistence worker's next transaction queues
behind it in the application instead of racing SQLite's file lock and burning
``busy_timeout``. It is also strictly best-effort — ``TRUNCATE`` returns a busy
indicator rather than an error when a reader is still attached, and the job
reports that as a plain outcome and tries again on the next cycle. Ingestion
never waits on any of this: nothing on the decoder poll or live-apply path
touches SQLite at all (``docs/ARCHITECTURE.md`` §3.1).

The ``VACUUM`` guard
--------------------

A plain ``VACUUM`` rewrites the entire database into a fresh file and blocks
writers for as long as that takes. On a Pi 4 with an SD card and a multi-gigabyte
database that is minutes, so it has to be rare, justified, and never
concurrent with a busy period. Four conditions, all required:

===================================== =========================================
:data:`VACUUM_MIN_DB_BYTES`           Below this the reclaimable space is not
                                      worth a full rewrite — 25% of 64 MB is
                                      16 MB, which no Pi install misses.
:data:`VACUUM_MIN_RECLAIMABLE_RATIO`  Free pages are *reused* by SQLite, so a
                                      modest freelist is healthy, not waste.
                                      A quarter of the file being dead space
                                      is the point where reuse is clearly not
                                      keeping up.
:data:`VACUUM_MIN_FREE_SPACE_FACTOR`  ``VACUUM`` needs room for a second copy
                                      of the database plus its journal. Running
                                      one that fills the card would turn a
                                      housekeeping job into an outage.
:data:`VACUUM_MAX_LIVE_AIRCRAFT`      The pressure heuristic — see below.
===================================== =========================================

**The pressure heuristic is deliberately cheap.** There is no measurement of
"ingestion pressure" that is both cheap and exact, and paying for an exact one
every hour to decide something that happens a few times a year would be the
wrong trade. Two free signals stand in for it: the size of the live aircraft
set, which is the traffic the persistence worker is about to write, and whether
the single writer lock is held at the instant of the decision. Either one says
"not now", and the job skips until the next daily evaluation. Both can be wrong
in the harmless direction — a skipped ``VACUUM`` costs a day — and neither can
be wrong in the harmful one, because a genuinely quiet receiver has neither a
large live set nor a contended writer.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from flightsite.maintenance.model import DatabaseStats

#: WAL size at which a ``TRUNCATE`` checkpoint is requested. Sixteen megabytes
#: is ~4,000 pages: far above the churn of a normal write cycle, so a healthy
#: install never trips it, and far below anything that threatens a Pi's card.
WAL_CHECKPOINT_THRESHOLD_BYTES: Final = 16 * 1024 * 1024

#: Smallest database worth rewriting.
VACUUM_MIN_DB_BYTES: Final = 64 * 1024 * 1024

#: Smallest fraction of dead pages that justifies a rewrite.
VACUUM_MIN_RECLAIMABLE_RATIO: Final = 0.25

#: Free disk space required, as a multiple of the database size.
VACUUM_MIN_FREE_SPACE_FACTOR: Final = 2.0

#: Live aircraft above which the receiver counts as busy. A quarter of SPEC §5's
#: 500-aircraft envelope: comfortably above a quiet night at any site, well
#: below the peak a ``VACUUM`` must stay out of the way of.
VACUUM_MAX_LIVE_AIRCRAFT: Final = 125


class VacuumVerdict(StrEnum):
    """Why the guard did or did not let a ``VACUUM`` run.

    Recorded verbatim in the job's diagnostics detail, so an operator asking
    "why has this never vacuumed?" gets an answer rather than an absence.
    """

    RUN = "run"
    BELOW_SIZE_FLOOR = "below_size_floor"
    LITTLE_RECLAIMABLE = "little_reclaimable"
    INSUFFICIENT_FREE_SPACE = "insufficient_free_space"
    INGESTION_PRESSURE = "ingestion_pressure"


@dataclass(frozen=True, slots=True)
class VacuumDecision:
    """The guard's verdict plus the measurements behind it."""

    verdict: VacuumVerdict
    db_bytes: int
    reclaimable_bytes: int
    reclaimable_ratio: float
    free_bytes: int

    @property
    def should_run(self) -> bool:
        """True only for :attr:`VacuumVerdict.RUN`."""
        return self.verdict is VacuumVerdict.RUN

    @property
    def required_free_bytes(self) -> int:
        """Free space this database would need before a ``VACUUM`` is allowed.

        Carried alongside :attr:`free_bytes` so a refusal can state the gap
        rather than only its name: on a multi-year database the requirement can
        exceed anything the card will ever have free, and an operator reading
        "insufficient_free_space" with no numbers cannot tell that apart from a
        condition that clears itself overnight (issue #116).
        """
        return int(self.db_bytes * VACUUM_MIN_FREE_SPACE_FACTOR)


def should_checkpoint(stats: DatabaseStats) -> bool:
    """True when the WAL has grown past :data:`WAL_CHECKPOINT_THRESHOLD_BYTES`."""
    return stats.wal_bytes > WAL_CHECKPOINT_THRESHOLD_BYTES


def vacuum_decision(stats: DatabaseStats, *, under_pressure: bool) -> VacuumDecision:
    """Decide whether a full ``VACUUM`` is justified and safe right now.

    The order the conditions are tested in is the order they are *cheap and
    informative* in: pressure is checked last so that a database which would
    never qualify anyway reports the structural reason rather than a transient
    one, which is far more useful to an operator reading diagnostics.
    """
    db_bytes = stats.db_bytes
    reclaimable = stats.reclaimable_bytes
    ratio = stats.reclaimable_ratio

    def decide(verdict: VacuumVerdict) -> VacuumDecision:
        return VacuumDecision(
            verdict=verdict,
            db_bytes=db_bytes,
            reclaimable_bytes=reclaimable,
            reclaimable_ratio=ratio,
            free_bytes=stats.free_bytes,
        )

    if db_bytes < VACUUM_MIN_DB_BYTES:
        return decide(VacuumVerdict.BELOW_SIZE_FLOOR)
    if ratio < VACUUM_MIN_RECLAIMABLE_RATIO:
        return decide(VacuumVerdict.LITTLE_RECLAIMABLE)
    if stats.free_bytes < db_bytes * VACUUM_MIN_FREE_SPACE_FACTOR:
        return decide(VacuumVerdict.INSUFFICIENT_FREE_SPACE)
    if under_pressure:
        return decide(VacuumVerdict.INGESTION_PRESSURE)
    return decide(VacuumVerdict.RUN)


__all__ = [
    "VACUUM_MAX_LIVE_AIRCRAFT",
    "VACUUM_MIN_DB_BYTES",
    "VACUUM_MIN_FREE_SPACE_FACTOR",
    "VACUUM_MIN_RECLAIMABLE_RATIO",
    "WAL_CHECKPOINT_THRESHOLD_BYTES",
    "VacuumDecision",
    "VacuumVerdict",
    "should_checkpoint",
    "vacuum_decision",
]
