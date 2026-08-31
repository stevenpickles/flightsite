"""Migration tests: empty upgrade, fixture upgrade, single head, schema drift.

The last two are the ``alembic check`` gate expressed as tests, which is why
the backend CI workflow needs no extra Alembic step: a divergent head or a
model/migration mismatch fails ``uv run pytest`` in exactly the place a
developer is already looking (``docs/DEVELOPMENT.md`` §"Parallel migrations",
rule 3).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flightsite.db import Database, database_path, migrate
from tests.db.harness import (
    INITIAL_REVISION,
    autogenerate_diffs,
    column_types,
    create_sql,
    database_at,
    not_null_columns,
    primary_key_columns,
    read_meta_rows,
    seed_meta_rows,
    table_names,
    upgrade_empty_database,
)

EXPECTED_META_COLUMNS = {"key": "TEXT", "value": "TEXT", "updated_ms": "INTEGER"}


def test_migration_graph_has_exactly_one_head() -> None:
    """Two heads mean two slices added revisions in parallel without reconciling."""
    heads = migrate.heads()

    assert len(heads) == 1, f"divergent Alembic heads: {heads}"
    assert migrate.head_revision() == heads[0]


def test_every_revision_file_is_reachable_from_the_head() -> None:
    """No orphaned revision file sitting outside the linear history."""
    walked = {revision.revision for revision in migrate.script_directory().walk_revisions()}
    on_disk = list((migrate.MIGRATIONS_DIR / "versions").glob("rev_*.py"))

    assert len(walked) == len(on_disk), (
        f"{len(on_disk)} revision files but {len(walked)} reachable from head: {sorted(walked)}"
    )


def test_the_database_file_does_not_exist_before_first_start(db_path: Path) -> None:
    """Precondition for the empty-upgrade test: nothing pre-creates the file."""
    assert not db_path.exists()


async def test_upgrading_an_empty_database_creates_the_schema(db_path: Path) -> None:
    stamped = await upgrade_empty_database(db_path)

    assert stamped == migrate.head_revision()
    assert "meta" in table_names(db_path)
    assert "alembic_version" in table_names(db_path)


async def test_meta_table_matches_the_data_model(db_path: Path) -> None:
    """Column names, types, nullability, PK and WITHOUT ROWID per DATA_MODEL §2.1."""
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "meta") == EXPECTED_META_COLUMNS
    assert not_null_columns(db_path, "meta") == {"key", "value", "updated_ms"}
    assert primary_key_columns(db_path, "meta") == ["key"]
    assert "WITHOUT ROWID" in create_sql(db_path, "meta").upper()


async def test_upgrade_is_idempotent(db_path: Path) -> None:
    """Startup runs `upgrade head` on every boot, including already-current ones."""
    await upgrade_empty_database(db_path)

    async with database_at(db_path, "head") as database:
        assert await database.current_revision() == migrate.head_revision()

    assert "meta" in table_names(db_path)


async def test_fixture_database_at_the_initial_revision_upgrades_to_head(db_path: Path) -> None:
    """The upgrade path an existing install takes: old schema + real rows, forward.

    The fixture is built at the initial revision and seeded with raw SQL — the
    way an older FlightSite would have left it — then upgraded to head. Data
    must survive, and the file must end up stamped at head.
    """
    async with database_at(db_path, INITIAL_REVISION) as database:
        assert await database.current_revision() == INITIAL_REVISION

    fixture_rows = {"install_id": "fixture-install", "t0_ms": "1756600000000"}
    seed_meta_rows(db_path, fixture_rows, updated_ms=1_756_600_000_000)

    async with database_at(db_path, "head") as database:
        assert await database.current_revision() == migrate.head_revision()
        assert await autogenerate_diffs(database) == []

    assert read_meta_rows(db_path) == fixture_rows


async def test_models_and_migrations_do_not_drift(migrated_database: Database) -> None:
    """`alembic check` as a test: autogenerate must find nothing to do."""
    diffs = await autogenerate_diffs(migrated_database)

    assert diffs == [], f"models and migrations disagree: {diffs}"


async def test_downgrade_removes_the_schema_again(migrated_database: Database) -> None:
    """Rollback is supported where practical (SPEC §107)."""
    assert "meta" in table_names(migrated_database.path)

    await migrated_database.downgrade_to("base")

    assert "meta" not in table_names(migrated_database.path)
    assert await migrated_database.current_revision() is None


async def test_upgrade_creates_the_data_directory_if_missing(isolated_data_dir: Path) -> None:
    """First boot on a fresh bind mount must not fail on a missing directory."""
    nested = isolated_data_dir / "nested" / "data"
    assert not nested.exists()

    await upgrade_empty_database(database_path(nested))

    assert database_path(nested).exists()


def test_build_config_escapes_percent_signs_in_urls() -> None:
    """A URL with '%' must survive ConfigParser interpolation intact."""
    url = "sqlite+aiosqlite:///C:/tmp/100%25/flightsite.sqlite3"

    config = migrate.build_config(url)

    assert config.get_main_option("sqlalchemy.url") == url


def test_head_revision_rejects_a_divergent_graph(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migrate, "heads", lambda: ("aaaa", "bbbb"))

    with pytest.raises(RuntimeError, match="exactly one Alembic head"):
        migrate.head_revision()
