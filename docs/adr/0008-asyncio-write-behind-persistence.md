# ADR-0008: Single-process asyncio backend with write-behind persistence

**Status:** Accepted (2026-08-31)

## Context

Hard requirements collide on a Pi 4: live ingestion must never be blocked by
analytics/database work (SPEC §5), SQLite has one writer at a time, and the whole
backend must stay under 1 GB. Multi-process architectures (worker pools, separate
ingest daemon) add IPC, shared-state complexity, and memory overhead that a ~500
aircraft / 1 Hz workload does not justify.

## Decision

One asyncio process. The live path is memory-only; the database is decoupled behind a
write-behind worker:

1. The adapter loop applies normalized batches to the in-memory live store —
   no `await` into the DB anywhere on this path.
2. The live store emits domain events (appeared/updated/stale/removed and derived
   sighting/alert/activity events) onto **bounded queues**.
3. A single **persistence worker** drains queues into batched short transactions on
   the sole writer session (ADR-0001). Read-only API queries use separate sessions.
4. Backpressure: queues are bounded; on saturation, coalescible data (track
   checkpoints) is thinned first, sheds are counted and surfaced in diagnostics.
   Shedding is acceptable; stalling ingestion is not.
5. WebSocket fan-out uses per-client outbound queues with drop-and-resync for slow
   consumers.
6. CPU-heavy or blocking work (metadata imports, large simplifications, backups) runs
   in `asyncio.to_thread`/subprocesses.

No Rust, no worker processes in v1 unless measurements demand it (then a superseding
ADR).

## Consequences

- Live queries and the WS stream reflect memory state instantly regardless of DB
  contention; slow analytics can at worst delay *persistence*, visibly, not tracking.
- Crash windows are explicit: anything queued but unwritten is lost within the
  bounded-loss contract of ADR-0005; recovery logic assumes it.
- Single-process simplicity: one deployment unit, trivial diagnostics, shared config.
  The cost is that a pathological consumer bug can affect the loop — mitigated by
  bounded queues, budgets tested in slices 008/009 and gated in 049.
- Concurrency is cooperative; long synchronous code in any handler is a defect class
  the perf harness (slice 049) exists to catch.
