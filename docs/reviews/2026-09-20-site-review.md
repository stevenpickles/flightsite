# FlightSite site review — 2026-09-20 (pre-v0.9.0)

**Scope.** Every user-facing page of FlightSite as built on `dev` at merge `b976c89`
(slice 075), reviewed against `docs/PRODUCT.md` §4 and `planning/SPEC.md` for two
questions the owner asked: *is each page providing useful information, and is it
providing it in a really robust way?*

**Method.** A demo-mode stack built from `dev` ran on `http://localhost:8090` with
first-run setup completed and deterministic traffic accumulating for ~90 minutes. Four
reviewers (Opus agents) each took a page group and worked from the same brief: for every
page, screenshots in light and dark at 1440×900 and 390×844; every loading, empty,
partial, error, unreachable and stale state, injected client-side with Playwright
`page.route` so the shared stack stayed untouched; sort/filter/pagination/deep-link
round-trips; units, timezone and number formatting; keyboard and heading structure; and a
read of the feature directory and the backend endpoints behind it. A fifth, cross-cutting
pass (Fable) covered routing. Every finding carries evidence a reader can reproduce.
Reviewer reports are reproduced verbatim in the appendices; screenshots are in the
session scratchpad and are not committed.

| Reviewer | Scope | Findings (crit / high / med / low) |
|---|---|---|
| R0 (Fable) | routing, cross-cutting | 2 (0 / 1 / 1 / 0) |
| R1 | Live Map and every panel on it | 17 (2 / 5 / 6 / 4) |
| R2 | Aircraft, Aircraft detail, Sightings, Sighting detail, Activity | 17 (0 / 8 / 9 / 0) |
| R3 | Analytics, Receiver | 14 (1 / 6 / 6 / 1) |
| R4 | Alerts, Settings, Health, Setup wizard | 21 (1 / 5 / 10 / 5) |
| **Total** | | **71 (4 / 25 / 32 / 10)** |

## 1. Executive summary

FlightSite's pages are, in their healthy state, well designed and closely follow the
specification: the Live Map's rendering, labels, filter model and detail panel; the honest
`Unknown` discipline on the history pages; the per-card failure isolation and accessible
chart summaries on Analytics and Receiver; the rule builder, the danger-zone dialogs and
the degraded rendering on Health. The "do not regress" lists in §4 are long and real.

What the review found is that the site is not yet **robust**, and in a few places the
information it shows is **wrong**. Four findings are critical and two of them are real
bugs on every install:

1. **Rollups are written under the wrong day (R1-02, R3-01, R1-17).** The analytics and
   receiver-metrics services capture the receiver timezone once at process start. On every
   fresh install that is `UTC`, because the setup wizard writes the timezone after the
   backend has booted; a later timezone change in Settings re-breaks it without a restart.
   The read side resolves the live timezone, so "Today" windows read a day that holds
   nothing: Today at a Glance shows `0 sightings` beside `112 unique aircraft`, Analytics
   says "No data for this window", the Receiver scorecard shows `Max range today —` next
   to a record set minutes earlier, and the activity feed announces a "new busiest day"
   for the same day it already recorded. This is the highest-value fix in the set.
2. **Switching the basemap deletes every FlightSite layer (R1-01).** One click on a
   first-class SPEC §32 control removes aircraft, range rings, receiver marker, airports,
   airspace and the selected track until the page is reloaded; the connection chip keeps
   saying "Live · 56 aircraft". One ordering bug in `MapLibreMap.tsx`, invisible to the
   unit test because the MapLibre mock never fires `style.load` from `setStyle`.
3. **Healthy status is invisible in both themes (R4-01).** `text-accent-foreground` is
   used on a card surface in five places, so the Health page's overall verdict pill,
   every "Connected"/"Intact"/"Imported"/"Keeping up" pill and the decoder test's
   "Connected — found readsb…" confirmation render as blank rectangles, icon included.
4. **No error boundary anywhere (R0-01, R1-06, R2-16, R3-04).** A single `null` in one
   optional card's payload, or a mistyped URL, replaces the whole app with React Router's
   "Unexpected Application Error! 💿 Hey developer 👋" screen.

Below the critical line, five **patterns** account for most of the 25 high findings and
should be fixed once, structurally, rather than page by page:

- **Nothing refreshes and nothing recovers.** Seventeen of eighteen Analytics/Receiver
  surfaces, all five history pages and the alert history fetch once on mount, retry once,
  and stop. A failed request unmounts the table, its sort headers and its pagination, so
  no control remains to retry (R2-03, R2-04, R3-05, R3-06, R4-05). The Health page goes
  further and discards a good cached payload on one failed poll (R4-04). No page says
  when its data is from.
- **The picture empties on a lost connection and the panels then assert falsehoods.**
  There is no REST fallback for the live picture; a socket drop clears it and the
  interesting panel says "No interesting aircraft right now", the non-positioned list says
  `0`, and the detail panel reports `Registration Unknown` for a registration it knew a
  second earlier. A socket that never connects shows "Connecting" forever (R1-03, R1-04).
- **Phone width is unusable everywhere inside the shell.** The sidebar is a fixed 256 px
  with no breakpoint, leaving 134 px for the map, every table and every card (R1-07,
  R2-08, R3-07, R4-06). The setup wizard, which renders outside the shell, is fine.
- **Ordering and "not yet" states mislead.** Ascending sorts put `NULL` first, so
  "Closest approach ▲" answers with aircraft that have no closest approach (R2-01); an
  aircraft overhead for sixteen minutes reports `Cumulative observed time 0s` (R2-02);
  rollup-backed cards print a confident `0` for "not computed yet" (R3-02); Settings
  asserts "Metadata last updated: never" while the status is still loading (R4-11).
- **Raw strings reach the user.** `Failed to fetch`, backend error text verbatim, internal
  subscriber names, `on watchlist 1`, `1 time(s)`, `1 points` (R3-08, R3-10, R4-09,
  R4-17, R4-19, R4-20).

Two findings are product decisions rather than bugs and were decided by Fable for the fix
slice, subject to the owner's veto: **alert templates get one control surface** — the
Alerts page's Templates gallery, with the Settings checkbox list reduced to a link and
the wizard's selection kept as a first-run seed only (R4-03); and **the units setting is
honoured in inputs by a conversion hint**, not by changing storage or the API (R4-13).

## 2. Verdict by page

| Page | Useful? | Robust? | Verdict |
|---|---|---|---|
| Live Map | Yes — richest surface in the product | No — basemap switch, socket loss, tile outage, render errors and phone width all break it | Fix R1-01..07 before release |
| Aircraft | Yes | No — no refresh, no retry, nulls sort first, phone unusable | Fix R2-01/03/04/08 |
| Aircraft detail | Yes, and honest about unknowns | Partly — open sightings misreport, tracker links drop two services, no age | Fix R2-02/10/11 |
| Sightings | Yes | No — rows unreachable by keyboard, Status column clipped at 1440 px, no refresh | Fix R2-07/13 plus the shared items |
| Sighting detail | Best history surface | Partly — path sample unlabelled, phone overlaps | Fix R2-12 |
| Activity | Only partly — the page whose job is "what happened while you weren't watching" is frozen from load, hides Alerts and Emergencies from its filter, shows no dates | No | Fix R2-03/05/06 |
| Analytics | **Wrong today** — reads the wrong day; contradicts itself on "never seen" | Partly — per-card isolation works; no refresh, no recovery | Fix R3-01/02/03 first |
| Receiver | Wrong today for the same reason; charts complete and accessible | Partly | Fix with Analytics |
| Alerts | Yes — best form in the app | Mostly — history never updates, no URL state, `window.confirm` deletes | Fix R4-05/07/10 |
| Settings | Yes | Mostly — a rejected save dead-ends six sections; templates contradict the Alerts page | Fix R4-02/03 |
| Health | Yes — but its headline verdict is invisible | Partly — one failed poll blanks it | Fix R4-01/04 |
| Setup wizard | Yes, and the only phone-usable surface | Mostly — reload loses the draft; stale copy | Fix R4-15/16 |

## 3. Consolidated work plan

Findings are deduplicated into work packages. Each package is one agent in an isolated
worktree on slice 076; one Conventional Commit per finding or tightly coupled group.
"Owner" is the agent tier: **opus** for backend queries, live state, map rendering and
cross-page contracts; **sonnet** for contained UI, state and formatting work.

| WP | Owner | Area | Findings | Notes |
|---|---|---|---|---|
| A1 | opus | Backend: day keys and rollup semantics | R1-02, R3-01, R1-17, R3-02, R3-03 | Timezone provider resolved live for the rollup writers; repair of rows keyed under the wrong day; a way for the API to say "not computed yet" (`null`) instead of `0`; the "never seen" definitions reconciled |
| A2 | opus | Backend: history ordering, open sightings, alert history | R2-01, R2-02, R4-08, R4-05, R4-20 | `nulls_last()` on every ascending sort; open-sighting durations computed from `started_at` to now; alert-match rows carry callsign/type/altitude/distance and link to their sighting; history list refreshes; plural wording in `describe()` |
| B | sonnet | App shell and API client | R0-01, R0-02, R1-06, R2-16, R3-04, R1-07, R2-08 (shell part), R3-07, R4-06, R3-08, R4-19 | Route error boundaries and a not-found page; collapsed rail below `md` with an overlay drawer; typed `NetworkError` with human messages in `lib/api/client.ts` |
| C1 | opus | Live Map rendering and live state | R1-01, R1-03, R1-04, R1-05, R1-10, R1-14, R1-16 | `style.load` ordering and a mock that fires it; REST fallback for the live picture and honest chip states (connecting / reconnecting / stale); receiver-derived defaults instead of the dev placeholder on tile outage; severity-weighted attention so a new install is not all "interesting"; theme-affine basemap; notice stacking |
| C2 | sonnet | Live Map panels and chrome | R1-08, R1-09, R1-11, R1-12, R1-13, R1-15 | Shown-of-total count and "no aircraft match" state; selection in the URL; skip links and headings; notification status surfaced; non-positioned list formatting through the shared formatters; chip live-region |
| D | opus | History pages (frontend) | R2-03, R2-04, R2-05, R2-06, R2-07, R2-08 (tables), R2-09, R2-10, R2-11, R2-12, R2-13, R2-14, R2-15, R2-17 | Per-query refresh policy and keep-table-on-error with retry; activity filter vocabulary and dates; focusable sighting rows; responsive column collapse; out-of-range page state; age from manufacture year; callsign tracker links; path sample labelled; timezone named; timeline fields; heading/table a11y |
| E | sonnet | Analytics and Receiver (frontend) | R3-05, R3-06, R3-08 (page banner), R3-09, R3-10 (frontend), R3-11, R3-12, R3-13, R3-14 | Retry per card and refresh with an "as of" line; polar plot labels; plurals; one date formatter; axis units; unsupported tiles hidden; T0 explained; `common_model` rendered or dropped |
| F | sonnet | Alerts, Settings, Health, Setup (frontend) | R4-01, R4-02, R4-03, R4-04, R4-07, R4-09, R4-10, R4-11, R4-12, R4-13, R4-14, R4-15, R4-16, R4-17, R4-18, R4-21 | Success-on-surface token; server errors never disable Save; templates managed on the Alerts page only; Health keeps its cached payload; Alerts URL state; watchlist names; shared confirm dialog; honest metadata status; date formatter; unit hints; shared source labels; wizard draft in `sessionStorage`; copy; version tile; touched gates |

Ordering constraints: A2 defines the alert-match payload F would otherwise render, so
A2 owns `AlertHistorySection.tsx`; B owns `lib/api/client.ts`, `routes.tsx` and
`components/shell/*`; nobody changes `lib/queryClient.ts` defaults (refresh policy is set
per query). The integrator runs the full suites once after all packages land.

## 4. What must not regress

Collected from the reviewers' "what works well" sections; the fix slice's self-review
checks each of these against the integrated branch.

- Live Map: aircraft layer, hierarchical icons, label declutter (36 symbols / 20 labels at
  390 px), the filter model's URL round-trip, detail-panel content, SPEC §32 aircraft
  rendering on a blank canvas when tiles are down, clean recovery when the socket returns.
- History: `Unknown` everywhere a value is missing, never a blank cell; distinct 404 states
  for "not a valid address" vs "never sighted here"; pagination to the last page; the
  closed-sighting detail page.
- Analytics/Receiver: the card inventory matches SPEC §58/§62; per-card failure isolation;
  sr-only data-bearing chart summaries; polar plot north-up and clockwise; both themes.
- Alerts: rule-builder validation and copy; edit round-trips; per-rule history drill-down
  with three distinct empty states; template "added" state from real provenance;
  watchlist entry validation and live match counts; tabs fail independently.
- Settings: exact per-field 422 mapping with `aria-invalid`/`aria-describedby`; secret
  handling; the danger-zone typed confirmation, focus trap and backup guidance;
  restart-required badges exactly where needed; independent per-section saves.
- Health: degraded rendering; self-recovery when the backend returns; distinct
  unknown/idle tones; the notifications card's shape; the Live events card disappearing
  on an older backend.
- Setup: step gating, decoder test/skip semantics, back navigation, keyboard-only
  completion, the honest Review step, phone layout.

## 5. Out of scope for the fix slice

Recorded here so they are not lost; each becomes a roadmap or issue entry if the owner
wants it:

- Aircraft age from a registry "first registered" date (R2-10 uses manufacture year).
- A hover readout on the sighting path (R2-12 delivers the label only).
- Bidirectional metric input in Settings and the rule builder (R4-13 delivers hints).
- Two-way sync between the Settings template checkboxes and rules (R4-03 delivers the
  single-surface alternative).
- Live-updating `/activity` over the WebSocket (R2-03 delivers polling on page 1).

---

# Appendices — reviewer reports, verbatim


## Appendix A — R0: cross-cutting (Fable)

## R0 — cross-cutting (Fable) — findings

### Findings
| ID | Page | Severity | Category | Title |
|----|------|----------|----------|-------|
| R0-01 | all routes | high | robustness | No route error boundary: any render error or unknown URL shows React Router's developer error screen |
| R0-02 | all routes | medium | robustness | No catch-all route: `/nonexistent` renders the same raw error screen instead of a styled "not found" with a way back |

#### R0-01 — No route error boundary
- **Page / surface:** `frontend/src/routes.tsx` (`createBrowserRouter`), every route
- **Severity:** high
- **Category:** robustness
- **Evidence:** `http://localhost:8090/nonexistent-page` renders "Unexpected Application Error! 404 Not Found 💿 Hey developer 👋 You can provide a way better UX than this…" (screenshot `review/r0/404.png`). `grep -rn "ErrorBoundary\|errorElement" frontend/src` returns nothing, so a thrown render error in any page component reaches the same default UI, with the app chrome gone.
- **Expected:** a styled, in-chrome error state that names the page that failed, offers "Try again" (reset the boundary) and a link back to the Live Map; the sidebar stays usable; the error is logged to console.
- **Proposed fix:** add `errorElement` on the `AppShell` route (in-chrome) and on the root layout (out-of-chrome fallback); a small `RouteErrorPage` component using `useRouteError` + `isRouteErrorResponse`; unit test that a throwing child renders the fallback with the shell still present. Files: `frontend/src/routes.tsx`, new `frontend/src/components/RouteErrorPage.tsx` (+ test). Estimate: S.
- **Suggested agent:** sonnet

#### R0-02 — No catch-all route
- **Page / surface:** `frontend/src/routes.tsx`
- **Severity:** medium
- **Category:** robustness
- **Evidence:** same screenshot; the SPA serves 200 for any path (correct) but the router has no `path: "*"` child.
- **Expected:** a "Page not found" view inside the shell with links to the seven sections.
- **Proposed fix:** add `{ path: "*", element: <NotFoundPage /> }` under `AppShell`; test. Estimate: S. Can share the component with R0-01.
- **Suggested agent:** sonnet


## Appendix B — R1: Live Map

## Live Map (`/`) — findings

Reviewer **R1**. Stack: demo mode at `http://localhost:8090`, built from current `dev`
(backend/frontend 0.8.0, schema 0016). Screenshots live in this directory; every image path
below is relative to it.

### Summary

The Live Map is, in its healthy state, the best page in the product: the aircraft layer,
labels, icon hierarchy, the interesting panel, the filter model and the detail panel are all
genuinely well built and closely follow SPEC §32–§37/§49/§50. What it does not survive is
anything going slightly wrong. Three problems dominate. **(1)** Switching the basemap — a
first-class SPEC §32 feature, one click away on every session — permanently deletes every
FlightSite layer from the map: aircraft, range rings, receiver marker, airports, airspace and
the selected track all vanish and never come back without a page reload, while the chip still
reports "Live · 56 aircraft". **(2)** "Today at a Glance" reports `0 sightings / 0 interesting
/ 0 mil-gov-police / max range —` next to its own `112 unique aircraft` and an interesting
panel listing 57; the cause is that the analytics rollup writer captures the receiver timezone
once at process start (UTC) while the query side reads the live one, so every rollup-backed
figure is keyed to the wrong local day on every install whose timezone was set by the setup
wizard. **(3)** The page has no fallback and no error boundaries: a lost WebSocket empties the
entire picture and the panels then *assert* "No interesting aircraft right now", and a single
`null` in one API response replaces the whole map with react-router's "Unexpected Application
Error!". Layout at 390 px is also effectively broken — the sidebar never collapses, leaving a
134 px map with every floating panel clipped off-screen. What works well is listed at the end
and is substantial; the fix slice should be careful not to trade any of it away.

### Findings

| ID | Page | Severity | Category | Title |
|----|------|----------|----------|-------|
| R1-01 | Live Map / basemap | critical | robustness | Switching basemap permanently deletes every FlightSite map layer |
| R1-02 | Live Map / Today at a Glance | critical | correctness | Today at a Glance reports zeros that contradict the same card and the panel beside it |
| R1-03 | Live Map / live picture | high | robustness | A momentary socket drop empties the map and the panels then assert false negatives |
| R1-04 | Live Map / connection chip | high | robustness | A socket that never connects is indistinguishable from an empty sky, forever |
| R1-05 | Live Map / overlays | high | robustness | Tile outage pins the receiver marker and range rings to the Seattle dev placeholder |
| R1-06 | Live Map (whole route) | high | code | No error boundaries: one bad field in one response blanks the entire page |
| R1-07 | Live Map / app shell | high | a11y-layout | At 390 px the sidebar never collapses; the map is 134 px wide and every panel is clipped |
| R1-08 | Live Map / filters | medium | usefulness | Nothing says how many aircraft are actually being shown |
| R1-09 | Live Map / selection | medium | usefulness | Selection is not in the URL: no deep link, lost on reload, not shareable |
| R1-10 | Live Map / interesting + styling | medium | usefulness | On a new install every aircraft is "interesting", so the panel and attention styling carry no information |
| R1-11 | Live Map / keyboard | medium | a11y-layout | The interesting list blocks keyboard reach to every other panel; the map has one heading |
| R1-12 | Live Map / notifications | medium | usefulness | Browser notifications are never surfaced on the map, including when they are blocked |
| R1-13 | Live Map / non-positioned list | medium | consistency | Non-positioned rows format altitude and RSSI unlike every other surface and ignore the unit setting |
| R1-14 | Live Map / basemap + theme | low | consistency | Light theme leaves the near-black Dark Aviation basemap; `themeAffinity` is unused |
| R1-15 | Live Map / connection chip | low | a11y-layout | The chip is a polite live region containing a constantly changing count |
| R1-16 | Live Map / map notices | low | a11y-layout | Bottom-corner notices render behind the panels that share those corners |
| R1-17 | Live Map / activity panel | low | correctness | "New busiest day" names the same day as its own previous record, on the UTC day |

---

#### R1-01 - Switching basemap permanently deletes every FlightSite map layer

- **Page / surface:** Live Map -> `BasemapSwitcher` (`frontend/src/features/map/BasemapSwitcher.tsx`),
  `frontend/src/features/map/MapLibreMap.tsx`
- **Severity:** critical
- **Category:** robustness
- **Evidence:** From a healthy map, click any other basemap. `basemap-osm.png`: the
  OpenStreetMap raster renders correctly and the map is *completely empty* - no aircraft, no
  range rings, no receiver marker - while the chip reads `Live . 56 aircraft` and the
  Interesting panel lists 55. Driven programmatically
  (`queryRenderedFeatures` + `getStyle().layers`):

  ```
  start (dark-aviation)     {"rings":16,"aircraft":46,"flightsiteLayers":17}
  after -> Light Aviation   {"rings":0,"aircraft":"LAYER MISSING","flightsiteLayers":0}
  after -> OpenStreetMap    {"rings":0,"aircraft":"LAYER MISSING","flightsiteLayers":0}
  after -> Dark Aviation    {"rings":0,"aircraft":"LAYER MISSING","flightsiteLayers":0}
  ```

  It never recovers - not by switching back, not after 8 s, not without a reload
  (`basemap-osm-empty.png`). The page additionally displays
  "Basemap unavailable - rings and receiver position still shown.", which is false twice over
  (the basemap *is* rendering; the rings are *not* shown).

  Root cause, traced in the running app by instrumenting `map.setStyle` / `map.once`:

  ```
  TRACE setStyle called
  TRACE native style.load fired; flightsite layers=0
  TRACE once(style.load) registered      <-- too late, never fires again
  ```

  `MapLibreMap.tsx` (basemap-switch effect, ~L236-248) calls `map.setStyle(basemap.style)`
  **and then** registers `map.once("style.load", handleStyleLoad)`. With maplibre-gl 6 and an
  inline style object the event is dispatched inside `setStyle`, so the handler - the only
  thing that calls `ensureOverlayLayers` and bumps `styleEpoch`, which `OverlaysLayer`,
  `useAirportOverlay`, `useAirspaceOverlay` and `useAircraftLayer` all key off - never runs.
  The unit test cannot catch it: `MapLibreMap.test.tsx` "swaps the style and re-adds overlay
  layers on a basemap change" emits `style.load` manually *after* the rerender, and
  `frontend/src/test/maplibreGlMock.ts`'s `setStyle` emits nothing.
- **Expected:** SPEC 32 makes multiple selectable basemaps a v1 requirement; switching one
  must not remove the live picture. `dev` is supposed to stay demo-able after every merge.
- **Proposed fix:** In `frontend/src/features/map/MapLibreMap.tsx`, register
  `map.once("style.load", handleStyleLoad)` *before* `map.setStyle(...)`, and make
  `handleStyleLoad` self-healing (also invoke it if `map.isStyleLoaded()` is already true
  after `setStyle` returns and the `flightsite-*` layers are absent). Make
  `frontend/src/test/maplibreGlMock.ts`'s `setStyle` emit `style.load` synchronously so the
  existing test exercises the ordering, and add an E2E case under `e2e/tests` that switches
  basemap and asserts the aircraft layer still renders. Estimate: **S**.
- **Suggested agent:** opus (map rendering)

---

#### R1-02 - Today at a Glance reports zeros that contradict the same card

- **Page / surface:** Live Map -> `frontend/src/features/today/TodayPanel.tsx`;
  `GET /api/v1/analytics/summary`; `backend/src/flightsite/analytics/*`,
  `backend/src/flightsite/app.py` L939, `backend/src/flightsite/api/context.py` L470
- **Severity:** critical
- **Category:** correctness
- **Evidence:** `today-expanded.png` - the card reads
  `Unique aircraft 112 | Sightings 0 | Interesting 0 | Mil / gov / police 0 / 0 / 0 |
  Max range - | Busiest hour 21:00-22:00 | New aircraft 0 | New milestones 148`, while the
  Interesting panel beside it lists **57** aircraft and the map shows several military
  airframes. Collapsed - the default state - the only figure shown is the badge
  `0 sightings`.

  The API agrees with the card and disagrees with itself:

  ```
  GET /api/v1/analytics/summary
  {"window":{"preset":"today","first_day":"2026-09-20","timezone":"America/New_York"},
   "summary":{"unique_aircraft":51,"new_aircraft":0,"sightings":0,"interesting":0,
              "military":0,"government":0,"law_enforcement":0,"max_range_nm":null,
              "first_sighting_at":"2026-09-21T01:33:19.000Z", ...}}
  GET /api/v1/sightings?limit=3            -> 51 sightings, all started today
  GET /api/v1/analytics/daily?window=today -> day 2026-09-20, every figure 0
  GET /api/v1/diagnostics                  -> row_counts.sightings 54, db_errors 0
  ```

  Root cause, from the backend's own startup log:

  ```
  {"timezone": "UTC", "flush_interval_s": 30.0, "event": "analytics_started"}
  GET /api/v1/receiver -> {"timezone": "America/New_York", ...}
  ```

  `app.py` L939 passes `settings.timezone` to `AnalyticsService` **once, at process start**,
  and the service keeps it in `self._zone` for the life of the process. The rollup writer
  therefore buckets each sighting under `local_day(started_ms, UTC)`, while
  `api/context.py:470` builds `AnalyticsQueries` per request from the *live*
  `settings.timezone` and asks for the receiver-local day - so the query reads a
  `daily_stats` row that was never written. `api/context.py`'s own docstring warns about
  exactly this hazard ("a captured zone would keep resolving 'today' against the old one for
  the rest of the process's life"); the writer does it anyway. Because the setup wizard
  writes the timezone *after* the backend has booted and `_apply_live_settings`
  (`api/internal.py`) has no analytics entry, **every fresh install is wrong until the next
  backend restart**, and every later timezone change in Settings re-breaks it. Even after a
  restart, any non-UTC receiver gets rollups attributed to the wrong local day for the hours
  where the two days differ (for `America/New_York`, 20:00-24:00 local - prime evening
  watching time), and `busiest_hour` is folded in UTC hours but displayed as local.
- **Expected:** SPEC 59 requires unique aircraft, sightings, interesting, mil/gov/police,
  max range, busiest hour, new aircraft and new milestones for the receiver's local day;
  SPEC 15 puts the receiver's zone in charge of what "today" means. A card cannot say
  `112 unique aircraft` and `0 sightings` in the same breath.
- **Proposed fix:** Make the analytics writer read its zone late, like everything else:
  either add an analytics entry to `_apply_live_settings` in
  `backend/src/flightsite/api/internal.py` calling a new
  `AnalyticsService.apply_timezone(tz)` (re-deriving `_current_day` and marking affected days
  dirty for rebuild), or hand `AnalyticsService` a zone *probe* closed over `app` instead of a
  string - the `flightsite.app._alert_radius` pattern its own docstring names as the model.
  Add a regression test that sets the timezone after start and asserts the next flush writes
  the new local day. Separately in `frontend/src/features/today/TodayPanel.tsx`: the card
  carries no "as of" timestamp and the collapsed state shows one of eight figures - surface
  the window's `to` time and at least sightings + interesting when collapsed. Estimate: **M**.
- **Suggested agent:** opus (backend queries; the Analytics page reads the same rollups)

---

#### R1-03 - A momentary socket drop empties the map and the panels assert false negatives

- **Page / surface:** Live Map - `frontend/src/features/live/useLiveConnection.ts`,
  `frontend/src/features/map/aircraft/store/useLiveAircraftStore.ts` (`dropLivePicture`),
  `frontend/src/features/interesting/InterestingPanel.tsx`,
  `frontend/src/features/filters/components/NonPositionedPanel.tsx`,
  `frontend/src/features/aircraft-detail/AircraftDetailPanel.tsx`
- **Severity:** high
- **Category:** robustness
- **Evidence:** Selected `GLEX52` (NOAA P-3, registration `N42RF`) from the interesting
  panel, then closed the WebSocket once from the Playwright proxy
  (`probe-selection-after-drop.png`):

  ```
  before:     GLEX52 | ICAO D66FE4 . Registration N42RF
  chip:       reconnecting
  panel now:  D66FE4 | ICAO D66FE4 . Registration Unknown | No live data for this aircraft.
  interesting panel now: Interesting | 0 | No interesting aircraft right now.
  ```

  Every status other than `live` calls `dropLivePicture()`, so the map goes blank, the
  Interesting panel states "No interesting aircraft right now.", the non-positioned list
  states "No non-positioned aircraft in the live set.", and the detail panel of the aircraft
  the user deliberately selected loses its callsign and prints `Registration Unknown` for a
  registration it knew one second earlier. Reconnect backoff makes this window 1-30 s on a
  flaky LAN; a 1013 slow-consumer close or a proxy timeout produces it too.
  `AircraftDetailPanel`'s own docstring promises the opposite - "A selected aircraft that has
  since departed the live picture ... still renders - the panel shows its last known values
  rather than snapping shut" - which is true only inside the 900 ms `REMOVAL_FADE_MS` window
  and not at all for a connection drop. There is no REST fallback:
  `GET /api/v1/aircraft/current` serves exactly this payload, and
  `grep -rn "aircraft/current" frontend/src` finds only two doc comments.
- **Expected:** An outage must never be rendered as an affirmative fact about the sky, and
  "Unknown" must never be fabricated where a value was known (SPEC 22, `docs/PRODUCT.md`
  4.3). The rubric's "does the page recover without a reload / do polls keep going after an
  error" both want a degraded-but-honest picture.
- **Proposed fix:** (a) In `useLiveAircraftStore`, keep the last picture and mark it stale
  (`lastPictureAt` + a `stale` flag) instead of clearing it; have the map fade it and the
  panels prefix "as of HH:MM:SS - feed lost" rather than print an empty-state sentence.
  (b) In `features/live/useLiveConnection.ts`, poll `GET /api/v1/aircraft/current` every ~5 s
  while `connection !== "live"` and drop the poll on reconnect. (c) In
  `AircraftDetailPanel.tsx`, when the record is gone keep the last-known header values and
  render the `/aircraft/:icao` link - that link currently sits inside the `aircraft !== null`
  branch, so it disappears exactly when it is most wanted. Estimate: **M**.
- **Suggested agent:** opus (live-state)

---

#### R1-04 - A socket that never connects is indistinguishable from an empty sky

- **Page / surface:** Live Map -> `frontend/src/features/map/aircraft/ConnectionStatusChip.tsx`,
  `frontend/src/lib/ws/liveSocket.ts`
- **Severity:** high
- **Category:** robustness
- **Evidence:** Blocked the WebSocket upgrade at the proxy and loaded `/`
  (`probe-ws-blocked.png`). After 12 s:

  ```
  chip: {"status":"connecting","text":"Connecting"}
  REST live-polling calls seen: 0
  mentions of offline/retry wording anywhere in the DOM: false
  interesting panel: Interesting 0 - "No interesting aircraft right now."
  ```

  The map draws the basemap, rings and receiver marker perfectly - it simply contains no
  aircraft - and the only signal is a dim grey dot and the word "Connecting" in an 11 px chip
  in the corner, which never changes. `liveSocket.ts` only promotes the chip to
  `reconnecting` once `everConnected` is true, so a first load against a broken upgrade path
  (the single most likely reverse-proxy misconfiguration for this product) shows "Connecting"
  indefinitely. Recovery once unblocked is clean and automatic
  (`probe-ws-recovered.png`, `Live . 64 aircraft`) - that part is right.
- **Expected:** The chip's own docstring states its purpose: "'nothing is flying' versus 'we
  have lost the feed' ... is the whole reason the chip exists". After a few failed attempts
  the user must be told the feed is down, not left staring at an empty sky.
- **Proposed fix:** In `frontend/src/lib/ws/liveSocket.ts` add a third state (or expose
  `attempt`) so `ConnectionStatusChip` can escalate after N failed attempts / ~10 s to
  "Live feed unavailable - retrying (attempt 4)" with a manual Retry action, styled like the
  amber `reconnecting` state. Pair with the REST fallback from R1-03 so a blocked upgrade
  still yields a picture. Add a Playwright case that blocks the upgrade and asserts the
  escalated wording. Estimate: **S**.
- **Suggested agent:** sonnet (contained UI/state), or opus if bundled with R1-03

---

#### R1-05 - Tile outage pins the receiver marker and range rings to the dev placeholder

- **Page / surface:** Live Map -> `frontend/src/features/map/MapLibreMap.tsx`,
  `frontend/src/features/map/overlayLayers.ts`,
  `frontend/src/features/map/store/useMapConfigStore.ts`
- **Severity:** high
- **Category:** robustness
- **Evidence:** Blocked only `tiles.openfreemap.org` and loaded `/`
  (`probe-tiles-only-blocked.png`). Aircraft render correctly on a blank canvas - SPEC 32's
  core requirement is met - but the range rings and receiver marker are gone:

  ```
  BASELINE   {"renderedRing":16,"renderedReceiver":1,"renderedAircraft":71}
  TILES-DEAD {"renderedRing":0, "renderedReceiver":0,"renderedAircraft":71}
  ```

  They are not missing - they are drawn 1,400 nm away. Reading the sources back:

  ```
  TILES-DEAD recSrc: {"features":[{"properties":{"label":
    "Development receiver (placeholder - slice 004/010 will supply the real position)"},
    "geometry":{"type":"Point","coordinates":[-122.3,47.6]}}]}
  BASELINE   recSrc: {"features":[{"properties":{"label":"Review Site"},
    "geometry":{"type":"Point","coordinates":[-98.5795,39.8283]}}]}
  ```

  The mount effect's `load` handler runs `ensureOverlayLayers(map, configRef.current)`; with
  no tiles to wait for, `load` fires before `GET /api/internal/config` resolves, so the
  placeholder is used. The config-change effect that would correct it bails on
  `if (!map || !map.isStyleLoaded()) return;` - `isStyleLoaded()` stays false while the vector
  source is erroring - and its deps are `[config]` only, so it never retries. The same race
  exists without a tile outage whenever the config fetch is slower than the style load.
  Secondly, the documented degraded-mode notice ("Basemap unavailable - rings and receiver
  position still shown.") never appeared: the `load` handler unconditionally calls
  `setTilesUnavailable(false)` after the `error` listener has already set it.
- **Expected:** SPEC 32 - "core functionality must not require internet maps"; SPEC 33 names
  receiver range rings as a v1 overlay. `MapLibreMap.tsx`'s own docstring: "The range rings
  and receiver marker are plain client-generated GeoJSON ... so they keep rendering
  regardless." A production build must never render the slice-004 placeholder.
- **Proposed fix:** In `frontend/src/features/map/MapLibreMap.tsx`: (a) drop the
  `isStyleLoaded()` guard in the config effect - guard on "the style object exists" and let
  `ensureOverlayLayers` no-op safely, or re-run it on `styleEpoch` as well as `config`;
  (b) make the degraded flag sticky per style load (set it from the error listener; clear it
  only when a tile/source load *succeeds*, not in the `load` handler); (c) make
  `DEV_PLACEHOLDER_MAP_CONFIG` render nothing (no rings, no marker) rather than a Seattle
  receiver, so this class of race can never show fabricated geography. Add a Playwright case
  that blocks the tile host and asserts ring + receiver features render. Estimate: **M**.
- **Suggested agent:** opus (map rendering)

---

#### R1-06 - No error boundaries: one bad field blanks the entire page

- **Page / surface:** Live Map (whole route), `frontend/src/routes.tsx`, every panel
- **Severity:** high
- **Category:** code
- **Evidence:** `grep -rln "ErrorBoundary|componentDidCatch|errorElement" frontend/src`
  returns **nothing** - no boundary anywhere in the app and no `errorElement` on any route.
  Demonstrated by fulfilling `GET /api/v1/analytics/summary` with a well-formed envelope whose
  counters are `null` (`eb-summary-malformed.png`):

  ```
  body: "Unexpected Application Error! | Cannot read properties of null (reading 'toLocaleString')"
  connection chip present: 0
  ```

  The whole Live Map is gone - map, aircraft, sidebar, connection chip - because
  `features/today/lib/format.ts:formatCount` calls `.toLocaleString()` on one number from one
  optional card. Two other injections behaved well by comparison (an unknown activity event
  type, and a broken `/api/v1/receiver`, both left the page up), so the *query-error* paths
  are fine; it is the *render-error* blast radius that is unbounded. Against the rubric's
  "does an error in one card take the whole page down": yes, every time.
- **Expected:** A failure in Today at a Glance, the activity panel or the interesting panel
  must degrade that card, not the radar.
- **Proposed fix:** Add `frontend/src/components/ErrorBoundary.tsx` (class component with
  `componentDidCatch` rendering a one-line "This panel failed to render - reload" card with a
  reset button) and wrap each independently-fetching child in
  `frontend/src/pages/LiveMapPage.tsx`: `TodayPanel`, `ActivityPanel`, `InterestingPanel`,
  `NonPositionedPanel`, `AircraftDetailPanel`, `FilterDrawer`. Add `errorElement` to the
  routes in `frontend/src/routes.tsx` so a shell-level throw still renders FlightSite chrome.
  Harden `features/today/lib/format.ts` and sibling formatters against `null`.
  Estimate: **M**.
- **Suggested agent:** sonnet (contained UI/state)

---

#### R1-07 - At 390 px the sidebar never collapses and every panel is clipped

- **Page / surface:** Live Map at 390x844 - `frontend/src/components/shell/AppShell.tsx`,
  `frontend/src/components/shell/Sidebar.tsx`, `frontend/src/pages/LiveMapPage.tsx`
- **Severity:** high
- **Category:** a11y-layout
- **Evidence:** `phone-map.png` (dark) and `map-phone-light-real.png` (light). The sidebar
  renders at its full 256 px on a 390 px viewport, leaving ~134 px of map. Everything floating
  over the map is cut off at the right edge: the quick-filter chips, the Basemap switcher
  (only "Light Aviation"/"OpenStreetMap" visible, the selected entry hidden behind the chips),
  the Layers card, the Filters button, the Interesting panel (rows truncate mid-word), the
  Today panel and the Activity panel. Measured boxes at 390 px:
  `Interesting {x:269,width:286}` -> right edge 555; `Today {x:144,width:357}` -> right edge
  501. `document.scrollWidth === clientWidth === 390`, so nothing scrolls - it is simply
  clipped and unreachable. Collapsing the sidebar by hand (`phone-map-collapsed.png`) makes
  the map usable, but the Today panel still overflows (`right: 406 > 390`) and the basemap
  card is still cut off at the top.
- **Expected:** SPEC 9 - "desktop-first; **responsive on tablets and phones**"; the review
  rubric - no horizontal scroll, nothing clipped, touch targets usable.
- **Proposed fix:** In `Sidebar.tsx` / `AppShell.tsx`, default the sidebar to collapsed below
  the `md` breakpoint (or render it as an off-canvas drawer under `md`). In `LiveMapPage.tsx`,
  cap `TodayPanel` at `w-[min(36rem,calc(100vw-1.5rem))]` instead of `92vw` (it is centred on
  the *viewport* while the map starts after the sidebar), and give the bottom-left column, the
  basemap card and the Layers/Filters stack phone variants so they do not occupy the same
  rows. Add a Playwright viewport assertion that no interactive element's `right` exceeds
  `innerWidth` at 390 px. Estimate: **M**.
- **Suggested agent:** sonnet (contained UI/layout)

---

#### R1-08 - Nothing says how many aircraft are actually being shown

- **Page / surface:** Live Map -> `frontend/src/features/map/aircraft/ConnectionStatusChip.tsx`,
  `frontend/src/features/filters/components/FilterDrawer.tsx`
- **Severity:** medium
- **Category:** usefulness
- **Evidence:** With every drawer control exercised (10 active filters,
  `filter-drawer-filled.png`):

  ```
  chip before: ". 77 aircraft"   rendered before: {"symbols":75,"labels":57}
  chip after:  ". 77 aircraft"   rendered after:  {"symbols":0,"labels":0}
  filter active-count badge: 10
  drawer mentions a match count: false
  ```

  The chip reads `Object.keys(state.aircraft).length` - the *unfiltered* live set - so it says
  "77 aircraft" over an empty map. The drawer shows how many filters are on but never how many
  aircraft survive them, so a filter that matches nothing (easy: `classifications` and
  `missionCategories` exclude every aircraft whose `classification` is `null`, by design) is
  indistinguishable from a receiver that has gone quiet. The two counters that do exist are
  both partial: the Interesting panel's "N hidden by the current filters" and the
  display-radius indicator's "N aircraft beyond 250 nm hidden".
- **Expected:** SPEC 37's filter drawer is only useful if its effect is legible. A live radar
  should always answer "how many am I looking at, out of how many I can hear".
- **Proposed fix:** Change `ConnectionStatusChip` to read `useFilteredLiveAircraft` and render
  "Live . 12 of 77 aircraft" whenever a filter is active ("Live . 77 aircraft" otherwise); add
  the same "N of M shown" line to the `FilterDrawer` header next to Clear all, and when the
  count is 0 say so explicitly ("No aircraft match these filters"). Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R1-09 - Selection is not in the URL: no deep link, lost on reload

- **Page / surface:** Live Map ->
  `frontend/src/features/map/aircraft/store/useLiveAircraftStore.ts`,
  `frontend/src/features/filters/lib/urlSync.ts`,
  `frontend/src/features/filters/hooks/useFilterUrlSync.ts`
- **Severity:** medium
- **Category:** usefulness
- **Evidence:** Selected an aircraft from the interesting panel: the panel opens
  (`probe-selected.png`) but `page.url()` stays `http://localhost:8090/`. After
  `page.reload()` the panel is gone (`panel after reload: false`). By contrast the filter
  state round-trips perfectly -
  `/?alt_min=30000&alt_max=40000&dist=120&cat=A32&op=Delta&opg=SkyTeam&cls=military&mission=medevac&hide_np=1&hide_stale=1&q=DAL`
  restores every control on reload - so the machinery already exists. Browser Back from a
  filtered map leaves the app entirely (`URL after goBack: about:blank`) because
  `useFilterUrlSync` replaces rather than pushes; defensible for filters, but it means neither
  a selection nor a filter can be undone with the browser's own controls.
- **Expected:** "Look at this aircraft" is the most shareable state on this page, and every
  other route in the product is deep-linkable. SPEC 48's "clicking should open/select the
  aircraft" is implemented in-process (`features/notifications/lib/dispatch.ts` calls
  `selectAircraft`), which works only for a tab that is already open.
- **Proposed fix:** Add a `sel=<icao>` param to `features/filters/lib/urlSync.ts`'s key set
  (or a sibling hook under `features/map/aircraft/`) that mirrors `selectedIcao` both ways,
  and have `dispatch.ts` navigate to `/?sel=<icao>` instead of `/` plus a store write.
  Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R1-10 - On a new install every aircraft is "interesting"

- **Page / surface:** Live Map -> `frontend/src/features/interesting/InterestingPanel.tsx`,
  `frontend/src/features/map/aircraft/aircraftLayers.ts` (attention styling)
- **Severity:** medium
- **Category:** usefulness
- **Evidence:** `map-desktop-dark.png`, `today-expanded.png`: the Interesting panel badge
  reads **76** against a live set of 77; the map draws a star glyph on essentially every label
  and an attention ring on every military/emergency aircraft. Cause: the default template set
  the setup wizard enables (`GET /api/internal/config` ->
  `enabled_templates: ["emergency_squawk","military","first_ever"]`), and `first_ever` matches
  every airframe a new receiver has not heard before - i.e. all of them, for the first weeks.
  The panel's viewport is `max-h-64` (~3 rows), so it becomes a 3-row scroll window over the
  entire live set, and it is also the first ~76 tab stops on the page (see R1-11). SPEC 36's
  "distinct attention styling" for interesting aircraft is, in practice, the styling of *all*
  aircraft.
- **Expected:** SPEC 49 wants a panel of "currently interesting aircraft" sorted by severity
  then distance - actionable, not a duplicate of the live set. SPEC 36 wants interesting
  aircraft to be *distinct*.
- **Proposed fix (map side; the template defaults belong to the Alerts reviewer):** In
  `features/map/aircraft/aircraftLayers.ts`, apply the attention ring only at
  severity >= "interesting" and let `info` matches show as the label star alone. In
  `InterestingPanel.tsx`, group by severity with collapsible sections and default the `info`
  group to collapsed with a count ("+63 info"), so critical/high rows are always the visible
  ones; raise the list height when the info group is collapsed. Estimate: **M**.
- **Suggested agent:** opus (map rendering + alert severity semantics)

---

#### R1-11 - The interesting list blocks keyboard reach to every other panel

- **Page / surface:** Live Map keyboard order and headings -
  `frontend/src/pages/LiveMapPage.tsx` and the panel components
- **Severity:** medium
- **Category:** a11y-layout
- **Evidence:** Tab order captured from a fresh load (`keyboard-focus.png`); first 40 stops:
  skip link -> 7 nav links -> theme -> collapse -> `canvas[Map]` -> 2 attribution links ->
  basemap radio -> 2 layer checkboxes -> 3 quick chips -> Filters -> `Interesting (76)` ->
  then **every one of the 76 interesting rows**, with the 40-stop budget exhausted before
  reaching the non-positioned list, the activity panel or the Today panel. With SPEC 5's load
  envelope (~500 aircraft) that is up to 500 tab stops between the filter button and the rest
  of the page. Separately, the map page's entire heading structure is `["H1: Live Map"]` - the
  Basemap, Layers, Interesting, Non-positioned, Activity and Today cards are unlabelled
  `div`s with a `button` header, so there is no heading or landmark route to any of them; and
  individual aircraft are not keyboard-reachable at all (the canvas is one tab stop), so the
  non-positioned list and the interesting panel are the only keyboard paths to a selection.
- **Expected:** Rubric 5 - headings hierarchy, keyboard reach. A long list must not sit
  between the user and the rest of the page.
- **Proposed fix:** Give each floating card a heading (`<h2>` inside its toggle button) plus
  `role="region" aria-labelledby=...`; default `InterestingPanel` to collapsed on first load
  like every other panel (it is the only one that defaults open), or keep it open and move it
  after the smaller panels in DOM order using CSS `order` for the visual column. Consider a
  "skip aircraft list" link inside the panel. Estimate: **S-M**.
- **Suggested agent:** sonnet

---

#### R1-12 - Browser notifications are never surfaced on the map

- **Page / surface:** Live Map - `frontend/src/features/notifications/lib/dispatch.ts`,
  `frontend/src/features/notifications/components/NotificationPermissionStatus.tsx` (rendered
  only from `frontend/src/features/settings/sections/NotificationsSection.tsx`)
- **Severity:** medium
- **Category:** usefulness
- **Evidence:** On the Live Map with `Notification.permission === "denied"`:
  `auto-asked on load: false` (correct - `docs/SECURITY.md` 5), and
  `any notification affordance on the map: false` - the strings "notification"/"notify" appear
  nowhere in the map's DOM. `grep` shows `NotificationPermissionStatus` is imported by exactly
  one file, the Settings page. So a user who skipped or dismissed the wizard's notification
  step gets an emergency-squawk alert - `DAL398` was broadcasting **7700** during this review -
  with no browser notification and no hint on the page they are actually watching.
  `dispatch.ts` does count these as `blocked`, but that count is only visible in Settings.
- **Expected:** SPEC 47 makes emergency squawks "prominent events ... support browser
  notification"; SPEC 48 is the map's headline alerting promise. The map is where the user is
  when alerts happen.
- **Proposed fix:** Render a dismissible chip near the Activity panel in
  `frontend/src/pages/LiveMapPage.tsx` when `Notification.permission !== "granted"` **and** at
  least one alert has been suppressed this session: "3 alerts not notified - Enable browser
  notifications", with a button that requests permission from that click (keeping it
  user-activated) and a link to Settings when the permission is `denied` and can only be
  changed in the browser. Reuse `features/notifications/useNotificationPermission.ts`.
  Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R1-13 - Non-positioned rows format altitude and RSSI unlike every other surface

- **Page / surface:** Live Map ->
  `frontend/src/features/filters/components/NonPositionedPanel.tsx`
- **Severity:** medium
- **Category:** consistency
- **Evidence:** `NonPositionedPanel.tsx` defines its own
  `formatAltitude(ft) => "<Math.round(ft)> ft"` and renders `RSSI <rssi_db.toFixed(1)> dB`.
  Every other surface uses `frontend/src/features/aircraft-detail/lib/format.ts`, which
  produces `FL207 . 20,696 ft` (thousands separator, flight level above FL180, **metres when
  `units === "metric"`**) and `-14.2 dBFS`. So the same aircraft reads `11880 ft` in the
  non-positioned list and `11,880 ft` in the detail panel, `dB` in one and `dBFS` in the
  other, and a metric user gets feet in this one list. The interesting panel immediately above
  it already imports the shared formatters and gets all of this right.
- **Expected:** Rubric 4 - same concept formatted the same way; SPEC 14 - the unit setting is
  honoured everywhere.
- **Proposed fix:** Delete the local `formatAltitude` in `NonPositionedPanel.tsx` and import
  `formatAltitude` / `formatRssi` from `features/aircraft-detail/lib/format`, taking `units`
  from `useLiveAircraftStore(state => state.receiver)` exactly as `InterestingPanel` does.
  Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R1-14 - Light theme leaves the near-black basemap

- **Page / surface:** Live Map - `frontend/src/features/map/basemaps.ts` (`themeAffinity`),
  `frontend/src/components/shell/ThemeToggle.tsx`, `frontend/src/lib/theme.ts`
- **Severity:** low
- **Category:** consistency
- **Evidence:** `theme-light.png` vs `theme-dark.png`. Chrome switches correctly (sampled
  sidebar pixel `(243,245,248)` light vs `(2,7,14)` dark), but the map pixel is `(10,14,26)`
  in **both** - the `dark-aviation` basemap stays selected, so light-theme users get bright
  panels floating over a near-black map. `BasemapDefinition.themeAffinity` exists for exactly
  this and nothing reads it. Also noted: `lib/theme.ts` ignores `prefers-color-scheme`
  entirely (`DEFAULT_THEME = "dark"`, no `matchMedia` anywhere in `frontend/src`) -
  defensible under SPEC 9's "dark is default", but a light-preferring user never sees light
  without finding the toggle.
- **Expected:** SPEC 9 - support dark and light themes; never visually chaotic.
- **Proposed fix:** In `ThemeToggle.tsx` (or a small effect in `LiveMapPage.tsx`), when the
  theme changes and the user has not explicitly picked a basemap this session, switch to the
  basemap whose `themeAffinity` matches; keep an explicit choice sticky. Optionally seed the
  first-ever theme from `matchMedia("(prefers-color-scheme: light)")`, keeping dark as the
  fallback. Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R1-15 - The connection chip is a live region containing a constantly changing count

- **Page / surface:** Live Map -> `frontend/src/features/map/aircraft/ConnectionStatusChip.tsx`
- **Severity:** low
- **Category:** a11y-layout
- **Evidence:** The chip is `role="status" aria-live="polite"` and includes
  `. {aircraftCount} aircraft` inside the same region. The count changed continuously during
  review (live set 43 -> 56 -> 64 -> 72 -> 77 over ~20 minutes), so a screen reader
  re-announces "Live . 58 aircraft" every time an aircraft enters or leaves the picture -
  noise that will bury the one announcement that matters, the feed dropping.
- **Expected:** Rubric 5. A live region should announce state changes, not a telemetry
  counter.
- **Proposed fix:** Keep `role="status" aria-live="polite"` on the status word only and move
  the count into a sibling `<span aria-hidden="true">` (or expose it through the chip's
  `aria-label`, recomputed only when the status changes). Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R1-16 - Bottom-corner notices render behind the panels that share those corners

- **Page / surface:** Live Map -> `frontend/src/features/map/MapLibreMap.tsx` (degraded
  notice, `bottom-3 left-3`),
  `frontend/src/features/filters/components/DisplayRadiusIndicator.tsx` (`bottom-3 right-3`),
  `frontend/src/pages/LiveMapPage.tsx` (bottom-left column, `ActivityPanel` bottom-right)
- **Severity:** low
- **Category:** a11y-layout
- **Evidence:** `basemap-osm.png` - the "Basemap unavailable - rings and receiver position
  still shown." notice renders at `bottom-3 left-3`, the same slot as the
  Interesting/Non-positioned column, and only its last word ("...still") is legible. The
  display-radius indicator occupies `bottom-3 right-3`, which is also where `ActivityPanel`
  sits. Both notices are `z-10` while the panels are `z-10`/`z-20`, so ordering is incidental.
- **Expected:** Nothing clipped; a degraded-mode notice must be readable.
- **Proposed fix:** Give the two map notices a shared stacked slot the panels do not claim
  (e.g. bottom-centre, above the attribution bar), owned by `LiveMapPage.tsx` so one place
  knows the map's floating layout. Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R1-17 - "New busiest day" names the same day as its own previous record

- **Page / surface:** Live Map -> `frontend/src/features/activity/ActivityPanel.tsx`,
  `frontend/src/features/activity/lib/describeActivityEvent.ts`; backend milestone producers
- **Severity:** low
- **Category:** correctness
- **Evidence:** `activity-panel.png` / panel text:

  ```
  New busiest day | 2026-09-21 . 68,764 messages . previous 2026-09-21 | 21:53
  ```

  The record and the record it beat carry the same date, which reads as nonsense; and the date
  shown is the **UTC** day (`2026-09-21`) while the row's own timestamp (`21:53`) and the
  Today card beside it are on the receiver-local day `2026-09-20` - the same UTC/local split
  as R1-02 surfacing in a second place on the map.
- **Expected:** SPEC 15/54 - receiver-local dates where the UI speaks in days; a "previous
  record" line should show the previous record's own day, or be omitted when the record is
  being improved within the same day.
- **Proposed fix:** Fix the day key alongside R1-02, then in
  `frontend/src/features/activity/lib/describeActivityEvent.ts` suppress the "previous ..."
  clause when the previous record's day equals the new one, or word it "previous best today".
  Estimate: **S**.
- **Suggested agent:** opus (shares the R1-02 day-key fix)

---

### What works well - do not regress

**Map & rendering**

- Aircraft render perfectly on a blank canvas with the tile host blocked
  (`probe-tiles-only-blocked.png`: 71 symbols with 0 tiles) - SPEC 32's core requirement is
  genuinely met - and the WebGL-unavailable path degrades to a notice instead of crashing.
- Hierarchical silhouettes, heading rotation, the MLAT dash ring, the attention ring and the
  severity-by-radius/stroke choice all avoid colour-only encoding (SPEC 36/80).
- Label declutter works: 1440 px -> 75 symbols / 57 labels; 390 px -> 36 symbols / 20 labels,
  with icons always kept and no clustering.
- Label content chain (callsign -> registration -> ICAO, operator, flight level above FL180)
  matches SPEC 35 exactly and matches the interesting panel's identity chain. The
  single-glyph star indicator, chosen so a missing SDF glyph range cannot produce tofu, proved
  its worth: the OpenFreeMap glyph endpoint 404'd throughout this review and labels still
  rendered.

**Live data & panels**

- WebSocket reconnect is automatic, backed off and resyncs cleanly from the snapshot
  (`probe-ws-recovered.png`); `seq`-gap detection forces a resync; unknown frame types are
  ignored rather than fatal.
- One socket per tab hoisted to `AppShell` (ADR-0015), so alerts reach every route.
- The interesting panel's ordering (severity desc -> distance asc -> ICAO) is literally the
  same comparison the backend makes, and it is derived from the live store rather than a
  second poll, so panel and map can never disagree. Rows carry all six SPEC 49 fields with a
  text-first severity badge.
- "N hidden by the current filters" on the interesting panel and "N aircraft beyond 250 nm
  hidden - still tracked and recorded" on the display-radius indicator are both exactly the
  right kind of honesty.
- The non-positioned list carries ICAO / callsign / altitude / squawk / signal and is
  selectable, per SPEC 20.

**Filters**

- Every control in the drawer round-trips through the URL and back into the controls after a
  reload (verified across all 14 fields); the active-count badge is accurate; "Clear all" is
  correctly disabled at zero; unknown values pass range filters rather than being silently
  excluded; `groundTraffic: "dim"` is a render hint, not an exclusion.
- The Military quick chip is gated on whether metadata rows actually exist and says where to
  fix that, while never locking an already-active filter.

**Detail panel**

- Comprehensive and close to complete against SPEC 50: severity/reasons first, per-field
  provenance indicators, ADS-B/MLAT position-source badge, emergency-squawk badge, FL + feet,
  `dBFS`, message count, receiver-local last-seen with a relative age, the explicitly labelled
  "Inferred by FlightSite ... not a reported route" airport block, Unknown-not-fabricated
  throughout, three external tracker links, and a link through to `/aircraft/:icao`. Escape
  closes it, focus returns to the row that opened it, and it is non-modal so the map stays
  live behind it.
- On phone it becomes a bottom sheet and remains usable (`phone-detail-panel.png`).

**Query error handling**

- A 500 on `/api/v1/analytics/summary` and an aborted `/api/v1/activity` both degrade to a
  per-card message with the rest of the page intact (`probe-api-500.png`), and the activity
  panel keeps its "View all activity ->" link. An unknown activity event type and a broken
  `/api/v1/receiver` are both absorbed without a render failure.


## Appendix C — R2: history pages

## History pages (`/aircraft`, `/aircraft/:icao`, `/sightings`, `/sightings/:id`, `/activity`) — findings

Reviewer: **R2**. Stack: demo mode at `http://localhost:8090`, built from `dev` @ `b976c89`.
Receiver config during the review: `timezone: America/New_York`, `units: aviation`,
`t0: 2026-09-21T01:33:19Z`. Browser timezone deliberately set to `Europe/London` so a
receiver-local render is distinguishable from a browser-local one. Data grew from 42 to
111 aircraft / 111 sightings / 7 closed sightings over the session; the history pages
were re-checked at the end (`final-*.png`).

### Summary

The five history pages are structurally sound and unusually honest about missing data —
`Unknown` is used consistently, never a blank cell, never a fabricated value, and the
404 states on both detail routes are genuinely good (they distinguish "not a valid
address" from "this receiver has never sighted it"). But three things undermine them.
**First, ordering and "not yet" states are wrong in ways that mislead:** every ascending
sort puts `NULL` rows first, so "Closest approach ▲" on `/aircraft` answers with aircraft
that have *no* closest approach, and "Duration ▲" on `/sightings` returns nothing but
open sightings; separately an aircraft that has been overhead for sixteen minutes reports
`Cumulative observed time: 0s`. **Second, nothing on these pages ever refreshes or
recovers:** there is no `refetchInterval`, `refetchOnWindowFocus` is off, and any failed
request leaves a one-line red sentence with no retry control and no table left to
interact with — `/activity` sat frozen for 95 s while 18 new events accrued server-side.
**Third, the promised capability set has visible holes:** the Activity feed's type filter
still omits `alert_triggered` and `emergency_squawk` (stale gating from before slice 039
merged) even though alerts are now the most common row; aircraft *age* (SPEC §23/§50) is
implemented nowhere; and `/aircraft/:icao` hard-codes `callsign: null` into its tracker
links, so a callsign-only airframe gets one of SPEC §24's three links instead of three.

What works well: the closed-sighting detail page is the best surface in my scope — the
simplified path renders cleanly with start/end markers and altitude colouring, closure
reason carries a tooltip, and §51's reception block including "time with a position" is
complete. Pagination to the genuine last page is correct on both tables. Filter changes
correctly reset to page 1, and the ICAO filter commits on submit rather than per
keystroke.

### Findings

| ID | Page | Severity | Category | Title |
|----|------|----------|----------|-------|
| R2-01 | Aircraft, Sightings | high | correctness | Ascending sorts put `NULL` rows first, so "closest"/"shortest" answers are wrong |
| R2-02 | Aircraft detail, Sightings, Sighting detail | high | correctness | Open sightings report `0s` and `Unknown` where the truth is "still running" |
| R2-03 | all five | high | robustness | No page ever refreshes; `/activity` is frozen from the moment it loads |
| R2-04 | all five | high | robustness | A failed request is a dead end: no retry control, and the table is unmounted |
| R2-05 | Activity | high | usefulness | The type filter omits Alerts and Emergencies — the feed's most common rows |
| R2-06 | Activity | high | usefulness | Feed rows show time-of-day only, so "what happened overnight" is unanswerable |
| R2-07 | Sightings | high | a11y-layout | Sighting rows contain no focusable element — no keyboard route to any detail |
| R2-08 | all five | high | a11y-layout | At 390 px the sidebar takes 256 px; tables show 3 of 10 columns, detail text overlaps |
| R2-09 | Aircraft, Sightings, Activity | medium | robustness | An out-of-range `page=` renders a blank table, "Page 999 of 2", and no empty state |
| R2-10 | Aircraft detail | medium | usefulness | Aircraft age (SPEC §23/§50, PRODUCT §4.3) is implemented nowhere |
| R2-11 | Aircraft detail | medium | usefulness | Tracker links hard-code `callsign: null`, dropping 2 of SPEC §24's 3 services |
| R2-12 | Sighting detail | medium | correctness | The path is a 5–20 vertex sample shown beside "Position reports: 543", unlabelled |
| R2-13 | Sightings | medium | a11y-layout | The Status column (§57's alert/interesting) is clipped off-screen at 1440×900 |
| R2-14 | all five | medium | correctness | Receiver-local timestamps are rendered with the timezone named nowhere |
| R2-15 | Activity, Sighting detail | medium | usefulness | Both timelines discard payload fields they already hold (rule name, severity, callsign) |
| R2-16 | all routes | medium | robustness | No catch-all route: a mistyped URL shows React Router's raw developer error page |
| R2-17 | all five | medium | a11y-layout | Heading hierarchy skips H2, tables unlabelled, errors never announced, path colour unkeyed |

---

#### R2-01 — Ascending sorts put `NULL` rows first, so "closest"/"shortest" answers are wrong

- **Page / surface:** `/aircraft` (every sortable column), `/sightings` (`duration_s`,
  `closest_approach_nm`, `max_range_nm`)
- **Severity:** high
- **Category:** correctness
- **Evidence:** Clicking "Closest approach" twice on `/aircraft` gives
  `?sort=closest_approach_nm&order=asc`, and the top four rows are:

  ```
  Unknown | 1CFB0F | ... | Unknown | Unknown
  Unknown | 8E5326 | ... | Unknown | Unknown
  Unknown | F7B993 | ... | Unknown | Unknown
  Unknown | 30ADC5 | ... | 0.8 nm  | 1.0 nm
  ```

  The aircraft that actually came closest (0.8 nm) is ranked *below* three with no
  closest approach at all. Same at the API:
  `GET /api/v1/aircraft?sort=closest_approach_nm&order=asc` returns
  `closest_approach_nm: null` for items 1-3. "Tail up-arrow" likewise leads with dozens
  of `Unknown` registrations. On `/sightings`,
  `GET /api/v1/sightings?sort=duration_s&order=asc` returns
  `duration_s: null, ended_at: null` for every item on page 1 — i.e. "shortest sighting
  first" returns only *open* sightings, page after page, and the shortest closed
  sighting is unreachable by sorting. Screenshots: `aircraft-desktop-dark.png`,
  `sightings-desktop-dark.png`. Cause: `backend/src/flightsite/api/history.py:216` and
  `backend/src/flightsite/api/sightings.py` both build
  `column.asc() if order == "asc" else column.desc()`, and SQLite sorts `NULL` first on
  `ASC`.
- **Expected:** "Unknown" is the absence of an answer, not the smallest answer. Every
  sort should place null rows last in both directions, so the first page of an ascending
  sort holds the genuinely smallest values and the first page of a descending sort the
  genuinely largest (which it already does, by SQLite accident).
- **Proposed fix:** In `backend/src/flightsite/api/history.py` (`list_aircraft`) and
  `backend/src/flightsite/api/sightings.py` (`sighting_list`), build the direction as
  `column.asc().nulls_last()` / `column.desc().nulls_last()`. Both already append
  `icao24` / `id` ascending as the stable tiebreak, which is unaffected. Add a repository
  test per sort key asserting a null-bearing fixture lands last in both directions.
  Estimate: **S**.
- **Suggested agent:** opus (backend query ordering, shared by two endpoints and the
  live-map track backfill that reads `/sightings`)

---

#### R2-02 — Open sightings report `0s` and `Unknown` where the truth is "still running"

- **Page / surface:** `/aircraft/:icao` ("Cumulative observed time"), `/sightings`
  (Duration column), `/sightings/:id` (Duration and Closure)
- **Severity:** high
- **Category:** correctness
- **Evidence:** `GET /api/v1/aircraft/7a602d` (G-KPOL, continuously overhead since T0):

  ```json
  "lifetime": { "first_seen": "2026-09-21T01:33:24.000Z",
                "last_seen":  "2026-09-21T01:49:30.000Z",
                "sighting_count": 1, "cumulative_duration_s": 0 }
  ```

  The detail page renders that verbatim as **`Cumulative observed time  0s`** next to
  `First seen 21:33 / Last seen 21:49 / Sighting count 1`
  (`aircraft-detail-desktop-dark.png`, `aircraft-detail-rich-desktop-dark.png`). The
  storage side is deliberate and correct —
  `backend/src/flightsite/sightings/repository.py:408` documents that
  `total_observed_ms` is a sum over *closed* sightings, to avoid double-counting on
  flush — but the UI presents that internal detail as the user-facing answer to SPEC
  §53's "cumulative observation duration". On `/sightings`, every open row shows
  `Duration: Unknown` (`sightings-desktop-dark.png`), and `/sightings/1` shows
  `Duration Unknown / Closure Unknown` for a sighting that started nine minutes earlier
  and is labelled "Ongoing" two columns to the left
  (`sighting-detail-open-desktop-dark.png`).
- **Expected:** A receiver owner asking "how long have I been watching this aircraft?"
  must not be told `0s`, and a sighting the page itself calls "Ongoing" must not have an
  `Unknown` duration — the start time and "now" are both known. `Unknown` means "the
  decoder never reported this"; "not closed yet" is a different fact needing different
  words.
- **Proposed fix:** (a) `backend/src/flightsite/api/serializers.py:765` — add the open
  sighting's elapsed duration to `cumulative_duration_s`, or return an additional
  `open_sighting_elapsed_s` the UI adds. (b)
  `frontend/src/features/sightings/SightingsTable.tsx` and
  `frontend/src/features/sighting-detail/SightingDetailPage.tsx` — when
  `ended_at === null`, render the running elapsed time (now minus `started_at`) with an
  "ongoing" affordance instead of `<UnknownValue />`, and render Closure as an em dash
  titled "Still open" rather than `Unknown`. Estimate: **M**.
- **Suggested agent:** opus (touches the aircraft-detail serializer contract and the
  sighting lifecycle semantics)

---

#### R2-03 — No page ever refreshes; `/activity` is frozen from the moment it loads

- **Page / surface:** `/aircraft`, `/sightings`, `/aircraft/:icao`, `/sightings/:id`,
  `/activity`
- **Severity:** high
- **Category:** robustness
- **Evidence:** Loaded `/activity` and left it untouched for 95 s. Top row before:
  `Alert: Rule: First-ever aircraft / 6CEB5F / 21:43`. Top row after: **identical**.
  Meanwhile `GET /api/v1/activity?limit=1` reported the newest server event as
  `id 195, at 2026-09-21T01:45:15Z` — the page was ~2 minutes and 18 events behind and
  said nothing. Dispatching a `window` `focus` event changed nothing either.
  Screenshot: `state-activity-stale-after-95s.png`. Code:
  `frontend/src/lib/queryClient.ts` sets `staleTime: 30_000, refetchOnWindowFocus: false`,
  and no in-scope hook (`lib/api/aircraft.ts`, `lib/api/sightings.ts`,
  `lib/api/activity.ts`) sets a `refetchInterval`. `ActivityPage.tsx`'s own docstring
  records that the page is REST-only by design while the Live Map's `ActivityPanel` does
  receive live WebSocket frames — so the *fuller* view of the feed is the *less* current
  one.
- **Expected:** PRODUCT §4.9 sells the feed as "what happened while I wasn't watching" —
  a tab left open on it is the intended use. The rubric asks how a user knows a figure is
  old; here there is no answer at all: no "as of" line, no manual refresh, no poll. The
  history tables share the problem in a milder form (an `/aircraft` tab left open for an
  hour silently omits every airframe seen since).
- **Proposed fix:** Add `refetchInterval` to the three list hooks
  (`frontend/src/lib/api/activity.ts` ~30 s, `aircraft.ts` / `sightings.ts` ~60 s) with
  `refetchIntervalInBackground: false`, and render a small "Updated HH:MM - Refresh"
  control in `AircraftPaginationControls` (already shared by all three pages) driven by
  `dataUpdatedAt` and `refetch`. For `/activity`, either subscribe the page to the same
  live store `ActivityPanel` uses, or poll — polling is the smaller change and keeps the
  page's documented REST-only design. Estimate: **M**.
- **Suggested agent:** opus (cross-page contract; the `/activity` option interacts with
  the live-state store)

---

#### R2-04 — A failed request is a dead end: no retry control, and the table is unmounted

- **Page / surface:** all five
- **Severity:** high
- **Category:** robustness
- **Evidence:** With `page.route("**/api/v1/aircraft?*")` fulfilling 500, `/aircraft`
  renders exactly one line: *"Could not load the aircraft list: Request failed with
  status 500"* (`state-aircraft-500.png`). Identical shape for `/sightings`
  (`state-sightings-500.png`), `/activity` (`state-activity-500.png`), and for
  `net::ERR_FAILED` aborts (`state-aircraft-abort.png`, `state-sightings-abort.png`,
  `state-activity-abort.png`). Detail routes behave the same
  (`state-aircraft-detail-500.png`, `state-sighting-detail-500.png`). After un-blocking
  the route: 3 s idle then still the error; a `focus` event then still the error. On
  `/aircraft` and `/sightings` the error branch replaces the whole `<div>` containing the
  table *and* its sort headers *and* its pagination footer, so **no control remains on
  the page that could trigger a refetch** — only a browser reload recovers. On
  `/activity` a filter chip survives, and clicking one does recover (new query key, new
  fetch, 50 rows returned) — but that is luck, not a retry affordance, and it silently
  changes the user's filter.
- **Expected:** Rubric 2: "Does the page recover without a reload? Do polls/refetches
  keep going after an error?" Neither. A transient decoder/DB hiccup on a Pi should not
  require the owner to reload the tab.
- **Proposed fix:** Add a shared `<QueryErrorState message retry>` component
  (`frontend/src/components/ui/`) rendering the message plus a "Try again" button wired
  to `query.refetch()`, used from `AircraftPage.tsx`, `SightingsPage.tsx`,
  `ActivityPage.tsx`, `AircraftDetailPage.tsx`, `SightingDetailPage.tsx`. Give it
  `role="alert"` (see R2-17). Keep the sort headers mounted on the two tables so the
  previous page's controls do not vanish. Combined with R2-03's `refetchInterval`,
  TanStack Query will also retry on its own cadence. Estimate: **M**.
- **Suggested agent:** sonnet (contained UI/state work: one shared component, five call
  sites)

---

#### R2-05 — The type filter omits Alerts and Emergencies, the feed's most common rows

- **Page / surface:** `/activity`
- **Severity:** high
- **Category:** usefulness
- **Evidence:** The chip row offers eight filters: *First seen, New types, Milestones,
  Range records, Records, Offline, Restored, Metadata* (`activity-desktop-dark.png`).
  There is no **Alerts** chip and no **Emergencies** chip — yet over half the visible
  rows are `alert_triggered` ("Alert: Rule: First-ever aircraft" appears 6 times in the
  first 13 rows), confirmed in the payload: `GET /api/v1/activity?limit=3` returns
  `"type": "alert_triggered"` for 2 of 3. Cause:
  `frontend/src/features/activity/lib/urlState.ts` —

  > *"The two phase-6 types (`alert_triggered`, `emergency_squawk`) are deliberately
  > absent: nothing emits them until roadmap slice 039, and a chip that can only ever
  > return an empty page is a worse answer than no chip."*

  `planning/roadmap.yaml:1075-1090` shows slice 039 with `status: merged` and
  *"alert events visible in activity feed"* in its scope. The gating comment is stale and
  its premise is now false. Consequence: the user can neither isolate alerts nor filter
  them *out* to see the firsts and records underneath — which is exactly what the page's
  own subtitle ("Firsts, records and milestones") promises.
- **Expected:** SPEC §55 lists alert triggered and emergency squawk among the feed's
  event kinds; the filter should cover the vocabulary the feed actually produces.
- **Proposed fix:** In `frontend/src/features/activity/lib/urlState.ts`, move
  `alert_triggered` and `emergency_squawk` out of the `KNOWN_TYPES`-only set into
  `FILTERABLE_TYPES` (labels already exist in `lib/typeLabels.ts`: "Alerts",
  "Emergencies") and delete the stale comment. Update
  `features/activity/lib/urlState.test.ts` and `ActivityPage.test.tsx`. While there,
  `describeActivityEvent`'s `alert_triggered` label reads "Alert: Rule: First-ever
  aircraft" — drop one of the two prefixes. Estimate: **S**.
- **Suggested agent:** sonnet (contained; no backend change)

---

#### R2-06 — Feed rows show time-of-day only, so "what happened overnight" is unanswerable

- **Page / surface:** `/activity` (and the Events timeline on `/sightings/:id`)
- **Severity:** high
- **Category:** usefulness
- **Evidence:** Every row's right-hand timestamp is `21:43`, `21:38`, `21:37` — bare
  `HH:MM`, no date, no date separators between days, and no `title` attribute carrying
  the full instant (audited: `main [title]` on `/activity` returns `[]`). Page 2 is the
  same: rows read `21:46` down to `21:42` with nothing to say which day
  (`state-activity-page2.png`). Cause:
  `frontend/src/features/activity/components/ActivityRow.tsx` calls
  `formatReceiverLocalTime` from `features/receiver/lib/format.ts`, which formats
  `{ hour, minute }` only. `/aircraft` and `/sightings` correctly use
  `formatReceiverLocalDateTime`.
- **Expected:** PRODUCT §4.9 / SPEC §55: the feed answers *"What happened while I wasn't
  watching?"* — a question whose premise is a gap of hours or days. After one night the
  top of the feed and page 3 of the feed are visually indistinguishable. The Live Map
  panel's compact variant can reasonably stay time-only; the full page cannot.
- **Proposed fix:** In `ActivityRow.tsx`, use `formatReceiverLocalDateTime` when
  `compact !== true`, and wrap the timestamp in a `<time dateTime={event.at}>` with a
  `title` carrying the full receiver-local instant. Better still, group the list by
  receiver-local day with a sticky "Today" / "Yesterday" / "2026-09-18" sub-header in
  `ActivityPage.tsx`. Same `<time>`/`title` treatment for
  `features/sighting-detail/SightingEventsTimeline.tsx`. Estimate: **S** (timestamp) /
  **M** (with day grouping).
- **Suggested agent:** sonnet

---

#### R2-07 — Sighting rows contain no focusable element: no keyboard route to any detail

- **Page / surface:** `/sightings`
- **Severity:** high
- **Category:** a11y-layout
- **Evidence:** Audited all 50 rendered rows:
  `{"rows":50,"anchors":0,"focusables":0}` — zero anchors, zero buttons, zero
  `[tabindex]` anywhere inside a `[data-testid=sighting-row]`, and `tabIndex >= 0` on
  0 of 50 rows. Tabbing 24 times from the top of `/sightings` walks the skip link, the
  seven nav items, the theme and collapse buttons, the filter inputs, "Open now", then
  the four sortable headers — and never reaches a row. Navigation is a bare
  `onClick={() => navigate(...)}` on the `<tr>`
  (`frontend/src/features/sightings/SightingsTable.tsx`), with `cursor-pointer` as the
  only hint. A keyboard-only or screen-reader user therefore cannot open **any**
  `/sightings/:id` page from the log. (`/aircraft` is fine by comparison: 50 of 50 rows
  contain the Tail `<Link>`, so detail is reachable — though the whole-row click is
  still mouse-only there too.)
- **Expected:** SPEC §57: "Opening a sighting shows its detailed summary and simplified
  path." Rubric 5: keyboard reach, focus visible.
- **Proposed fix:** In `SightingsTable.tsx`, make the first cell (Start) a
  `<Link to={...}>` exactly as `AircraftTable.tsx` does for Tail — that single change
  restores keyboard and screen-reader reach and gives the row's id a place in the DOM.
  Keep the row `onClick` for mouse convenience, with `event.stopPropagation()` on the
  link. Add an E2E assertion that tabbing reaches a row link on both tables.
  Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R2-08 — At 390 px the sidebar takes 256 px; tables show 3 of 10 columns, detail text overlaps

- **Page / surface:** all five, at 390x844
- **Severity:** high
- **Category:** a11y-layout
- **Evidence:** `frontend/src/components/shell/Sidebar.tsx` has no responsive
  breakpoint — it is `w-64` (256 px) unless the user manually collapses it, leaving
  **134 px** of content width at 390 px. `aircraft-phone-dark.png` shows the Aircraft
  table reduced to the "Tail" column and a sliver of "ICAO"; `sightings-phone-dark.png`
  and `activity-phone-dark.png` are equivalent. The answer to "which columns collapse?"
  is **none**: `AircraftTable` is `min-w-[900px]`, `SightingsTable` is `min-w-[1100px]`,
  and there is no card/stacked layout at any breakpoint. Even with the sidebar manually
  collapsed the table scroller measures `scrollWidth 933 / clientWidth 292`
  (`phone-aircraft-sidebar-collapsed.png`) — 3.2x horizontal scrolling inside a nested
  scroller to reach "Closest approach"/"Farthest detection", the two columns that answer
  the actual question. The collapse is also not persisted, so it resets on the next page
  load. Worst case is `/sightings/:id`: `sighting-detail-rich-phone-dark-2.png` shows
  "Alert matched" printed **on top of** its own `21:34:36` timestamp, "Ended Ongoing"
  running off the right edge, and the map reduced to a tall sliver with the attribution
  control overlaying it.
- **Expected:** Rubric 5: phone 390x844, nothing clipped, touch targets usable. The
  document does not scroll horizontally (checked: `scrollWidth === clientWidth`), so
  nothing *looks* broken — the content is simply unreachable.
- **Proposed fix:** Two parts. (a) Shell: auto-collapse the sidebar below `md` in
  `Sidebar.tsx` / `AppShell.tsx` (likely another reviewer's territory — coordinate).
  (b) In scope here: give both tables a phone layout. Cheapest useful version — hide the
  low-value columns under `md` (`hidden md:table-cell` on Operator, Classification,
  Model, and on `/sightings` Lowest/Highest alt.) so the phone shows identity plus time
  plus distance; better version — a stacked card list under `md` in `AircraftTable.tsx`
  and `SightingsTable.tsx`. For `/sightings/:id`, make the header `<dl>` single-column
  under `sm` and give `SightingEventsTimeline` a wrapping flex row so the label and
  timestamp cannot overlap. Estimate: **L**.
- **Suggested agent:** opus (cross-page layout contract; coordinate with the shell fix)

---

#### R2-09 — An out-of-range `page=` renders a blank table, "Page 999 of 2", and no empty state

- **Page / surface:** `/aircraft`, `/sightings`, `/activity`
- **Severity:** medium
- **Category:** robustness
- **Evidence:** `/aircraft?page=999` renders the table header row, zero body rows, and a
  footer reading **"Page 999 of 2 - 68 aircraft"** — a self-contradicting sentence, with
  "Previous" enabled (leading to page 998, also empty) and no other recovery.
  `/sightings?page=999` renders header row, zero body rows, footer "Page 999"
  (`state-sightings-page999.png`). Neither shows the "no results" copy, because all
  three pages guard it on `state.page === 1`:
  `listQuery.data.items.length === 0 && state.page === 1 ? <empty> : <table>`
  (`AircraftPage.tsx`, `SightingsPage.tsx`, `ActivityPage.tsx`). Reachable in normal use
  from a bookmarked deep link after history is pruned, or from a shared URL.
  (Paginating to the *genuine* last page is correct: "Page 3 of 3 - 111 aircraft",
  11 rows, Next disabled — `final-aircraft-last-page.png`,
  `final-sightings-last-page.png`.)
- **Expected:** An empty page beyond the end should say so and offer a way back, and
  "Page 999 of 2" should never be printable.
- **Proposed fix:** In `AircraftPaginationControls.tsx`, clamp the displayed page to
  `totalPages` and, when `page > totalPages`, render "Page 999 is past the end — go to
  page 1" with a button calling `onPageChange(1)`. In the three page components, drop the
  `&& state.page === 1` guard and show the empty-state copy whenever
  `items.length === 0`, with a "back to page 1" action when `page > 1`. Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R2-10 — Aircraft age (SPEC §23/§50, PRODUCT §4.3) is implemented nowhere

- **Page / surface:** `/aircraft/:icao`
- **Severity:** medium
- **Category:** usefulness
- **Evidence:** The "Manufacture & ownership" section shows `Manufacture year` and
  `Owner` only (`aircraft-detail-desktop-dark.png`). `GET /api/v1/aircraft/{icao}`
  returns `manufacture_year` and no age field. Greps across
  `backend/src/flightsite/api/` and `frontend/src/features/aircraft-detail/` find no
  aircraft-age concept at all (the only `age` hits are `formatRelativeAge` /
  `useRelativeAge`, which are *last-seen* age). `planning/roadmap.yaml` has no slice
  carrying it, so it is not deferred work — it is missed scope. SPEC §23 lists
  "manufacture year; aircraft age" as separate items; SPEC §50 and PRODUCT §4.3 both
  repeat "manufacture year, age".
- **Expected:** A derived "Age" row beside Manufacture year, `Unknown` when the year is
  null, carrying `derived` provenance (SPEC §22 — it is computed, not received).
- **Proposed fix:** Purely derivable on the client, so no migration:
  `frontend/src/features/aircraft-detail/AircraftDetailPage.tsx` adds a
  `FieldRow label="Age"` computing current year minus `manufacture_year` (with a small
  plural-aware helper and unit test in `features/aircraft-detail/lib/format.ts`:
  "1 year" / "18 years"), `provenanceSource="derived"`. Add it to
  `AircraftDetailPanel.tsx` too so the live panel and the page agree. Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R2-11 — Tracker links hard-code `callsign: null`, dropping 2 of SPEC §24's 3 services

- **Page / surface:** `/aircraft/:icao`, "External trackers"
- **Severity:** medium
- **Category:** usefulness
- **Evidence:** `frontend/src/features/aircraft-detail/AircraftDetailPage.tsx`:

  ```tsx
  <ExternalTrackerLinks
    aircraft={{ icao: detail.icao, callsign: null, registration: detail.registration }}
  />
  ```

  `buildTrackerLinks` (`lib/trackerLinks.ts`) explicitly falls back to the callsign for
  both FlightRadar24 (`flightradar24.com/{callsign}`) and FlightAware
  (`/live/flight/{ident}`) when there is no registration — but the page never gives it
  one. Measured: `/aircraft/7a602d` (registration G-KPOL) offers all three links;
  `/aircraft/b034be`, whose current sighting carries callsign **AFR1641**, offers only
  `["ADS-B Exchange"]` (`state-aircraft-detail-callsign-only-trackers.png`). In this
  dataset that is the *majority* case — most airframes have no offline metadata but do
  broadcast a callsign, which `/api/v1/sightings?icao=...` and
  `/api/v1/aircraft/{icao}/sightings` both return and which `RecentSightingsSection`
  already fetches on this very page.
- **Expected:** SPEC §24: "Provide convenient links to FlightRadar24, FlightAware,
  ADS-B Exchange, using the best available identifier." A known callsign *is* an
  available identifier, and the link builder already knows how to use it.
- **Proposed fix:** In `AircraftDetailPage.tsx`, take the callsign from the most recent
  sighting — lift `useAircraftSightingsQuery` out of `RecentSightingsSection` (or read
  live state) and pass `callsign: latestSighting?.callsign ?? null`. Note in the UI that
  an FR24/FlightAware callsign link is flight-scoped, not airframe-scoped (a `title` is
  enough). Extend `trackerLinks.test.ts`. Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R2-12 — The path is a 5-20 vertex sample shown beside "Position reports: 543", unlabelled

- **Page / surface:** `/sightings/:id`, "Path" section
- **Severity:** medium
- **Category:** correctness
- **Evidence:** Closed sighting 4 (`final-sighting-detail-closed.png`): the Reception
  block reads **"Position reports 543"** and **"Time with a position 100.0%"**, while
  `GET /api/v1/sightings/4` returns `path` with **11** points for a 542 s sighting that
  moved 55.3 to 64.1 nm and 8,607 to 9,899 ft. Open sighting 1: "Position reports 943",
  `path` = **20** points at a fixed 30 s cadence
  (`01:33:19, 01:33:49, 01:34:20, ... 01:42:42`) — the crash-recovery checkpoint tail
  from `sighting_track_checkpoints`, which `backend/src/flightsite/api/sightings.py` is
  candid about in its module docstring. Nothing on the page says the drawn line is a
  sample: the section is titled simply "Path", there is no vertex count, no "simplified"
  note, and no hover readout of a point's time or altitude. A user comparing the two
  numbers on one screen can only conclude that one of them is wrong.
- **Expected:** SPEC §19 makes simplification correct for a *closed* sighting ("simplify
  the historical path using an appropriate geometry reduction algorithm"), so the data is
  right — but the presentation is not. For an *open* sighting SPEC §19 says "retain the
  full current track", and this view shows a 30 s sample of it, which also means the same
  aircraft's track looks different here than on the Live Map.
- **Proposed fix:** In `frontend/src/features/sighting-detail/SightingDetailPage.tsx`,
  title the section "Path (simplified)" for a closed sighting and "Path (checkpointed,
  ~30 s)" for an open one, with a one-line caption naming the vertex count ("11 points,
  simplified from 543 position reports"). Add a MapLibre hover popup in
  `SightingPathLayer.tsx` reading each vertex's receiver-local time and altitude. Longer
  term (roadmap item, not this slice): serve an open sighting's full live track here.
  Estimate: **S** for the labelling, **M** with the hover readout.
- **Suggested agent:** opus (map rendering plus the open/closed path contract)

---

#### R2-13 — The Status column (§57's alert/interesting) is clipped off-screen at 1440x900

- **Page / surface:** `/sightings`
- **Severity:** medium
- **Category:** a11y-layout
- **Evidence:** Measured at 1440x900 with the sidebar expanded: the table's
  `.overflow-x-auto` scroller has `scrollWidth 1216` vs `clientWidth 1118` — 98 px
  hidden. The right-most column renders as a truncated "STA..." header with the severity
  badge cut in half, in both themes (`sightings-desktop-dark.png`,
  `sightings-desktop-light.png`). There is no visible scrollbar (overlay scrollbars) and
  no fade or shadow affordance, so nothing signals that a column exists past the edge.
  `/aircraft` fits exactly (`1118 / 1118`), so the problem is specific to
  `SightingsTable`'s `min-w-[1100px]` plus 13 columns.
- **Expected:** SPEC §57 names "alert/interesting status" as a column of this page; it is
  the column that answers "was anything interesting?" and it is the one a standard
  desktop cannot see.
- **Proposed fix:** In `frontend/src/features/sightings/SightingsTable.tsx`, reclaim
  width — the Lowest/Highest altitude cells render "FL320 - 32,022 ft" (flight level
  *and* feet); show the flight level alone above FL180 and drop the duplicate, or move
  Status to the second column beside Start where it also reads better. Add a scroll-edge
  shadow to the `.overflow-x-auto` wrapper (shared with `AircraftTable`) so a hidden
  column is at least discoverable. Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R2-14 — Receiver-local timestamps are rendered with the timezone named nowhere

- **Page / surface:** all five
- **Severity:** medium
- **Category:** correctness
- **Evidence:** The stack's receiver timezone is `America/New_York`; I ran the browser in
  `Europe/London`. `/aircraft` renders `2026-09-20 21:33` — correctly receiver-local, and
  five hours from what the browser's own clock would say. But the strings
  "America/New_York", "EDT", "EST", "UTC" and "GMT" appear nowhere on `/aircraft`,
  `/activity`, `/aircraft/:icao` or `/sightings/:id` (audited against
  `document.body.innerText`), and no timestamp carries a `title` attribute with the zone
  or the underlying UTC instant (`main [title]` returns `[]` on every page; the only hit
  anywhere is the map's "Toggle attribution"). `formatReceiverLocalDateTime` and
  `formatReceiverLocalTime` (`features/aircraft-detail/lib/format.ts`,
  `features/receiver/lib/format.ts`) both omit `timeZoneName` deliberately.
- **Expected:** SPEC §15 mandates receiver-local display against a configurable timezone,
  which is implemented correctly — but a reader who is not sitting at the receiver (the
  remote-access case the product supports) has no way to know whose clock these are, and
  around a DST transition no way to disambiguate a repeated hour.
- **Proposed fix:** Name the zone once per page rather than per row: add a muted
  "All times {receiverQuery.data.timezone}" line under the `<h1>` on `AircraftPage`,
  `SightingsPage`, `ActivityPage`, and in the header of both detail pages (the
  `useReceiverQuery` data is already in hand at every one of those call sites). Add the
  full ISO instant as a `title` on each rendered timestamp. Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R2-15 — Both timelines discard payload fields they already hold

- **Page / surface:** `/sightings/:id` Events, `/activity` rows
- **Severity:** medium
- **Category:** usefulness
- **Evidence:** (a) `GET /api/v1/sightings/1` returns
  `events: [{ "at": "...", "type": "alert_matched",
  "detail": {"reason": "Rule: First-ever aircraft", "severity": "info"} }]`, but
  `frontend/src/features/sighting-detail/lib/eventDescriptions.ts` returns
  `{ label: "Alert matched", detail: null }` for both `alert_matched` and
  `alert_severity_upgraded` — the rule name and severity are dropped on the floor. The
  page shows a bare "Alert matched" (`sighting-detail-open-desktop-dark.png`,
  `final-sighting-detail-closed.png`) while the Activity feed, from the same underlying
  event, manages "Alert: Rule: First-ever aircraft". SPEC §52 calls out "important alert
  transition" as a meaningful event; *which* alert is the meaningful part.
  (b) `airframe()` in `features/activity/lib/describeActivityEvent.ts` resolves identity
  as `registration ?? ICAO`, never consulting `payload.callsign` — so feed rows read
  "First ever sighting - 1D1713" where the payload carries a callsign
  (`"callsign": "N355MD"` in `GET /api/v1/activity`). With no metadata imported — the
  common fresh-install state — every feed row is a bare hex string
  (`activity-desktop-dark.png`, `state-activity-page2.png`).
- **Expected:** SPEC §49's sibling surface asks for "callsign/tail" precisely because a
  hex address is not how a human identifies an aircraft; the feed should not be less
  readable than the panel. And a timeline entry should say what matched.
- **Proposed fix:** (a) `eventDescriptions.ts` — return the joined reason and severity
  label as `detail` for `alert_matched` and `alert_severity_upgraded`, reusing the
  existing `stringDetail` helper; extend `eventDescriptions.test.ts`.
  (b) `describeActivityEvent.ts` — insert `str(payload, "callsign")` into `airframe()`'s
  identity chain between `registration` and the ICAO fallback, keeping the ICAO in the
  detail line so the address is still present; extend `describeActivityEvent.test.ts`.
  Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R2-16 — No catch-all route: a mistyped URL shows React Router's raw developer error page

- **Page / surface:** any path not in `routes.tsx` (e.g. `/sightings-log`, an old
  bookmark)
- **Severity:** medium
- **Category:** robustness
- **Evidence:** `/nope-not-a-route` renders, unstyled, with no shell and no nav:
  *"Unexpected Application Error! / 404 Not Found / Hey developer / You can provide a way
  better UX than this when your app throws errors by providing your own `ErrorBoundary`
  or `errorElement` prop on your route."* (`state-unknown-route.png`).
  `document.querySelector("main")` is `null` — the app shell is gone, so there is no way
  back except editing the URL. `frontend/src/routes.tsx` declares no `path: "*"` child
  and no `errorElement` on the root. Also noted: `/sightings/abc` renders the correct
  in-app "Sighting not found" message but still logs "Error handled by React Router
  default ErrorBoundary" to the console.
- **Expected:** The two in-scope detail routes get this exactly right —
  `/aircraft/zzzzzz` gives "'zzzzzz' is not a valid ICAO 24-bit address",
  `/aircraft/000000` gives "This receiver has never sighted 000000", `/sightings/999999`
  gives "No sighting exists with id 999999" (`state-aircraft-404.png`,
  `state-sighting-404.png`). A path that matches no route at all deserves the same
  treatment inside the shell.
- **Proposed fix:** Add `{ path: "*", element: <NotFoundPage /> }` as the last child of
  the `AppShell` route in `frontend/src/routes.tsx`, plus an `errorElement` on the root
  so a render-time throw also keeps the chrome. `NotFoundPage` (new,
  `frontend/src/pages/NotFoundPage.tsx`) shows the attempted path and links to the Live
  Map. Estimate: **S**.
- **Suggested agent:** sonnet

---

#### R2-17 — Heading hierarchy skips H2, tables unlabelled, errors never announced, path colour unkeyed

- **Page / surface:** all five
- **Severity:** medium
- **Category:** a11y-layout
- **Evidence:** Audited each route's `main`:
  - `/aircraft/:icao` gives `H1:70F20D` then `H3:Identity & metadata`,
    `H3:Manufacture & ownership`, `H3:History`, `H3:Recent sightings`,
    `H3:External trackers` — no H2. `/sightings/:id` gives `H1:ACA3438` then `H3:Path`,
    `H3:Events`, `H3:Reception`, `H3:Records`. Section headings come from
    `DetailSection`, which hard-codes `h3`.
  - Both tables: `caption` null, `aria-label` null — a screen reader reaching the table
    gets no name for it.
  - `main [aria-live], main [role=alert], main [role=status]` returns **`[]`** on all
    five routes. The loading line ("Loading aircraft..."), the error line, the
    `refreshing` opacity dim and the empty state are all silent to assistive tech, and
    the error is distinguished visually by `text-destructive` red alone — colour as the
    only channel.
  - `/sightings/:id`: `SightingPathLayer.tsx` colours the path by altitude
    (0 ft `#2ecc71`, 20,000 `#f1c40f`, 45,000 `#e74c3c`) with **no legend anywhere on
    the page**, while the endpoint markers use red for *start* and green for *end* — the
    same two hues carrying an unrelated meaning a few pixels away
    (`final-sighting-detail-closed.png`).
- **Expected:** Rubric 5: headings hierarchy, labelled controls, colour never the only
  channel.
- **Proposed fix:** (a) `frontend/src/features/aircraft-detail/components/DetailSection.tsx`
  — render `h2`, or accept a level prop. (b) Add `<caption className="sr-only">` to
  `AircraftTable.tsx` and `SightingsTable.tsx`. (c) Give the shared error component from
  R2-04 `role="alert"` and a Lucide `AlertTriangle` icon so red is not the only signal;
  give the loading and empty paragraphs `role="status"`. (d) Add a small altitude colour
  key under the path map in `SightingDetailPage.tsx` and restyle the start/end markers as
  distinguishable *shapes* (hollow vs filled) rather than a second red/green pair.
  Estimate: **M**.
- **Suggested agent:** sonnet (opus for (d) if the marker restyle materially touches
  `SightingPathLayer`'s paint expressions)

### What works well — do not regress

**`/aircraft`**
- `Unknown` is rendered as an italic, muted `<UnknownValue />` in every cell that has no
  value — never a blank, never a dash, never a fabricated zero. With demo metadata absent
  for most airframes this page is mostly `Unknown` and remains readable and honest.
- `aria-sort` is set correctly on the active header, and the up/down glyph plus the
  `text-foreground` weight change means sort direction is not colour-only.
- Sort and page round-trip through the URL cleanly, writing only non-default keys
  (`/aircraft` and `/aircraft?sort=last_seen&order=desc&page=1` are the same page), and a
  sort or filter change correctly resets to page 1.
- `placeholderData: keepPreviousData` plus the `opacity-60` dim means paging never
  flashes an empty table.
- `total` is computed exactly here (`history.py` explains why the count is cheap for this
  table but not for `/sightings`) and the footer reads "Page 3 of 3 - 111 aircraft".

**`/aircraft/:icao`**
- The three not-found states are distinguished and worded for a human: invalid address,
  never sighted, and load failure.
- `ProvenanceIndicator` is a real focusable button with the full sentence in its
  `aria-label`, so provenance does not depend on a tooltip being visible (SPEC §22).
- "Live now — view on map" appears only when `detail.live`, and "View all sightings for
  this aircraft" links back to the log — the aircraft / sightings / map cross-links the
  rubric asks for are present.

**`/sightings`**
- "Ongoing" for an open sighting is prominent and honest.
- The ICAO filter commits on submit, not per keystroke (verified: 0 requests while
  typing, 1 on Enter), validates the hex pattern with `aria-invalid` plus a text message,
  and "Clear filters" appears only when a filter is set.
- Closure reason is a tooltip on a dotted-underline trigger rather than a raw enum.
- Altitudes carry the flight level above FL180 alongside the raw value, in the receiver's
  unit system.

**`/sightings/:id`**
- The closed-sighting path renders very well — fit-to-bounds, start/end markers,
  altitude-coloured line over the same basemap as the Live Map.
- SPEC §51's reception block is complete, including "Time with a position 100.0%", which
  is the one statistic that tells an owner whether a sighting's geometry is trustworthy.
- The header links straight back to `/aircraft/:icao`, and the page stays fully usable
  from the sighting payload alone if the aircraft fetch fails (`aircraftQuery` is
  explicitly best-effort).

**`/activity`**
- `describeActivityEvent` keeps the English on the client and the payloads structured,
  degrades field-by-field rather than throwing, and renders an unknown future event type
  readably — worth preserving exactly as is.
- Records read well with their context: "New record: most aircraft at once — 44
  (previous 42) aircraft".
- Rows link to the most specific target the event names (aircraft over sighting), and a
  receiver-wide event links nowhere rather than somewhere wrong.
- Filter chips are `aria-pressed` toggles, multi-select, additive, and round-trip through
  repeated `type=` params.

### Method note

All findings were reproduced against the shared stack with Playwright/chromium at
1440x900 and 390x844, dark and light, browser timezone `Europe/London`. Fault injection
was client-side only (`page.route` fulfilling 500 or aborting), affecting no other
reviewer. No settings were changed, no data was reset, and no alert rule or watchlist was
created or deleted. Throwaway scripts (`e2e/review-r2-*.mjs`) were deleted after the run.


## Appendix D — R3: Analytics and Receiver

## Analytics (`/analytics`) and Receiver (`/receiver`) — findings

Reviewer **R3**. Stack: demo mode at `http://localhost:8090`, built from `dev`. Backend
process started ~01:33:34 UTC; first-run wizard wrote `config.yaml` at 01:34:35 UTC.
Review window 01:37 → 02:12 UTC on 2026-09-21 (receiver timezone `America/New_York`, so
the receiver-local date is 2026-09-20). Screenshots in `scratchpad/review/r3/`.

### Summary

Both pages are structurally good — the card/chart inventory matches SPEC §58 and §62
almost item for item (all nine receiver charts are implemented), failure is isolated per
card so one 500 never blanks a page, every chart carries an sr-only text summary, the
polar plot is genuinely north-up and clockwise, and both themes repaint correctly. But
the numbers on them are currently wrong. The dominant problem is a single backend defect
(**R3-01**): every rollup table is written under a **UTC** day key while every API read
asks for the **receiver-local** day, so on this install `daily_stats` holds
`unique_aircraft=60, sightings=60, max_range=225.6 nm` for day `2026-09-21` while the
Analytics page confidently reports `0 aircraft, 0 sightings`, `0 military` and "No data
for this window", and the Receiver scorecard shows `Max range today —` beside
`Max range ever 224.9 nm` set six minutes earlier. The second problem is that the page
then **contradicts itself in public** (**R3-03**): "Never seen before — 0 total" sits two
cards above "99 aircraft never seen before this window". The third is that nothing on
either page refreshes or recovers (**R3-05**, **R3-06**): seventeen of the eighteen data
surfaces fetch once on mount, retry once, then stop forever, and no surface says when its
figure is from. Layout is also unusable at phone width, though the cause is the app shell
(**R3-07**).

What works well and must not regress: per-card failure isolation, the sr-only chart
summaries, unit labels on every receiver chart axis, the polar orientation, preset↔URL
round-tripping, and the scorecard's honest `—` for nulls — it never fabricates a zero.

### Findings

| ID | Page | Severity | Category | Title |
|----|------|----------|----------|-------|
| R3-01 | Both | critical | correctness | Rollups written under a UTC day key, read under the receiver-local day — Analytics reads zero while the data exists |
| R3-02 | Both | high | robustness | Rollup-backed cards render a confident `0` instead of "not computed yet" on a young install |
| R3-03 | Analytics | high | consistency | The same page reports "never seen before" as both 0 and 99 |
| R3-04 | Receiver | high | robustness | No error boundary: one render-time throw replaces the whole route with React Router's developer error screen |
| R3-05 | Both | high | robustness | A failed card never recovers — `retry: 1`, no interval, no focus refetch |
| R3-06 | Both | high | usefulness | Charts never refresh and no surface shows when the data is from |
| R3-07 | Both | high | a11y-layout | At 390 px the sidebar keeps 256 px and `main` gets 134 px; every scorecard tile clips |
| R3-08 | Both | medium | robustness | Raw backend error strings shown verbatim; no page-level state when the API is unreachable |
| R3-09 | Receiver | medium | a11y-layout | Polar plot: `nm` axis name collides with the `3°` label, no cardinal points, permanent dead "Today" legend entry |
| R3-10 | Both | medium | correctness | Plural / tie-break / day-key defects: "1 points", "1 sightings", a meaningless "most frequently seen aircraft" |
| R3-11 | Both | medium | consistency | Five renderings of a date across the two pages |
| R3-12 | Analytics | medium | correctness | Six of seven analytics charts carry no unit on the value axis; one bar series is unnamed |
| R3-13 | Receiver | medium | usefulness | SPEC §60 "gracefully hide" implemented as permanent `—` tiles; histogram discards its own window/stats |
| R3-14 | Receiver | low | usefulness | "Since T0" is unexplained at the point of use; `common_model` fetched and never rendered |

---
#### R3-01 — Rollups written under a UTC day key, read under the receiver-local day

- **Page / surface:** `/analytics` (every card), `/receiver` (scorecard "Max range today",
  range-by-bearing "Today" ring, "Daily message totals", "Daily position totals")
- **Severity:** critical
- **Category:** correctness
- **Evidence:**
  The configured timezone is `America/New_York`; at 01:47 UTC the receiver-local date is
  2026-09-20, and the API read path agrees —
  `GET /api/v1/analytics/summary?preset=today` returns
  `"window": {"from":"2026-09-20T04:00:00.000Z","first_day":"2026-09-20","last_day":"2026-09-20","timezone":"America/New_York"}`.
  The rollup writers disagree. Reading the live DB inside the backend container:

  ```
  daily_stats:            ('2026-09-21', 60, 60, 60, 55, 1, 6, 4, 225.5866698827864, None)
                           day  unique new sightings interesting mil gov le max_range_nm busiest_hour
  daily_operator_stats:   ('2026-09-21', 56, 2, 2) ... 4 rows, all day='2026-09-21'
  receiver_metrics_daily: [('2026-09-21',)]
  range_by_bearing_daily: [('2026-09-21', 58)]
  ```

  Every row is keyed `2026-09-21` (the **UTC** day); every read asks for `2026-09-20`.
  They never meet, so the API answers zero over real data:

  ```
  /analytics/daily?preset=today  -> items:[{"day":"2026-09-20","unique_aircraft":0,
      "sightings":0,"military":0,"government":0,"law_enforcement":0,
      "max_range_nm":null,"busiest_hour":null,"receiver_messages":null, ...}]
  /analytics/summary?preset=today -> "sightings":0,"new_aircraft":0,"military":0,
      "government":0,"law_enforcement":0,"max_range_nm":null
  /analytics/top-operators?preset=today -> items:[]   (daily_operator_stats has 4 rows)
  /receiver/scorecard  -> "max_range_today_nm":null, "max_range_ever_nm":224.92141643501415
  /receiver/range-by-bearing -> today: 72 sectors, 0 non-null / ever: 72 sectors, 40 non-null
  ```

  `/receiver/lifetime` confirms the "ever" record was set **today**:
  `"max_range":{"nm":224.92,"at":"2026-09-21T01:34:34.127Z","bearing_deg":148.8,"icao":"bef93c"}`.
  In the UI (`t1-analytics-light-desktop.png`, `t1-receiver-dark-desktop.png`): "Daily
  aircraft & sighting counts — 2026-09-20 — 0 aircraft, 0 sightings"; "Military /
  government / police activity — 0 military, 0 government, 0 law-enforcement"; "Maximum
  detection distance — No data for this window"; "Receiver activity — No data for this
  window"; "Top operators — No data for this window"; and the scorecard's
  "Max range today —" directly beside "Max range ever 224.9 nm".

  Root cause, confirmed in code. The **read** path resolves the zone live, per request —
  `backend/src/flightsite/api/context.py:210`:
  ```python
  def _receiver_timezone(self) -> ZoneInfo:
      return ZoneInfo(self.settings.timezone)   # self.settings -> self._app.state.settings
  ```
  The **write** path snapshots it once at construction —
  `backend/src/flightsite/app.py:939-943` and `:391-397`:
  ```python
  app.state.analytics = AnalyticsService(..., timezone=settings.timezone)
  return ReceiverMetricsService(..., timezone=settings.timezone, ...)
  ```
  each storing `self._zone = ZoneInfo(timezone)` (`analytics/service.py:178`,
  `receiver_metrics/service.py:238`) and bucketing with it forever
  (`analytics/service.py:308,340`; `receiver_metrics/service.py:437`).
  On a first run `config.yaml` does not exist yet, so the captured value is the model
  default `timezone: str = "UTC"` (`backend/src/flightsite/config/models.py:341`). File
  timestamps on this stack show exactly that ordering: process start ~01:33:34 UTC,
  `config.yaml` mtime **01:34:35** UTC — written by the wizard a minute later. The
  services therefore hold `UTC` for the life of the process while every read uses
  `America/New_York`.
- **Expected:** SPEC §58/§61 and `docs/DATA_MODEL.md` §10 specify receiver-local day
  bucketing. Writes and reads must agree, and a timezone change must take effect without a
  backend restart.
- **Impact beyond this install:** not only a first-run artifact. Because the writer keeps
  its boot-time zone, **any** later Settings timezone change desynchronises writes from
  reads until a restart. And even with the zone fixed, a UTC-vs-local mismatch would recur
  daily for any receiver behind UTC — for `America/New_York` the UTC date runs a day ahead
  between 20:00 and 24:00 local, so the Analytics page would collapse to zero every
  evening and then, at local midnight, present that evening's traffic as "today". Note too
  that after a restart the already-written UTC-keyed rows survive as orphans
  (`daily_stats` day `2026-09-21` alongside a rebuilt `2026-09-20`), so the fix needs a
  rebuild/cleanup pass, not only a code change.
- **Proposed fix:** stop snapshotting the zone. Pass a zone *provider* (e.g.
  `Callable[[], ZoneInfo]` reading `app.state.settings`) into `AnalyticsService`
  (`backend/src/flightsite/analytics/service.py`) and `ReceiverMetricsService`
  (`backend/src/flightsite/receiver_metrics/service.py`), replacing the `self._zone` reads
  at `analytics/service.py:308,340` and
  `receiver_metrics/service.py:437,593,618,627-628`; wire it at
  `backend/src/flightsite/app.py:391,939`. Add a settings-save hook that rebuilds the
  affected days, and a startup repair that drops/rebuilds rollup rows whose day key does
  not match the current zone. Add a regression test that constructs the services with one
  zone, changes `settings.timezone`, and asserts a written day key matches what
  `/analytics/daily?preset=today` reads back. Estimate: **L**
- **Suggested agent:** opus

---

#### R3-02 — Rollup-backed cards render a confident `0` instead of "not computed yet"

- **Page / surface:** `/analytics` (Daily counts, Never seen before, Mil/gov/police, Max
  distance, Receiver activity); `/receiver` (four charts on the default window)
- **Severity:** high
- **Category:** robustness
- **Evidence:** Independently of R3-01, the rollup pipeline has real latency and the UI
  presents that gap as a measurement.
  `backend/src/flightsite/analytics/queries.py:324-330` zero-fills any day with no rollup
  row (`DailyRow(day=day)` — every field `0`/`None`), deliberately ("the zero is the
  measurement"). The analytics flush runs every 30 s (`analytics/service.py:98`) and only
  for dirty days; `receiver_metrics_hourly`/`_daily` are first written by the maintenance
  pass at t ~ 300 s (`receiver_metrics/service.py:126`); `busiest_hour` is deliberately
  `null` for the in-progress day (`analytics/rollup.py:151`).
  Observed at t ~ 4 min, the Analytics page renders "Daily aircraft and sighting counts
  across 1 days: 2026-09-20 — 0 aircraft, 0 sightings" and "New (never-seen-before)
  aircraft by day, 0 total: 2026-09-20 — 0" — a genuine-looking zero bar with no hint the
  install is minutes old. `RarityListsCard.tsx:48-51` prints a bare count with no
  young-install qualifier, and `AnalyticsPage.tsx:171-172` coerces absent data to zero
  (`rarityQuery.data?.never_seen_before ?? 0`).
  On `/receiver` the **default** window is the worst case: `7d -> hourly`
  (`features/receiver/lib/metricConfig.ts:45`, `ReceiverPage.tsx:23`) reads
  `receiver_metrics_hourly`, so for the first five minutes of any install four charts read
  "No data for this window." See `t1-receiver-dark-desktop.png` — one lone data point per
  chart, x-axis reading only "2026-09-20 21:00".
- **Expected:** a fresh install should say "not enough history yet", not report zero
  aircraft and zero sightings as fact. An honest empty state and a real zero must be
  distinguishable.
- **Proposed fix:** carry completeness per day — add `complete: bool` (or
  `source: "rollup" | "pending"`) to the `DailyRow` schema in
  `backend/src/flightsite/api/schemas.py` / `serializers.py`, set from whether a rollup row
  existed in `analytics/queries.py:324-330`. In the frontend render pending days as a gap
  with an explicit caption rather than a zero bar
  (`frontend/src/features/analytics/components/cards/{DailyCountsCard,NeverSeenBeforeCard,ClassificationActivityCard}.tsx`),
  and add a young-install qualifier at `RarityListsCard.tsx:48-51`. On `/receiver`, fall
  back to `resolution=high` when the hourly series is empty
  (`features/receiver/components/ReceiverSeriesChart.tsx`). Estimate: **M**
- **Suggested agent:** opus

---

#### R3-03 — The same page reports "never seen before" as both 0 and 99

- **Page / surface:** `/analytics` — "Never seen before" card vs "Locally rare" card
- **Severity:** high
- **Category:** consistency
- **Evidence:** One screenshot, two cards, same window, same instant
  (`t1-analytics-light-desktop.png`, and the preset capture at 02:00 UTC):
  ```
  Never seen before
  Sep 20, 2026 · America/New_York
  New (never-seen-before) aircraft by day, 0 total: 2026-09-20 — 0.

  Locally rare
  Sep 20, 2026 · America/New_York
  99 aircraft never seen before this window.
  ```
  The two read different sources for the same SPEC §58 concept ("count of aircraft never
  previously seen"): `NeverSeenBeforeCard` uses `daily.new_aircraft`, summed from the
  `daily_stats` rollup (`analytics/queries.py:297-330`), while `RarityListsCard` uses
  `rarity.never_seen_before`, computed live. The API confirms it:
  `/analytics/summary?preset=today -> "new_aircraft":0` against
  `/analytics/rarity?preset=today -> "never_seen_before":60`, rising to 99 as I watched.
  The same split produces a cross-page contradiction: Analytics reports "0 military,
  0 government, 0 law-enforcement sightings" for today while the Live Map's filter panel
  simultaneously counts **76** interesting aircraft, most labelled
  "Rule: Military aircraft" (`consistency-livemap-glance.png`), and `daily_stats` holds
  `military=1, government=6, law_enforcement=4`. Likewise "Top operators — No data for
  this window" sits on the same page as a Locally-rare table listing NASA and US Customs
  as operators.
- **Expected:** rubric §4 — the same concept named and counted the same way across cards
  and pages. Two visible numbers for one quantity is worse than either alone.
- **Proposed fix:** make one source authoritative. Either derive `new_aircraft` in
  `/analytics/summary` and `/analytics/daily` from the same live query that backs
  `/analytics/rarity` (`backend/src/flightsite/analytics/queries.py`), or drop
  `never_seen_before` from the rarity payload and have `RarityListsCard` read the daily
  series. Add a backend test asserting
  `summary.new_aircraft == rarity.never_seen_before` for the same window, and a frontend
  test asserting the two cards render the same figure. Fixing R3-01 removes today's
  instance but not the structural duplication. Estimate: **M**
- **Suggested agent:** opus

---

#### R3-04 — No error boundary: a render-time throw takes the whole route down

- **Page / surface:** `/receiver` (the same exposure exists on `/analytics`)
- **Severity:** high
- **Category:** robustness
- **Evidence:** I served `/api/v1/receiver/lifetime` a 200 whose body omitted the
  `max_range` key (Playwright `page.route` fulfil). The entire route was destroyed — the
  `h1` count went from 1 to **0** — and the user was shown React Router's *developer*
  fallback, stack trace and all (`fault-receiver-huge-lifetime.png`):
  ```
  TypeError: Cannot read properties of undefined (reading 'nm')
  React Router caught the following error during render ...
  "Hey developer" - You can provide a way better UX than this when your app throws errors
  by providing your own ErrorBoundary or errorElement prop on your route.
  ```
  There is no `ErrorBoundary` or `errorElement` anywhere in `frontend/src` —
  `frontend/src/routes.tsx:56-88` wraps `/analytics` and `/receiver` in `<Suspense>` only.
  The specific trigger is a strict-equality guard at
  `frontend/src/features/receiver/components/LifetimeStatsSection.tsx:99-101`:
  ```tsx
  maxRange === null ? "—" : `${formatDistance(maxRange.nm, units)} (${cardinalFromDegrees(maxRange.bearing_deg)})`
  ```
  `=== null` does not cover `undefined`. **In fairness:** today's backend always
  serialises `"max_range": null` explicitly, so this exact payload is not reachable from
  the real API — the reportable defect is the *blast radius*, not this field. Any
  render-time throw in any one of the ~18 cards (a malformed row in a tooltip formatter, a
  future optional field, a proxy rewriting JSON, a version-skewed backend) loses the whole
  page and shows a developer screen to the receiver's owner.
- **Expected:** rubric §2 — an error in one card must not take the whole page down, and a
  user should never see a React stack trace.
- **Proposed fix:** add a reusable `ErrorBoundary` under `frontend/src/components/` and
  wrap each card/section — `AnalyticsCard.tsx` and
  `features/receiver/components/{ChartCard,ReceiverScorecard,LifetimeStatsSection}.tsx` —
  plus an `errorElement` on both routes in `frontend/src/routes.tsx:56-88` as the
  backstop. Relax the guard to `maxRange == null` (likewise `busiestDay`, `mostFrequent`)
  at `LifetimeStatsSection.tsx:51-53,99-101`. Add tests that render a card whose child
  throws and assert the rest of the page survives. Estimate: **M**
- **Suggested agent:** sonnet

---
#### R3-05 — A failed card never recovers

- **Page / surface:** all `/analytics` cards; all `/receiver` charts and the lifetime section
- **Severity:** high
- **Category:** robustness
- **Evidence:** I 500ed `/api/v1/analytics/top-aircraft`, then made the route healthy
  again and waited 20 s on the same open page. The request count stayed at **2** (the
  initial call plus the single `retry: 1`) and the card still read `temporary`
  (`fault-analytics-no-self-heal.png`). Only a preset change or navigating away and back
  re-fetches. Cause: the hooks set no options at all
  (`frontend/src/lib/api/analytics.ts:335-387`), inheriting
  `frontend/src/lib/queryClient.ts:9-17`:
  ```ts
  queries: { staleTime: 30_000, retry: 1, refetchOnWindowFocus: false }
  ```
  with no `refetchInterval`. The same holds for six of the seven receiver queries
  (`frontend/src/lib/api/receiverStats.ts:205-275`); only `useReceiverScorecardQuery`
  polls (5 s, `:161,167-173`).
  A related sharp edge: `/analytics/daily` backs **four** cards
  (`AnalyticsPage.tsx:124-167`), so one 500 there prints the same red message four times —
  verified in `fault-analytics-500-daily.png`, where "daily exploded" appears
  simultaneously in Daily counts, Maximum detection distance, Receiver activity and Never
  seen before.
- **Expected:** rubric §2 — "Does the page recover without a reload? Do polls/refetches
  keep going after an error?" A transient backend blip should heal itself.
- **Proposed fix:** give the analytics and receiver queries a `refetchInterval` (60 s for
  analytics cards, 30–60 s for receiver charts) and `refetchOnWindowFocus: true` in
  `frontend/src/lib/api/analytics.ts:335-387` and
  `frontend/src/lib/api/receiverStats.ts:205-275`; raise `retry` to 2–3 with backoff. Add
  a "Try again" button to the error branch of
  `frontend/src/features/analytics/components/AnalyticsCard.tsx:49-57` and
  `features/receiver/components/ChartCard.tsx:32-40`, calling `refetch()`. Estimate: **S**
- **Suggested agent:** sonnet

---

#### R3-06 — Charts never refresh and nothing says when the data is from

- **Page / surface:** `/analytics` (all nine cards), `/receiver` (all nine charts + lifetime)
- **Severity:** high
- **Category:** usefulness
- **Evidence:** Only the receiver scorecard auto-refreshes (5 s). Every chart and the
  lifetime block fetches once on mount and then never again — no `refetchInterval`, and
  `refetchOnWindowFocus: false` — so a tab left open overnight shows yesterday's numbers
  indefinitely. Watching `/analytics` for ~25 minutes, no card changed until I
  re-navigated, while `/analytics/rarity` climbed from 60 to 99 aircraft underneath.
  Nothing anywhere renders a fetch time: no `dataUpdatedAt` is read, there is no "updated"
  caption, no `isFetching` indicator and no manual refresh control on either page. The
  only temporal caption is the *queried window* (`AnalyticsCard.tsx:41-47`, rendering
  "Sep 20, 2026 · America/New_York") — the range asked for, not when it was answered — so
  stale data is presented under a caption that looks current. Past local midnight a page
  left open still says "Today" and shows the previous day with no cue.
  `/receiver`'s signal-distribution endpoint actually returns
  `from_ts`/`to_ts`/`sample_count`/`avg_db`, and the component discards all of them
  (`features/receiver/components/SignalDistributionChart.tsx:16-17`), so even the data
  that would answer "from when?" is thrown away.
- **Expected:** rubric §2 ("stale data — how does the user know the figure is old?") and
  §1. `docs/PRODUCT.md` §4.6/§4.7 present these as live observatory surfaces.
- **Proposed fix:** add `refetchInterval` per R3-05, then render a shared
  "Updated <relative time>" caption from TanStack's `dataUpdatedAt` in
  `frontend/src/features/analytics/components/AnalyticsCard.tsx` and
  `frontend/src/features/receiver/components/ChartCard.tsx`, with a page-level refresh
  button in `AnalyticsPage.tsx` / `ReceiverPage.tsx`. Surface the histogram's returned
  `from_ts`/`to_ts`/`sample_count`/`avg_db` in `SignalDistributionChart.tsx`. Invalidate
  the `today` preset queries on local-midnight rollover. Estimate: **M**
- **Suggested agent:** sonnet

---

#### R3-07 — At 390 px the sidebar keeps 256 px and the content gets 134 px

- **Page / surface:** `/receiver` and `/analytics` at 390x844 (root cause is the app shell)
- **Severity:** high
- **Category:** a11y-layout
- **Evidence:** Fresh browser context, 390x844, no storage tampering, on `/receiver`:
  ```json
  {"aside": {"w": 256, "display": "block"},
   "main": {"w": 134, "left": 256},
   "clipped": ["\"Aircraft visible\" scroll=38 client=19",
               "\"Messages/sec\" scroll=73 client=19",
               "\"77.9 msg/s\" scroll=55 client=19",
               "\"224.9 nm\" scroll=49 client=19", ...]}
  ```
  `main` is 34 % of the viewport, and every scorecard tile's text overflows its box
  (`phone-390-receiver-default.png`, `t1-receiver-light-phone.png`): "Messages/sec 63.0
  msg/" and "Health Demo mod" are visibly cut off and values wrap mid-unit. `/analytics`
  is identical (`main` 134 px, `phone-390-analytics-default.png`). The polar plot in that
  space is illegible — angle labels collide into "333° 3° 33°" printed over the plot area
  (`t1-maximum-light-phone.png`).
  Note there is no horizontal *page* scroll — document `scrollWidth == clientWidth == 390`
  on both pages in both themes — because the content is clipped and wrapped rather than
  overflowing. That is exactly why an overflow-only check passes while the page is
  unusable.
- **Expected:** rubric §5 — phone (390x844) with nothing clipped and usable touch targets.
  The sidebar should collapse to an overlay/drawer below the `md` breakpoint.
- **Proposed fix:** collapse the sidebar by default below `md` in
  `frontend/src/components/AppShell.tsx` (the `<aside>` around line 54) — off-canvas with
  a hamburger toggle. Then, within this scope: keep the scorecard at `grid-cols-2` but let
  tiles grow (`ReceiverScorecard.tsx:97`), and make chart heights responsive instead of
  the fixed `DEFAULT_HEIGHT = 280` / `POLAR_HEIGHT = 360`
  (`features/analytics/components/EChart.tsx:64`,
  `features/receiver/components/RangeByBearingChart.tsx:21`). Add an `md:` step to the
  analytics grid (`AnalyticsPage.tsx:73` jumps `grid-cols-1` straight to
  `lg:grid-cols-2`, leaving 768–1023 px as one very wide column).
  **Likely overlaps another reviewer's app-shell scope — coordinate before fixing.**
  Estimate: **M**
- **Suggested agent:** sonnet

---

#### R3-08 — Raw backend error strings shown verbatim; no page-level unreachable state

- **Page / surface:** `/analytics` (and `/receiver`, differently)
- **Severity:** medium
- **Category:** robustness
- **Evidence:** 500ing `/analytics/top-aircraft` with `{"error":{"message":"kaboom"}}`
  renders the literal word **`kaboom`** in red where the card sits
  (`fault-analytics-500-top-aircraft.png`); `/analytics/daily` with `"daily exploded"`
  prints that string four times (`fault-analytics-500-daily.png`). The developer-written
  fallbacks ("Could not load top aircraft.") are effectively dead code, because
  `frontend/src/features/analytics/AnalyticsPage.tsx:36-45` prefers `error.message`:
  ```ts
  return error?.message ?? fallback;
  ```
  and `AnalyticsApiError` (`frontend/src/lib/api/analytics.ts:182-192`) takes its message
  from the backend body.
  Aborting every analytics call yields nine identical **`Failed to fetch`** paragraphs and
  nothing else — no page-level "FlightSite can't reach the API", no retry
  (`fault-analytics-all-abort.png`). The error paragraph carries no `role="alert"` or
  `aria-live` (`AnalyticsCard.tsx:49-57`), so a screen-reader user not tabbing through
  never learns a card failed — unlike the empty state, which correctly has `role="status"`
  (`EChart.tsx:133`). `/receiver` behaves better here (fixed friendly strings, e.g. "Could
  not load the scorecard." in `fault-receiver-500-scorecard.png`) but never distinguishes
  a 400 from a 500, so an unsupported metric/resolution pairing reads like a server fault.
- **Expected:** users see human copy, not backend internals; an unreachable API is stated
  once at page level rather than nine times as "Failed to fetch"; failures are announced.
- **Proposed fix:** invert the precedence at `AnalyticsPage.tsx:36-45` to prefer the
  written fallback, keeping `error.message` for a dev-only detail line. Add `role="alert"`
  to the error paragraphs at `AnalyticsCard.tsx:54` and
  `features/receiver/components/ChartCard.tsx:36`. Detect the all-failed case in
  `AnalyticsPage.tsx` and render one page-level banner with a retry. Estimate: **S**
- **Suggested agent:** sonnet

---

#### R3-09 — Polar plot: colliding axis name, no cardinal points, dead "Today" legend

- **Page / surface:** `/receiver` — "Maximum range by bearing"
- **Severity:** medium
- **Category:** a11y-layout
- **Evidence:** `theme-after-toggle-polar.png` (light) and `t1-maximum-dark-desktop.png`
  (dark).
  Orientation is **correct** — north up, bearings clockwise — confirmed both visually and
  at `frontend/src/features/receiver/lib/chartOptions.ts:275-283`
  (`startAngle: 90, clockwise: true`, neither left to the ECharts default), and the
  lifetime record's bearing 148.8° is reported as "SSE", which matches the demo traffic.
  Three defects around it:
  1. The radius-axis name `nm` is drawn at the top of the polar area and **overlaps the
     `3°` angle label** in both themes — legible as "nm" printed through "3°".
  2. Angle labels are rounded sector midpoints — `3°, 33°, 63°, 93°, 123°, 153°, 183°,
     213°, 243°, 273°, 303°, 333°` (`chartOptions.ts:239` with
     `axisLabel: { interval: 5 }`). A compass rose whose ticks all miss 0/90/180/270 and
     carry no N/E/S/W reads as broken. `cardinalFromDegrees` already exists
     (`features/receiver/lib/format.ts:192-196`) and is unused here.
  3. The legend always shows a "Today" entry even when the Today series draws nothing —
     the current state, since `today` is 72 nulls per R3-01. The sr-only summary correctly
     says "today's maximum is not set yet", but a sighted user sees a legend key with no
     marks and no explanation.
  Related code-level defect: the empty-state guard is unreachable. `chartOptions.ts:232`
  tests `ever.length === 0`, but the backend *always* emits all 72 sectors for both series
  (`backend/src/flightsite/api/serializers.py:567-584`, whose docstring says so
  explicitly). On an install with no range records at all the chart therefore draws an
  empty polar grid instead of "No data for this window", while the sr-only text says the
  opposite — sighted and screen-reader users get different stories.
- **Expected:** a readable compass rose with cardinal points, no overlapping labels, and a
  legend that reflects what is actually drawn.
- **Proposed fix:** in `frontend/src/features/receiver/lib/chartOptions.ts:273-290` — move
  the radius name (`nameLocation: "end"` with a `nameGap`, or drop it and put `nm` in the
  card subtitle); build angle labels from `cardinalFromDegrees`, labelling the eight
  cardinals and blanking the rest, instead of `interval: 5`; set `boundaryGap: false`
  explicitly so bucket 0 sits exactly on north; change the guard at `:232` to
  `everPresent.length === 0`; and omit the "Today" series and legend entry when
  `todayPresent.length === 0`. Estimate: **S**
- **Suggested agent:** sonnet

---
#### R3-10 — Plural, tie-break and day-key defects in generated copy

- **Page / surface:** `/receiver` (chart summaries, lifetime stats) and `/analytics`
- **Severity:** medium
- **Category:** correctness
- **Evidence:** All taken from rendered page text (`t1-receiver-*.png`):
  - **"1 points"** in every receiver chart summary — "Messages per second: **1 points**
    from 2026-09-20 21:00 to 2026-09-20 21:00." Note also that start equals end, so the
    stated range is degenerate rather than a range.
  - **"0A4FCE (1 sightings)"** under "Most frequently seen aircraft" — wrong plural, and
    the statistic itself is meaningless: all 95 aircraft have exactly one sighting, so
    "most frequently seen" is an arbitrary tie-break presented as a record. SPEC §63 asks
    for a real record; with no winner it should say so.
  - **"Busiest day 2026-09-21 (24,790 msgs)"** — the raw UTC rollup day key leaking into
    the UI while every other date on the page says Sep 20 (a user-visible symptom of
    R3-01), and rendered as a bare ISO string where the rest of the section uses locale
    dates.
  - **"Unique aircraft per day: 31 points from 08/21/2026 to 09/20/2026. Latest 0,
    peak 0."** — 31 zero points presented as a measured series on a day-old install.
  - `/analytics/top-types` returns `"days_seen": 0` for every row and `TopGroupCard`
    renders it in the tooltip ("... · 0 days"), an always-zero figure on any young
    install.
- **Expected:** rubric §3 — plural and zero wording correct, no fabricated records, dates
  formatted consistently.
- **Proposed fix:** add a pluralisation helper and apply it at
  `frontend/src/features/receiver/lib/chartOptions.ts:92-96` ("1 point") and in
  `features/receiver/lib/format.ts` — the analytics side already gets this right
  (`features/analytics/lib/format.ts:119-121`), so reuse it rather than writing a second.
  In `features/receiver/components/LifetimeStatsSection.tsx`, render "—" (or "no clear
  leader") when the top count ties at 1, and format `busiest_day` through
  `formatReceiverLocalDate`. Collapse a degenerate single-point range to "at <time>". Hide
  `days_seen` when it is zero at
  `features/analytics/components/cards/TopGroupCard.tsx:62-71`. Estimate: **S**
- **Suggested agent:** sonnet

---

#### R3-11 — Five renderings of a date across the two pages

- **Page / surface:** `/analytics` and `/receiver`
- **Severity:** medium
- **Category:** consistency
- **Evidence:** On adjacent surfaces, at the same instant:
  - `Sep 20, 2026 · America/New_York` — analytics card captions (`AnalyticsCard.tsx:41-47`)
  - `Lifetime statistics since 09/20/2026` — receiver lifetime header
    (`LifetimeStatsSection.tsx:60-67`)
  - `2026-09-20 21:00` — receiver chart summaries and x-axis labels
  - `08/21/2026 to 09/20/2026` — the "Unique aircraft per day" summary
  - `2026-09-20 — 0 aircraft, 0 sightings` — the analytics daily summary
  - `2026-09-21` — lifetime "Busiest day"
  The analytics captions name the timezone; no receiver surface does, although both are
  receiver-local.
- **Expected:** rubric §4 — the same concept formatted the same way across pages.
- **Proposed fix:** promote one formatter (`formatReceiverLocalDate` in
  `frontend/src/features/receiver/lib/format.ts`) into a shared
  `frontend/src/lib/datetime.ts` and use it from `features/analytics/lib/format.ts:62-68`,
  the summaries and axis label formatters in `features/receiver/lib/chartOptions.ts`, and
  `LifetimeStatsSection.tsx`. Show the timezone once per page rather than once per card.
  Estimate: **S**
- **Suggested agent:** sonnet

---

#### R3-12 — Six of seven analytics charts carry no unit on the value axis

- **Page / surface:** `/analytics`
- **Severity:** medium
- **Category:** correctness
- **Evidence:** Only `MaxDistanceCard` labels its value axis —
  `frontend/src/features/analytics/components/cards/MaxDistanceCard.tsx:62-67`:
  ```ts
  yAxis: { type: "value", name: unitLabel, nameTextStyle: {...}, ...axisStyle }
  ```
  and it is also the only one with a unit-bearing tooltip (`:54-55`, giving `"18 nm"`).
  The others use a bare value axis — `NeverSeenBeforeCard.tsx:53`
  (`yAxis: { type: "value", ...axisStyle }`), and likewise `DailyCountsCard.tsx`,
  `ClassificationActivityCard.tsx:53`, `ReceiverActivityCard.tsx`,
  `TopAircraftCard.tsx:116-121` and `TopGroupCard.tsx:122-127`. So "Military: 3" never
  says *3 sightings*. Worse, `NeverSeenBeforeCard.tsx:54-59` gives its bar series **no
  `name`**, so its axis tooltip shows an empty series label beside a bare number.
  **Credit where due:** every `/receiver` series chart *does* set `yAxis.name`
  (`msg/s`, `pos/s`, `aircraft`, `nm`) plus a unit-bearing `valueFormatter` — clearly
  visible in `t1-receiver-dark-desktop.png`. The analytics page simply did not follow
  suit. The one receiver gap is the signal histogram's tooltip, which has no formatter
  (`features/receiver/lib/chartOptions.ts:180`) even though its axes are labelled `dB` and
  `Sightings`.
  Minor related risk: `AnalyticsPage.tsx:50` defaults units to `"aviation"` while
  `/api/v1/receiver` is still loading, so a metric-configured site briefly draws the
  distance chart labelled `nm` before it flips to `km`.
- **Expected:** CLAUDE.md — "units are nm/ft/kt canonically"; rubric §1/§3 — no numbers
  without units.
- **Proposed fix:** set `yAxis.name` on the remaining six charts (`"aircraft"`,
  `"sightings"`, `"messages"`/`"positions"`) and add a `name` to the `NeverSeenBeforeCard`
  bar series; add a `tooltip.valueFormatter` carrying the unit to each, mirroring
  `MaxDistanceCard.tsx:54-55`. Add a unit formatter to the signal histogram tooltip
  (`features/receiver/lib/chartOptions.ts:180`). Gate the distance chart on
  `receiverQuery.isSuccess` to remove the unit flash. Estimate: **S**
- **Suggested agent:** sonnet

---

#### R3-13 — SPEC §60 "gracefully hide" implemented as permanent dead tiles

- **Page / surface:** `/receiver` — scorecard and signal-strength histogram
- **Severity:** medium
- **Category:** usefulness
- **Evidence:** `/api/v1/receiver/scorecard` returns `"decoder_uptime_s": null` on this
  stack, and the scorecard renders a permanent `Decoder uptime —` tile
  (`t1-receiver-dark-desktop.png`;
  `features/receiver/components/ReceiverScorecard.tsx:128-131`, with
  `formatDurationCompact(null) -> "—"` at `lib/format.ts:81-84`). No tile is ever hidden —
  `StatTile` renders unconditionally (`:40-50`). On a real decoder serving no `stats.json`,
  Messages/sec, Positions/sec and Decoder uptime would all three be permanently `—` with
  no explanation on the tiles themselves; the only hint is the Health tile.
  The `—` itself is *right* — it never fabricates a zero, confirmed by injecting an
  all-null scorecard (`fault-receiver-null-scorecard.png`, `—` for every nullable metric
  and no false zeros) — but SPEC §60 asks for unsupported metrics to be **hidden**, not
  shown blank forever. Note the inverse gap too: `current_visible`,
  `unique_aircraft_today` and `unique_aircraft_since_t0` are typed non-nullable, so for
  those tiles "no data yet" and "genuinely zero" are indistinguishable.
  Separately, the histogram discards the context it is handed: the endpoint returns
  `sample_count: 42, min_db: -25.3, max_db: -5.0, avg_db: -13.9` plus `from_ts`/`to_ts`,
  and `features/receiver/components/SignalDistributionChart.tsx:16-17` reads only
  `buckets` — so the card never states its window or the average signal, the single most
  useful number for an owner tuning an antenna.
- **Expected:** SPEC §60 — "Normalize common fields and gracefully hide unsupported
  decoder metrics." SPEC §62 — a signal-strength distribution an owner can act on.
- **Proposed fix:** at `ReceiverScorecard.tsx:99-136`, omit tiles whose metric is
  unsupported — add a `supported` flag to the scorecard payload in
  `backend/src/flightsite/api/serializers.py:484-530`, driven by `service.stats_supported`,
  rather than inferring it from `null` — while keeping `—` for "supported but not yet
  sampled". Render `sample_count`/`avg_db`/`min_db`/`max_db` and the covered window as a
  caption in `SignalDistributionChart.tsx`. Estimate: **M**
- **Suggested agent:** opus

---

#### R3-14 — "Since T0" unexplained; `common_model` fetched and never rendered

- **Page / surface:** `/receiver` — scorecard tile and lifetime section
- **Severity:** low
- **Category:** usefulness
- **Evidence:** The scorecard tile reads literally `Unique aircraft since T0`
  (`ReceiverScorecard.tsx:124-127`) with no date, tooltip or `title` attribute — "T0" is
  unexplained jargon at the point of use. The date exists two sections below
  ("Lifetime statisticssince 09/20/2026", `LifetimeStatsSection.tsx:60-67`) and comes from
  a *different* endpoint, so when `/receiver/lifetime` fails the date vanishes while the
  scorecard still says "since T0" (`fault-receiver-500-scorecard.png` shows the inverse
  case, the scorecard gone and the lifetime date still present). `ReceiverInfo.t0` is
  already fetched on this page (`ReceiverPage.tsx:27`) and simply unused for the tile.
  Note also the heading renders as "Lifetime statisticssince 09/20/2026" — a missing space
  in the DOM text.
  Separately, `/receiver/lifetime` returns
  `common_model: {"value":"Airbus H145","aircraft_count":2}`, the frontend types it
  (`lib/api/receiverStats.ts:122`), and `LifetimeStatsSection` never renders it — SPEC §63
  lists "common type/model/operator records" and only type and operator appear.
  Two smaller accessibility notes on the same surfaces: the scorecard has **no heading at
  all** (only `role="group" aria-label="Receiver scorecard"`,
  `ReceiverScorecard.tsx:94-97`), so it cannot be reached by heading navigation; and
  `LifetimeStatsSection` uses `h3` (`:60`) while sitting as a sibling of the `h2`
  "Charts", giving a hierarchy of `h1 -> (none) -> h2 -> h3 x9 -> h3`.
- **Expected:** SPEC §61/§63 — the scorecard and lifetime statistics state their "since"
  clearly, and all listed lifetime records are shown.
- **Proposed fix:** at `ReceiverScorecard.tsx:124-127` render `Unique aircraft since
  <date>` (or keep "since T0" with the date as a subtitle) from the already-available
  `ReceiverInfo.t0`; add an `<h2>` for the scorecard and promote `LifetimeStatsSection`'s
  heading to `h2`; fix the missing space at `:60-67`; add a "Common model" row.
  Estimate: **S**
- **Suggested agent:** sonnet

---
### What works well — do not regress

**Both pages**

- **Per-card failure isolation.** One 500 degrades exactly one card and leaves the rest of
  the page fully functional — verified against `/analytics/top-aircraft`,
  `/analytics/daily`, `/receiver/scorecard` and `/receiver/range-by-bearing`
  (`fault-*.png`). Page chrome, headings and every other card survive each case. This is
  hand-rolled per query rather than boundary-based (see R3-04), but it works, and the fix
  slice must not lose it.
- **Text alternatives for every chart.** `EChart.tsx:142-152` pairs a `role="img"` +
  `aria-label` container with an sr-only `<p>` summary, and the summaries are genuinely
  data-bearing rather than mere labels — e.g. "Daily aircraft and sighting counts across
  1 days: 2026-09-20 — 0 aircraft, 0 sightings" and "Lifetime maximum range 224.9 nm
  across 72 bearing sectors; today's maximum is not set yet." This is better than most
  dashboards manage and must survive any chart rework.
- **Empty states are announced** with `role="status"` (`EChart.tsx:133`), and the charts
  distinguish a null from a zero: `connectNulls: false` plus per-day null mapping in
  `MaxDistanceCard.tsx:71-77` and `ReceiverActivityCard.tsx` means "not recorded" renders
  as a gap, never as a false zero.
- **Both themes repaint live.** Toggling the theme with the page open rebuilds every
  ECharts option from live CSS custom properties and calls `setOption(..., true)`
  (`EChart.tsx:74-127`, `chartTheme.ts:64-77`) — no reload needed and no stale light
  colours left in dark mode (`theme-as-loaded-polar.png` vs
  `theme-after-toggle-polar.png`).
- **No horizontal page scroll** in any of the eight page x theme x viewport combinations
  tested.

**Analytics**

- **Preset ↔ URL round-trip.** All five SPEC §58 presets are present and in the right
  order (Today, 7 days, 30 days, This year, Since T0); the URL is the single source of
  truth (`useAnalyticsPresetState.ts:25-37`); the default is omitted from the query string
  so a shared link stays short; garbage falls back to `today` (`urlState.ts:22-25`); and a
  deep link survives a refresh with the right radio still checked.
- **`PresetSelector` accessibility:** `role="radiogroup"` with `aria-label="Time range"`,
  `role="radio"` plus `aria-checked`, a roving tabindex and a visible focus ring
  (`PresetSelector.tsx:34-58`).
- **Provenance on every card** — each card states the resolved window *and* the timezone
  ("Sep 20, 2026 · America/New_York"), echoed from the backend rather than recomputed in
  the browser. This is what made R3-01 diagnosable from the UI alone.
- **Clean heading hierarchy**: one `h1`, an `h2` per card, `h3` for the rarity sub-tables.
- **Only four network requests back eight cards**; `/analytics/daily` is shared rather
  than refetched per card. (Its blast radius is noted in R3-05, but the sharing itself is
  right.)

**Receiver**

- **All nine SPEC §62 charts are implemented** — messages/sec, positions/sec, simultaneous
  aircraft, unique aircraft per day, maximum range over time, signal-strength
  distribution, range-by-bearing polar, daily message totals and daily position totals.
  Nothing from the spec list is missing.
- **Polar orientation is correct** — north up, bearings clockwise, set explicitly at
  `chartOptions.ts:275-283` rather than left to the ECharts default (whose `clockwise`
  would have been wrong).
- **Units on every receiver chart axis and tooltip** (`msg/s`, `pos/s`, `aircraft`, `nm`,
  `dB`) — `chartOptions.ts:117`, `metricConfig.ts:62-119`. This is the pattern the
  analytics page should copy.
- **Nulls never become zeros** on the scorecard — an all-null payload renders `—`
  throughout (`fault-receiver-null-scorecard.png`), and the existing test
  `ReceiverPage.test.tsx:161-204` locks that behaviour in.
- **Series distinguished by shape as well as colour** — "Ever" is solid with circles,
  "Today" dashed with diamonds (`chartOptions.ts:291-314`), satisfying SPEC §80's
  "colour is never the only channel".
- **Scorecard polls at 5 s** (`receiverStats.ts:161,167-173`) — the one surface on either
  page that is genuinely live.
---

### Re-check after ~30 minutes (02:03 UTC, install age ~30 min)

The brief asked for a second look once the demo had accumulated history. The picture did
not improve — it got starker. Raw output in `recheck-api.txt`.

The rollup tables kept filling, correctly, under the **wrong** key:

```
daily_stats: [('2026-09-21', 112, 112, 117, 9, 12, 6, 225.5866698827864)]
              day  unique new sightings military government law_enforcement max_range_nm
range_by_bearing_daily: [('2026-09-21', 72)]   <- all 72 sectors now populated
receiver_metrics_daily: [('2026-09-21',)]      receiver_metrics_hourly: 2 rows
```

while every read still asked for `2026-09-20` and still answered zero:

```
/analytics/summary?preset=today -> unique_aircraft:112, new_aircraft:0, sightings:0,
    military:0, government:0, law_enforcement:0, max_range_nm:null
/analytics/daily?preset=today   -> [{"day":"2026-09-20","unique_aircraft":0,"sightings":0,
    "military":0, ..., "max_range_nm":null,"receiver_messages":null}]
/analytics/top-operators?preset=today -> items:[]
/receiver/scorecard -> max_range_today_nm:null, max_range_ever_nm:224.92
```

Three conclusions for the fix slice:

1. **R3-01 is not rollup lag that resolves itself.** Thirty minutes in, with every rollup
   table populated, the Analytics page still reports zero military, zero government, zero
   law-enforcement and zero sightings while `daily_stats` holds 9, 12, 6 and 117 for the
   same traffic. It persists for the life of the backend process. This is the finding to
   fix first; several others are only visible because of it.
2. **R3-03 widened rather than closed.** The live-computed figures kept climbing
   (`unique_aircraft` 42 → 58 → 95 → **112**, `rarity.never_seen_before` 60 → 99 →
   **157** milestones) while every rollup-backed card stayed pinned at zero, so the gap
   between the two numbers on the same page grew all session.
3. **R3-02's receiver symptom is genuinely transient** — `receiver_metrics_hourly` went
   from 0 to 2 rows once the 5-minute maintenance pass ran, and the hourly charts gained
   points. That part does heal on its own; the analytics zero-fill does not.

One incidental observation worth passing to whoever owns demo mode: over the session
`current_visible` fell from 80 to 13 and `messages_per_sec` from 73 to 5.3, so the demo
traffic ebbs. Nothing on either page distinguishes "the receiver went quiet" from "the
poller stopped" — the scorecard shows a falling number with no trend or staleness cue,
which is the same gap as R3-06.

---

### Screenshot index (`scratchpad/review/r3/`)

Baseline, both pages x both themes x both viewports:
`t1-analytics-{light,dark}-{desktop,phone}.png`,
`t1-receiver-{light,dark}-{desktop,phone}.png`

Lower receiver charts captured per element (the page scrolls inside a container, so
full-page capture truncates them): `t1-maximum-{light,dark}-desktop.png`,
`t1-maximum-light-phone.png`, `t1-signal-*.png`, `t1-lifetime-*.png`

Theme toggle without reload: `theme-as-loaded-polar.png`, `theme-after-toggle-polar.png`,
`theme-{as-loaded,after-toggle}-signal.png`

Phone layout at default state: `phone-390-receiver-default.png`,
`phone-390-analytics-default.png`

Analytics presets: `t1-analytics-preset-Today.png`, `t1-analytics-preset-7-days.png`
(all five presets were exercised and their payloads captured; the 30-days / This-year /
Since-T0 renders were identical to 7 days on this young install, so only the two
distinct states were kept)

Injected failure states (all client-side via `page.route`):
`fault-analytics-500-top-aircraft.png` (one card 500s, page survives),
`fault-analytics-500-daily.png` (one endpoint, four cards fail),
`fault-analytics-all-abort.png` (API unreachable),
`fault-analytics-slow-daily.png` (8 s response, loading state),
`fault-analytics-no-self-heal.png` (backend healthy again, card still broken),
`fault-receiver-500-scorecard.png`, `fault-receiver-500-polar.png`,
`fault-receiver-null-scorecard.png` (all-null payload renders `—`, no false zeros),
`fault-receiver-huge-lifetime.png` (whole route replaced by the React Router dev screen)

Cross-page consistency: `consistency-livemap-glance.png`

API captures: `recheck-api.txt`


## Appendix E — R4: Alerts, Settings, Health, Setup

## Configuration & operations surfaces (/alerts, /settings, /health, /setup) — findings

Reviewer R4. Stack: demo build at `http://localhost:8090`, 2026-09-20.
Screenshots referenced below live beside this file in `scratchpad/review/r4/`.

### Summary

These four surfaces are the best-reasoned part of the app I have seen: the danger-zone typed-confirmation flow, the rule builder's validation, the per-rule alert-history drill-down and the degraded-payload rendering on Health are all genuinely well built and well tested. Three problems undercut that. First, every "healthy" status on the Health page and every successful decoder connection test renders as invisible text in **both** themes — the headline verdict of the diagnostics page and the one confirmation a first-run owner needs are literally unreadable (R4-01). Second, a save the backend rejects leaves six of the nine Settings sections permanently unsavable until the page is reloaded, because the server's field error feeds the same flag that disables Save (R4-02) — the Enrichment section already documents why that is wrong and does it correctly, so the fix has a precedent in the file next door. Third, the Alerts feature has two contradictory controls for the same thing: Settings presents eight template checkboxes that read as live on/off state, while the Templates gallery creates rules that never tick them and unticking a box never removes the rule it created (R4-03). Beyond those: the Health page throws away a perfectly good cached payload on one failed poll (R4-04), the alert history never updates while you watch it (R4-05), and at phone width the fixed 256 px sidebar leaves 134 px of content with tabs off-screen (R4-06). What works well is listed at the end and should not be regressed.

### Findings

| ID | Page | Severity | Category | Title |
|----|------|----------|----------|-------|
| R4-01 | Health, Settings, Setup | critical | a11y-layout | "OK" status text and decoder-test success are invisible in both themes |
| R4-02 | Settings | high | robustness | A rejected save leaves the section permanently unsavable |
| R4-03 | Settings + Alerts | high | consistency | Two contradictory controls for alert templates; unticking never removes a rule |
| R4-04 | Health | high | robustness | One failed poll replaces the whole page with an error and discards the cached payload |
| R4-05 | Alerts | high | usefulness | The alert history never updates while it is on screen |
| R4-06 | all four | high | a11y-layout | At phone width the sidebar leaves 134 px of content; tabs and buttons are off-screen |
| R4-07 | Alerts | medium | robustness | No page state is in the URL: no deep link, refresh resets, `?rule_id=` ignored |
| R4-08 | Alerts | medium | usefulness | History rows name the rule twice and identify the aircraft only by hex |
| R4-09 | Alerts | medium | usefulness | Rule cards describe a watchlist condition as "on watchlist 1" |
| R4-10 | Alerts | medium | consistency | Deleting a rule (and its recorded alerts) is guarded only by `window.confirm` |
| R4-11 | Settings | medium | correctness | "Metadata last updated: never" is asserted while the status is still loading, and after it fails |
| R4-12 | Settings, Health | medium | correctness | Time-only formatter used for values that are routinely days or months old |
| R4-13 | Settings, Alerts | medium | consistency | The units setting is ignored by every configuration and rule input |
| R4-14 | Health | medium | consistency | Metadata sources shown by raw internal name, unlike Settings |
| R4-15 | Setup | medium | robustness | A browser refresh mid-wizard silently discards everything entered |
| R4-16 | Setup | medium | correctness | The Alerts step says the rule engine has not arrived yet |
| R4-17 | Health | low | usefulness | Live events card: raw consumer names, and "shed" means two things on one page |
| R4-18 | Health | low | usefulness | The Version tile drops the frontend and API versions SPEC §67 asks for |
| R4-19 | all four | low | correctness | Raw browser/transport strings surfaced as user-facing error text |
| R4-20 | Alerts | low | correctness | Placeholder plurals in rule descriptions: "1 time(s)", "airframe(s)" |
| R4-21 | Setup, Health | low | a11y-layout | Location step errors shown before any input; long decoder errors overflow their tile |

---

#### R4-01 — "OK" status text and decoder-test success are invisible in both themes

- **Page / surface:** `/health` (every healthy status pill), `/settings` → Decoder → Test connection, `/setup` → Decoder step → Test connection.
- **Severity:** critical
- **Category:** a11y-layout
- **Evidence:** `text-accent-foreground` is used as an *on-surface* text colour in five places that do not also set `bg-accent`. `--accent-foreground` is defined as the text colour that sits **on** the accent fill: `oklch(0.145 0.03 250)` in dark, `oklch(0.99 0.01 195)` in light (`frontend/src/index.css:42,93`). Rendered on a card (`oklch(0.185 …)` dark / `oklch(0.995 …)` light) it is a lightness delta of 0.04 and 0.005 respectively — invisible.
  - `dark-desktop-health.png` / `light-desktop-health.png`: the overall verdict pill next to "Receiver" is a **blank rounded rectangle**; so are Decoder "Connected" (×2), Shutdown recovery "Intact", metadata "Imported", Live events "Keeping up".
  - `setup-decoder-success-dark.png` / `setup-decoder-success-light.png`: with a successful test injected, "Connected — found readsb, 37 aircraft (24 with positions)." is unreadable. Measured in the page: `{"text":"Connected — found readsb, 37 aircraft (24 with positions).","color":"oklch(0.145 0.03 250)","bg":"oklch(0.185 0.022 250)","cls":"text-accent-foreground"}`
  - `settings-decoder-success-invisible.png`: identical in Settings.
  - The icon is inside the pill and inherits the same colour, so SPEC §80's "never colour alone" protection does not save it — icon *and* word both vanish.
- **Expected:** the single most important element on the diagnostics page ("Healthy") and the one confirmation a first-run owner gets ("Connected — found readsb…") must be legible in both themes at WCAG AA.
- **Proposed fix:** add an on-surface success token (e.g. `--success-on-surface`, the mirror of the existing `--accent` on-surface usage `index.css:28-30` already discusses) and use it in `frontend/src/features/health/components/StatusPill.tsx:26`, `frontend/src/features/notifications/components/NotificationPermissionStatus.tsx:83`, `frontend/src/features/setup/steps/DecoderStep.tsx` (success `<p>`) and `frontend/src/features/settings/sections/DecoderSection.tsx` (`testResult.ok` branch). Add a contrast assertion to the existing visual suite so the pair cannot drift again. Estimate: S.
- **Suggested agent:** sonnet

#### R4-02 — A rejected save leaves the section permanently unsavable

- **Page / surface:** `/settings` — Receiver, Decoder, Units & time, Display, Alerts, Retention (6 of 9 sections).
- **Severity:** high
- **Category:** robustness
- **Evidence:** injected a 422 on `PUT /api/internal/config` with `detail:[{loc:["display_radius_nm"],msg:"Input should be greater than 0"}]`, then edited the Display section:
  ```
  save enabled before attempt: true
  save enabled after 422: false
  save enabled after typing a new valid value: false
  ```
  (`settings-422-deadend.png`, `settings-422-display.png`.) The per-field rendering itself is excellent — the message lands under the right input, `aria-invalid="true"`, `aria-describedby` wired, the typed value is kept, a second injected error on `map.range_ring_radii_nm` landed on the right field too. But `DisplaySection.tsx` folds the *server* message into the same variable that gates the button (`displayRadiusError = validateDisplayRadius(...) ?? fieldErrors.display_radius_nm`, then `hasBlockingError = Boolean(displayRadiusError ?? radiiError)`), and `mutation.error` is only cleared by the next `mutate()` — which the disabled button makes impossible. Only a page reload recovers. The same shape is in `ReceiverSection.tsx`, `DecoderSection.tsx` (`fieldsValid`), `UnitsTimeSection.tsx`, `AlertsSection.tsx`, `RetentionSection.tsx`.
  `EnrichmentSection.tsx:68-71` already gets this right and says why in a comment: *"a server-side message for the same field is still shown, but never disables the button — a rejection the user cannot see the cause of would otherwise leave the section unsavable until an unrelated edit."*
- **Expected:** a rejected save shows the reason and lets the user correct and retry.
- **Proposed fix:** in each of the six sections, keep the server message for display but derive `hasBlockingError` from the client-side validators only — exactly the `budgetBoundsError` / `budgetError` split `EnrichmentSection.tsx` uses. Better still, lift that split into a small shared helper in `frontend/src/features/settings/lib/errors.ts` (e.g. `fieldMessage(client, server)` returning `{message, blocking}`) so the next section cannot re-derive it wrongly. Add a test per section asserting Save is re-enabled after a 422 plus an edit. Estimate: M.
- **Suggested agent:** sonnet

#### R4-03 — Two contradictory controls for alert templates; unticking never removes a rule

- **Page / surface:** `/settings` → Alerts ("which built-in templates are enabled") and `/alerts` → Templates.
- **Severity:** high
- **Category:** consistency (with a usefulness/correctness edge)
- **Evidence:** the two surfaces are backed by different state and never reconcile.
  - Added a rule from the Templates gallery ("Government aircraft" → "Add rule"). The card correctly flipped to "Added" (`alerts-templates-after-add.png`), a live rule appeared on the Rules tab — and the config was unchanged: `config.alerts.enabled_templates after gallery add: ["emergency_squawk","military","first_ever"]`. So Settings → Alerts still shows "Government aircraft" **unticked** (`settings-alerts-templates.png`) while a Government rule is enabled and firing.
  - The reverse is worse: `AlertService.apply_enabled_templates` (`backend/src/flightsite/alerts/service.py:216-299`) only ever *creates* rules — there is no delete path. Unticking "Military aircraft" in Settings, saving, and being told "Saved" removes the key from `config.yaml` and leaves the Military rule enabled and alerting. (I did not run that mutation on the shared stack; the code has no branch that could do otherwise, and the docstring confirms the one-way semantics.)
  - The section description — "How far alerts consider aircraft, and which built-in templates are enabled" — states the property that does not hold.
- **Expected:** one place to manage templates, or two places that agree. A checkbox labelled "enabled" must reflect and control whether the thing is enabled.
- **Proposed fix:** make the Templates gallery the single surface (it already resolves "added" from real rule provenance, which is the honest source) and replace the checkbox list in `frontend/src/features/settings/sections/AlertsSection.tsx` with the alert radius field plus a link to `/alerts` → Templates. Keep `alerts.enabled_templates` as the wizard's first-run seed only, and say so in the section that still writes it. If the checkboxes must stay, they have to read from the rule list and their unticking must disable (not delete) the rule — a backend change in `alerts/service.py`. Estimate: M (link-out) / L (two-way sync).
- **Suggested agent:** opus (touches alert rule lifecycle and a config/DB contract)

#### R4-04 — One failed poll replaces the whole page with an error and discards the cached payload

- **Page / surface:** `/health`
- **Severity:** high
- **Category:** robustness
- **Evidence:** loaded `/health` normally, waited for a full render, then started aborting `GET /api/v1/diagnostics`. Within one 10 s poll cycle every card vanished and the page became a single red line (`health-stale-after-abort.png`):
  ```
  generated before: Generated 2026-09-20 21:43 · refreshes automatically.
  generated after 35s of aborted polls: undefined
  while failing, page shows: ERROR PAGE (cards gone)
  after failure clears: recovered without reload
  ```
  Cause: `HealthPage.tsx:63` — `if (isError || data === undefined)` returns the error view, although TanStack still holds the last good payload in `data`. Recovery when the backend returns is clean (no reload needed), which is good; the blanking is the problem. There is also no Retry control here, unlike `SettingsPage.tsx:41` which has one.
- **Expected:** this page exists to be readable *while* things are going wrong. It should keep the last payload, mark it stale ("last updated 40 s ago — refresh failing"), and only show the full-page error when it has never loaded. The footer already prints `Generated …` and claims "refreshes automatically" — that claim must become false visibly when refreshing stops.
- **Proposed fix:** in `frontend/src/features/health/HealthPage.tsx`, gate the error view on `data === undefined` only, and render a warning banner when `isError && data` with the age of `data.generated_at` and a Retry button. Re-word the footer to state the age rather than the promise. Test the "loaded then failing" path in `HealthPage.test.tsx`. Estimate: S.
- **Suggested agent:** sonnet

#### R4-05 — The alert history never updates while it is on screen

- **Page / surface:** `/alerts` → History
- **Severity:** high
- **Category:** usefulness (robustness)
- **Evidence:** sat on the History tab for 70 s on the demo stack:
  ```
  history top row before:    2026-09-20 21:47 | Info | Rule: First-ever aircraft | 46BF08 | ...
  history top row after 70s: 2026-09-20 21:47 | Info | Rule: First-ever aircraft | 46BF08 | ...
  newest match id before/after: 104 109
  history auto-updated: false
  ```
  Five alerts fired into the database while the screen showed none of them. `useAlertMatchesQuery` (`frontend/src/lib/api/alertMatches.ts`) sets no `refetchInterval`, the global default is `staleTime: 30_000` with `refetchOnWindowFocus: false` (`frontend/src/lib/queryClient.ts`), and nothing invalidates the key when the app shell's live socket delivers an alert — even though ADR-0015 puts that socket in the shell precisely so alerts reach any route.
- **Expected:** the record of alerts, on the alerts page, should show an alert that just fired — either by polling while `offset === 0`, or by invalidating `alertMatchesQueryKeys` from the live-alert handler, or at minimum by offering a "3 new alerts — show" affordance so the user knows the list is not the whole truth.
- **Proposed fix:** in `frontend/src/features/alerts/components/AlertHistorySection.tsx` pass `refetchInterval: offset === 0 && severity === "" ? 10_000 : false`, or (better) invalidate the list key from the existing live alert dispatcher in `frontend/src/features/notifications/` when a match arrives. Keep `keepPreviousData` so paging still does not blank. Estimate: S–M.
- **Suggested agent:** opus (touches live-state plumbing)

#### R4-06 — At phone width the sidebar leaves 134 px of content; tabs and buttons are off-screen

- **Page / surface:** all four routes at 390×844.
- **Severity:** high
- **Category:** a11y-layout
- **Evidence:** measured in the page at 390 px:
  ```
  /alerts   {"sidebar":256,"mainWidth":134,"mainScrollWidth":333,
             "clipped":["BUTTON:Rules","BUTTON:Templates","BUTTON:History","BUTTON:Create watchlist"]}
  /settings {"sidebar":256,"mainWidth":134,"mainScrollWidth":231,
             "clipped":["A:Health & diagnostics","BUTTON:Test connection","BUTTON:Detect from browser",
                        "BUTTON:Update Aircraft Metadata","H2:Danger zone"]}
  /health   {"sidebar":256,"mainWidth":134,"mainScrollWidth":285,
             "clipped":["A:Receiver","H2:Stored data","H2:Metadata datasets","A:Update metadata in Settings"]}
  ```
  See `dark-phone-alerts-rules.png` (three of the four Alerts tabs are past the right edge; the rule card's Delete button is cut in half) and `dark-phone-settings.png`. `components/shell/AppShell.tsx` renders `<aside>` + `<main>` in a flex row and `components/shell/Sidebar.tsx` is a fixed `w-64`/`w-16` driven only by a user-toggled `sidebarCollapsed` store value — there is no breakpoint and no drawer, so a phone visitor lands on the 256 px sidebar every time.
  Note: the setup wizard renders *outside* the shell and is fine at 390 px (`setup-dark-phone-welcome.png`, `setup-dark-phone-location.png`, no overflow).
- **Expected:** rubric — "phone (390×844), no horizontal scroll, nothing clipped, touch targets usable". PRODUCT §2 targets a Pi appliance whose owner checks it from a phone.
- **Proposed fix:** in `components/shell/Sidebar.tsx` / `AppShell.tsx`, default to the collapsed rail below `md` and make the expanded state an overlay drawer at that width (`fixed inset-y-0 z-40` + scrim), leaving `<main>` full width. Cross-cutting — likely shared with R1–R3's findings, so it belongs in the fix slice once, not per page. Estimate: M.
- **Suggested agent:** sonnet

#### R4-07 — No page state is in the URL: no deep link, refresh resets, `?rule_id=` ignored

- **Page / surface:** `/alerts` (tab selection and the per-rule history filter).
- **Severity:** medium
- **Category:** robustness
- **Evidence:**
  ```
  url after choosing History tab:        http://localhost:8090/alerts
  tab selected after reload:             Watchlists
  tab after deep link ?rule_id=1:        Watchlists
  url while filtered to a rule:          http://localhost:8090/alerts
  ```
  Browser Back after switching tabs leaves the page entirely. `pages/AlertsPage.tsx` documents the choice ("The filter is not in the URL because none of this page's state is"), which makes it deliberate and consistent — but consistent at the wrong end: the page has four sections, one of which is a paged, filtered record, and none of it survives F5 or can be shared. The rubric asks for deep link + refresh and query-param round-trips on every route in scope, and the brief names `?rule_id=` specifically.
- **Expected:** `/alerts?tab=history&rule_id=3` selects that tab and that filter; refresh and Back/Forward preserve them.
- **Proposed fix:** move `activeTabId` and `historyRule` in `frontend/src/pages/AlertsPage.tsx` into `useSearchParams` (tab id + `rule_id`), resolve the rule's name from the already-cached rule list when only the id is present, and have `AlertHistorySection` put `severity`/`offset` there too. Estimate: M.
- **Suggested agent:** sonnet

#### R4-08 — History rows name the rule twice and identify the aircraft only by hex

- **Page / surface:** `/alerts` → History
- **Severity:** medium
- **Category:** usefulness
- **Evidence:** a row renders as `2026-09-20 21:44 | High | Rule: Military aircraft | D25F97 | Military aircraft` (`alerts-history-filter-military.png`). The stored `reason` is literally `"Rule: " + rule.name` (`backend/src/flightsite/alerts/model.py:240-250` documents this), and `sourceLabel()` then prints `rule.name` again — so two of the five fields on every row are the same string. Meanwhile the API payload carries `sighting_id` and the row shows no callsign, registration, type, altitude or distance; the aircraft is a bare hex code. SPEC §48 requires a notification to carry "callsign/tail, aircraft type, classification, altitude, distance, match reason", and the history is where a user goes when they missed the notification.
- **Expected:** one identity line a human recognises ("VIPER588 · C17 · 05-5153"), the rule named once, and what was actually true at the time (altitude/distance).
- **Proposed fix:** either drop `sourceLabel` when `match.rule !== null` and keep only the `reason` (S, cosmetic), or — better — extend `AlertMatch` in `backend/src/flightsite/api/` with the callsign/type/altitude/distance snapshot already available on the sighting it points at, and render it in `frontend/src/features/alerts/components/AlertHistorySection.tsx`, linking the row to `/sightings/{sighting_id}` as well as `/aircraft/{icao}`. Estimate: M.
- **Suggested agent:** opus (backend query + cross-page contract)

#### R4-09 — Rule cards describe a watchlist condition as "on watchlist 1"

- **Page / surface:** `/alerts` → Rules (rule card "Matches aircraft that are").
- **Severity:** medium
- **Category:** usefulness / correctness
- **Evidence:** created a rule whose only condition was membership of the watchlist named "R4 probe list". The card rendered: `R4 watchlist rule | Interesting | Enabled | … | Matches aircraft that are | on watchlist 1` (`alerts-rule-watchlist-describes.png`). Source: `backend/src/flightsite/alerts/model.py:259` — `phrases.append(f"on watchlist {self.watchlist_id}")`. The builder resolves the name when *editing* (the `<select>` shows "R4 probe list"), so the card is the only place that regresses to the id. On an install with several watchlists this is unreadable, and a deleted-then-recreated watchlist makes the number meaningless.
- **Expected:** "on watchlist R4 probe list" — the same vocabulary the builder uses.
- **Proposed fix:** the backend cannot resolve the name without joining watchlists into the rule serializer; the cheaper fix is client-side — in `frontend/src/features/alerts/components/RuleCard.tsx`, take the already-fetched watchlist list (`useWatchlistsQuery`, already loaded by the builder) and substitute the name for `rule.conditions.watchlist_id` when rendering `describes`, falling back to the id for a watchlist that no longer exists. Estimate: S.
- **Suggested agent:** sonnet

#### R4-10 — Deleting a rule (and its recorded alerts) is guarded only by `window.confirm`

- **Page / surface:** `/alerts` → Rules → Delete; `/alerts` → Watchlists → Delete.
- **Severity:** medium
- **Category:** consistency / robustness
- **Evidence:** the delete guard is a native browser dialog:
  ```
  dialog: confirm "Delete “R4 probe rule (edited)”? The alerts it has already recorded are deleted with it."
  dialog: confirm "Delete \"R4 probe list\" and all 1 of its entries? This cannot be undone."
  ```
  (`RuleCard.tsx:handleDelete`, `WatchlistCard.tsx`.) This is an unstyled, theme-ignoring dialog that some browsers let a user suppress for the session ("prevent this page from creating additional dialogs") — after which Delete becomes a one-click irreversible action that also destroys alert history. Two rooms away, the same app ships `ConfirmDangerDialog` with a typed phrase, a focus trap, focus restoration and backup guidance, and uses it for actions that are *less* destructive per click (`settings-danger-clear-metadata.png`).
- **Expected:** one destructive-confirmation pattern across the app; history-destroying deletes should use it.
- **Proposed fix:** reuse `frontend/src/features/settings/components/ConfirmDangerDialog.tsx` from `RuleCard.tsx` and `WatchlistCard.tsx` (a plain confirm variant without the typed phrase is fine for a single rule; keep the "the alerts it has already recorded are deleted with it" sentence as the body). Estimate: S.
- **Suggested agent:** sonnet

#### R4-11 — "Metadata last updated: never" is asserted while the status is still loading, and after it fails

- **Page / surface:** `/settings` → Aircraft Metadata.
- **Severity:** medium
- **Category:** correctness
- **Evidence:** delayed `GET /api/internal/metadata/status` by 8 s, then separately made it 500:
  ```
  while loading: "Metadata last updated: never | Update Aircraft Metadata | [OpenSky toggle]"
  on 500:        "Metadata last updated: never | Update Aircraft Metadata | Could not load metadata source status."
  ```
  (`settings-metadata-loading.png`, `settings-metadata-500.png`.) `MetadataSection.tsx` reads `statusQuery.data?.sources ?? []` and hands the empty array to `overallMetadataAge`, which correctly returns `null` for "no source has ever succeeded" — but the component has no loading branch and no source-card placeholder, so "I do not know yet" and "it has never run" print the same word. On the 500 path the "never" line sits directly above the error that says the status could not be read. The module's own docstring insists "a fresh install where nothing has ever run reads as `null` rather than a fabricated zero"; the UI fabricates it anyway.
- **Expected:** §2.7 null/unknown semantics — absence, not a guess. "Checking…" while pending, "Unknown — could not read source status" on error.
- **Proposed fix:** in `frontend/src/features/settings/sections/MetadataSection.tsx`, pass `statusQuery.isPending`/`isError` into `MetadataAgeLine` and render "Checking…" / "Unknown" instead of "never"; add skeleton source cards while pending. Also disable "Update Aircraft Metadata" while the status is unknown, since `isBusy` is currently `false` in that state. Estimate: S.
- **Suggested agent:** sonnet

#### R4-12 — Time-only formatter used for values that are routinely days or months old

- **Page / surface:** `/settings` → Aircraft Metadata; `/health` → Recent errors.
- **Severity:** medium
- **Category:** correctness
- **Evidence:** the metadata section prints `Metadata last updated: 21:33:19 (17m ago)` and per source `Last updated 21:33:19 · 17m ago` via `formatReceiverLocalTime` (`features/aircraft-detail/lib/format.ts:241`), which emits **hour:minute:second with no date**. Metadata is imported manually and is commonly weeks old, at which point the line reads "Metadata last updated: 03:14:22 (23d ago)" — a wall-clock time for a day nobody can name. The sibling `formatReceiverLocalDateTime` exists for exactly this and says so in its docstring ("for contexts where the instant may be months or years old"). `RecentErrorsSection.tsx` has the same problem: on a long-uptime Pi, an ingestion error from three days ago is stamped `14:02:11` with no date.
- **Expected:** a date whenever the value can be older than today.
- **Proposed fix:** swap to `formatReceiverLocalDateTime` in `frontend/src/features/settings/sections/MetadataSection.tsx` (`MetadataAgeLine` and `SourceCard`) and in `frontend/src/features/health/components/RecentErrorsSection.tsx`. The relative age ("23d ago") stays as the secondary. Estimate: S.
- **Suggested agent:** sonnet

#### R4-13 — The units setting is ignored by every configuration and rule input

- **Page / surface:** `/settings` (Display, Alerts, Receiver) and `/alerts` → Rules.
- **Severity:** medium
- **Category:** consistency
- **Evidence:** switched Units to "Metric (km / m / km/h)", saved, confirmed `units: metric` in the config, then read the labels back (`settings-units-metric.png`, `alerts-builder-metric-units.png`):
  ```
  Display radius (nm) · Alert radius (nm, optional) · Antenna height (ft, optional)
  Range ring radii (nm, comma-separated)
  builder: "At least (nm)" "Within (nm)" "At or above (ft)" "At or below (ft)"
  summaries: "...in nautical miles." / "...in feet."
  rule card: "Matches aircraft that are ... within 250 nm"
  ```
  (restored to `aviation` afterwards — verified). The setting *is* honoured elsewhere: `features/aircraft-detail`, `features/analytics`, `features/receiver`, `features/interesting`, and notably `features/notifications/lib/compose.ts`. So a metric user is told "12 km" in the alert notification produced by a rule they had to write in nautical miles, and sets a map radius in nm for a map that reads in km.
- **Expected:** storage and the API stay nm/ft (SPEC, CLAUDE.md) — but the *input* should acknowledge the user's chosen system, at minimum with a live conversion hint.
- **Proposed fix:** cheapest useful version — in `frontend/src/features/alerts/components/ConditionEditor.tsx` and the three Settings sections, append a converted hint under metric ("250 nm ≈ 463 km") using the existing conversion helpers in `features/receiver/lib/format.ts`. Full version: accept metric input and convert in `conditionsToDocument` / the `build*Patch` helpers, with the unit in the label. Estimate: S (hint) / M (bidirectional).
- **Suggested agent:** sonnet

#### R4-14 — Metadata sources shown by raw internal name, unlike Settings

- **Page / surface:** `/health` → Metadata datasets.
- **Severity:** medium
- **Category:** consistency
- **Evidence:** the Health card lists `airports`, `faa`, `mictronics`, `routes`, `demo` in lower case with `N rows` (`health-live-events-card.png`), while Settings renders the same five as "Airports", "FAA", "Mictronics", "Flight routes (VRS)", "Demo" with "18 aircraft" (`settings-metadata-section.png`). The display-name and row-noun maps (`SOURCE_LABELS`, `SOURCE_ROW_NOUNS`) live inside `features/settings/sections/MetadataSection.tsx` and are not shared. Rubric §4: the same concept named the same way across pages.
- **Expected:** "FAA", not "faa"; "18 aircraft", not "18 rows".
- **Proposed fix:** move `sourceLabel` / `rowNoun` out of `MetadataSection.tsx` into a shared module (e.g. `frontend/src/lib/metadata/sources.ts`) and use them from `frontend/src/features/health/HealthPage.tsx`'s Metadata datasets card. While there, point the card's "Update metadata in Settings" link at `/settings#settings-metadata` rather than the top of the page. Estimate: S.
- **Suggested agent:** sonnet

#### R4-15 — A browser refresh mid-wizard silently discards everything entered

- **Page / surface:** `/setup`
- **Severity:** medium
- **Category:** robustness
- **Evidence:** walked the wizard to the Decoder step with a site name, coordinates, antenna height and a decoder endpoint entered, then pressed reload:
  ```
  after reload, step:      Welcome
  after reload, site name: (empty)
  ```
  (`setup-after-reload.png`.) `SetupWizardPage.tsx` holds the entire draft in `useState` with `initializedRef` guarding re-seeding, and the step index is not in the URL, so a refresh, a crash, or an accidental Back-out of the tab costs the whole wizard. Back navigation *within* the wizard is fine — I walked back seven steps and every field was intact ("site name after walking all the way back: R4 Review Site", latitude and antenna height preserved, the skipped-test state preserved) — so this is specifically the reload path.
- **Expected:** an eight-step first-run form on a headless appliance should survive a page refresh.
- **Proposed fix:** persist the draft and `stepIndex` to `sessionStorage` on change in `frontend/src/features/setup/SetupWizardPage.tsx` (wrapped in try/catch; clear on a successful finish), and/or put the step id in the URL as `/setup?step=decoder`. Estimate: S.
- **Suggested agent:** sonnet

#### R4-16 — The Alerts step says the rule engine has not arrived yet

- **Page / surface:** `/setup` → Alerts step (`setup-7-alerts.png`).
- **Severity:** medium
- **Category:** correctness
- **Evidence:** step copy read back verbatim:
  > "Choose which of the built-in interesting-aircraft templates to start with. **These take effect once the alert rule engine arrives**; you can change this anytime from Settings."

  The rule engine shipped (slices 038/041) — the demo stack was firing template-created rules throughout this review. A first-run owner is told the thing they just configured does nothing yet. (`frontend/src/features/setup/steps/AlertsStep.tsx`.)
  Two smaller copy issues on neighbouring steps: the Metadata step says metadata "is downloaded from Settings after setup finishes — nothing to do here", which satisfies SPEC §31's "optional aircraft metadata setup" only by deferring it and never mentions the opt-in OpenSky source; and the Review step summarises templates without saying they become editable rules.
- **Expected:** copy that matches the build.
- **Proposed fix:** reword in `frontend/src/features/setup/steps/AlertsStep.tsx` — "Each one you tick becomes a rule you can retune or switch off on the Alerts page." Add a repo-wide grep for "arrives"/"will be available"/"once … lands" in user-facing strings to the fix slice. Estimate: S.
- **Suggested agent:** sonnet

#### R4-17 — Live events card: raw consumer names, and "shed" means two things on one page

- **Page / surface:** `/health` → Live events (slice 075) and the WebSocket clients tile.
- **Severity:** low
- **Category:** usefulness
- **Evidence:** on a healthy install the card is six near-identical rows (`health-live-events-card.png`):
  ```
  Live events — Shed live events by consumer; a consumer that fell behind resyncs from a snapshot.
  Events published 85,641 | Shed in total 0
  airports 0 shed 0 / 1,024 queued        alerts 0 shed 0 / 2,048 queued
  enrichment 0 shed 0 / 1,024 queued      metadata-cache 0 shed 0 / 2,048 queued
  persistence 0 shed 0 / 4,096 queued     websocket 0 shed 0 / 4,096 queued
  ```
  The names are internal subscriber identifiers, and nothing says what it means for the owner if, say, `metadata-cache` sheds. Worse, the tile four inches above reads "**0 clients shed** since start-up" — the same verb for WebSocket *client* disconnects. The slice-075 comment in `HealthPage.tsx` shows the wording was chosen to fix issue #185's confusion between the browser feed and the persistence queue; it swapped one ambiguity for another. The card correctly disappears on a pre-075 backend, and the degraded rendering is good (`health-degraded-scrolled.png`).
- **Expected:** a card on a "never SSH in" page should say what a number means for the install, in words the owner shares with the rest of the UI.
- **Proposed fix:** in `frontend/src/features/health/HealthPage.tsx`, map subscriber names to owner-facing labels ("Live map feed", "Alert engine", "History writer", "Route enrichment", "Aircraft metadata", "Airport lookups") with a one-line consequence under a shedding one; change the WebSocket tile's secondary to "N client disconnects since start-up"; collapse the per-consumer list behind a disclosure while every consumer reads 0. Estimate: S.
- **Suggested agent:** sonnet

#### R4-18 — The Version tile drops the frontend and API versions SPEC §67 asks for

- **Page / surface:** `/health` → Version tile.
- **Severity:** low
- **Category:** correctness
- **Evidence:** the payload carries all four — `{"backend":"0.8.0","frontend":"0.8.0","api":"v1","schema_revision":"0016"}` — and the tile renders `Version / 0.8.0 / Schema 0016`, i.e. `data.versions.backend` only (`HealthPage.tsx`, Version `StatTile`). SPEC §67 lists "frontend/backend version". The case this matters is exactly the one the tile hides: a browser holding a stale cached bundle against an upgraded backend, where the two numbers differ and the single unlabelled number is ambiguous about which it is.
- **Expected:** both versions, labelled, with the mismatch made visible.
- **Proposed fix:** render `backend` as the value and `Frontend {frontend} · API {api} · Schema {schema_revision}` as the secondary, with a warn pill when `frontend !== backend` ("Reload to update the page"). Estimate: S.
- **Suggested agent:** sonnet

#### R4-19 — Raw browser/transport strings surfaced as user-facing error text

- **Page / surface:** all four routes, on any aborted request.
- **Severity:** low
- **Category:** correctness
- **Evidence:** aborting requests produced, verbatim on screen:
  ```
  Settings → Display save:   "Failed to fetch"            (settings-offline-save.png)
  Alerts → Watchlists:       "Could not load watchlists: Failed to fetch"
  Health:                    "Could not load diagnostics: Failed to fetch FlightSite's backend may be down — check the container logs."
  ```
  The Health sentence also runs two sentences together with no separator after the interpolated message. Everything else about these paths is right — the Display save kept the typed value, Save stayed enabled and the retry worked (`field value kept: 275`, `save still enabled (can retry): true`), and each Alerts tab failed independently without taking the others down (`alerts-rules-500.png`, `alerts-history-500.png`).
- **Expected:** a transport failure reads as "FlightSite's backend is not responding.", not as a `TypeError` message.
- **Proposed fix:** give `frontend/src/lib/api/client.ts` (and the `apiV1Fetch` copies in `alertMatches.ts` / `diagnostics.ts`) a typed `NetworkError` with a written message, and use `error.message` only when it came from the documented envelope. Fix the missing punctuation in `HealthPage.tsx`. Estimate: S.
- **Suggested agent:** sonnet

#### R4-20 — Placeholder plurals in rule descriptions

- **Page / surface:** `/alerts` → Rules (rule card), and anywhere `describes` is echoed.
- **Severity:** low
- **Category:** correctness
- **Evidence:** the shipped "First-ever aircraft" rule describes itself as `seen at most 1 time(s) here`; the rare-type condition produces `type seen on at most N airframe(s) here` (`backend/src/flightsite/alerts/model.py:264-265`, visible on the Rules tab — `alerts-rules-desktop.png`). Rubric §3 calls out plural/zero wording. The builder's own field label for the same idea reads properly ("At most this many sightings here").
- **Expected:** "seen at most once here" / "seen at most 3 times here".
- **Proposed fix:** pluralise in `describe()` in `backend/src/flightsite/alerts/model.py` (`1 → "once"`, `n → "n times"`; likewise "airframe"/"airframes"), and extend the existing describe tests. Estimate: S.
- **Suggested agent:** sonnet

#### R4-21 — Location step errors shown before any input; long decoder errors overflow their tile

- **Page / surface:** `/setup` → Location step; `/health` → Decoder stat tile.
- **Severity:** low
- **Category:** a11y-layout
- **Evidence:**
  - Landing on the Location step of a genuine first run (no stored coordinates) shows two red `role="alert"` messages before the user has typed a character (`setup-2-location.png`): `["Enter a latitude between -90 and 90.","Enter a longitude between -180 and 180."]`. The rule builder explicitly argues the opposite position and is right — "a form that argues while it is being filled in is worse than one that answers when asked" (`RuleBuilderForm.tsx`). The validation itself is correct: `91`, `-91`, `181`, `abc` and `45,5` are all rejected and Next stays disabled for each.
  - On `/health`, a realistic multi-line decoder error rendered into the Decoder tile's `secondary` overflows the card's right edge (`health-degraded.png`); the `HealthCard` version of the same string uses `break-all` and wraps correctly.
  - A failed decoder test with no backend detail renders a dangling colon: `"Unreachable: could not reach http://192.0.2.1:9/data/aircraft.json:"` (`describeConnectionFailure` appends `detail` without checking for an empty string; `setup-3-decoder-failed.png`).
- **Expected:** errors after a field is touched or a step is advanced; long strings wrapped; no trailing punctuation with nothing after it.
- **Proposed fix:** add a `touched` gate in `frontend/src/features/setup/steps/LocationStep.tsx` (the wizard's own `EntryForm` already uses this pattern); add `break-all` + `line-clamp-3` to `StatTile`'s secondary in `frontend/src/features/health/components/HealthCard.tsx`; treat an empty `detail` as absent in `frontend/src/features/setup/lib/decoderTestMessage.ts`. Estimate: S.
- **Suggested agent:** sonnet

---

### What works well — do not regress

**Alerts**
- The rule builder's validation is the best form in the app. Errors appear only after the first submit attempt, the submit button stays enabled so a click *explains* rather than silently refuses, and every message is specific: "Add at least one condition. A rule with none would match every aircraft.", "The minimum must be below the maximum, or the rule can never match.", "Enter distances in nautical miles." Contradictory ranges, non-numeric input and the empty rule were all caught client-side without a round trip.
- A condition kind already in use is removed from the "Add a condition" picker, which makes the document's flatness visible instead of discoverable.
- Edit round-trips exactly: opening a rule re-hydrated name, severity, both range bounds, the classification checkboxes and the enabled flag, and saving changed only what I changed.
- The per-rule history drill-down (issue #98) works end to end, filters server-side, and has three genuinely distinct empty states: "No alerts have fired yet.", "“X” has not fired yet.", "“X” has not fired at this severity." Paging resets correctly when the filter is cleared.
- The template gallery's "added" state is derived from real rule provenance, so deleting a shipped rule re-offers the template; the emergency template is correctly shown as a statement ("Always on") rather than a switch.
- Watchlist entry validation is exact and helpfully worded ("Enter exactly six hex digits (e.g. 'ae1463')."), and the live match count updated within seconds of adding an entry.
- Every Alerts tab fails independently: a 500 on rules left the "New rule" button usable and the other tabs untouched.

**Settings**
- Per-field 422 mapping is exact, including nested paths (`map.range_ring_radii_nm`), with `aria-invalid` and `aria-describedby` correctly wired and the typed value preserved.
- Secrets are handled correctly: the key input is `type="password"`, empty on load, with "Not configured" / "•••••••• (configured — leave blank to keep)" placeholders; the config payload carries `aerodatabox_api_key: null` and a separate `secrets_set` boolean, and an untouched field never overwrites a stored key.
- The danger-zone dialogs are exemplary: confirm disabled until the phrase matches character-for-character (partial and wrong-case both rejected), focus moved into the dialog and restored to the opening button on cancel, Escape and scrim both close, and the `docker compose exec … flightsite-backup create` suggestion appears in front of *both* actions. Cancelling ran nothing.
- Restart-required badges are accurate and use one shared component and one wording: section-level on Receiver, Decoder and Retention; field-level on the timezone and the OpenSky toggle; correctly absent from Display, Alerts, Notifications and Enrichment, all of which are genuinely read late or rebuilt on save (verified against `app.py`'s `_display_radius`/`_alert_radius` late-read probes and `internal.py`'s `_apply_live_settings`).
- Failed saves keep the section's edits and stay retryable; each section saves independently, so one rejection never blocks another.

**Health**
- Degraded rendering is strong: a `down` decoder, a failed integrity check with its quick-check rows, error lists and counters all render clearly and the warn/bad pills are legible (`health-degraded.png`).
- The page recovers on its own when the backend comes back — no reload needed.
- The unknown/idle tones are a real design decision, not a fallback: "Not yet checked", "Never imported", "Not yet run" are all distinct from healthy and from broken.
- The notifications card is the right shape — it reports the browser permission and links rather than prompting, and says what still happens when blocked ("Alerts are still recorded in the activity feed and alert history").
- The Live events card correctly disappears against a backend that does not publish `live_events` rather than rendering zeroes.

**Setup wizard**
- Step gating is right: Next is disabled until the step is valid, and the Decoder step accepts either a successful test *or* an explicit "Skip test — decoder may be offline", with the skip cleared automatically the moment a tested field is edited.
- Back navigation preserves everything, including the decoder test/skip state, across all seven steps.
- Keyboard-only operation works: tab order on a valid step is progress-step → field → Next, the focus ring is present, and Enter on Next advances.
- The Review step is an honest summary and correctly reports "Connection test: Skipped".
- The wizard renders outside the app shell and is the one surface in my scope that is usable at 390 px.
