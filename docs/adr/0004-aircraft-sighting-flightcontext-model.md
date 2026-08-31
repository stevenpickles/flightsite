# ADR-0004: Aircraft / Sighting / Flight Context identity model

**Status:** Accepted (2026-08-31)

## Context

ADS-B conflates identities: an ICAO hex address names a physical airframe, while
callsign, squawk, and route describe the flight it is currently operating. Mixing them
corrupts history (an airframe's record polluted by one flight's callsign) and blocks
receiver-relative statistics (SPEC §17 demands the separation).

## Decision

Three distinct concepts, persisted distinctly:

- **Aircraft** — the persistent physical airframe, keyed by ICAO hex address. Carries
  permanent/slow-changing properties (registration, type, model, year, operator
  metadata, classification) and receiver-relative lifetime records (first/last seen,
  sighting count, cumulative duration, closest approach, farthest detection,
  lowest/highest altitude).
- **Sighting** — one continuous observation period of that aircraft by this receiver.
  Opens on first observation, closes after the configured absence window (default
  10 min); a new sighting cannot open until the previous one closes (SPEC §18). Owns
  its track, reception statistics, and sighting events.
- **Flight Context** — temporary flight information attached to the sighting, never
  the aircraft: callsign, squawk, origin/destination/route (enriched), operator-in-use,
  emergency state.

ICAO hex reuse/anomalies (hijacked addresses, bit errors) are tolerated: the aircraft
row is keyed by hex; suspect data is a metadata/classification concern, not an
identity-model one.

## Consequences

- "How often has this airframe visited" and "what flight was that" are independently
  answerable; analytics and rarity computations use aircraft identity, alert reasons
  can cite flight context.
- Callsign changes mid-sighting are sighting events, not identity changes.
- The model maps directly onto tables (see `docs/DATA_MODEL.md`) and onto the API
  (aircraft resources vs sighting resources).
- Future multi-receiver support extends Sighting (per-receiver observation), not
  Aircraft — the airframe stays global.
