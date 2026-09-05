"""Rebuilding a SQLite table inside a migration, without eating its children.

SQLite cannot alter a ``CHECK`` constraint (or most other things) in place, so
a migration that widens one has to rebuild the table: create the new shape,
copy every row, drop the old table, rename. Revisions 0014 and 0015 both do it.

The part that is *not* obvious — and that cost a broken release, issue #178 —
is what ``DROP TABLE`` means while ``PRAGMA foreign_keys`` is on. SQLite runs
the drop as an implicit ``DELETE FROM`` of every row, and every deleted row is
checked against every child table that references it. On a table with five
``NO ACTION`` children, two of them unindexed on the referencing column, that
is a full scan of those children *per parent row*, and it ends in
``FOREIGN KEY constraint failed`` regardless: the children still point at the
rows being deleted. Minutes of CPU, then a failure.

Foreign keys are therefore turned **off** around the rebuild and turned back on
afterwards — and because turning them off is silently a no-op inside a
transaction, doing that correctly needs the care spelled out in
:func:`set_foreign_keys`.

What replaces the enforcement while it is off is
:func:`check_foreign_keys`: after the rename, every child of the rebuilt table
is verified to still resolve. Enforcement is suspended for the rebuild, not
abandoned.

:func:`rebuilding` packages the whole discipline as a context manager, and is
what a revision should use.

Also here: the ``has_*`` predicates, because a SQLite migration is **not
atomic**. Alembic marks SQLite as non-transactional DDL, so every statement
before a failing one stays committed and ``alembic_version`` still names the
older revision — a restart re-runs the whole revision from the top over a
half-migrated database. A rebuild step that cannot tolerate its own prior
completion turns one failure into an unrecoverable one.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection


class ForeignKeysNotSuspended(RuntimeError):
    """``PRAGMA foreign_keys`` would not take the value the rebuild needs."""


class DanglingForeignKeys(RuntimeError):
    """A rebuild left rows referencing a parent row that is no longer there."""


def has_table(bind: Connection, name: str) -> bool:
    """True if a table called ``name`` exists."""
    found = bind.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
    ).scalar()
    return found is not None


def has_index(bind: Connection, name: str) -> bool:
    """True if an index called ``name`` exists."""
    found = bind.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?", (name,)
    ).scalar()
    return found is not None


def has_column(bind: Connection, table: str, column: str) -> bool:
    """True if ``table`` exists and carries ``column``."""
    rows = bind.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(str(row[1]) == column for row in rows)


def foreign_keys_enabled(bind: Connection) -> bool:
    """Whether this connection currently enforces foreign keys."""
    return bool(bind.exec_driver_sql("PRAGMA foreign_keys").scalar())


def _end_transaction(bind: Connection, *, commit: bool) -> None:
    """End the transaction the DBAPI opened implicitly, if there is one.

    pysqlite (and aiosqlite over it) begins a transaction on the first DML
    statement and holds it open until something commits. Alembic's own
    ``UPDATE alembic_version`` is DML, so a run that applies more than one
    revision arrives at the next revision's body already inside a transaction,
    while an install stepping over a single revision — the production upgrade
    path — arrives outside one. Both happen; only the first needs ending.
    """
    driver = bind.connection.driver_connection
    if getattr(driver, "in_transaction", False):
        bind.exec_driver_sql("COMMIT" if commit else "ROLLBACK")


def set_foreign_keys(bind: Connection, *, enabled: bool) -> None:
    """Turn foreign-key enforcement on or off, and make sure it took.

    ``PRAGMA foreign_keys`` is a **no-op inside a transaction** and SQLite
    reports no error when it is ignored — which is exactly how a migration ends
    up believing it disabled enforcement while the following ``DROP TABLE``
    runs with enforcement on. So the value is written, read back, and only if
    the read-back disagrees is the open transaction ended and the write
    retried. A second disagreement is raised rather than assumed away.

    Committing here is not a liberty the rebuild takes lightly; it is the only
    way to reach a statement boundary where the pragma is honoured, and SQLite
    DDL under Alembic is already non-transactional in the single-revision case.
    """
    wanted = "ON" if enabled else "OFF"
    bind.exec_driver_sql(f"PRAGMA foreign_keys={wanted}")
    if foreign_keys_enabled(bind) is enabled:
        return
    _end_transaction(bind, commit=True)
    bind.exec_driver_sql(f"PRAGMA foreign_keys={wanted}")
    if foreign_keys_enabled(bind) is not enabled:
        raise ForeignKeysNotSuspended(
            f"PRAGMA foreign_keys would not go {wanted}; refusing to rebuild a table "
            "with enforcement in an unknown state"
        )


def child_tables(bind: Connection, parent: str) -> tuple[str, ...]:
    """Every table holding a foreign key that references ``parent``.

    Discovered from the schema rather than listed by hand, so a later slice
    adding a table that references the rebuilt one is covered by the check
    without anyone remembering to add it.
    """
    names = [
        str(row[0])
        for row in bind.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    children = []
    for name in names:
        references = bind.exec_driver_sql(f"PRAGMA foreign_key_list({name})").fetchall()
        if any(str(row[2]) == parent for row in references):
            children.append(name)
    return tuple(children)


def check_foreign_keys(bind: Connection, table: str) -> None:
    """Verify ``table`` and every table referencing it still resolve.

    ``PRAGMA foreign_key_check`` is scoped to the rebuilt table and its
    children rather than run over the whole database: those are the only
    relationships a rebuild can break, and a database that arrived with an
    unrelated violation from some older build must not have its upgrade
    blocked by it.

    Raises:
        DanglingForeignKeys: if any checked row no longer resolves.
    """
    violations: list[str] = []
    for name in (table, *child_tables(bind, table)):
        for row in bind.exec_driver_sql(f"PRAGMA foreign_key_check({name})").fetchall():
            violations.append(f"{name} rowid={row[1]} -> {row[2]}")
    if violations:
        raise DanglingForeignKeys(
            f"rebuilding {table} left {len(violations)} dangling reference(s): "
            + "; ".join(violations[:10])
        )


@contextmanager
def rebuilding(bind: Connection, table: str) -> Iterator[None]:
    """Suspend foreign keys for a table rebuild, then check and restore them.

    On the way out the references are verified; on the way out *through an
    exception* the open transaction is rolled back first, so a rebuild that
    fails half-way does not commit its own wreckage on the way to re-enabling
    enforcement.
    """
    set_foreign_keys(bind, enabled=False)
    try:
        yield
        check_foreign_keys(bind, table)
    except BaseException:
        _end_transaction(bind, commit=False)
        raise
    finally:
        set_foreign_keys(bind, enabled=True)


def reconcile_staging_table(bind: Connection, table: str, staging: str) -> None:
    """Resolve the ``staging`` table a previous, failed attempt may have left.

    Two states are possible after an interrupted rebuild, and they are not the
    same. If ``table`` is gone and ``staging`` is present, the crash landed
    between the drop and the rename and ``staging`` *is* the data: it is
    renamed into place, and the rebuild then proceeds over it from the top. If
    both are present, ``staging`` is a discarded copy and is dropped.
    """
    if not has_table(bind, staging):
        return
    if not has_table(bind, table):
        bind.exec_driver_sql(f"ALTER TABLE {staging} RENAME TO {table}")
        return
    bind.exec_driver_sql(f"DROP TABLE {staging}")


def row_count(bind: Connection, table: str) -> int:
    """Number of rows in ``table`` (used by rebuilds to assert the copy)."""
    return int(bind.exec_driver_sql(f"SELECT COUNT(*) FROM {table}").scalar_one())


def assert_copied(bind: Connection, source: str, destination: str) -> None:
    """Fail unless ``destination`` received every row of ``source``.

    Cheap next to the copy itself, and the difference between a rebuild that
    lost history and a rebuild that reported losing history.
    """
    before = row_count(bind, source)
    after = row_count(bind, destination)
    if before != after:
        raise RuntimeError(f"copy from {source} to {destination} moved {after} of {before} rows")


__all__ = (
    "DanglingForeignKeys",
    "ForeignKeysNotSuspended",
    "assert_copied",
    "check_foreign_keys",
    "child_tables",
    "foreign_keys_enabled",
    "has_column",
    "has_index",
    "has_table",
    "rebuilding",
    "reconcile_staging_table",
    "row_count",
    "set_foreign_keys",
)
