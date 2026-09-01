"""Restoring a backup into a data directory.

Restore is the destructive half of SPEC §72, so its shape is dictated by two
rules: **validate everything before touching anything**, and **never leave the
data directory in a half-restored state**.

Sequence
--------

1. Refuse without explicit confirmation (SPEC §72's "destructive restore
   operations must be deliberate"; the same posture §73 gives data reset).
2. Read and validate the manifest, then check schema compatibility — both cheap
   — so a newer-schema archive is refused before a multi-gigabyte database is
   written anywhere.
3. Extract every payload member into a staging directory *inside the data
   directory*, verifying SHA-256 as the bytes stream past. Staging inside the
   data directory keeps the final moves on one filesystem, which is what makes
   them atomic renames rather than copies.
4. Swap. For each member: move the live file aside to
   ``<name>.pre-restore.<timestamp>``, then :func:`os.replace` the staged file
   into place. If any step fails, every move already made is undone and the
   directory is left exactly as it was found.
5. Delete the preserved copies only after the whole swap succeeded.

Stale WAL sidecars
------------------

``flightsite.sqlite3-wal`` and ``-shm`` belong to the database being replaced.
Left beside a restored database file they are worse than useless — SQLite would
try to recover a write-ahead log written against a *different* file. They are
therefore moved aside with the same ``.pre-restore`` discipline. The snapshot in
the archive is fully materialized (``VACUUM INTO``, see :mod:`.snapshot`), so it
needs no sidecar of its own, and the pragmas in
:mod:`flightsite.db.engine` put it back into WAL mode on the first connection.

Restoring while FlightSite is running
-------------------------------------

There is no lock file or pid check, deliberately: any cheap heuristic would be
both spoofable and wrong across container restarts, and a wrong "FlightSite is
running" refusal is worse than no check. The operational rule is documented
instead — *stop FlightSite before restoring* (``docs/BACKUP.md``) — and the
mechanism is chosen so that a restore performed against a running instance is
survivable rather than corrupting: each file is swapped whole by rename, so a
running process keeps its open handle on the old inode and writes to a file
that is no longer linked into the directory, instead of writing into the middle
of the restored one. Its work is lost on the next restart, which is what the
user asked for, but the restored files are intact.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from flightsite.backup.compat import SchemaCompatibility
from flightsite.backup.errors import (
    ArchiveValidationError,
    ConfirmationRequiredError,
    RestoreError,
    SchemaCompatibilityError,
)
from flightsite.backup.manifest import (
    DATABASE_MEMBER,
    PAYLOAD_MEMBERS,
    SECRETS_MEMBER,
    Manifest,
)
from flightsite.backup.verify import inspect_archive

#: Suffix given to the files a restore displaces, until it succeeds.
PRESERVED_SUFFIX = "pre-restore"

#: SQLite sidecars of the database being replaced. They describe the *old*
#: file and must not survive into the restored installation.
DATABASE_SIDECARS = (f"{DATABASE_MEMBER}-wal", f"{DATABASE_MEMBER}-shm")

#: The rule that stands in for a running-process check. Printed whenever a
#: restore is refused for lack of confirmation.
OPERATIONAL_RULE = "Stop FlightSite before restoring (docs/BACKUP.md)."

#: What a completed restore tells the operator to do next.
NEXT_STEP = (
    "start FlightSite; it applies any pending migrations and runs its startup integrity check"
)


@dataclass(frozen=True, slots=True)
class RestoreResult:
    """What a completed restore changed."""

    data_dir: Path
    archive: Path
    manifest: Manifest
    compatibility: SchemaCompatibility
    #: Member names now live in the data directory.
    restored: tuple[str, ...]
    #: Files that were moved aside and then removed once the swap succeeded.
    displaced: tuple[str, ...]

    @property
    def migration_required(self) -> bool:
        """True when the next startup has migrations to apply."""
        return self.compatibility.migration_required

    @property
    def secrets_restored(self) -> bool:
        """True when ``secrets.yaml`` came out of the archive."""
        return SECRETS_MEMBER in self.restored

    def render(self) -> str:
        """The summary ``flightsite-backup restore`` prints."""
        lines = [
            f"restored {self.archive}",
            f"  into:              {self.data_dir}",
            f"  files:             {', '.join(self.restored)}",
            f"  schema:            {self.compatibility.summary()}",
            f"  secrets restored:  {'yes' if self.secrets_restored else 'no'}",
        ]
        if not self.secrets_restored:
            lines.append(
                f"  note:              the archive carried no {SECRETS_MEMBER}; any existing "
                "one was left untouched"
            )
        lines.append(f"  next:              {NEXT_STEP}")
        return "\n".join(lines)


def restore_backup(
    archive: Path,
    data_dir: Path,
    *,
    confirm: bool,
    now: Callable[[], datetime] | None = None,
) -> RestoreResult:
    """Replace the contents of ``data_dir`` with the contents of ``archive``.

    Args:
        archive: the ``tar.gz`` to restore.
        data_dir: the data directory to restore into. Created if absent.
        confirm: must be ``True``. The flag exists so that no caller — CLI,
            test, or future UI action — can perform a destructive restore
            without saying so explicitly (SPEC §72).
        now: clock injection point for the ``.pre-restore`` timestamps.

    Raises:
        ConfirmationRequiredError: if ``confirm`` is not ``True``.
        SchemaCompatibilityError: if the backup's schema is not restorable.
        ArchiveValidationError: if the archive is damaged or does not match its
            manifest.
        RestoreError: if the data directory could not be swapped over.
    """
    if not confirm:
        raise ConfirmationRequiredError(
            "restore is destructive: it replaces the database and configuration in "
            f"{data_dir}. Re-run with --confirm once you have stopped FlightSite."
        )

    clock = now or _utc_now
    stamp = clock().astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")

    try:
        data_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RestoreError(f"cannot create data directory {data_dir}: {exc}") from exc

    staging = data_dir / f".flightsite-restore-{stamp}"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()

    try:
        report = inspect_archive(archive, extract_to=staging)
        compatibility = report.compatibility
        if compatibility is not None and not compatibility.restorable:
            raise SchemaCompatibilityError(compatibility.summary())
        if not report.ok:
            raise ArchiveValidationError(
                f"{archive} failed validation and was not restored:\n"
                + "\n".join(f"  - {problem}" for problem in report.problems)
            )
        # Both are non-None once the report is clean; assert for the type checker.
        manifest = report.manifest
        if manifest is None or compatibility is None:  # pragma: no cover - unreachable when ok
            raise ArchiveValidationError(f"{archive} produced no manifest")

        restored, displaced = _swap(data_dir, staging, manifest, stamp=stamp)
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    return RestoreResult(
        data_dir=data_dir,
        archive=archive,
        manifest=manifest,
        compatibility=compatibility,
        restored=restored,
        displaced=displaced,
    )


def _swap(
    data_dir: Path, staging: Path, manifest: Manifest, *, stamp: str
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Move staged files into place, all or nothing.

    Returns the member names restored and the names of the files displaced (and
    then removed). On any failure every move is undone before re-raising.
    """
    incoming = [name for name in PAYLOAD_MEMBERS if name in manifest.file_names]
    # Sidecars of the database being replaced are displaced but never restored.
    aside = list(DATABASE_SIDECARS) if DATABASE_MEMBER in incoming else []

    moved_aside: list[tuple[Path, Path]] = []
    placed: list[Path] = []

    try:
        for name in [*incoming, *aside]:
            live = data_dir / name
            if not live.exists():
                continue
            preserved = data_dir / f"{name}.{PRESERVED_SUFFIX}.{stamp}"
            preserved.unlink(missing_ok=True)
            os.replace(live, preserved)
            moved_aside.append((live, preserved))

        for name in incoming:
            target = data_dir / name
            os.replace(staging / name, target)
            placed.append(target)
    except OSError as exc:
        _roll_back(placed, moved_aside)
        raise RestoreError(
            f"restoring into {data_dir} failed ({exc}); the data directory was left unchanged"
        ) from exc

    for _, preserved in moved_aside:
        preserved.unlink(missing_ok=True)

    return tuple(incoming), tuple(preserved.name for _, preserved in moved_aside)


def _roll_back(placed: list[Path], moved_aside: list[tuple[Path, Path]]) -> None:
    """Undo a partial swap: remove what landed, put back what was displaced."""
    for target in placed:
        target.unlink(missing_ok=True)
    for live, preserved in moved_aside:
        if preserved.exists():
            os.replace(preserved, live)


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "DATABASE_SIDECARS",
    "NEXT_STEP",
    "OPERATIONAL_RULE",
    "PRESERVED_SUFFIX",
    "RestoreResult",
    "restore_backup",
]
