"""Failure paths: every refusal must be a clear message, never a traceback.

A backup tool earns trust by how it behaves when something is wrong, so the
error handlers get the same coverage as the happy path (SPEC §84 puts
backup/restore in the critical set).
"""

from __future__ import annotations

import sqlite3
import tarfile
from pathlib import Path

import pytest

from flightsite.backup import (
    DATABASE_MEMBER,
    MANIFEST_MEMBER,
    ArchiveValidationError,
    BackupError,
    RestoreError,
    SnapshotError,
    create_backup,
    restore_backup,
    verify_archive,
)
from flightsite.backup import archive as archive_io
from flightsite.backup.snapshot import metadata_source_entries, quick_check, vacuum_into
from tests.backup.conftest import FIXED_NOW, BytesReader, fixed_clock, make_backup, read_members

# --------------------------------------------------------------- snapshotting


def test_snapshot_refuses_a_missing_source(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError, match="no database to back up"):
        vacuum_into(tmp_path / "absent.sqlite3", tmp_path / "out.sqlite3")


def test_snapshot_refuses_to_overwrite_its_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    sqlite3.connect(source).close()
    destination = tmp_path / "out.sqlite3"
    destination.write_bytes(b"")

    with pytest.raises(SnapshotError, match="destination already exists"):
        vacuum_into(source, destination)


def test_snapshot_of_a_non_database_is_reported(tmp_path: Path) -> None:
    junk = tmp_path / "not-a-database.sqlite3"
    junk.write_bytes(b"SQLite format 3\x00 but not really" + b"\x00" * 200)

    with pytest.raises(SnapshotError, match="SQLite snapshot"):
        vacuum_into(junk, tmp_path / "out.sqlite3")

    assert not (tmp_path / "out.sqlite3").exists()


def test_integrity_check_of_a_non_database_is_reported(tmp_path: Path) -> None:
    junk = tmp_path / "junk.sqlite3"
    junk.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)

    with pytest.raises(SnapshotError, match="integrity check"):
        quick_check(junk)


def test_reading_metadata_sources_from_a_non_database_is_reported(tmp_path: Path) -> None:
    junk = tmp_path / "junk.sqlite3"
    junk.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4096)

    with pytest.raises(SnapshotError, match="reading metadata sources"):
        metadata_source_entries(junk)


# ------------------------------------------------------------------- creating


async def test_create_reports_an_unusable_output_directory(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    blocked = tmp_path / "a-file-not-a-directory"
    blocked.write_text("in the way", encoding="utf-8")

    with pytest.raises(BackupError, match="cannot create backup directory"):
        create_backup(data_dir, out_dir=blocked, now=fixed_clock())


# ------------------------------------------------------------------ restoring


async def test_restore_reports_an_unusable_data_directory(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    archive = make_backup(data_dir)
    blocked = tmp_path / "a-file-not-a-directory"
    blocked.write_text("in the way", encoding="utf-8")

    with pytest.raises(RestoreError, match="cannot create data directory"):
        restore_backup(archive, blocked, confirm=True, now=fixed_clock())


# -------------------------------------------------------------- archive I/O


async def test_a_truncated_archive_fails_while_reading_the_index(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    """The tar index is interleaved with the data, so truncation breaks it."""
    archive = make_backup(data_dir)
    truncated = tmp_path / "truncated.tar.gz"
    payload = archive.read_bytes()
    truncated.write_bytes(payload[: len(payload) // 2])

    report = verify_archive(truncated)

    assert not report.ok
    assert any(
        "unreadable" in problem or "not a readable" in problem for problem in report.problems
    )


async def test_a_member_the_manifest_lists_but_that_is_a_symlink_is_refused(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    """A hostile archive cannot smuggle a link in under a listed member's name."""
    members = read_members(make_backup(data_dir))
    hostile = tmp_path / "hostile.tar.gz"
    with tarfile.open(hostile, "w:gz") as handle:
        manifest = tarfile.TarInfo(MANIFEST_MEMBER)
        manifest.size = len(members[MANIFEST_MEMBER])
        manifest.mtime = int(FIXED_NOW.timestamp())
        handle.addfile(manifest, BytesReader(members[MANIFEST_MEMBER]))

        link = tarfile.TarInfo(DATABASE_MEMBER)
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        link.mtime = int(FIXED_NOW.timestamp())
        handle.addfile(link)

    report = verify_archive(hostile)

    assert not report.ok
    assert any("is not a regular file" in problem for problem in report.problems)


async def test_a_member_that_fails_mid_read_is_reported_not_raised(
    data_dir: Path, populated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An I/O error part-way through a member becomes a validation problem."""
    archive = make_backup(data_dir)

    class FailingStream:
        def read(self, size: int = -1) -> bytes:
            raise OSError("input/output error")

        def close(self) -> None:
            return None

    with archive_io.open_archive(archive) as handle:
        monkeypatch.setattr(handle, "extractfile", lambda info: FailingStream())

        with pytest.raises(ArchiveValidationError, match="could not be read"):
            archive_io.copy_member(handle, DATABASE_MEMBER, None)

        with pytest.raises(ArchiveValidationError, match="could not be read"):
            archive_io.read_member(handle, MANIFEST_MEMBER)


async def test_reading_a_member_the_archive_lacks_is_reported(
    data_dir: Path, populated_db: Path
) -> None:
    archive = make_backup(data_dir)

    with (
        archive_io.open_archive(archive) as handle,
        pytest.raises(ArchiveValidationError, match="missing member"),
    ):
        archive_io.read_member(handle, "secrets.yaml")
