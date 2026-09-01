"""Reset FlightSite Data (SPEC §73): mark-and-restart semantics.

``create_app`` (:mod:`flightsite.app`) wires eight interdependent long-lived
services around one database — the live store, the write-behind persistence
worker, the metadata cache, enrichment, airport context, receiver metrics,
analytics and maintenance — several of them holding background tasks and
in-memory state built from the database at startup. Tearing all of that down,
deleting the database file out from under it, and building it back up again
live, without leaking a task, a subscription or a stale in-memory entry, is
exactly the failure mode ``docs/BACKUP.md`` designs *restore* around by
refusing to attempt it while the process is live: *"Restoring is not safe —
stop FlightSite first."* SPEC §73 gives reset the same posture SPEC §72 gives
restore, so this module gives it the same answer: **mark, then restart.**

``POST /api/internal/reset/data`` (:mod:`flightsite.api.internal`) never
touches the database. It writes a marker file to the data directory and
answers ``202`` telling the operator to restart the stack. The marker is
consumed once, synchronously, at the very start of the *next*
:func:`~flightsite.app.create_app` call — before :class:`~flightsite.db.engine.Database`
is even constructed — so the fresh process opens a database that the process
which requested the reset never touched.

What is deleted, what survives
-------------------------------

``flightsite.sqlite3`` and its ``-wal``/``-shm`` sidecars are removed. Nothing
else in the data directory is touched: ``config.yaml`` and ``secrets.yaml``
survive, so the receiver endpoint, timezone, retention settings and any
configured AeroDataBox key do not need to be re-entered after a reset that was
about clearing *data*, not about reconfiguring the install. That is the
"preserves ... config" reading of SPEC §73's "preserves nothing except
optionally config" — the same direction a restore leaves things in when its
archive carries no ``secrets.yaml`` (``docs/BACKUP.md``).

The next startup's ordinary migration path then creates a brand new,
schema-head database with an empty ``meta`` table. SPEC §73's acceptance
criterion — *"post-reset app behaves as fresh install: new T0 on next
observation"* — falls out of that for free: T0 is nothing but the
first-write-wins row :mod:`flightsite.db.meta` installs once ingestion sees
its first aircraft, and a brand new database has no such row.
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog

from flightsite.config.loader import atomic_write_text
from flightsite.db.engine import DB_FILENAME

logger = structlog.get_logger(__name__)

#: Hidden so nothing scanning the data directory mistakes it for application
#: data; the leading dot follows the same convention
#: :mod:`flightsite.backup.restore` uses for its own staging directory.
RESET_MARKER_FILENAME = ".flightsite-reset-pending"

#: The database file and its WAL-mode sidecars — everything a reset deletes.
_DATABASE_FILENAMES = (DB_FILENAME, f"{DB_FILENAME}-wal", f"{DB_FILENAME}-shm")


def marker_path(data_dir: Path) -> Path:
    """Path of the pending-reset marker inside ``data_dir``."""
    return data_dir / RESET_MARKER_FILENAME


def write_reset_marker(data_dir: Path, *, requested_ms: int) -> Path:
    """Record that a reset was requested. Idempotent — a later call just overwrites.

    Written atomically (temp file plus ``os.replace``, via
    :func:`flightsite.config.loader.atomic_write_text`), so a crash mid-write
    can never leave a half-written marker for the next startup to trip over.
    """
    path = marker_path(data_dir)
    document = json.dumps({"requested_ms": requested_ms}, indent=2) + "\n"
    atomic_write_text(path, document)
    logger.warning(
        "reset_marker_written",
        data_dir=str(data_dir),
        requested_ms=requested_ms,
        remediation="restart FlightSite (docker compose restart) to apply the reset",
    )
    return path


def reset_pending(data_dir: Path) -> bool:
    """True while a reset has been requested and not yet applied."""
    return marker_path(data_dir).exists()


def apply_pending_reset(data_dir: Path) -> bool:
    """Delete the database if a reset was requested. Returns whether one was applied.

    Called once, synchronously, at the very start of
    :func:`~flightsite.app.create_app` — before :class:`~flightsite.db.engine.Database`
    opens anything — so a pending reset always lands before the migration that
    follows creates the fresh database. Safe to call with nothing pending: it
    is then a single ``Path.exists()`` check and nothing else.

    ``config.yaml`` and ``secrets.yaml`` are never touched here — see the
    module docstring for why configuration survives a reset.
    """
    path = marker_path(data_dir)
    if not path.exists():
        return False

    requested_ms = _read_requested_ms(path)
    removed = [name for name in _DATABASE_FILENAMES if _unlink_if_present(data_dir / name)]
    path.unlink(missing_ok=True)
    logger.warning(
        "reset_applied",
        data_dir=str(data_dir),
        requested_ms=requested_ms,
        removed_files=removed,
        note="config.yaml and secrets.yaml preserved; a fresh database follows this startup",
    )
    return True


def _unlink_if_present(path: Path) -> bool:
    if not path.exists():
        return False
    path.unlink()
    return True


def _read_requested_ms(path: Path) -> int | None:
    """Best-effort read of the marker's timestamp. Never blocks applying the reset.

    A marker that failed to parse still means "a reset was requested" —
    refusing to apply it because its own bookkeeping is unreadable would be
    exactly backwards, so this only affects what gets logged.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    requested = payload.get("requested_ms") if isinstance(payload, dict) else None
    return requested if isinstance(requested, int) else None


__all__ = [
    "RESET_MARKER_FILENAME",
    "apply_pending_reset",
    "marker_path",
    "reset_pending",
    "write_reset_marker",
]
