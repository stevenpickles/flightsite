"""Fixtures and helpers for the backup tests.

The helpers here build and *tamper with* archives, because half of what this
slice must prove is that damaged or mislabelled archives are refused. Repacking
goes through :func:`repack` so a test can express "same archive, but the
manifest claims a future schema revision" or "same archive, but one byte of the
database is flipped" in a line.
"""

from __future__ import annotations

import json
import sqlite3
import tarfile
from collections.abc import AsyncIterator, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from flightsite.backup.manifest import MANIFEST_MEMBER
from flightsite.config import ConfigStore, Settings
from flightsite.db import Database, database_path
from flightsite.db.models import Aircraft, MetadataSource, Sighting
from tests.conftest import SECRET_SENTINEL

#: A fixed creation moment, so archive names and manifests are predictable.
FIXED_NOW = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)


def fixed_clock(moment: datetime = FIXED_NOW) -> Callable[[], datetime]:
    """A ``now`` callable for the backup/restore commands."""
    return lambda: moment


@pytest.fixture
def data_dir(isolated_data_dir: Path) -> Path:
    """The test's data directory (from the root ``conftest``)."""
    return isolated_data_dir


@pytest.fixture
def config_files(data_dir: Path) -> ConfigStore:
    """A data directory carrying both ``config.yaml`` and ``secrets.yaml``."""
    store = ConfigStore(data_dir)
    settings = Settings.model_validate(
        {"data_dir": data_dir, "enrichment": {"aerodatabox_api_key": SECRET_SENTINEL}}
    )
    store.save(settings)
    store.save_secrets(settings)
    return store


@pytest.fixture
async def populated_db(data_dir: Path) -> AsyncIterator[Path]:
    """A migrated database at head holding a small, self-consistent data set."""
    path = database_path(data_dir)
    database = Database(path)
    try:
        await database.upgrade_to("head")
        await write_sightings(database, count=5)
        await write_metadata_source(
            database,
            source="opensky",
            dataset_version="2026-08-01",
            last_success_ms=1_756_000_000_000,
        )
    finally:
        await database.dispose()
    yield path


async def insert_pair(session: AsyncSession, index: int) -> None:
    """Insert one aircraft and its sighting on ``session``, without committing.

    Called inside a writer session so the pair lands in a single transaction:
    that is the atomic unit a snapshot must never split.
    """
    aircraft = Aircraft(
        icao24=f"{index:06x}",
        first_seen_ms=1_700_000_000_000 + index,
        last_seen_ms=1_700_000_000_000 + index,
        sighting_count=1,
    )
    session.add(aircraft)
    await session.flush()
    session.add(
        Sighting(
            aircraft_id=aircraft.id,
            started_ms=1_700_000_000_000 + index,
            ended_ms=1_700_000_000_500 + index,
        )
    )


async def write_sightings(database: Database, *, count: int, start: int = 0) -> None:
    """Insert ``count`` aircraft each with one sighting, in one transaction each.

    Aircraft and its sighting are written together so that a snapshot may never
    legitimately contain a sighting whose aircraft is missing — that is the
    invariant the live-backup consistency test checks.
    """
    for index in range(start, start + count):
        async with database.writer_session() as session:
            await insert_pair(session, index)


async def write_metadata_source(
    database: Database, *, source: str, dataset_version: str, last_success_ms: int
) -> None:
    """Seed one ``metadata_sources`` row so the manifest has something to record."""
    async with database.writer_session() as session:
        session.add(
            MetadataSource(
                source=source,
                status="ok",
                last_attempt_ms=last_success_ms,
                last_success_ms=last_success_ms,
                dataset_version=dataset_version,
                row_count=42,
            )
        )


def make_backup(data_dir: Path, *, include_secrets: bool = False) -> Path:
    """Take a backup at :data:`FIXED_NOW` and return the archive path."""
    from flightsite.backup import create_backup

    return create_backup(data_dir, include_secrets=include_secrets, now=fixed_clock()).path


def read_members(archive: Path) -> dict[str, bytes]:
    """Every member of an archive as raw bytes."""
    members: dict[str, bytes] = {}
    with tarfile.open(archive, "r:gz") as handle:
        for info in handle.getmembers():
            stream = handle.extractfile(info)
            members[info.name] = b"" if stream is None else stream.read()
    return members


def read_manifest_dict(archive: Path) -> dict[str, Any]:
    """The archive's manifest as a plain dict."""
    payload = read_members(archive)[MANIFEST_MEMBER]
    parsed: dict[str, Any] = json.loads(payload)
    return parsed


def write_members(destination: Path, members: Mapping[str, bytes]) -> Path:
    """Write ``members`` as a gzip tar at ``destination``."""
    destination.unlink(missing_ok=True)
    with tarfile.open(destination, "w:gz") as handle:
        for name, payload in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mtime = int(FIXED_NOW.timestamp())
            handle.addfile(info, BytesReader(payload))
    return destination


def repack(
    archive: Path,
    destination: Path,
    *,
    mutate: Callable[[dict[str, bytes]], None] | None = None,
    mutate_manifest: Callable[[dict[str, Any]], None] | None = None,
) -> Path:
    """Rebuild ``archive`` at ``destination`` with the given mutations applied."""
    members = read_members(archive)
    if mutate_manifest is not None:
        manifest = json.loads(members[MANIFEST_MEMBER])
        mutate_manifest(manifest)
        members[MANIFEST_MEMBER] = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    if mutate is not None:
        mutate(members)
    return write_members(destination, members)


def flip_byte(payload: bytes, offset: int) -> bytes:
    """Return ``payload`` with the byte at ``offset`` inverted."""
    mutable = bytearray(payload)
    mutable[offset] ^= 0xFF
    return bytes(mutable)


class BytesReader:
    """Minimal read-only stream over bytes for :meth:`tarfile.TarFile.addfile`."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            size = len(self._payload) - self._offset
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def file_bytes(path: Path) -> bytes:
    """Read a file. A plain function so ``async`` tests stay free of blocking I/O calls."""
    return path.read_bytes()


def glob_names(directory: Path, pattern: str) -> list[str]:
    """Sorted names of the entries in ``directory`` matching ``pattern``."""
    return sorted(path.name for path in directory.glob(pattern))


def tree_mtimes(directory: Path) -> dict[str, int]:
    """Modification times of every path under ``directory``, keyed by name."""
    return {str(path): path.stat().st_mtime_ns for path in sorted(directory.rglob("*"))}


def sqlite_rows(path: Path, sql: str) -> list[tuple[Any, ...]]:
    """Run a query against a database file with stdlib ``sqlite3``.

    Deliberately not through the ORM: an assertion about what a *restored file*
    contains must not be satisfiable by the application's own machinery.
    """
    connection = sqlite3.connect(path)
    try:
        return [tuple(row) for row in connection.execute(sql).fetchall()]
    finally:
        connection.close()


def sqlite_scalar(path: Path, sql: str) -> Any:
    """Run a single-value query against a database file."""
    return sqlite_rows(path, sql)[0][0]
