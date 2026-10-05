# Changelog

All notable changes to FlightSite are documented here, per release. The format
follows [Keep a Changelog](https://keepachangelog.com/); versions follow
[Semantic Versioning](https://semver.org/) (`0.x.y` during pre-1.0 development).
This file is updated only on release branches (see `docs/RELEASE.md`).

## [0.12.0] — 2026-10-02

Aircraft on the Live Map now look like what they are. The three-shape icon set is
replaced by twenty-one first-party silhouettes chosen by type designator, category or the
aircraft's own emitter category, with military and government aircraft tinted as a
secondary cue. Demo mode shows the whole set. No schema change.

### Added
- **Bespoke aircraft silhouettes** (SPEC §34): Cessna-style high-wing single, Cirrus,
  low-wing single, light twin, twin turboprop, business jet, narrowbody, widebody twin,
  widebody three/four-engine, fighter, bomber, tanker (boom and all), military transport,
  maritime patrol, helicopter (redrawn), tiltrotor, tandem rotor, glider and UAV, beside
  the unchanged generic fallback and its on-the-ground form. The type level keys on the
  ICAO designator the metadata registries resolve (`C172`, `SR22`, `B738`, `A388`,
  `F16`, `K35R`, `H47`, …); every backend `icon_category` and the emitter categories
  `A1`–`A7`, `B1`, `B4` and `B6` map to a shape, so an aircraft with no registry entry
  still draws what its transponder says it is. Original MIT artwork, recorded in
  `docs/LICENSES.md`
- **Classification tint** (SPEC §36): each silhouette is drawn in a civil, a military
  (olive) and a government / law-enforcement (blue) palette, chosen from the published
  classification flags alone. The shape stays the primary cue and the classification is
  always also stated in text, so nothing is said by colour alone
- **Demo airframes for every shape**: commercial, rare, first-ever and MLAT demo profiles
  carry a type designator and model with no operator — so a demo 737 is drawn as a 737
  while its classification stays honestly unknown — and fighters, a bomber and a Chinook
  join the demo military traffic. Ground traffic and the emitter-only helicopter are
  left as they were

### Changed
- The icon resolver's chain (type → category → emitter → generic) and its ground rule are
  unchanged; its tables are populated. A typed airliner keeps its planform while taxiing,
  so the ground icon now appears only on traffic no registry describes
- Sixty-four icon images (21 shapes × 3 palettes + the MLAT ring) register once per
  basemap style load, in parallel; a drawing that fails to decode is now reported in the
  browser console by name instead of silently leaving the map without aircraft, and the
  e2e suite probes a sample of registered images
- `docs/PRODUCT.md` describes the silhouette set and the tint; `docs/LICENSES.md` records
  the artwork's new location

### Upgrade notes
- No migration and no configuration change. `docker compose pull && docker compose up -d`
  is the whole upgrade; a backup first is still the documented habit.
- The new icons draw from `aircraft_type` and `classification`, which come from the
  imported metadata registries (Settings → Metadata → Update Aircraft Metadata). An
  install that has never imported metadata sees the emitter-category shapes (light,
  airliner, heavy, high-performance, rotorcraft, glider, UAV) and the generic fallback.
- Palette colours and the designator tables live in
  `frontend/src/features/map/aircraft/icons/`; a new silhouette is a drawing plus a table
  row.

### Known issues
- A P-8 and a 737-800 share a planform and differ only by tint (the P-8 is a 737); the
  detail panel states the classification. The KC-10 carries the `DC10` designator and the
  A330 MRTT the `A332`, so both draw as their civil airframes. Carried over: #255, #241,
  #244, #153 (deferred), #209–#212

## [0.11.0] — 2026-10-01

The post-v0.10.0 usability and observatory program (`docs/design/080-feature-program.md`),
shipped as one release: everyday usability first — units everywhere, every page in the
sidebar, keyboard shortcuts, sharing, list search, a phone Live Map that installs to a
home screen, map display controls — then the receiver as an instrument: readsb fields
FlightSite used to discard, alerts about the station itself, "What was that?", coverage
against the radio horizon, and richer alert rules.

### Added
- **Ten-section sidebar** — Activity, Health (with a roll-up status dot) and Feeders join
  the seven original sections (SPEC §10 amended by the owner, 2026-09-28) (#225)
- **Keyboard shortcuts** with a `?` sheet: `/` search, `L` layers, `F` filters, `H`
  recentre, `[` `]` step through interesting aircraft, `M` measure, `T` trails, `W`
  "What was that?", and `g` + a letter to go to any section; suspended while typing
- **Copy link, share and QR code** on the aircraft, sighting and Live Map views, for
  moving a view from a wall screen to a phone (#225)
- **System theme** option that follows the OS, and a sidebar collapse that is remembered
- **List search**: a filter box on Aircraft (ICAO, registration, any callsign the airframe
  has flown, type, operator) and an ICAO-or-callsign prefix on Sightings; `q=` on both
  list endpoints, matched case-insensitively from an index; the boxes wait for two
  characters (#226)
- **Phone Live Map**: below 768 px the floating cards become a bottom dock that opens one
  card at a time, and the aircraft detail panel becomes a draggable bottom sheet (#227)
- **Installable app**: a web app manifest and a hand-written service worker that caches
  only the app shell — never `/api/`, the live socket, tiles or anything cross-origin —
  with a "new version available — Reload" prompt (#227)
- **Map display controls**: toggles for range rings, the receiver marker and labels; label
  presets (full / compact / altitude only); optional short trails for every aircraft
  (30 points, 2 minutes); a distance-and-bearing measure tool (#228)
- **Decoder fields**: readsb's emitter category, autopilot-selected altitude and emergency
  state are captured and shown; the category chooses the silhouette when no metadata
  exists and joins the category filter; the decoder's emergency state (general, lifeguard,
  minimum fuel, no radio, unlawful interference, downed) is an emergency source beside
  squawks 7500/7600/7700, never double-notified (#229)
- **Receiver self-alerts**: browser notifications when the message rate collapses against
  the same hour-of-week baseline, when the decoder is disconnected, or when a feeder goes
  offline — once per episode with a restore, a Settings section, an *Active self-alerts*
  card on Health, and a `self_alerts` diagnostics block (#231)
- **"What was that?"** (`GET /api/v1/overhead`): the aircraft whose stored position fixes
  came closest to the receiver near a chosen moment, from the Live Map, the phone Activity
  sheet, the Activity page or `W`; every result is a stored fix, never interpolated (#233)
- **Coverage by altitude** on the Receiver page: the furthest aircraft heard per 5° sector
  in three altitude bands against the 4/3-earth radio horizon from the antenna height,
  with findings that name sectors reaching under 60 % of the horizon ("likely
  obstruction") (#230)
- **Richer alert conditions**, still a flat AND: squawk sets, callsign and registration
  patterns, ground-speed and vertical-rate bounds, emitter category, and a polygon drawn
  on a mini-map in the rule builder (with a keyboard-accessible text fallback) (#232)

### Changed
- The **units preference** is honoured on map labels, the activity feed's range records,
  the Feeders range tile and the display-radius notice, which always printed ft / nm
  before; a guard test now fails on any new hard-coded unit suffix (#224)
- **Antenna height is above ground level** (owner decision 2026-09-30): the field is
  labelled so in the wizard and Settings, and "What was that?" no longer subtracts it from
  the aircraft's altitude
- Migration **0018** adds four case-insensitive prefix indexes for list search; the
  metadata import drops and rebuilds the two on `aircraft_metadata_resolved` around its
  swap, so the writer hold stays within ~4 % of before
- Migration **0019** adds the nullable `aircraft.emitter_category` column
- Migration **0020** adds `range_by_bearing_band_daily` (72 sectors × 3 bands a day,
  kept indefinitely like `range_by_bearing_daily`)
- Alert rule conditions are stored as a versioned document (`version: 2`); v1 rules load
  unchanged and are rewritten only when next saved
- The frontend builder image and CI run on Node 24 LTS; vitest 5; Dependabot watches the
  uv-managed backend
- The visual-regression fixtures were re-recorded and every baseline retaken; the Receiver
  baseline viewport grew for the coverage card, and phone baselines were added
- The in-suite perf smoke run takes 21 ticks so a per-tick p95 is not a single stalled
  runner tick (#240)

### Fixed
- Filters button no longer overlaps the Layers card header; Basemap, Layers and Filters
  stack in one column (#245)
- A failed Feeders page is labelled "Feeders", not "Receiver", by the error boundary
- Receiver is no longer highlighted in the sidebar on the Feeders page
- The analytics busiest-hour test no longer collides with itself within two hours of the
  receiver's local midnight, which had failed every Dependabot PR's backend job (#221)
- `undici` and `brace-expansion` advisories of 2026-09-30 cleared (dev dependencies)

### Upgrade notes
- **Back up first** (`docker compose exec flightsite-backend flightsite-backup create`):
  three migrations run on first start. 0018 builds four indexes, 0019 adds one column,
  0020 creates one empty table. Pre-flighted on a copy of a 590 MB production database
  (112,771 sightings, revision 0017): the index build took about 16 s and the whole
  start, migrations plus the startup integrity check, 55 s on a desktop; foreign keys
  checked clean.
- **Set the antenna height** (Settings → Receiver, *above ground*) to see the radio horizon
  and obstruction findings on the Receiver page; the coverage chart fills from the day of
  the upgrade onward.
- **Install to a phone** requires a secure context: HTTPS or `localhost`. Over plain HTTP
  on a LAN address the phone layout works but there is no install prompt or offline shell.
- Receiver self-alerts are on by default with a 40 % / 15 min rate threshold and a 5 min
  decoder threshold; the rate condition stays in "learning" until two weeks of hourly
  history exist. Demo installs script a decoder outage at :30 every hour.

### Known issues
- The kill-drill test fails in most full local runs on Windows and passes alone (#255);
  the unfiltered Sightings page may switch to a full scan once SQLite statistics exist
  (#241, to confirm); the visual-test container keeps a stale dependency volume after a
  package change (#244); #153 remains deferred; review follow-ups #209–#212 remain open

## [0.10.0] — 2026-09-26

FlightSite now watches the networks the receiver feeds. A Feeders page under
Receiver shows every feed's status, when it last sent data, its MLAT sync, gaps
in feeding with availability over a day, a week or a month, links to each
network and to its feed-stats page, and links to the other pages hosted beside
FlightSite.

### Added
- **Feeders page** at `/receiver/feeders`, reached from Receiver and Health:
  receiver uplink tiles (bytes out, messages and positions per minute, aircraft,
  MLAT inbound, dropped samples, max range); one card per feed with its status,
  since / last data sent, MLAT and ADS-B-out chips, an *Open* link and a *View
  stats on …* link; a gap timeline with availability over 24 h / 7 d / 30 d,
  scored over the span FlightSite actually observed; metric charts; and a Local
  pages card (#215)
- Feed kinds: `readsb` (the receiver's uplink), `piaware` (FlightAware),
  `fr24` (FlightRadar24), `ultrafeeder` (ADS-B Exchange, AeroDataBox and any
  other connector: MLAT stats over HTTP, ADS-B-out from container logs),
  `opensky_logs`, `docker_health`, `link_only`
- **Opt-in Docker socket** (`feeders.docker_socket`) for the feeds that publish
  their state only in container logs (OpenSky, the ADS-B-out legs); off by
  default, documented as a trust decision in `docs/SECURITY.md` and
  `docs/INSTALL.md`
- Settings → **Feeders**: poll interval, socket path, an entries editor with
  kind-dependent fields, local pages, and a masked per-feed *stats URL* (kept in
  `secrets.yaml`, reached through an internal redirect, never shown); an
  "Load the example" button fills the six-entry layout for a Pi running
  ultrafeeder + piaware + fr24 + opensky
- Health: a Feeders card (up / degraded / down / unknown, socket state); a down
  feed degrades the overall status without taking it down
- Activity: `feeder_offline` (high) and `feeder_restored` (info) events, with
  the outage length; both in the Activity page's filter
- Receiver page: a Feeders summary card
- API: `GET /api/v1/feeders`, `GET /api/v1/feeders/{name}/history?window=`,
  diagnostics `feeders` section, `counters.feeder_poll_failures`
  (`docs/API.md` §3.12)
- ADR-0017 (feeder status sources and the opt-in Docker socket); SPEC notes in
  §10, §67 and §79

### Changed
- Migration **0017** adds `feeder_episodes` and `feeder_samples`; it creates
  two empty tables and moves no data
- The visual-regression fixtures gained the Feeders view; the Receiver baseline
  was re-taken for the summary card

### Fixed
- Setup wizard: the location map's marker follows the just-typed coordinate
  (a dependency the map memo had missed)
- Feeder status writes survive the poll task being cancelled at shutdown, so a
  stop can no longer strand the writer connection or leave an episode open
  (#218)

### Upgrade notes
- **Back up first** (`docker compose exec backend flightsite-backup create`).
- Nothing is watched until feeds are configured: Settings → Feeders → *Load
  the example*, adjust hosts and ports, save. Entries poll over HTTP without any
  further setup.
- To watch OpenSky and the ADS-B-out legs, mount the Docker socket into the
  backend container read-only and set `feeders.docker_socket`
  (`docs/INSTALL.md` "Feeders"); this grants the container root-equivalent
  access to the Docker daemon on most hosts — leave it off if that is not
  acceptable, and those feeds read `unknown`.
- Paste each network's feed-stats page URL into the Feeders section (stored in
  `secrets.yaml`); FlightAware's is filled from piaware automatically.

### Known issues
- #153 (clean Raspberry Pi 4 qualification on non-SD storage) remains deferred
  by the owner; review follow-ups #209–#212 remain open

## [0.9.0] — 2026-09-25

Every page is now expected to be useful *and* robust: a formal site review
found 71 things that were wrong, misleading or fragile, and this release fixes
all of them. Underneath, a full metadata import no longer stalls the live
pipeline, and the diagnostics say which consumer fell behind.

### Fixed — correctness
- **Analytics, Receiver and Today at a Glance read the right day.** The
  rollup writers captured the receiver timezone once at process start, which
  on every fresh install is `UTC` because the setup wizard writes the
  timezone after the backend has booted; "today" then read a day that held
  nothing. The writers now resolve the live timezone on every pass, and an
  install whose rollups were built under another zone rebuilds them once on
  the first boot after upgrade, one day per transaction (#205, R1-02/R3-01)
- **Switching the basemap keeps every layer.** One click on the basemap
  picker removed aircraft, range rings, receiver marker, airports, airspace
  and the selected track until a reload (R1-01)
- Ascending sorts on the Aircraft and Sightings tables put unknown values
  last instead of first, so "closest approach" no longer answers with
  aircraft that have none (R2-01)
- An open sighting reports its running duration and "still open" rather than
  `0s` / `Unknown`; an aircraft's cumulative observed time includes it
  (R2-02)
- Analytics no longer reports "never seen before" as two different numbers
  on one page; rollup-backed figures that are not computed yet read
  "Not computed yet" rather than `0` (R3-02/R3-03)
- "New busiest day" is judged on the receiver's calendar and never names a
  day as its own previous record (R1-17)
- Healthy status pills and the decoder test's "Connected" confirmation are
  legible in both themes; they were rendered in an on-accent colour on a card
  surface (R4-01)

### Fixed — robustness
- A render error or a mistyped URL shows an in-app error or not-found page
  instead of React Router's developer screen (R0-01/R0-02)
- The Live Map keeps its picture across a lost connection, marks it stale,
  polls the REST API while the socket is down, and the connection chip says
  what is happening; panels no longer assert an empty sky (R1-03/R1-04)
- Every history page, the Analytics and Receiver cards, the alert history
  and Today at a Glance refresh on their own and say when their data is from;
  a failed request keeps the last data on screen with a retry instead of
  unmounting the table (R2-03/R2-04, R3-05/R3-06, R4-05)
- The Health page keeps its last good payload when a poll fails and shows a
  stale banner with a retry (R4-04)
- A Settings save the backend rejects no longer leaves the section unsavable
  (R4-02); the setup wizard survives a browser refresh (R4-15)
- Phone width: the sidebar collapses to a rail with an overlay drawer below
  the `md` breakpoint, and tables collapse secondary columns with a visible
  scroll edge (R1-07/R2-08/R3-07/R4-06)
- Tile outages no longer draw the receiver at a development placeholder
  (R1-05); transport failures read as "FlightSite's backend is not
  responding." rather than `Failed to fetch` (R3-08/R4-19)

### Added
- Live Map: selected aircraft in the URL, "showing N of M" beside the
  filters, browser-notification status on the map, headings and skip links
  for every panel, a light basemap by default in the light theme, attention
  styling weighted by severity so a new install is not all "interesting"
- Aircraft detail: age from the manufacture year, tracker links that use the
  callsign when no registration is known
- Sightings: every row reachable by keyboard; the drawn path labelled as a
  sample of N of M points; the receiver's timezone named on every history
  page
- Activity: Alerts and Emergencies in the type filter, rows grouped by day
- Alerts: the history identifies the aircraft (callsign · type ·
  registration) and links to its sighting; tab and rule filter in the URL;
  watchlist names on rule cards; the app's own confirmation dialog for
  deletes; alert templates managed in one place — the Alerts page's Templates
  gallery (the Settings checkbox list is gone; the wizard's selection seeds
  the first run)
- Settings: metric conversion hints under nm/ft inputs; honest "Checking…" /
  "Unknown" metadata status; dates on values that can be weeks old
- Health: a Live events card naming each consumer of the live event stream
  with its shed count and backlog; frontend/API/schema versions with a warning
  on mismatch; shared metadata source names
- Receiver: unsupported decoder metrics hidden with one explanatory line;
  cardinal points on the range polar plot; units on every chart axis
- `GET /api/v1/diagnostics` gains `live_events`; `websocket.events_dropped`
  is now the WebSocket subscriber's own figure (#185)

### Changed
- A full **Update Aircraft Metadata** run no longer holds the database writer
  for the length of the resolution rebuild: resolution and classification
  are built page by page in a worker thread into two scratch tables
  (migration 0016) and installed with a set-based swap, so sighting
  persistence and alert evaluation keep up during an import (#185)
- API: nulls-last ordering on every list endpoint (§2.4); `open` and
  `elapsed_s` on sightings (§3.7); `lifetime.open_sighting_elapsed_s` (§3.5);
  `complete` on analytics rows, classification activity and summary, with the
  rollup-backed fields nullable when not computed (§3.8/§3.9); alert-match
  rows carry `callsign`, `registration`, `aircraft_type`,
  `closest_approach_nm`, `lowest_altitude_ft` (§3.10)
- The visual-regression fixtures and every baseline were re-recorded

### Upgrade notes
- **Back up first** (`docker compose exec backend flightsite-backup create`).
- Migration 0016 adds two empty scratch tables and moves no data.
- On the first boot after upgrade the analytics rollups are rebuilt once
  from the sightings history, one day per transaction; Analytics and the
  Receiver charts may lag a minute or two on a multi-year database while
  that runs. Receiver daily metrics older than the high-resolution window and
  the range-by-bearing history keep their original day key.
- The review itself is in `docs/reviews/2026-09-20-site-review.md`.

### Known issues
- #153 (clean Raspberry Pi 4 qualification on non-SD storage) remains
  deferred by the owner. Follow-ups from the review: #209 (aircraft age on the
  Live Map panel needs `manufacture_year` on the live payload), #210 (E2E for
  basemap switch and tile outage), #211 (severity/offset in the Alerts URL),
  #212 (consolidate the analytics-local error helper)

## [0.8.0] — 2026-09-19

The Analytics page's two headline rankings now explain themselves: an
aircraft is named by its tail number and type, and a type by its designator
and its long-form description.

### Added
- **Top aircraft** bars carry the registration (ICAO hex when none is known)
  and the ICAO type designator; the tooltip shows hex, type and model, operator
  and sighting count, and the screen-reader summary names identity and type
  (#198)
- **Top types** bars carry the designator's long-form description beside the
  shorthand — `B738  Boeing 737-800` — cut on the axis and whole in the
  tooltip, which also shows sightings, distinct aircraft and days seen (#198)
- `GET /api/v1/analytics/top-types` rows gain `description`: derived from the
  metadata already imported as the model string most of that designator's
  airframes carry, ties broken alphabetically, `null` when no airframe of the
  type has a model. No new dataset and no migration; `top-operators` rows
  carry `description: null` (`docs/API.md` §3.8)

### Changed
- Metadata strings (registrations, operator names, model descriptions) are
  HTML-escaped before they reach an ECharts tooltip
- The visual-regression fixtures and Analytics baselines were re-recorded to
  carry the new field and labels

### Known issues
- #153 (clean Raspberry Pi 4 qualification on non-SD storage) remains
  deferred by the owner; #185 (a full metadata import starves live consumers
  for the duration of the run) is open at low severity

## [0.7.0] — 2026-09-06

The tracker is empty. This release clears the six low-severity items that
remained after every open issue was triaged in v0.4.0, and it is the first
release with no known product bug of any severity.

### Added
- **Per-rule alert history**: each rule on the Alerts page has a *Show
  matches* control that filters the history to that rule, backed by a new
  `rule_id` filter on `GET /api/v1/alerts/matches` (#98)
- `metadata.source_url_overrides`: point any metadata dataset download at a
  mirror or a local fixture server, per source, from `config.yaml` or the
  environment; never applied to a request that carries a key (#112)
- Demo mode now carries a handful of military, government and police
  airframes, so those alert templates fire in demo and in the end-to-end
  suite (#112)

### Changed
- The alert engine no longer evaluates rules on a stale-aircraft event,
  which carries no new input; a removal no longer forces an immediate
  persistence flush; and the nearest-airport context keeps an inferred
  approach or departure through a two-minute dropout, so an aircraft that
  goes quiet on final does not lose its phase (#138)
- The map's label-density tier is driven by the number of labelled aircraft
  rather than by every live entry, so Mode S-only contacts no longer push
  labels into the sparse tier; anchor behaviour under sustained collision
  was measured against MapLibre's placement code and accepted as already
  bounded (#147)

### Fixed
- The WAL kill-drill test no longer fails on a slow or busy machine: it
  waits on the subprocess's own progress instead of a fixed window (#100)
- Every aircraft-layer style expression is validated against the MapLibre
  style specification in the unit suite, so an invalid expression fails a
  test instead of failing silently in the browser (#96)

### Upgrade notes
- No database migration: `docker compose pull && docker compose up -d`.
- No configuration change is required; the URL overrides are optional.

### Known issues
- The Raspberry Pi 4 SSD performance qualification (#153) remains deferred
  by the owner; the Pi 5 NVMe baseline is the current reference run. No
  other issue is open.

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
