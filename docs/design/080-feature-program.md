# 080 — Usability & observatory expansion program

Status: accepted as the planning record for slices 081–090 (owner request 2026-09-27:
"plan for ways to improve the usability and additional featuresets that would make
FlightSite more valuable — think outside the box", approved for implementation
2026-09-28). Items marked **pending owner decision** are proposals only: they touch a
SPEC.md v1 non-goal or scope limit and are not scheduled until the owner records a
dated amendment (the §79 feeder-monitoring amendment of 2026-09-26 is the precedent).

## 1. Why

Every roadmap slice through 079 is merged and v0.10.0 runs on the owner's receiver.
The roadmap has no feature themes after v0.10.0; v1.0.0 waits only on #153 (deferred
by the owner). A read-only survey of the codebase on 2026-09-27 found:

- **Capture we discard.** `ingest/readsb.py` keeps hex, flight, altitudes, gs, track,
  vertical rate, squawk, position, seen/seen_pos, rssi and messages. It drops
  `category`, `nav_altitude_mcp`/`nav_altitude_fms`, `nav_qnh`, `nav_heading`,
  `emergency`, `ws`/`wd` (wind), `oat`/`tat`, `ias`/`tas`/`mach` and `roll`.
- **Data stored but not shown.** Per-sighting `inferred_airport_ident` /
  `inferred_phase`, route-directory intermediate stops, and the `/api/v1/aircraft/interesting`
  endpoint, which has no frontend caller.
- **Alerting is narrow.** Rule conditions cover classification, type, model, watchlist,
  rarity, distance, altitude and ground state. There are none for squawk,
  callsign/registration pattern, speed, vertical rate, emitter category or area.
  Delivery is browser-only, as SPEC §48 requires.
- **Usability gaps.**
  - Activity, Health and Feeders are routed but not in the sidebar.
  - No keyboard shortcuts, share/copy-link or QR hand-off, and no PWA manifest.
  - The theme cannot follow the OS, and sidebar collapse is forgotten on reload.
  - `/aircraft` has no filter at all; `/sightings` needs an exact six-hex ICAO.
  - There are about ten floating Live Map cards with no phone layout.
  - Only two layer toggles.
  - No trails except for the selected aircraft.
  - Map labels always print ft/FL, and several notices always print "nm", whatever
    the units preference says.

## 2. Guardrails every item follows

- **Pi budget (SPEC §5, §85).**
  - Live work is bounded and in memory: per-aircraft ring buffers with O(1) work per
    tick.
  - New persistence goes through the write-behind worker as hourly or daily rollups,
    never as per-point tables.
  - Slices touching ingest, workers or migrations run the perf harness.
- **Migrations** follow the table-rebuild rules from slice 072. They are tested against
  seeded child tables (the slice-050 synthetic dataset) and serialized against other
  migration-bearing slices.
- **Offline-first and honest.** Nothing new needs the internet. Inferred values say so
  ("Likely", "Estimated", "derived from N reports"). Unknown is shown rather than
  invented.
- **Scope.** Items that touch a §79 non-goal, the §33 overlay list, §37 or §48 need an
  owner amendment first. They are listed in §5 and never implemented silently.

## 3. Wave A — everyday usability (slices 081–085, release theme v0.11.0)

No spec amendments; mostly frontend.

| Slice | Item |
|---|---|
| 081 | **Units everywhere.** Every surface that prints altitude, speed or distance goes through the unit-aware formatters: map labels (`features/map/labels/labelContent.ts`), the display-radius notice, filter-drawer hints, the interesting and non-positioned panels, and notification bodies. An audit test fails on any new hard-coded unit suffix. |
| 082 | **Shell, keyboard & sharing.** Activity, Health (with a roll-up status dot) and Feeders in the nav (owner amended SPEC §10 to ten primary sections, 2026-09-28). A "System" theme option that follows `prefers-color-scheme`. Persisted sidebar collapse. A `?` shortcut sheet with map and navigation shortcuts. Copy-link / `navigator.share` on the aircraft, sighting and map views. A QR code of the current URL for moving a view from a wall screen to a phone. |
| 083 | **List search.** A filter box on `/aircraft` (ICAO, registration, callsign, type or operator prefix) and prefix matching on `/sightings`, backed by `q=` on the existing list endpoints. This is list-scoped filtering within §37, not the deferred global search. |
| 084 | **Phone Live Map & installable shell.** Below 768 px the floating cards collapse into a bottom toolbar and the detail panel becomes a bottom sheet. A web app manifest, icons and a service worker that caches only the app shell. Live data is never cached. |
| 085 | **Map controls.** Toggles for range rings, the receiver marker and labels. Label content presets (full / compact / altitude-only). Optional short trails for every aircraft from the live store, with a bounded point count. A distance/bearing measure tool. |

## 4. Wave B — the receiver as an instrument (slices 086–090, release theme v0.12.0)

No spec amendments.

| Slice | Item |
|---|---|
| 086 | **Decoder emitter category, selected altitude & emergency state.** Capture readsb `category`, `nav_altitude_mcp`/`nav_altitude_fms` and `emergency`. Show them in the detail panel. Use `category` for the §34 category-silhouette fallback when no metadata exists, and in the §37 category filter. Treat the decoder's `emergency` state (general, lifeguard, minfuel, nordo, unlawful, downed) as an emergency source beside squawk 7500/7600/7700. |
| 087 | **Coverage analysis.** A daily rollup of maximum range per 5° bearing × altitude band (<10k, 10–25k, >25k ft). A Receiver page chart compares observed range against the theoretical radio horizon (from `receiver.antenna_height_ft` and band altitude), then flags sectors that reach a low share of line of sight ("NE sector at 58 % of radio horizon: likely obstruction"). |
| 088 | **Receiver self-alerts.** Built-in, toggleable conditions with activity events and browser notifications: message rate below a configurable share of the same hour-of-week baseline, decoder disconnected longer than N minutes, and feeder offline. |
| 089 | **Richer alert conditions (flat AND, §43).** Squawk set, callsign/registration glob, ground-speed and vertical-rate bounds, emitter category (after 086), and a drawn polygon area, edited on a mini-map inside the rule builder. |
| 090 | **"What was that?"** Pick a moment (default: now) and get the aircraft that passed closest overhead within ±N minutes, with altitude, distance and sighting link. `GET /api/v1/overhead?at=&window=` decodes stored tracks only for sightings overlapping the window. |

## 5. Pending owner decision

These proposals touch a spec limit and need a dated amendment before they are scheduled.

| Item | Spec limit | Proposal |
|---|---|---|
| Aircraft-derived weather station | §79 "weather integration" (interpretation: measurement from our own receiver is not integration) | Capture `ws`/`wd`/`oat`/`tat`/`nav_qnh`; hourly rollups by altitude band. Winds-aloft profile, jet-stream strength over time, lapse rate / estimated tropopause, and the local altimeter setting inferred from approach traffic. Labelled "derived from N aircraft reports". |
| Coverage and traffic-density map layers | §33 overlay list | A grid-cell rollup (~2 NM × altitude band) drawn as a coverage outline and a flight-corridor heatmap; filter by band to answer "what flies low over my house?" |
| Command palette / global search | §37, §79 "free-form global search" | Ctrl/⌘-K across live and historical aircraft, callsigns, airports, pages and actions; `GET /api/v1/search`. |
| Notification channels | §48 browser-only, §79 HA/email/push | A `NotificationProvider` seam (ADR-0006) with webhook, ntfy, MQTT (Home Assistant discovery) and SMTP email. A delivery worker on its own bounded queue off the live path, with retry, backoff and a circuit breaker. Tokens in secrets.yaml; each channel listed in SECURITY's outbound table. |
| Manoeuvre detection | §79 circling / loitering / repeated-pass | Holding and orbits (cumulative turn), plus go-around, emergency descent, low pass and hover, labelled "Likely …"; activity events and alert conditions. |
| Hardware change log with before/after | §79 period-over-period | Mark a hardware change and compare msg/min, range by bearing and coverage for N days either side, normalised by traffic. |
| Airport movements board | §79 airport-level historical analytics (a live/recent board may be outside it) | A split-flap arrivals/departures board for nearby airports from inferred airport/phase and the route directory. |
| Time machine | §79 historical animated playback | A Live Map scrubber reconstructing the sky at any past moment from stored tracks (the §19 schema was built for it). |
| Export | §79 data export | CSV/JSON of history and analytics; GeoJSON/KML per sighting track. |
| Unusual-for-now indicator | §79 period-over-period | "Traffic 42 % below the usual Tuesday 17:00" from the hour-of-week baseline. |
| Kiosk / wall display | §79 aircraft-follow (for auto-follow) | `/display`: chrome-less, auto-cycling focus and cards, night dimming, burn-in drift. |
| Optional `/metrics` | §79 says only that Prometheus must not be *required* | An optional exposition endpoint; confirm this reading. |

Not spec-limited, held for later waves on value/effort grounds:
- **Regulars & schedule watch:** "usually passes 14:05, not seen today", plus a visit
  punch card.
- **Collections:** type life list, operator passport, daily bingo, streaks.
- **Digest and annual "year in the sky" recap page.**
- **Overhead ETA / "look up now" in-app notice.**
- **Spoken announcements** via browser SpeechSynthesis.
- **Radar-scope skin and sky-dome view.**
- **Sun/moon transit finder.**
- **SVG stats badge and static snapshot export.**

## 6. Sequencing

Wave A comes first because it is the cheapest and highest-return, and it has no
migrations. Slices 082–085 can run in parallel worktrees once 081 lands, because 081
touches the formatters they render through.

Wave B follows. 086 and 087 carry migrations and are serialized; 088–090 follow in
any order (089 after 086).

Each wave is released as a minor version with the owner's approval. The pending items
are re-planned as a Wave C once the owner has decided them.
