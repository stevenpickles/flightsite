# ADR-0003: Decoder adapter abstraction; polling ReadsbJsonAdapter first

**Status:** Accepted (2026-08-31)

## Context

FlightSite does not decode RF in v1 (SPEC §11); it consumes readsb or dump1090-fa.
Their `aircraft.json` HTTP output is near-identical, ubiquitous, and easy to consume,
but future sources (Beast/SBS streams, remote receivers) have different transports and
cadences. Decoder-specific field names must not leak into the domain (SPEC §11).

## Decision

All aircraft input enters through a `DecoderAdapter` protocol that yields batches of
**normalized `AircraftStateUpdate`** values (decoder-agnostic domain types carrying
position source, provenance, and raw-signal fields) and exposes an
`AdapterHealth` state machine (connected/degraded/down) with automatic reconnect.

v1 ships three implementations:

- `ReadsbJsonAdapter` — polls `aircraft.json` at the configured interval; tolerates
  readsb and dump1090-fa variants; classifies position source (ADS-B / MLAT / Mode S
  no-position / other); hardens against malformed input.
- `DemoAdapter` — deterministic simulator (slice 011).
- `ReplayAdapter` — fixture replay (slice 012).

Polling (not stream) is the v1 transport: it matches the ~1 Hz product cadence, is
stateless across decoder restarts, and both supported decoders serve it natively.
`BeastAdapter`, `SbsAdapter`, `RemoteReceiverAdapter` remain backlog.

## Consequences

- Everything downstream (live store, sightings, alerts, demo, replay, tests) is
  decoder-agnostic; new sources are additive.
- Demo and replay being ordinary adapters means the entire stack is exercisable
  without hardware — this is what makes deterministic E2E/visual testing possible.
- Polling caps update latency at the polling interval; acceptable for v1's 1 Hz
  envelope. A push adapter can be added later without domain changes.
- Normalization cost is paid once at the boundary; fuzz/hardening tests concentrate
  there.
