"""Migration 0012: schema shape, linear history, drift, dedupe indexes, rollback.

Every assertion reads the database file with stdlib ``sqlite3`` through
:mod:`tests.db.harness`, so "the migration created this" cannot be satisfied by
a model declaration alone.

The two partial unique indexes get their own tests rather than a single
"indexes exist" assertion: they *are* SPEC §48's once-per-sighting-per-rule
guarantee, so what matters is that SQLite refuses the second insert — and that
it still accepts the rows the rule deliberately allows (a second rule on the
same sighting, the same rule on a different sighting, a built-in beside a rule).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from flightsite.db import migrate
from tests.db.harness import (
    autogenerate_diffs,
    column_types,
    create_sql,
    database_at,
    foreign_keys,
    index_names,
    index_sql,
    not_null_columns,
    primary_key_columns,
    table_names,
    upgrade_empty_database,
)

REVISION = "0012"
PREVIOUS = "0011"

TABLES = ("alert_rules", "alert_matches")

#: ``docs/DATA_MODEL.md`` §4.2, column for column.
ALERT_RULES_COLUMNS = {
    "id": "INTEGER",
    "name": "TEXT",
    "description": "TEXT",
    "severity": "TEXT",
    "enabled": "INTEGER",
    "template_key": "TEXT",
    "conditions_json": "TEXT",
    "created_ms": "INTEGER",
    "updated_ms": "INTEGER",
}

#: ``docs/DATA_MODEL.md`` §4.3, column for column.
ALERT_MATCHES_COLUMNS = {
    "id": "INTEGER",
    "rule_id": "INTEGER",
    "builtin_key": "TEXT",
    "sighting_id": "INTEGER",
    "aircraft_id": "INTEGER",
    "matched_ms": "INTEGER",
    "severity": "TEXT",
    "reason": "TEXT",
    "notified": "INTEGER",
}

_RULE_COLUMNS = "(id, name, severity, conditions_json, created_ms, updated_ms)"
_MATCH_COLUMNS = "(rule_id, builtin_key, sighting_id, aircraft_id, matched_ms, severity, reason)"


def _seed(connection: sqlite3.Connection) -> None:
    """An airframe, two sightings of it, and two enabled rules to match with."""
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(
        "INSERT INTO aircraft (id, icao24, first_seen_ms, last_seen_ms) VALUES (1, 'ae1463', 0, 0)"
    )
    connection.execute("INSERT INTO sightings (id, aircraft_id, started_ms) VALUES (10, 1, 0)")
    connection.execute("INSERT INTO sightings (id, aircraft_id, started_ms) VALUES (11, 1, 1)")
    for rule_id in (1, 2):
        connection.execute(
            f"INSERT INTO alert_rules {_RULE_COLUMNS} "
            f"VALUES ({rule_id}, 'R{rule_id}', 'high', '{{\"version\":1}}', 0, 0)"
        )


@pytest.fixture
async def seeded(db_path: Path) -> Path:
    """A database at head with the airframe/sighting/rule rows the tests match on."""
    await upgrade_empty_database(db_path)
    with sqlite3.connect(db_path) as connection:
        _seed(connection)
    return db_path


@pytest.fixture
def connection(seeded: Path) -> Iterator[sqlite3.Connection]:
    """A foreign-key-enforcing connection to the seeded database."""
    with sqlite3.connect(seeded) as open_connection:
        open_connection.execute("PRAGMA foreign_keys = ON")
        yield open_connection


def test_this_revision_sits_directly_on_the_previous_head() -> None:
    """The linear-history rule of ``docs/DEVELOPMENT.md`` §"Parallel migrations"."""
    script = migrate.script_directory().get_revision(REVISION)

    assert script.down_revision == PREVIOUS


async def test_a_database_at_the_previous_revision_upgrades_cleanly(db_path: Path) -> None:
    """The upgrade path an existing install takes."""
    async with database_at(db_path, PREVIOUS) as database:
        assert await database.current_revision() == PREVIOUS
    assert not set(TABLES) & table_names(db_path)

    async with database_at(db_path, REVISION) as database:
        assert await database.current_revision() == REVISION
    assert set(TABLES) <= table_names(db_path)

    async with database_at(db_path, "head") as database:
        assert await autogenerate_diffs(database) == []


async def test_the_alert_rules_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "alert_rules") == ALERT_RULES_COLUMNS
    assert primary_key_columns(db_path, "alert_rules") == ["id"]
    assert not_null_columns(db_path, "alert_rules") == {
        "id",
        "name",
        "severity",
        "enabled",
        "conditions_json",
        "created_ms",
        "updated_ms",
    }


async def test_the_alert_matches_table_matches_the_data_model(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert column_types(db_path, "alert_matches") == ALERT_MATCHES_COLUMNS
    assert primary_key_columns(db_path, "alert_matches") == ["id"]
    assert not_null_columns(db_path, "alert_matches") == {
        "id",
        "sighting_id",
        "aircraft_id",
        "matched_ms",
        "severity",
        "reason",
        "notified",
    }


async def test_alert_matches_declares_exactly_the_three_documented_indexes(
    db_path: Path,
) -> None:
    await upgrade_empty_database(db_path)

    declared = {
        name for name in index_names(db_path, "alert_matches") if not name.startswith("sqlite_")
    }
    assert declared == {
        "ux_amatch_rule_sighting",
        "ux_amatch_builtin_sighting",
        "ix_amatch_matched",
    }


@pytest.mark.parametrize(
    ("index", "predicate"),
    [
        ("ux_amatch_rule_sighting", "rule_id IS NOT NULL"),
        ("ux_amatch_builtin_sighting", "builtin_key IS NOT NULL"),
    ],
)
async def test_the_dedupe_indexes_are_unique_and_partial(
    db_path: Path, index: str, predicate: str
) -> None:
    """Partial, because SQLite treats every ``NULL`` in a unique index as
    distinct: without the ``WHERE`` these would constrain nothing for the
    origin they are not about."""
    await upgrade_empty_database(db_path)

    sql = index_sql(db_path, index).upper()
    assert "UNIQUE" in sql
    assert predicate.upper() in sql


def test_a_rule_can_match_a_sighting_only_once(connection: sqlite3.Connection) -> None:
    """SPEC §48's once-per-sighting-per-rule guarantee, in SQL."""
    connection.execute(
        f"INSERT INTO alert_matches {_MATCH_COLUMNS} VALUES (1, NULL, 10, 1, 5, 'high', 'why')"
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            f"INSERT INTO alert_matches {_MATCH_COLUMNS} "
            "VALUES (1, NULL, 10, 1, 9, 'high', 'why again')"
        )


def test_a_builtin_can_match_a_sighting_only_once(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"INSERT INTO alert_matches {_MATCH_COLUMNS} "
        "VALUES (NULL, 'emergency_7700', 10, 1, 5, 'critical', 'why')"
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            f"INSERT INTO alert_matches {_MATCH_COLUMNS} "
            "VALUES (NULL, 'emergency_7700', 10, 1, 9, 'critical', 'again')"
        )


def test_the_dedupe_indexes_still_allow_every_row_the_rule_permits(
    connection: sqlite3.Connection,
) -> None:
    """A second rule, the same rule on the next sighting, a built-in beside a
    rule, and a second built-in key — the four ways SPEC §48 allows another
    match, none of which the unique indexes may refuse."""
    rows = [
        "(1, NULL, 10, 1, 5, 'high', 'rule 1')",
        "(2, NULL, 10, 1, 5, 'info', 'rule 2, same sighting')",
        "(1, NULL, 11, 1, 5, 'high', 'rule 1, next sighting')",
        "(NULL, 'emergency_7600', 10, 1, 5, 'critical', 'radio failure')",
        "(NULL, 'emergency_7700', 10, 1, 6, 'critical', 'general emergency')",
    ]
    for row in rows:
        connection.execute(f"INSERT INTO alert_matches {_MATCH_COLUMNS} VALUES {row}")

    assert connection.execute("SELECT COUNT(*) FROM alert_matches").fetchone()[0] == len(rows)


def test_a_match_must_name_a_rule_or_a_builtin(connection: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            f"INSERT INTO alert_matches {_MATCH_COLUMNS} VALUES (NULL, NULL, 10, 1, 5, 'info', 'x')"
        )


@pytest.mark.parametrize("table", TABLES)
def test_both_tables_reject_a_severity_outside_the_ladder(
    connection: sqlite3.Connection, table: str
) -> None:
    statement = (
        f"INSERT INTO alert_rules {_RULE_COLUMNS} VALUES (9, 'R', 'urgent', '{{}}', 0, 0)"
        if table == "alert_rules"
        else f"INSERT INTO alert_matches {_MATCH_COLUMNS} VALUES (1, NULL, 10, 1, 5, 'urgent', 'x')"
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute(statement)


async def test_alert_matches_foreign_keys_target_the_documented_tables(db_path: Path) -> None:
    await upgrade_empty_database(db_path)

    assert foreign_keys(db_path, "alert_matches") == {
        ("rule_id", "alert_rules", "id"),
        ("sighting_id", "sightings", "id"),
        ("aircraft_id", "aircraft", "id"),
    }


def test_deleting_a_rule_that_has_matched_is_refused_until_its_matches_go(
    connection: sqlite3.Connection,
) -> None:
    """``rule_id`` has no ``ON DELETE`` action (§4.3) and ADR-0001 enforces
    foreign keys, so the repository deletes a rule's matches with it rather
    than leaving the schema to decide."""
    connection.execute(
        f"INSERT INTO alert_matches {_MATCH_COLUMNS} VALUES (1, NULL, 10, 1, 5, 'high', 'why')"
    )

    with pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM alert_rules WHERE id = 1")

    connection.execute("DELETE FROM alert_matches WHERE rule_id = 1")
    connection.execute("DELETE FROM alert_rules WHERE id = 1")
    assert connection.execute("SELECT COUNT(*) FROM alert_rules").fetchone()[0] == 1


def test_notified_defaults_to_zero(connection: sqlite3.Connection) -> None:
    """Delivery state belongs to slice 040; this slice writes the default."""
    connection.execute(
        f"INSERT INTO alert_matches {_MATCH_COLUMNS} VALUES (1, NULL, 10, 1, 5, 'high', 'why')"
    )

    assert connection.execute("SELECT notified FROM alert_matches").fetchone()[0] == 0


def test_enabled_defaults_to_one(connection: sqlite3.Connection) -> None:
    """A rule created without an explicit flag is on — §4.2's ``DEFAULT 1``."""
    assert connection.execute("SELECT enabled FROM alert_rules WHERE id = 1").fetchone()[0] == 1


@pytest.mark.parametrize("table", TABLES)
async def test_every_table_is_a_plain_rowid_table(db_path: Path, table: str) -> None:
    """Addressed by surrogate id and edited through CRUD — the same shape as
    ``watchlists``, not the ``WITHOUT ROWID`` derived-view shape."""
    await upgrade_empty_database(db_path)

    assert "WITHOUT ROWID" not in create_sql(db_path, table).upper()


async def test_models_and_migrations_do_not_drift_at_head(db_path: Path) -> None:
    async with database_at(db_path, "head") as database:
        assert await autogenerate_diffs(database) == []


async def test_the_downgrade_drops_exactly_this_slice_s_tables(db_path: Path) -> None:
    await upgrade_empty_database(db_path)
    before = table_names(db_path)

    async with database_at(db_path) as database:
        await database.downgrade_to(PREVIOUS)
        assert await database.current_revision() == PREVIOUS

    assert before - table_names(db_path) == set(TABLES)
    assert {"sightings", "aircraft", "watchlists"} <= table_names(db_path)
