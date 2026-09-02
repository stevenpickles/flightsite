"""Creating backups: contents, manifest correctness, secrets policy."""

from __future__ import annotations

import tarfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from flightsite import __version__
from flightsite.backup import (
    CONFIG_MEMBER,
    DATABASE_MEMBER,
    FORMAT_VERSION,
    MANIFEST_MEMBER,
    SECRETS_MEMBER,
    BackupError,
    archive_name,
    create_backup,
    default_backup_dir,
)
from flightsite.backup import archive as archive_io
from flightsite.backup.snapshot import quick_check
from flightsite.config import ConfigStore
from flightsite.db import migrate
from tests.backup.conftest import (
    FIXED_NOW,
    fixed_clock,
    read_manifest_dict,
    read_members,
    sqlite_scalar,
)
from tests.conftest import SECRET_SENTINEL


async def test_backup_lands_in_the_documented_location(data_dir: Path, populated_db: Path) -> None:
    result = create_backup(data_dir, now=fixed_clock())

    assert result.path.parent == default_backup_dir(data_dir)
    assert result.path.name == "flightsite-backup-20260901T120000Z.tar.gz"
    assert result.path.exists()
    assert result.size_bytes == result.path.stat().st_size


async def test_backup_contains_database_config_and_manifest(
    data_dir: Path, populated_db: Path, config_files: ConfigStore
) -> None:
    result = create_backup(data_dir, now=fixed_clock())

    assert set(read_members(result.path)) == {MANIFEST_MEMBER, DATABASE_MEMBER, CONFIG_MEMBER}


async def test_manifest_records_version_revision_and_checksums(
    data_dir: Path, populated_db: Path, config_files: ConfigStore
) -> None:
    result = create_backup(data_dir, now=fixed_clock())
    manifest = read_manifest_dict(result.path)

    assert manifest["format_version"] == FORMAT_VERSION
    assert manifest["flightsite_version"] == __version__
    assert manifest["schema_revision"] == migrate.head_revision()
    assert manifest["created_utc"] == "2026-09-01T12:00:00Z"
    assert manifest["includes_secrets"] is False

    members = read_members(result.path)
    for name, entry in manifest["files"].items():
        assert entry["size_bytes"] == len(members[name])
        assert len(entry["sha256"]) == 64


async def test_manifest_checksums_match_the_archived_bytes(
    data_dir: Path, populated_db: Path
) -> None:
    import hashlib

    result = create_backup(data_dir, now=fixed_clock())
    members = read_members(result.path)
    manifest = read_manifest_dict(result.path)

    for name, entry in manifest["files"].items():
        assert hashlib.sha256(members[name]).hexdigest() == entry["sha256"]


async def test_manifest_records_metadata_source_versions(
    data_dir: Path, populated_db: Path
) -> None:
    manifest = read_manifest_dict(create_backup(data_dir, now=fixed_clock()).path)

    assert manifest["metadata_sources"] == [
        {
            "source": "opensky",
            "dataset_version": "2026-08-01",
            "last_success": "2025-08-24T01:46:40Z",
        }
    ]


async def test_snapshot_is_a_healthy_standalone_database(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    result = create_backup(data_dir, now=fixed_clock())

    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(result.path, "r:gz") as handle:
        member = handle.extractfile(DATABASE_MEMBER)
        assert member is not None
        (extracted / DATABASE_MEMBER).write_bytes(member.read())

    snapshot = extracted / DATABASE_MEMBER
    assert quick_check(snapshot) == ["ok"]
    assert sqlite_scalar(snapshot, "SELECT COUNT(*) FROM sightings") == 5


async def test_secrets_are_excluded_unless_requested(
    data_dir: Path, populated_db: Path, config_files: ConfigStore
) -> None:
    result = create_backup(data_dir, now=fixed_clock())

    members = read_members(result.path)
    assert SECRETS_MEMBER not in members
    assert result.manifest.includes_secrets is False
    assert SECRET_SENTINEL.encode() not in b"".join(members.values())


async def test_secrets_are_included_and_declared_when_requested(
    data_dir: Path, populated_db: Path, config_files: ConfigStore
) -> None:
    result = create_backup(data_dir, include_secrets=True, now=fixed_clock())

    members = read_members(result.path)
    assert SECRET_SENTINEL.encode() in members[SECRETS_MEMBER]
    assert result.manifest.includes_secrets is True
    assert read_manifest_dict(result.path)["includes_secrets"] is True


async def test_include_secrets_stays_honest_when_there_are_no_secrets(
    data_dir: Path, populated_db: Path
) -> None:
    """No ``secrets.yaml`` means the manifest says ``false``, not ``true``."""
    result = create_backup(data_dir, include_secrets=True, now=fixed_clock())

    assert SECRETS_MEMBER not in read_members(result.path)
    assert result.manifest.includes_secrets is False


async def test_backup_of_a_data_dir_without_config_still_works(
    data_dir: Path, populated_db: Path
) -> None:
    result = create_backup(data_dir, now=fixed_clock())

    assert set(read_members(result.path)) == {MANIFEST_MEMBER, DATABASE_MEMBER}


async def test_out_dir_overrides_the_default_location(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "usb-stick" / "flightsite"
    result = create_backup(data_dir, out_dir=elsewhere, now=fixed_clock())

    assert result.path.parent == elsewhere
    assert not default_backup_dir(data_dir).exists()


async def test_backup_refuses_a_data_dir_with_no_database(data_dir: Path) -> None:
    with pytest.raises(BackupError, match="no FlightSite database"):
        create_backup(data_dir, now=fixed_clock())


async def test_backup_refuses_to_overwrite_an_existing_archive(
    data_dir: Path, populated_db: Path
) -> None:
    create_backup(data_dir, now=fixed_clock())

    with pytest.raises(BackupError, match="already exists"):
        create_backup(data_dir, now=fixed_clock())


async def test_backup_leaves_no_temporary_files_behind(data_dir: Path, populated_db: Path) -> None:
    result = create_backup(data_dir, now=fixed_clock())

    assert [path.name for path in result.path.parent.iterdir()] == [result.path.name]


async def test_a_failed_backup_leaves_the_destination_clean(
    data_dir: Path, populated_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("flightsite.backup.create.archive_io.write_archive", explode)

    with pytest.raises(OSError, match="disk full"):
        create_backup(data_dir, now=fixed_clock())

    assert list(default_backup_dir(data_dir).iterdir()) == []


def test_archive_name_is_utc_regardless_of_the_clock_s_zone() -> None:
    from datetime import timedelta, timezone

    local = FIXED_NOW.astimezone(timezone(timedelta(hours=9)))

    assert archive_name(local) == archive_name(FIXED_NOW)
    assert archive_name(datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)).startswith(
        "flightsite-backup-20260102T030405Z"
    )


async def test_result_render_summarises_the_backup(data_dir: Path, populated_db: Path) -> None:
    rendered = create_backup(data_dir, now=fixed_clock()).render()

    assert "includes secrets:   no" in rendered
    assert migrate.head_revision() in rendered
    assert DATABASE_MEMBER in rendered


def test_the_archive_is_written_at_the_chosen_compression_level(
    data_dir: Path, populated_db: Path
) -> None:
    """Issue #117: level 6, not tarfile's default of 9.

    Slice 050 measured both levels compressing a real database to the same
    0.188 ratio while level 6 ran 2.7x faster, on a backup whose cost is
    dominated by gzip. The level is asserted through the container rather than
    by reading the constant back: gzip records it in the ``XFL`` byte of its
    header — 2 for "best compression", 4 for "fastest", 0 for anything else —
    so this fails if the level drifts back to 9 by any route, including
    somebody dropping the ``compresslevel`` argument.
    """
    result = create_backup(data_dir, now=fixed_clock())

    header = result.path.read_bytes()[:10]
    assert header[:2] == b"\x1f\x8b", "not a gzip container"
    assert header[8] == 0, (
        f"XFL byte {header[8]} says the archive was written at an extreme "
        f"compression level; {archive_io.COMPRESS_LEVEL} was intended"
    )
