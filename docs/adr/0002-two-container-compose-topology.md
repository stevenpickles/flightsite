# ADR-0002: Two-container Compose topology with host bind mount

**Status:** Accepted (2026-08-31)

## Context

SPEC §6 prescribes Docker Compose on a Pi 4 with no separate DB container and all
persistent state in a clearly defined location. The deployment must be trivially
backupable and portable, and images must ship for linux/arm64 and linux/amd64.

## Decision

Exactly two containers:

1. `flightsite-frontend` — nginx serving the built React app and reverse-proxying
   `/api` (including WebSocket upgrade) to the backend. The browser talks only to this
   container.
2. `flightsite-backend` — the FastAPI process: ingestion, live state, persistence
   (in-process SQLite per ADR-0001), alerts, analytics, APIs.

All persistent state lives in a host **bind mount**, default `/opt/flightsite/data`
(config.yaml, secrets.yaml, SQLite files, logs, backups). No anonymous or named
volumes for important state. Containers run as non-root; images publish to
`ghcr.io/<owner>/flightsite-{backend,frontend}` for arm64+amd64.

## Consequences

- One origin for the browser: no CORS complexity; a future auth proxy slots in at the
  frontend container.
- Backup/migration is "stop or snapshot, copy `/opt/flightsite/data` + compose file".
- The frontend container is a pure static artifact; all state and logic concentrate in
  the backend, keeping the two-container split stable across v1.
- Anything needing a third service (Prometheus, Postgres, tile server) is out of v1 by
  construction and would need a superseding ADR.
