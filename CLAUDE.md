# FlightSite — Agent Instructions

FlightSite is a self-hosted ADS-B observatory (live map, history, analytics, alerts)
targeting Raspberry Pi 4 via Docker Compose. Development is orchestrated by "Fable"
per the governing specification.

## Authority order

1. `planning/SPEC.md` — the governing specification (verbatim owner contract)
2. `docs/adr/` — accepted architecture decisions
3. `planning/roadmap.yaml` — canonical execution plan (slice scope/status source of truth)
4. `docs/` — ARCHITECTURE, DATA_MODEL, API, PRODUCT, TEST_STRATEGY, SECURITY, DEVELOPMENT, RELEASE

## Hard process rules (never violate)

- One slice = one numbered branch (`NNN-short-description`) = one PR into `dev`.
- Merge commits only. Never squash-merge or rebase-merge a PR.
- Conventional Commits. Never touch `CHANGELOG.md` outside a `release/*` branch.
- No direct pushes to `main` or `dev`. `main` merges require human approval.
- `dev` must stay deployable after every merge (build, tests, migrations, compose, demo mode).
- Implement only the active slice's scope; discovered work becomes a roadmap/issue entry.
- No TODO/FIXME/HACK without a tracked issue or roadmap item.
- Timestamps are UTC in storage and APIs; units are nm/ft/kt canonically.
- Secrets (API keys) must never reach logs, diagnostics, or `/api/v1` responses.

## Stack (pinned; change requires an ADR)

- Backend: Python 3.12 + uv, FastAPI, SQLAlchemy 2.x async + aiosqlite, Alembic,
  ruff, mypy (strict), pytest. Package: `backend/src/flightsite/`.
- Frontend: Vite + React + TypeScript strict, Zustand, TanStack Query, ECharts,
  Tailwind + shadcn/ui + Lucide, MapLibre GL JS. E2E: Playwright.
- Persistence: single SQLite DB (WAL) in `/opt/flightsite/data`; single-writer
  discipline via the write-behind persistence worker; ingestion never blocks on DB.

## Verification

Backend: `cd backend && uv run ruff check . && uv run mypy && uv run pytest`
Frontend: `cd frontend && npm run lint && npm run typecheck && npm test`
(Concrete commands live in `docs/DEVELOPMENT.md` once slices 001/002 land.)
