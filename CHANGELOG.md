# Changelog

All notable changes to FlightSite are documented here, per release. The format
follows [Keep a Changelog](https://keepachangelog.com/); versions follow
[Semantic Versioning](https://semver.org/) (`0.x.y` during pre-1.0 development).
This file is updated only on release branches (see `docs/RELEASE.md`).

## [0.3.2] — 2026-09-03

The Military filter comes alive, and the performance story gets its first
fully-passing hardware qualification.

### Added
- Measured Raspberry Pi 5 (NVMe) performance baseline in
  `docs/PERFORMANCE.md` §5.5 — **all 12 metrics pass**, confirming the Pi 4
  baseline's duty-cycle failure was SD-card write stalls (#132; the clean
  Pi 4 calibration run is tracked as #153)
- Five performance budgets promoted from trend-tracked references to hard
  CI gates on the strength of that run (`ws_fanout`, `db_read`,
  `analytics_query`, `startup`, `recovery`) — no budget value changed in
  either direction

### Fixed
- **The Military quick-filter chip works** once aircraft metadata is
  imported: it was hard-disabled since the pre-metadata era. It now enables
  on real metadata availability (Mictronics/FAA/OpenSky — an airports-only
  import doesn't count), mirrors the filter drawer's checkbox, and when
  disabled its tooltip says exactly what to do (Settings → Metadata). The
  drawer's outdated "arrives in a later slice" notes now tell the
  present-tense truth (#151)

## [0.3.1] — 2026-09-02

A same-day patch for two owner-reported live-map irritations.

### Fixed
- **Aircraft labels no longer blink**: the density-driven label tier latches
  through a hysteresis band (callsign-only above 60 visible aircraft,
  full stack again below 50) instead of flapping on a single threshold, and
  a colliding label now tries the other sides of its aircraft
  (`text-variable-anchor`, per-anchor justification) before MapLibre hides
  it; the selected aircraft's label remains always visible (#143)
- **Aircraft markers no longer oscillate forward and back**: position fixes
  are dated by the decoder's own `seen_pos` age instead of their arrival
  time, so dead reckoning projects from the moment the fix was actually
  measured and consecutive projections hand over continuously — the
  per-decode backwards step (fix age × ground speed, ~0.1–0.3 nm at jet
  speeds) is gone (#144)

## [0.3.0] — 2026-09-02

A fresh-install polish and live-picture correctness release, driven by the
owner's Raspberry Pi deployment: the setup wizard now starts ingestion without
a restart, the live map's count and tracks now tell the truth, and OpenSky
joins the metadata sources.

### Added
- OpenSky Network aircraft database as an opt-in metadata source: default-off,
  fetch-on-demand, filling gaps below Mictronics and FAA precedence; licensing
  status recorded in ADR-0013 and `docs/LICENSES.md`, and surfaced beside the
  Settings toggle
- Measured Raspberry Pi 4 performance baseline in `docs/PERFORMANCE.md` §5.4
  (contended-run, 11/12 budgets met; the ingest duty-cycle finding is tracked
  in #132) (#101)

### Fixed
- **First-run installs no longer need a backend restart**: saving the setup
  wizard now hot-starts decoder ingestion and applies the receiver location
  live (#122)
- **The live aircraft count now matches what the receiver actually hears**:
  aircraft are aged by the decoder's own last-heard report, so entries
  dump1090 retains for ~5 minutes after their last message expire on the
  documented 15 s stale / 60 s removal thresholds instead of inflating the
  count (measured 80 shown vs 59 audible before the fix); the stale "fading"
  state now actually occurs, and already-expired entries are never admitted
  (#134)
- **Clicking an aircraft now draws its whole current track**: the selected
  aircraft's trail is backfilled from its open sighting's stored path instead
  of accumulating only from the moment of selection; re-clicking no longer
  resets the trail, backfills self-correct across sighting boundaries, and
  the merge is robust to clock skew and out-of-order points (#133, #136,
  #137)
- WebSocket clients are no longer evicted by activity bursts on connect:
  activity events ship as batched frames (measured evictions in the
  first-connect scenario: 20 → 0) (#99)
- FAA registry metadata updates no longer fail with HTTP 403 (the download
  now presents a browser-compatible User-Agent) (#121)
- Demo mode's "Today" and Analytics panels are no longer empty (demo data is
  stamped relative to now) (#107)

### Changed
- The Sightings page's default max-range sort is served by a covering index
  (first page ~92 ms → ~0.1 ms on a 3-year dataset) (#115)
- Backup archives compress at gzip level 6 instead of 9 — same ratio,
  ~2.7× faster (#117)
- VACUUM's 2× free-space refusal is now surfaced in the maintenance report
  and diagnostics instead of failing silently (#116)
- Pagination footers name what they count (e.g. "sightings") (#112)

## [0.2.0] — 2026-09-01

Everything between the live-radar MVP and a feature-complete observatory: full
history and analytics, the complete alerting stack with browser notifications,
operations tooling (backup/restore, maintenance, diagnostics), and a hardening
pass (performance gates, visual regression, accessibility, multi-year storage
qualification) driven by the first real-world Raspberry Pi deployment. This
release consolidates the roadmap's planned v0.2–v0.4 themes into one version.

### Added

**History & analytics**
- Aircraft page: the full seen-here fleet, sortable and filterable, with
  per-airframe history (#29)
- Sightings page with filtering and per-sighting detail incl. decoded track
  playback data (#30)
- Analytics backend and page: activity, rarity, altitude/distance
  distributions, records, and five time presets, all deep-linkable (#31, #32)
- Receiver metrics with retention/downsampling, and the Receiver page:
  message rates, range envelope, signal statistics (#33, #34)
- Activity feed with milestones, and the Today-at-a-glance panel (#35, #36)

**Aircraft identity completion**
- One-click offline metadata updates (Mictronics/tar1090, FAA, airports) with
  transactional import and per-source status (#25)
- Optional AeroDataBox route enrichment — airline callsigns only, at most one
  request per callsign per UTC day; nothing else ever leaves your network (#26)
- Airport context on sightings and aviation map overlays (#27, #28)

**Alerts & notifications**
- Watchlists with live matching (#37)
- In-memory alert rule engine: ten condition kinds, shipped template
  catalogue, built-in 7500/7600/7700 emergency detection, severity ladder
  with upgrade events; a 500-aircraft evaluation cycle costs ~6 ms (#38)
- Interesting-aircraft surfaces: Live Map panel (severity→distance ordering),
  severity-scaled map attention ring, label indicator — severity is never
  signaled by color alone (#39)
- Browser notifications with correct permission handling: asked only from an
  explicit user click, never on load; denied/blocked/insecure-context states
  surfaced and degrade cleanly (#40)
- Alerts page: rule list, visual rule builder covering every condition kind,
  template gallery, match history (#41)

**Operations**
- Health & diagnostics: `GET /api/v1/diagnostics` serving every SPEC §67 item
  plus a diagnostics UI — assess an install without SSH; provably
  secret-free output (#42)
- SQLite-safe backup & restore with checksum-verified archives (#43)
- Scheduled database maintenance (integrity checks, pruning, vacuum) (#44)
- Explicit, confirmed data-reset actions (#45)
- Rotating file logs under the data directory (#42)

**Quality & qualification**
- Complete SPEC §82 critical-flow E2E suite across Chromium/Firefox/WebKit
  (#46), deterministic visual-regression baselines (#47), WCAG-oriented
  accessibility baseline with axe checks in CI (#48)
- Performance harness with hard CI gates on the SPEC §85 correctness budgets
  and a documented on-hardware procedure (`flightsite-perf`);
  `docs/PERFORMANCE.md` budget table (#49)
- Multi-year storage qualification tool (`flightsite-storage-qual`): 3-year
  synthetic datasets validate retention and query behavior at scale (#50)
- Install & configuration guides written from a rehearsed fresh install,
  including Raspberry Pi troubleshooting (mixed-architecture userlands,
  libseccomp SIGSYS, port conflicts, mDNS-in-containers) (#51)

### Fixed
- Live map aircraft no longer stutter forward and snap back: dead reckoning
  is anchored to the last actual position fix instead of the last message
  (#54, #119)
- Alert templates enabled in the setup wizard now instantiate immediately on
  save instead of requiring a backend restart; deleted shipped rules still
  stay deleted (#55, #110)
- The wizard's law-enforcement template selection is no longer silently
  dropped (key mismatch; old configs accepted via alias), and the
  locally-rare-type template is now actually offered (#55, #111)
- Frontend runtime image patched for CVE-2026-66046 (libexpat)

### Changed
- Default frontend host port is now **8090** (was 8080, which collides with
  decoder web UIs on the same host); override with `FLIGHTSITE_HOST_PORT`
- API documentation corrected against the served OpenAPI (bbox axis order,
  `/ready` shape, metric and field names) (#51)

### Known limitations
- A first-run install still needs one backend restart after the setup wizard
  saves the receiver configuration before ingestion starts (#122) — *fixed in
  0.3.0*

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
