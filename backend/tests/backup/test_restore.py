"""Restore: confirmation gating, validation refusals, and the atomic-ish swap."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from flightsite.backup import (
    CONFIG_MEMBER,
    DATABASE_MEMBER,
    SECRETS_MEMBER,
    ArchiveValidationError,
    ConfirmationRequiredError,
    RestoreError,
    SchemaCompatibilityError,
    restore_backup,
)
from flightsite.backup.restore import DATABASE_SIDECARS, PRESERVED_SUFFIX
from flightsite.backup.snapshot import quick_check
from flightsite.config import ConfigStore
from flightsite.db import Database, database_path
from tests.backup.conftest import (
    file_bytes,
    fixed_clock,
    flip_byte,
    glob_names,
    make_backup,
    repack,
    sqlite_scalar,
    write_sightings,
)
from tests.conftest import SECRET_SENTINEL


async def test_restore_refuses_without_confirmation(data_dir: Path, populated_db: Path) -> None:
    archive = make_backup(data_dir)
    before = file_bytes(populated_db)

    with pytest.raises(ConfirmationRequiredError, match="--confirm"):
        restore_backup(archive, data_dir, confirm=False)

    assert file_bytes(populated_db) == before


async def test_restore_replaces_the_database(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    archive = make_backup(data_dir)

    # Move the installation on: five more sightings after the backup.
    database = Database(populated_db)
    try:
        await write_sightings(database, count=5, start=100)
    finally:
        await database.dispose()
    assert sqlite_scalar(populated_db, "SELECT COUNT(*) FROM sightings") == 10

    result = restore_backup(archive, data_dir, confirm=True, now=fixed_clock())

    assert result.restored == (DATABASE_MEMBER,)
    assert sqlite_scalar(populated_db, "SELECT COUNT(*) FROM sightings") == 5
    assert quick_check(populated_db) == ["ok"]


async def test_restore_into_an_empty_directory(
    data_dir: Path, populated_db: Path, config_files: ConfigStore, tmp_path: Path
) -> None:
    archive = make_backup(data_dir)
    fresh = tmp_path / "new-host-data"

    result = restore_backup(archive, fresh, confirm=True, now=fixed_clock())

    assert sorted(result.restored) == [CONFIG_MEMBER, DATABASE_MEMBER]
    assert sqlite_scalar(database_path(fresh), "SELECT COUNT(*) FROM sightings") == 5
    assert (fresh / CONFIG_MEMBER).exists()


async def test_restore_removes_the_preserved_copies_on_success(
    data_dir: Path, populated_db: Path
) -> None:
    archive = make_backup(data_dir)

    result = restore_backup(archive, data_dir, confirm=True, now=fixed_clock())

    assert result.displaced == (f"{DATABASE_MEMBER}.{PRESERVED_SUFFIX}.20260901T120000Z",)
    assert glob_names(data_dir, f"*.{PRESERVED_SUFFIX}.*") == []


async def test_restore_leaves_no_staging_directory(data_dir: Path, populated_db: Path) -> None:
    archive = make_backup(data_dir)

    restore_backup(archive, data_dir, confirm=True, now=fixed_clock())

    assert glob_names(data_dir, ".flightsite-restore-*") == []


async def test_restore_clears_stale_wal_sidecars(data_dir: Path, populated_db: Path) -> None:
    """A ``-wal`` describing the replaced file must not survive the swap."""
    archive = make_backup(data_dir)
    for sidecar in DATABASE_SIDECARS:
        (data_dir / sidecar).write_bytes(b"stale write-ahead log")

    restore_backup(archive, data_dir, confirm=True, now=fixed_clock())

    for sidecar in DATABASE_SIDECARS:
        assert not (data_dir / sidecar).exists()


async def test_restore_replaces_config_and_secrets_when_the_archive_carries_them(
    data_dir: Path, populated_db: Path, config_files: ConfigStore
) -> None:
    archive = make_backup(data_dir, include_secrets=True)
    config_files.config_path.write_text("map: {}\n", encoding="utf-8")
    config_files.secrets_path.write_text("enrichment:\n  aerodatabox_api_key: changed\n", "utf-8")

    result = restore_backup(archive, data_dir, confirm=True, now=fixed_clock())

    assert result.secrets_restored is True
    assert SECRET_SENTINEL in config_files.secrets_path.read_text(encoding="utf-8")
    assert "map: {}" not in config_files.config_path.read_text(encoding="utf-8")


async def test_restore_leaves_existing_secrets_alone_when_the_archive_has_none(
    data_dir: Path, populated_db: Path, config_files: ConfigStore
) -> None:
    """A secrets-free backup must not silently delete a live API key."""
    archive = make_backup(data_dir)

    result = restore_backup(archive, data_dir, confirm=True, now=fixed_clock())

    assert result.secrets_restored is False
    assert SECRETS_MEMBER not in result.restored
    assert SECRET_SENTINEL in config_files.secrets_path.read_text(encoding="utf-8")
    assert "carried no secrets.yaml" in result.render()


async def test_restore_refuses_a_corrupted_archive_and_changes_nothing(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    archive = make_backup(data_dir)
    before = file_bytes(populated_db)

    def corrupt(members: dict[str, bytes]) -> None:
        members[DATABASE_MEMBER] = flip_byte(members[DATABASE_MEMBER], 4096)

    damaged = repack(archive, tmp_path / "damaged.tar.gz", mutate=corrupt)

    with pytest.raises(ArchiveValidationError, match="checksum mismatch"):
        restore_backup(damaged, data_dir, confirm=True, now=fixed_clock())

    assert file_bytes(populated_db) == before
    assert glob_names(data_dir, ".flightsite-restore-*") == []


async def test_restore_refuses_an_archive_that_is_not_an_archive(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    plain = tmp_path / "readme.txt"
    plain.write_text("hello", encoding="utf-8")

    with pytest.raises(ArchiveValidationError, match="not a readable FlightSite backup archive"):
        restore_backup(plain, data_dir, confirm=True, now=fixed_clock())


async def test_restore_refuses_a_newer_schema_backup(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    """SPEC §72: an older FlightSite must refuse a newer-schema backup."""
    archive = make_backup(data_dir)
    before = file_bytes(populated_db)

    from_the_future = repack(
        archive,
        tmp_path / "future.tar.gz",
        mutate_manifest=lambda manifest: manifest.__setitem__("schema_revision", "9999"),
    )

    with pytest.raises(SchemaCompatibilityError, match="not part of this build's migration"):
        restore_backup(from_the_future, data_dir, confirm=True, now=fixed_clock())

    assert file_bytes(populated_db) == before


async def test_restore_rolls_back_a_failed_swap(
    data_dir: Path, populated_db: Path, config_files: ConfigStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = make_backup(data_dir, include_secrets=True)
    database_before = file_bytes(populated_db)
    config_before = file_bytes(config_files.config_path)
    secrets_before = file_bytes(config_files.secrets_path)

    real_replace = os.replace
    calls: list[int] = []

    def flaky(src: object, dst: object) -> None:
        calls.append(1)
        # Fail once the first payload has landed, so a rollback is genuinely needed.
        if len(calls) == 5:
            raise OSError("read-only file system")
        real_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr("flightsite.backup.restore.os.replace", flaky)

    with pytest.raises(RestoreError, match="left unchanged"):
        restore_backup(archive, data_dir, confirm=True, now=fixed_clock())

    assert file_bytes(populated_db) == database_before
    assert file_bytes(config_files.config_path) == config_before
    assert file_bytes(config_files.secrets_path) == secrets_before
    assert glob_names(data_dir, f"*.{PRESERVED_SUFFIX}.*") == []


async def test_restore_render_states_the_next_step(data_dir: Path, populated_db: Path) -> None:
    archive = make_backup(data_dir)

    rendered = restore_backup(archive, data_dir, confirm=True, now=fixed_clock()).render()

    assert "start FlightSite" in rendered
    assert str(data_dir) in rendered


async def test_restore_replaces_a_stale_staging_directory(
    data_dir: Path, populated_db: Path
) -> None:
    archive = make_backup(data_dir)
    stale = data_dir / ".flightsite-restore-20260901T120000Z"
    stale.mkdir()
    (stale / "leftover").write_text("from an interrupted run", encoding="utf-8")

    restore_backup(archive, data_dir, confirm=True, now=fixed_clock())

    assert not stale.exists()
