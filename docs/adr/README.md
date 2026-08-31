# Architecture Decision Records

ADRs record consequential, hard-to-reverse decisions (SPEC §90): persistence changes,
ingestion architecture, container topology, public API strategy, major external
services, persistence semantics, security assumptions, substantial retention changes.
Trivial implementation details do not get ADRs.

## Conventions

- Files: `NNNN-kebab-case-title.md`, numbered sequentially, never renumbered or
  deleted. Superseded ADRs stay in place with status updated and a link forward.
- Format: Title, Status, Context, Decision, Consequences.
- Statuses: `Proposed`, `Accepted`, `Superseded by ADR-NNNN`, `Rejected`.
- New ADRs are added in the slice that makes the decision (e.g., basemap provider
  choice in slice 013, airspace data source in slice 028).

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-sqlite-sole-persistence-store.md) | SQLite as the sole persistence store | Accepted |
| [0002](0002-two-container-compose-topology.md) | Two-container Compose topology with host bind mount | Accepted |
| [0003](0003-decoder-adapter-abstraction.md) | Decoder adapter abstraction; polling ReadsbJsonAdapter first | Accepted |
| [0004](0004-aircraft-sighting-flightcontext-model.md) | Aircraft / Sighting / Flight Context identity model | Accepted |
| [0005](0005-track-checkpointing-and-simplification.md) | Track checkpointing, simplification, and packed storage at sighting close | Accepted |
| [0006](0006-provider-architecture.md) | Internal provider architecture, no plugin ecosystem | Accepted |
| [0007](0007-api-surface-split.md) | Split API surface: read-only /api/v1 vs internal mutations | Accepted |
| [0008](0008-asyncio-write-behind-persistence.md) | Single-process asyncio backend with write-behind persistence | Accepted |
| [0009](0009-receiver-metric-retention.md) | Receiver metric retention and downsampling | Accepted |
| [0010](0010-no-auth-trusted-lan.md) | No built-in authentication in v1 (trusted LAN) | Accepted |
