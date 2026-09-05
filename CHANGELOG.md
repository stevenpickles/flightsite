# Changelog

All notable changes to FlightSite are documented here, per release. The format
follows [Keep a Changelog](https://keepachangelog.com/); versions follow
[Semantic Versioning](https://semver.org/) (`0.x.y` during pre-1.0 development).
This file is updated only on release branches (see `docs/RELEASE.md`).

## [0.6.1] — 2026-09-05

A same-day hotfix that supersedes v0.6.0, which must not be installed on any
database that already holds sightings.

### Fixed
- **Migration 0015 no longer hangs and fails on a populated database** (#178).
  The `sightings` rebuild ran its `DROP TABLE` with foreign-key enforcement
  on, so every existing sighting triggered full scans of child tables that
  carry no index on their sighting column, and the statement would end in a
  constraint error after minutes of work; the upgrade of the owner's
  receiver hung for five minutes and was rolled back from its pre-upgrade
  backup. The rebuild now disables foreign keys while no transaction is
  open, verifies them with `PRAGMA foreign_key_check` after the rename, and
  restores enforcement afterwards. It is also resumable: an install that
  tried v0.6.0 and was left with the directory tables, the new column, its
  sighting indexes dropped and an empty rebuild table completes the same
  migration to the same end state
- Migration tests now seed every child of `sightings` before upgrading, and
  the release checklist requires the adjacent-version upgrade test against
  a populated data directory before a release PR opens; the discipline for
  SQLite table rebuilds is written down in `docs/DEVELOPMENT.md`

### Upgrade notes
- Everything in the v0.6.0 notes applies, including **take a backup first**
  and the one-time *Update Aircraft Metadata* run to import the routes
  dataset.
- If you already attempted v0.6.0 and it hung: stop the stack, pin the
  v0.6.1 images, and start — the corrected migration resumes from where the
  failed one stopped. If you restored your backup instead, upgrade normally.

## [0.6.0] — 2026-09-05

Origin and destination without an API key. The Virtual Radar Server
standing-data route directory becomes the primary source of routes — imported
on demand, 620,000 scheduled callsigns under a public-domain licence — and
AeroDataBox is consulted only for callsigns the directory does not know.
SPEC §28 was amended by the owner to admit it (ADR-0016).

### Added
- **Offline route directory**: a `routes` dataset under Settings → Metadata,
  fetched by *Update Aircraft Metadata* from the VRS standing-data repository
  (7 MB, routes only; CC0-1.0). Once imported, every scheduled callsign is
  resolved locally with provenance `vrs`; the route worker runs with or
  without an AeroDataBox key, and with no key it makes no external call at
  all. Migration 0015 adds `route_directory`, `route_cache.source`, and
  admits `vrs` on `sightings.route_source`
- **Inferred route end**: when no source knows a callsign but the aircraft
  has been seen departing or arriving at a field, the detail panel shows
  that airport as the inferred origin or destination, visibly marked as
  inferred and never written as a route (SPEC §28)
- **Last-known route**: an expired cached route is kept when neither the
  directory nor the provider can answer — budget spent, breaker open, rate
  limited, offline, or no key — logged once a day and counted on the Health
  page
- Health page: the enrichment card names the provider (AeroDataBox or
  "Directory only"), directory hits, and last-known routes served; Settings
  → Metadata shows the routes dataset with its credit and honest row-count
  nouns

### Changed
- A directory route contradicted by the aircraft's own departure or arrival
  is invalidated and re-asked of AeroDataBox once, so a changed schedule is
  caught by the sky rather than by waiting for the next dataset import
- Adding or removing the AeroDataBox key is adopted in place: removing it
  no longer stops directory lookups, adding it starts online lookups for
  misses without a restart
- CI performance gates carry headroom sized from their recorded flakes
  (`ingest_duty_cycle` asserts 0.9 of a poll, `ingest_apply_ms` 800 ms; the
  metadata latency test gates the median); the Raspberry Pi budgets are
  unchanged (#166, #170)

### Fixed
- A provider swap closed the old HTTP client before installing the new
  provider, so a lookup racing the swap could rebuild a client with the key
  that had just been removed; the new provider is now installed first
- Frontend runtime image: every Alpine package with a published fix is
  upgraded at build time (seven HIGH util-linux advisories on the pinned
  nginx base)

### Upgrade notes
- **Migration 0015 rebuilds the `sightings` table** to admit the new route
  source (measured: about a second per 200,000 sightings on an SSD, so of
  the order of ten seconds for a three-year history; longer on an SD card).
  **Take a backup first**: `docker compose exec flightsite-backend
  flightsite-backup create`, then `docker compose pull && docker compose
  up -d`.
- After upgrading, run **Settings → Metadata → Update Aircraft Metadata**
  once to import the routes dataset; until then the directory is empty and
  behaviour matches 0.5.0. Re-run it every few weeks to pick up schedule
  changes.
- Diagnostics gain `enrichment.provider`, `cache.directory_hits` and
  `cache.stale_served`; `provenance.route` may now be `vrs`.

### Known issues
- Six low-severity items remain open (#96, #98, #100, #112, #138, #147);
  the Raspberry Pi 4 SSD qualification (#153) is deferred by the owner.

## [0.5.0] — 2026-09-04

A credit-economy release for route enrichment, plus airport names. Measured
on the owner's receiver, v0.4.0 spent roughly one AeroDataBox lookup per
airline callsign per day — 2,200 to 2,650 a day — faster than the feeder
programme earned them. This release makes each scheduled flight cost one
lookup a week, then one a month, caps the daily spend, and stops paying for
flights the provider will never describe.

### Added
- **Daily lookup budget** (`enrichment.daily_lookup_budget`, Settings →
  Enrichment; 0 = uncapped): lookups stop when the day's budget is spent and
  resume at midnight UTC. The count is taken from the route cache, so it
  survives restarts. Pending lookups are spent in priority order — aircraft
  matching an alert rule first, then aircraft inside the display radius, then
  the rest, with refreshes of already-known routes last
- **Route cache lifetime** (`enrichment.route_ttl_days`, default 7, 1–30):
  a found route is kept for a week, keyed by callsign alone instead of
  callsign-plus-day, so a callsign seen twice in one day costs one lookup and
  a daily flight costs one a week. Both settings apply on save
- **Learned schedules**: a route confirmed identical on three separate days
  is frozen for thirty days (migration 0014 adds `confirmations` and
  `first_fetched_ms` to `route_cache`)
- **Airport names beside route idents**: every `route` object carries
  `origin_name` and `destination_name` resolved from the local airports
  table (slice 027), and the aircraft detail panel and sighting detail show
  "KATL · Hartsfield-Jackson Atlanta Intl" instead of the ident alone. No
  provider call is involved; names are `null` until an airports import has
  run
- Health page: the enrichment card shows budget used and remaining, the
  reset time, and cache hits / misses / learned routes; diagnostics gain
  `enrichment.budget` and `enrichment.cache`

### Fixed
- **Legally restricted flights no longer burn credits or trip the breaker**
  (#165): an HTTP 451 from AeroDataBox is now cached as `restricted` for the
  route lifetime, logged with its own reason, and never counted as a provider
  failure. Before, one blocked business jet was retried nine times in twelve
  minutes and paused every other lookup for five minutes, twice
- A cached route contradicted by the aircraft's own behaviour — a latched
  departure or arrival at an airport that is neither end of the route — is
  invalidated and re-fetched once, so a changed schedule is caught without
  waiting out the cache lifetime
- Negative answers (no schedule for a callsign) are remembered for 24 hours
  instead of one

### Upgrade notes
- **Migration 0014** rebuilds `route_cache` (a few thousand rows at most).
  Take a backup first: `docker compose exec flightsite-backend
  flightsite-backup create`, then `docker compose pull && docker compose up -d`.
- After upgrading, set **Settings → Enrichment → Daily lookup budget** to
  what your credit source sustains; the default is uncapped, which preserves
  the previous behaviour apart from the cache changes above.
- Cached routes from before the upgrade keep their day-bucketed keys and
  expire within hours; the new cache warms over the first week.

### Known issues
- The `ingest_duty_cycle` performance gate has no CI headroom and can fail
  on a contended shared runner (#166); a re-run is the remedy until headroom
  lands. Six low-severity items and the deferred Pi 4 SSD qualification
  (#153) remain open. A free route source ahead of AeroDataBox is an owner
  decision (#168).

## [0.4.0] — 2026-09-04

Settings that take effect when you save them, and alerts that reach you
wherever the tab is. Route enrichment, decoder statistics and browser
notifications no longer depend on a backend restart or on which page happens
to be open — and every open issue is now triaged by severity.

### Added
- **The Alerts page's "Notified" marker now means something**: a match is
  marked notified when a browser notification was actually shown for it, via
  a new idempotent internal endpoint
  (`POST /api/internal/alerts/matches/{id}/notified`); alert activity events
  carry the `match_id` the client needs (#104)
- "Applies on next restart" badges on every Settings section or field that
  still needs one — Retention, the timezone selector, the OpenSky toggle —
  and none on the Enrichment section, which no longer does (#161)
- ADR-0015 (the app shell owns the live WebSocket) and ADR-0014 (the measured
  `sighting_tracks` storage cost is accepted for v1): `docs/DATA_MODEL.md` §9
  now predicts ~1.7 GB/year for a typical receiver and ~20 GB/year at the
  SPEC §5 envelope, replacing the 1.0–1.2 / 12–14 GB/year design estimate,
  with the page-size and rowid remedies recorded as a backlog item (#114)
- A severity scale for the issue tracker (`severity:critical/high/medium/low`,
  `release-gate`, `decision`), documented in `docs/DEVELOPMENT.md`; SPEC §114's
  bug gate is now a label query named in `docs/RELEASE.md` (slice 067)

### Changed
- **Browser notifications arrive on every FlightSite route**, not only while a
  tab sits on the Live Map — SPEC §48's "while FlightSite is open in the
  browser" as written. Clicking one brings the tab back to the map with the
  aircraft selected. The live picture and activity tail now reset on
  connection loss rather than on navigation; the selection and its track
  reset when leaving the map (#105)

### Fixed
- **Route enrichment applies when you save it.** Enabling AeroDataBox,
  disabling it, or pasting a new key takes effect immediately; previously the
  provider was built once at startup, so a key added after boot produced no
  origin/destination until a restart, with the Settings section claiming
  "Applies immediately" all the while (#161)
- **Decoder statistics populate after the setup wizard** (messages,
  positions, RSSI, decoder uptime) without a restart: the receiver-metrics
  service can now be given its `stats.json` poller after it has started
  (#129)
- **Aircraft marker and trail share one clock**: live track points are dated
  by the decoder's fix time rather than arrival, so the marker no longer
  leads its own trail head by up to a nautical mile, a backfilled history
  merges with no seam, and a new position never inherits a stale age from the
  previous report (#145)
- `docs/CONFIGURATION.md` tells the truth about alert templates (they apply
  on save since 0.3.0) and about which settings still need a restart

### Upgrade notes
- No database migration in this release: `docker compose pull && docker
  compose up -d`.
- Alert matches recorded before this release keep reading "not notified";
  the marker is written only from this release on.
- Every open FlightSite tab now holds one WebSocket whichever route it is on;
  previously only Live Map tabs did.

### Known issues
- Six low-severity items remain open (#96, #98, #100, #112, #138, #147). The
  Raspberry Pi 4 SSD qualification (#153) is deferred by the owner; the Pi 5
  NVMe baseline (`docs/PERFORMANCE.md` §5.5) is the current reference run.

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
