# ADR-0009: Receiver metric retention and downsampling

**Status:** Accepted (2026-08-31)

## Context

Receiver telemetry (messages/sec, positions/sec, aircraft counts, range-by-bearing,
signal levels) arrives continuously. Kept at full resolution it would dominate
database growth on a Pi within months (SPEC §64 requires downsampling; §86 requires
multi-year viability), yet the Receiver page needs fine-grained recent charts and
lifetime records must never be lost.

## Decision

Three-tier retention, executed by the persistence/maintenance machinery:

1. **High-resolution samples** (polling cadence) are kept for a rolling window —
   **default 14 days**, configurable 7–30 days.
2. Older data is **downsampled to hourly, then daily summaries** (min/max/avg/count
   per metric as appropriate; daily totals for message/position counters). Hourly and
   daily rows are retained indefinitely (their volume is trivial).
3. **Lifetime aggregates** (max range ever with bearing, busiest day, totals since
   T0, record values) are maintained incrementally in dedicated rows and are never
   derived solely from prunable data — downsampling/pruning can never lose a record.

Pruning of expired high-res rows is automatic (maintenance job, slice 044), sized to
run without ingestion impact. Downsampling is idempotent so crash/restart cannot
double-count.

## Consequences

- Multi-year storage stays bounded: high-res is a fixed-size window; hourly/daily
  grow at a few rows per metric per day. Verified at scale in slice 050.
- Charts show full detail for the recent window and summarized detail beyond it; the
  UI communicates the resolution change rather than pretending uniform data.
- Changing the window only shifts the prune boundary — no migration needed within the
  7–30 day range.
- The idempotency and never-lose-records invariants are critical-coverage test
  targets (slices 033/044).
