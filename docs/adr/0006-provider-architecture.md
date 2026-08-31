# ADR-0006: Internal provider architecture, no plugin ecosystem

**Status:** Accepted (2026-08-31)

## Context

FlightSite integrates several external data sources — offline aircraft metadata
(Mictronics/tar1090), FAA registry, AeroDataBox route enrichment — and will plausibly
gain more (ownership, photos, notification channels). SPEC §78 requires clean internal
interfaces but explicitly forbids a user-installable plugin ecosystem in v1.

## Decision

Each integration category gets one small internal Python protocol, implemented
in-tree:

- `DecoderAdapter` (ADR-0003) — aircraft state input.
- `MetadataProvider` — download / validate / transform into normalized records;
  implementations: `MictronicsProvider`, `FaaRegistryProvider`. The import pipeline
  (staging → validate → transactional swap, per-source status, field-precedence with
  provenance) is provider-agnostic.
- `RouteEnrichmentProvider` — flight-context lookup; implementation:
  `AeroDataBoxProvider` behind caching, rate limiting, and a circuit breaker. No
  user-facing multi-provider selector in v1.

**Reserved seams — ownership, photo, and notification providers:** SPEC §78's
reserved provider categories are satisfied in v1 by *documented architectural seams*
(this ADR plus ARCHITECTURE.md), **not** by declared-but-unused code protocols.
Declaring a Python protocol with zero implementations and zero consumers would be
dead code that quality gates cannot exercise; the protocol definitions are deferred
until a first consumer exists, at which point the boundary described here (normalized
records in, provenance tagged at the boundary, no domain leakage) is the contract
they implement.

Explicitly **not** built: runtime plugin discovery, third-party packaging contracts,
provider configuration UIs beyond what shipped providers need.

## Consequences

- Upstream format changes are contained to one module per source; the domain sees
  only normalized records with provenance.
- Adding a source is an in-tree change with tests, keeping quality gates meaningful —
  the cost is that users cannot extend FlightSite without forking, which is the
  accepted v1 trade-off.
- Provenance (SPEC §22) is enforceable because every provider tags its output at the
  boundary.
- If a plugin ecosystem is ever wanted, these protocols are its starting contract and
  a superseding ADR is required.
