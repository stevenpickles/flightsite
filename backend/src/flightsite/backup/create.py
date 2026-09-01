"""Taking a backup.

Produces one self-describing ``tar.gz`` under ``<data_dir>/backups/``
(``docs/ARCHITECTURE.md`` §2.1) holding a SQLite-safe snapshot of the database,
``config.yaml``, optionally ``secrets.yaml``, and the manifest that makes the
archive version-aware (SPEC §72).

The whole command is synchronous stdlib work over files. It borrows nothing
from a running application — no engine, no writer lock, no event loop — which
is what lets the same command serve both documented situations: taken from
inside the running container (``docker compose exec``) while ingestion
continues, and taken against a stopped installation's data directory.

Secrets are opt-in (``docs/SECURITY.md`` §3). ``includes_secrets`` in the
manifest records what actually went in, not what was asked for: requesting
secrets for an installation that has no ``secrets.yaml`` yields an archive
whose manifest honestly says ``false``.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from flightsite import __version__
from flightsite.backup import archive as archive_io
from flightsite.backup.errors import BackupError
from flightsite.backup.manifest import (
    CONFIG_MEMBER,
    DATABASE_MEMBER,
    FORMAT_VERSION,
    MANIFEST_MEMBER,
    SECRETS_MEMBER,
    FileEntry,
    Manifest,
    utc_iso,
)
from flightsite.backup.snapshot import (
    metadata_source_entries,
    snapshot_revision,
    vacuum_into,
)
from flightsite.config.paths import config_path, secrets_path
from flightsite.db.engine import database_path

#: Backup directory inside the data directory (``docs/ARCHITECTURE.md`` §2.1).
BACKUPS_DIRNAME = "backups"

#: ``strftime`` pattern for the timestamp in an archive's filename.
FILENAME_TIMESTAMP = "%Y%m%dT%H%M%SZ"

#: Prefix of every archive this command writes.
FILENAME_PREFIX = "flightsite-backup-"

FILENAME_SUFFIX = ".tar.gz"


@dataclass(frozen=True, slots=True)
class BackupResult:
    """What a completed backup produced."""

    path: Path
    manifest: Manifest
    size_bytes: int

    def render(self) -> str:
        """The summary ``flightsite-backup create`` prints."""
        lines = [
            f"wrote {self.path} ({self.size_bytes} bytes)",
            f"  flightsite version: {self.manifest.flightsite_version}",
            f"  schema revision:    {self.manifest.schema_revision or '(unstamped)'}",
            f"  created (UTC):      {self.manifest.created_utc}",
            f"  includes secrets:   {'yes' if self.manifest.includes_secrets else 'no'}",
            "  contents:           " + ", ".join(sorted(self.manifest.file_names)),
        ]
        return "\n".join(lines)


def default_backup_dir(data_dir: Path) -> Path:
    """Where backups land when ``--out`` is not given."""
    return data_dir / BACKUPS_DIRNAME


def archive_name(created: datetime) -> str:
    """Archive filename for a backup created at ``created``."""
    return (
        f"{FILENAME_PREFIX}{created.astimezone(UTC).strftime(FILENAME_TIMESTAMP)}{FILENAME_SUFFIX}"
    )


def create_backup(
    data_dir: Path,
    *,
    include_secrets: bool = False,
    out_dir: Path | None = None,
    now: Callable[[], datetime] | None = None,
) -> BackupResult:
    """Create a backup of the installation rooted at ``data_dir``.

    Args:
        data_dir: the FlightSite data directory to back up.
        include_secrets: also archive ``secrets.yaml`` (``docs/SECURITY.md`` §3).
        out_dir: destination directory; defaults to ``<data_dir>/backups``.
        now: clock injection point for tests.

    Raises:
        BackupError: if there is no database to back up, the destination is
            unusable, or an archive of the same name already exists.
    """
    clock = now or _utc_now
    created = clock().astimezone(UTC)

    database = database_path(data_dir)
    if not database.exists():
        raise BackupError(
            f"no FlightSite database at {database} — is {data_dir} really a data directory?"
        )

    destination_dir = out_dir if out_dir is not None else default_backup_dir(data_dir)
    try:
        destination_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise BackupError(f"cannot create backup directory {destination_dir}: {exc}") from exc

    final_path = destination_dir / archive_name(created)
    if final_path.exists():
        raise BackupError(
            f"{final_path} already exists; a backup for this second has already been taken"
        )

    # The workspace lives beside the finished archive so the snapshot and the
    # final rename stay on one filesystem, and so a Pi's small /tmp is never
    # asked to hold a multi-gigabyte database.
    workspace = Path(tempfile.mkdtemp(dir=destination_dir, prefix=".flightsite-backup-"))
    temp_archive = destination_dir / f".{final_path.name}.tmp"
    try:
        sources = _stage(workspace, data_dir, database, include_secrets=include_secrets)
        manifest = _build_manifest(workspace, sources, created=created)
        manifest_file = workspace / MANIFEST_MEMBER
        manifest_file.write_text(manifest.to_json(), encoding="utf-8", newline="\n")

        members = {MANIFEST_MEMBER: manifest_file}
        members.update(sources)
        temp_archive.unlink(missing_ok=True)
        archive_io.write_archive(temp_archive, members, mtime=int(created.timestamp()))
        os.replace(temp_archive, final_path)
    except BaseException:
        temp_archive.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(workspace, ignore_errors=True)

    return BackupResult(path=final_path, manifest=manifest, size_bytes=final_path.stat().st_size)


def _stage(
    workspace: Path, data_dir: Path, database: Path, *, include_secrets: bool
) -> dict[str, Path]:
    """Collect the payload files into ``workspace``, keyed by member name."""
    staged: dict[str, Path] = {}

    snapshot = workspace / DATABASE_MEMBER
    vacuum_into(database, snapshot)
    staged[DATABASE_MEMBER] = snapshot

    config = config_path(data_dir)
    if config.exists():
        shutil.copy2(config, workspace / CONFIG_MEMBER)
        staged[CONFIG_MEMBER] = workspace / CONFIG_MEMBER

    if include_secrets:
        secrets = secrets_path(data_dir)
        if secrets.exists():
            shutil.copy2(secrets, workspace / SECRETS_MEMBER)
            staged[SECRETS_MEMBER] = workspace / SECRETS_MEMBER

    return staged


def _build_manifest(workspace: Path, sources: dict[str, Path], *, created: datetime) -> Manifest:
    snapshot = workspace / DATABASE_MEMBER
    entries: list[FileEntry] = []
    for name, path in sorted(sources.items()):
        digest = archive_io.digest_file(path)
        entries.append(FileEntry(name=name, sha256=digest.sha256, size_bytes=digest.size_bytes))

    return Manifest(
        format_version=FORMAT_VERSION,
        flightsite_version=__version__,
        schema_revision=snapshot_revision(snapshot),
        created_utc=utc_iso(created),
        includes_secrets=SECRETS_MEMBER in sources,
        files=tuple(entries),
        metadata_sources=metadata_source_entries(snapshot),
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "BACKUPS_DIRNAME",
    "FILENAME_PREFIX",
    "FILENAME_SUFFIX",
    "FILENAME_TIMESTAMP",
    "BackupResult",
    "archive_name",
    "create_backup",
    "default_backup_dir",
]
