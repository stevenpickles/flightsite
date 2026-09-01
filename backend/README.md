# flightsite backend

Python backend for FlightSite (FastAPI + SQLite). See
[`../docs/ARCHITECTURE.md`](../docs/ARCHITECTURE.md) and
[`../docs/DEVELOPMENT.md`](../docs/DEVELOPMENT.md) for the full picture.

```bash
uv sync
uv run pytest
uv run flightsite-serve
```

## API

The documented read-only surface is `/api/v1` and its OpenAPI document is
served beside it: schema at `/api/v1/openapi.json`, interactive docs at
`/api/v1/docs`. `/api/internal` is the frontend's unsupported mutation surface
and is excluded from that schema.

The live WebSocket, `/api/v1/ws/live`, cannot be described in OpenAPI; its
protocol reference is the `flightsite.api.ws` module docstring.

## Database

SQLite (WAL) at `<data dir>/flightsite.sqlite3`, reached through
`flightsite.db` — see that package's module docstrings for the single-writer
discipline and the connection pragmas. The app applies `alembic upgrade head`
itself during startup, so the CLI below is only for authoring and inspecting
migrations.

Migrations live inside the package (`src/flightsite/db/migrations/`) so they
ship in the wheel and a container can migrate itself; `alembic.ini` points the
CLI at the same directory. Both the CLI and the app resolve the database from
`FLIGHTSITE_DATA_DIR` (default `/opt/flightsite/data`).

```bash
FLIGHTSITE_DATA_DIR=./.localdata uv run alembic upgrade head
FLIGHTSITE_DATA_DIR=./.localdata uv run alembic revision --autogenerate -m "add x"
uv run alembic heads    # must print exactly one head
```

A divergent head or any drift between `flightsite.db.models` and the
migrations fails `uv run pytest` (`tests/db/test_migrations.py`), which is the
`alembic check` gate the CI backend job runs.
