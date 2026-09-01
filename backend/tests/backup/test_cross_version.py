"""Cross-version restore (SPEC §72, roadmap 043 ACs 2 and 3).

Two directions, both required:

* an **older** backup restores into this build and is migrated to head by the
  ordinary startup sequence — proven with a real earlier revision produced by
  the migration harness's downgrade, not a hand-built fixture file;
* a **newer** backup is refused, because this build has no migration that could
  bring the schema back.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flightsite.backup import (
    SchemaCompatibilityError,
    SchemaRelation,
    check_schema,
    restore_backup,
    verify_archive,
)
from flightsite.counters import counters
from flightsite.db import Database, database_path, migrate
from flightsite.db.startup import DATABASE_SUBSYSTEM, initialize_database
from flightsite.readiness import ReadinessRegistry
from tests.backup.conftest import fixed_clock, make_backup, repack, sqlite_scalar, write_sightings
from tests.db.harness import INITIAL_REVISION

#: An earlier revision that predates several tables — far enough back that
#: "restore then migrate" is doing real work, not a no-op.
OLDER_REVISION = "0004"


def test_head_is_reported_as_same() -> None:
    verdict = check_schema(migrate.head_revision())

    assert verdict.relation is SchemaRelation.SAME
    assert verdict.restorable
    assert not verdict.migration_required
    assert "no migration needed" in verdict.summary()


def test_an_ancestor_revision_is_older_and_migratable() -> None:
    verdict = check_schema(INITIAL_REVISION)

    assert verdict.relation is SchemaRelation.OLDER
    assert verdict.restorable
    assert verdict.migration_required
    assert "migrate it forward on the next start" in verdict.summary()


def test_an_unknown_revision_is_refused() -> None:
    verdict = check_schema("deadbeef")

    assert verdict.relation is SchemaRelation.UNKNOWN
    assert not verdict.restorable
    assert "newer FlightSite" in verdict.summary()


def test_an_unstamped_database_is_treated_as_base() -> None:
    verdict = check_schema(None)

    assert verdict.relation is SchemaRelation.OLDER
    assert "(unstamped)" in verdict.summary()


async def test_an_old_backup_restores_and_migrates_to_head_on_startup(
    data_dir: Path, tmp_path: Path
) -> None:
    """The rollback path of ``docs/RELEASE.md``, end to end."""
    # 1. Build a data directory at an earlier real revision, the way an older
    #    release left it: upgrade to head, then downgrade through the graph.
    source = Database(database_path(data_dir))
    try:
        await source.upgrade_to("head")
        await source.downgrade_to(OLDER_REVISION)
        assert await source.current_revision() == OLDER_REVISION
        await write_sightings(source, count=3)
    finally:
        await source.dispose()

    # 2. Back it up. The manifest must record the old revision, not head.
    archive = make_backup(data_dir)
    report = verify_archive(archive)
    assert report.manifest is not None
    assert report.manifest.schema_revision == OLDER_REVISION
    assert report.compatibility is not None
    assert report.compatibility.migration_required
    assert report.ok

    # 3. Restore into a fresh data directory.
    target = tmp_path / "upgraded-host"
    result = restore_backup(archive, target, confirm=True, now=fixed_clock())
    assert result.migration_required
    restored_db = database_path(target)
    assert sqlite_scalar(restored_db, "SELECT version_num FROM alembic_version") == OLDER_REVISION

    # 4. Start FlightSite on it: the ordinary startup sequence migrates to head.
    database = Database(restored_db)
    readiness = ReadinessRegistry()
    readiness.register(DATABASE_SUBSYSTEM)
    try:
        assert await initialize_database(database, readiness, counters=counters) is True
        assert await database.current_revision() == migrate.head_revision()
        assert await database.quick_check() == ["ok"]
    finally:
        await database.dispose()

    assert readiness.snapshot()[DATABASE_SUBSYSTEM] is True
    # The pre-migration rows survived the upgrade.
    assert sqlite_scalar(restored_db, "SELECT COUNT(*) FROM sightings") == 3


async def test_a_newer_schema_backup_is_refused_by_verify_and_restore(
    data_dir: Path, populated_db: Path, tmp_path: Path
) -> None:
    archive = make_backup(data_dir)
    from_the_future = repack(
        archive,
        tmp_path / "future.tar.gz",
        mutate_manifest=lambda manifest: manifest.__setitem__("schema_revision", "0999_warp_drive"),
    )

    report = verify_archive(from_the_future)
    assert not report.ok
    assert any("not part of this build's migration history" in p for p in report.problems)
    assert "Upgrade FlightSite" in report.render()

    with pytest.raises(SchemaCompatibilityError):
        restore_backup(from_the_future, tmp_path / "victim", confirm=True, now=fixed_clock())


async def test_an_unstamped_snapshot_restores_and_migrates_from_base(
    data_dir: Path, tmp_path: Path
) -> None:
    """A backup of a data directory that was created but never migrated."""
    import sqlite3

    path = database_path(data_dir)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE placeholder (x INTEGER)")
    connection.commit()
    connection.close()

    archive = make_backup(data_dir)
    report = verify_archive(archive)
    assert report.ok
    assert report.manifest is not None
    assert report.manifest.schema_revision is None
    assert report.manifest.metadata_sources == ()

    target = tmp_path / "from-blank"
    restore_backup(archive, target, confirm=True, now=fixed_clock())

    database = Database(database_path(target))
    readiness = ReadinessRegistry()
    readiness.register(DATABASE_SUBSYSTEM)
    try:
        assert await initialize_database(database, readiness, counters=counters) is True
        assert await database.current_revision() == migrate.head_revision()
    finally:
        await database.dispose()
