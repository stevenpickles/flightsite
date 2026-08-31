"""Programmatic Alembic wiring.

Alembic is the *only* way FlightSite's schema changes (SPEC §107). The
migration environment lives inside the installed package
(``flightsite/db/migrations/``) rather than beside ``pyproject.toml``, so the
revisions ship in the wheel and the container can migrate itself at startup;
``backend/alembic.ini`` points the ``alembic`` CLI at the same directory.

The functions here are the connection-sharing form of Alembic's programmatic
API: they run migrations on a connection the caller already owns, which lets
:class:`flightsite.db.engine.Database` apply them on the writer connection
under the writer lock instead of opening a second, unmanaged one.
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import AsyncEngine

#: The Alembic environment shipped inside the package.
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def build_config(url: str | None = None) -> Config:
    """Build an Alembic :class:`~alembic.config.Config` for FlightSite.

    The config is assembled in code rather than read from ``alembic.ini`` so
    that it does not depend on the process's working directory: the app
    migrates itself at startup from wherever uvicorn happens to be running.

    Args:
        url: database URL to migrate. Omitted when a live connection is
            supplied via ``config.attributes["connection"]``.
    """
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if url is not None:
        # Escape '%' so ConfigParser interpolation leaves the URL untouched.
        config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def script_directory() -> ScriptDirectory:
    """The revision graph on disk (used by the single-head check)."""
    return ScriptDirectory.from_config(build_config())


def heads() -> tuple[str, ...]:
    """Revision ids of every head in the migration graph.

    More than one head means two slices added revisions in parallel without
    reconciling them — the divergence ``docs/DEVELOPMENT.md`` §"Parallel
    migrations" forbids.
    """
    return tuple(script_directory().get_heads())


def head_revision() -> str:
    """The single head revision id.

    Raises:
        RuntimeError: if the graph has zero or multiple heads.
    """
    found = heads()
    if len(found) != 1:
        raise RuntimeError(f"expected exactly one Alembic head, found {len(found)}: {found}")
    return found[0]


def current_revision(connection: Connection) -> str | None:
    """The revision stamped in ``connection``'s database, or ``None``."""
    return MigrationContext.configure(connection).get_current_revision()


def _upgrade_sync(connection: Connection, revision: str) -> None:
    config = build_config()
    config.attributes["connection"] = connection
    command.upgrade(config, revision)


async def upgrade(engine: AsyncEngine, revision: str = "head") -> None:
    """Upgrade the database behind ``engine`` to ``revision``."""
    async with engine.begin() as connection:
        await connection.run_sync(_upgrade_sync, revision)


def _downgrade_sync(connection: Connection, revision: str) -> None:
    config = build_config()
    config.attributes["connection"] = connection
    command.downgrade(config, revision)


async def downgrade(engine: AsyncEngine, revision: str) -> None:
    """Downgrade the database behind ``engine`` to ``revision``.

    Rollback is supported where practical (SPEC §107); the migration tests
    exercise it to keep ``downgrade()`` bodies honest.
    """
    async with engine.begin() as connection:
        await connection.run_sync(_downgrade_sync, revision)
