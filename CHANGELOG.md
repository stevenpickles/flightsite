# Changelog

All notable changes to FlightSite are documented here, per release. The format
follows [Keep a Changelog](https://keepachangelog.com/); versions follow
[Semantic Versioning](https://semver.org/) (`0.x.y` during pre-1.0 development).
This file is updated only on release branches (see `docs/RELEASE.md`).

## [0.1.0] — 2026-09-01

First integrated release: the live radar MVP, plus the aircraft-identity layer.
FlightSite ingests a readsb/dump1090-fa decoder (or its built-in demo mode),
persists aircraft and sightings with full track history, and renders a live,
filterable aviation map with rich aircraft identification.

### Added

**Live tracking**
- readsb / dump1090-fa `aircraft.json` ingestion with tolerant parsing (modern
  and legacy field vocabularies), malformed-input hardening, connection health
  with automatic backoff/reconnect, and a decoder connection test (#18)
- In-memory live aircraft registry: 15 s stale / 60 s removal lifecycle on a
  monotonic clock, receiver-relative distance/bearing, non-positioned aircraft
  as first-class entries, per-aircraft full-resolution current track (#27)
- Read-only live API: `GET /api/v1/aircraft/current`, `GET /api/v1/receiver`,
  and a seq-numbered snapshot+delta WebSocket at `/api/v1/ws/live` with
  slow-consumer protection (#37)

**History & persistence**
- SQLite persistence (WAL, single-writer discipline, startup integrity checks,
  automatic Alembic migrations) storing aircraft, sightings with flight
  context, lifetime records (closest approach, max range, altitude extremes),
  and the T0 first-observation anchor (#16, #33)
- Sighting tracks: checkpointed while active, Douglas-Peucker-simplified and
  stored as one compact packed row per sighting at close (playback-capable);
  per-sighting reception statistics and event timelines (#39)
- Unclean-shutdown recovery: open sightings are repaired from checkpoints with
  bounded data loss and `shutdown_recovery` closure honesty — validated by
  real process-kill drills (#42)

**Aircraft identity**
- Offline metadata framework with staged, transactional imports and per-field
  precedence/provenance (#44); Mictronics/tar1090 (#54) and FAA releasable
  registry (#53) importers — both fetch-on-demand, never bundled
- Classification engine: military/government/law-enforcement flags and mission
  categories with per-claim provenance and calibrated confidence — weak or
  conflicting evidence yields `unknown`, never false certainty (#57)
- Operator normalization: ~95 curated operator groups (passenger, cargo,
  government, law enforcement, medical, firefighting) with exact-operator
  preservation (#57)

**Live map experience**
- MapLibre map with an abstracted basemap registry: dark-aviation default over
  OpenFreeMap (no API key required), light variant, OSM raster fallback, range
  rings, receiver marker, graceful tile-outage and no-WebGL degradation
  (#15, #43, #58)
- Live aircraft rendering: original silhouette icon set, heading rotation,
  smooth interpolation, stale fading, non-color MLAT distinction, selection
  with current-track polyline, 500-aircraft performance headroom (#43)
- Priority-based labels with zoom/density decluttering (#49); comprehensive
  aircraft detail panel with field provenance indicators, external tracker
  links, and honest `Unknown` rendering (#50)
- Filter drawer, quick filters, non-positioned aircraft panel, display-radius
  cap, URL-persisted filter state (#56)

**Setup & configuration**
- First-run setup wizard: receiver location (map-pick or manual), decoder
  endpoint with live connection test, units, timezone, notification
  preferences, alert-template selection (#30)
- Settings page over the canonical `config.yaml` model with masked secrets and
  per-section saves (#34); `config.yaml` / `secrets.yaml` / `FLIGHTSITE_*`
  environment layering (#9)

**Deployment & operations**
- Two-container Docker Compose deployment (multi-arch arm64/amd64), all state
  under one host bind mount (`/opt/flightsite/data`), non-root containers,
  GHCR publishing (#22)
- Deterministic demo mode (`FLIGHTSITE_DEMO=1`): full simulated traffic —
  commercial, military, government, police, MLAT, non-positioned, emergency
  squawks, rare aircraft — with zero configuration (#32)
- Developer capture/replay tooling for reproducing real-world decoder
  behavior as regression fixtures (#26)
- CI quality gates: lint/type/test/coverage for both stacks, dependency and
  secret scanning, license checks, container scanning, Playwright E2E across
  Chromium/Firefox/WebKit (#8, #58)

### Known limitations

- Alerts, watchlists, and browser notifications arrive in a later 0.x release
  (roadmap phase 6); analytics and receiver-statistics pages in phase 5;
  backup/restore tooling in phase 7.
- Route enrichment (AeroDataBox) and airport context are in development.
- No built-in authentication: FlightSite assumes a trusted LAN and must not be
  exposed directly to the public internet (see `docs/SECURITY.md`).
- Raspberry Pi 4 performance qualification is trend-tracked; formal hard
  gates land with the phase-8 performance harness.

[0.1.0]: https://github.com/stevenpickles/flightsite/releases/tag/v0.1.0
