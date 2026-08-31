# ADR-0001: SQLite as the sole persistence store

**Status:** Accepted (2026-08-31)

## Context

FlightSite targets a Raspberry Pi 4 homelab deployment (SPEC §5–6): one box, easy
backup/restore/migration, years of history, ~500 live aircraft at ~1 Hz, backend under
1 GB RAM. A separate database server adds a container, memory pressure, operational
surface, and makes "copy the data directory" backups unreliable. The workload is
modest in write volume once live state is kept in memory and only domain-meaningful
rows are persisted.

## Decision

SQLite is the only persistence store, running in-process in the backend. No database
container exists in the Compose topology.

Configuration for long-running use:

- WAL journal mode; `synchronous=NORMAL`; `busy_timeout` set; `foreign_keys=ON`.
- **Single-writer discipline**: all writes flow through one persistence-worker session
  in batched short transactions; reads use separate connections (WAL keeps readers
  non-blocking).
- Schema managed exclusively by Alembic; migrations applied at startup.
- Startup integrity check (`PRAGMA quick_check`); automated maintenance (optimize,
  checkpoints, guarded VACUUM) in slice 044.

Replacing SQLite (e.g., with Postgres) would require a superseding ADR backed by
measurements (SPEC §7 makes the same demand of introducing Rust).

## Consequences

- Backup = SQLite-safe snapshot of one file plus config (slice 043); portability =
  move the data directory.
- Write throughput is bounded by a single writer — acceptable because the live path
  never touches the DB (ADR-0008) and persisted volume is domain events, not raw
  messages.
- Analytics must be designed for SQLite (incremental rollups, real indexes) rather
  than leaning on a server database's planner; validated at multi-year scale in
  slice 050.
- Corruption risk from power loss is mitigated by WAL + integrity checks + recovery
  design (SPEC §71), not by an external DB's durability machinery.
