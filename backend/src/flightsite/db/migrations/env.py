"""Alembic environment for FlightSite (async, aiosqlite).

Two entry paths share one configuration:

* **Connection sharing** — :mod:`flightsite.db.migrate` puts a live
  :class:`~sqlalchemy.Connection` on ``config.attributes``; migrations then run
  on the caller's connection (the app's single writer, under its lock).
* **Standalone CLI** — ``uv run alembic ...`` from ``backend/`` has no
  connection, so this module builds an async engine itself. It is built with
  :func:`flightsite.db.engine.create_sqlite_engine`, so a CLI migration gets
  exactly the same URL and the same pragmas (WAL, ``foreign_keys=ON``,
  ``busy_timeout``) as the running application.

``render_as_batch`` is on because SQLite cannot ``ALTER`` most things in place;
batch mode makes future column drops/alterations expressible as migrations
rather than hand-written table rebuilds.
"""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy import Connection
from sqlalchemy.pool import NullPool

from flightsite.config import resolve_data_dir
from flightsite.db.engine import create_sqlite_engine, database_path, sqlite_url
from flightsite.db.models import Base

config = context.config
target_metadata = Base.metadata


def resolve_url() -> str:
    """URL to migrate: the configured one, else the data directory's database."""
    configured = config.get_main_option("sqlalchemy.url", None)
    if configured:
        return configured
    return sqlite_url(database_path(resolve_data_dir()))


def run_migrations_offline() -> None:
    """Emit migration SQL to stdout without connecting (``alembic --sql``)."""
    context.configure(
        url=resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations on an established connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Build FlightSite's own engine and migrate through it (CLI path)."""
    engine = create_sqlite_engine(resolve_url(), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await engine.dispose()


def run_migrations_online() -> None:
    """Migrate, reusing a caller-supplied connection when there is one."""
    connection = config.attributes.get("connection")
    if connection is not None:
        do_run_migrations(connection)
        return
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
