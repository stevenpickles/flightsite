# FlightSite API Design

This document defines the FlightSite HTTP/WebSocket API: the **documented, supported,
read-only external API** (`/api/v1/...`) and the **internal mutation API**
(`/api/internal/...`) used by the FlightSite frontend.

Governing requirements: `planning/SPEC.md` §74 (read-only external API), §75 (no
authentication), §21–22 (position source and provenance), §29 (secrets), §15 (UTC).
Delivery is mapped to roadmap slices in `planning/roadmap.yaml`; the slice that
delivers each endpoint group is noted throughout.

---

## 1. API Philosophy

- **The supported external API is read-only in v1.** Everything under `/api/v1/` is
  safe to expose to other LAN tools (dashboards, scripts, Home Assistant users doing
  their own integration). It never mutates application state.
- **REST for state, WebSocket for live flow.** Query/history/analytics resources are
  REST. The live aircraft picture and activity stream are delivered over one
  WebSocket endpoint as snapshot + deltas.
- **The internal API is not a contract.** `/api/internal/` exists because the
  frontend needs mutations (setup, config, watchlists, alert rules, metadata update,
  reset). It is undocumented externally, unsupported for third parties, and may
  change at any time without notice, including within a minor release. It is not part
  of the v1 external API contract (SPEC §74).
- **No authentication in v1.** FlightSite assumes a trusted-LAN deployment (SPEC
  §75). Neither API surface performs authentication; `docs/SECURITY.md` documents why
  direct public exposure is unsupported.
- **Honesty over completeness.** Absent data is `null`, never fabricated. Enriched or
  inferred values always carry provenance (§ 2.6).

## 2. Conventions

### 2.1 Base URLs and versioning

- External: `/api/v1/` — version prefix is part of the contract. Breaking changes
  require `/api/v2/` (post-v1 concern).
- Internal: `/api/internal/` — unversioned, may change freely.
- The frontend container proxies `/api/` to the backend; both surfaces share one
  FastAPI app.

### 2.2 Time

All timestamps are UTC, ISO-8601 with `Z` suffix and millisecond precision where
relevant: `"2026-08-31T14:03:22.418Z"`. Durations are integer seconds. The API never
returns receiver-local time; local rendering is the client's job (configured timezone
is available from the receiver info endpoint).

### 2.3 Units

The API returns **canonical aviation-native units** everywhere:

| Quantity | Unit | Field suffix convention |
|---|---|---|
| Altitude | feet | `altitude_ft` |
| Speed | knots | `ground_speed_kt` |
| Distance/range | nautical miles | `distance_nm`, `range_nm` |
| Vertical rate | feet/minute | `vertical_rate_fpm` |
| Bearing/heading/track | degrees true | `bearing_deg`, `track_deg` |
| Signal strength | dBFS (as reported by decoder) | `rssi_db` (instantaneous), `rssi_avg_db` / `rssi_peak_db` / `rssi_min_db` (aggregates) |

Metric display mode is a **client-side conversion**; the API payload does not change
with the configured unit mode.

### 2.4 Pagination, sorting, filtering

List endpoints use offset pagination:

```
GET /api/v1/aircraft?limit=50&offset=100&sort=last_seen&order=desc
```

- `limit` (default 50, max 500), `offset` (default 0).
- `sort` accepts documented column keys per endpoint; `order` is `asc`|`desc`.
- **Rows whose sort value is `null` come last, in both directions.** §2.7 makes a
  missing value the absence of an answer rather than the smallest one, so ascending
  by `closest_approach_nm` puts the aircraft that genuinely came closest on the first
  page, not the ones that have no closest approach. Every sort also carries a stable
  final tiebreak (`icao24` or `id`, always ascending) so paging cannot repeat or skip
  a row.
- Filters are endpoint-specific query params (documented per endpoint).
- Responses wrap items in an envelope:

```json
{
  "items": [ ... ],
  "total": 14382,
  "limit": 50,
  "offset": 100
}
```

- `total` MAY be `null` or approximate — an exact filtered `COUNT(*)` per page is too
  expensive at multi-year scale on Pi-class hardware. Clients must not rely on
  `total` for anything beyond display. In practice:

  | Endpoint | `total` |
  |---|---|
  | `/aircraft` | exact |
  | `/sightings`, `/aircraft/{icao}/sightings`, `/activity`, `/alerts/matches` | always `null` |

- **Two list endpoints do not paginate at all**: `/aircraft/current` and
  `/aircraft/interesting` describe the live picture, which is already bounded by what
  is in the air right now. They return `items` and `total` only — no `limit` or
  `offset` in the envelope, and neither is accepted as a parameter.

### 2.5 Error envelope

Non-2xx responses use a single shape:

```json
{
  "error": {
    "code": "not_found",
    "message": "No aircraft with ICAO a1b2c3",
    "detail": null
  }
}
```

`code` is a stable machine-readable slug (`bad_request`, `not_found`,
`validation_error`, `conflict`, `unavailable`, `internal_error`). Validation errors
put field details in `detail`. Secrets never appear in error output.

### 2.6 Provenance representation

Objects that carry enriched/derived fields include a `provenance` map naming the
source of each non-decoder field group (SPEC §22):

```json
{
  "operator": "Delta Air Lines",
  "registration": "N302DN",
  "route": {
    "origin": "KATL",
    "origin_name": "Hartsfield Jackson Atlanta International Airport",
    "destination": "KSLC",
    "destination_name": "Salt Lake City International Airport"
  },
  "provenance": {
    "operator": "mictronics",
    "registration": "faa",
    "route": "aerodatabox",
    "nearest_airport": "heuristic",
    "distance_nm": "derived"
  }
}
```

Provenance values: `decoder` | `derived` | `mictronics` | `faa` | `opensky` | `vrs` |
`aerodatabox` | `heuristic`. `opensky` appears only on installs that enabled the
opt-in OpenSky source (`metadata.opensky_enabled`, default off — ADR-0013), and only
on `operator`, `owner`, `model` or `manufacture_year`, the four fields it may fill.
Fields without an entry are decoder-direct. Position source is a
separate, always-present field (§ 3.3) because it is safety-relevant display state,
not enrichment.

**`provenance.route` is one of exactly two values** ([ADR-0016](adr/0016-offline-route-directory.md)):

| Value | Meaning |
|---|---|
| `vrs` | The offline route directory — Virtual Radar Server standing data (CC0), imported locally by the "Update Aircraft Metadata" action and consulted first. No third party was contacted for this route, and the install can see which snapshot it came from. Community-corrected data, so it can be out of date until an aircraft's own behaviour contradicts it. |
| `aerodatabox` | A live lookup against AeroDataBox, made because the directory did not know this callsign. Requires the user's own API key. |

Both are **reported** routes and both are distinct from the locally inferred airport
context beside them (SPEC §28, § 3.3's `nearest_airport`), which is FlightSite's own
inference and never written into `route`. The entry is absent entirely when there is no
route to attribute — § 2.6 entries name the source of a *value*, and two nulls have no
source.

The `route` block carries four members: `origin` and `destination` (the idents the
source reported) and `origin_name` and `destination_name` (those idents
looked up in the **local** `airports` table imported by slice 027 — never a second
provider call). All four are always present. A name is `null` when the ident is
`null`, and also whenever the local dataset does not carry that ident — including on
every install until an airports import has run, where every name is `null` while the
idents are unaffected. Names carry no provenance entry of their own: `route` already
names where the route came from, and a name is a local label for it rather than a
second claim. Clients render the name when there is one and fall back to the ident.

### 2.7 Null / Unknown semantics

- Missing data is `null` in JSON. The UI renders `Unknown`.
- FlightSite never substitutes guesses for nulls. A classification with weak evidence
  is `"unknown"`, not a best guess (SPEC §39).
- Empty collections are `[]`, not `null`.

### 2.8 Canonical vocabulary

These enum values and field names are canonical across the API, `docs/DATA_MODEL.md`,
and the roadmap. Any document using different spellings is wrong and must be fixed.

| Concept | Canonical form |
|---|---|
| Position source | `position_source`: `"adsb"` \| `"mlat"` \| `"none"` \| `"other"` (SPEC §21; `none` = tracked without a valid position / Mode S) |
| Signal strength (instantaneous) | `rssi_db` (dBFS) |
| Signal strength (aggregates) | `rssi_avg_db`, `rssi_peak_db`, `rssi_min_db` (dBFS) |
| Sighting closure | `closure_reason`: `"gap_timeout"` \| `"shutdown_recovery"` \| `"data_reset"` |
| Closest range | `closest_approach_nm` (per-sighting closest and aircraft lifetime closest) |
| Farthest range | `max_range_nm` (per-sighting maximum and aircraft lifetime farthest detection) |
| Provenance values | `decoder` \| `derived` \| `mictronics` \| `faa` \| `opensky` (opt-in, default off) \| `vrs` \| `aerodatabox` \| `heuristic` |
| Route source | `route_source` / `provenance.route`: `"vrs"` (offline directory) \| `"aerodatabox"` (online provider) |
| Alert severity | `info` \| `interesting` \| `high` \| `critical` |
| Decoder emergency state | `decoder_emergency`: `"general"` \| `"lifeguard"` \| `"minfuel"` \| `"nordo"` \| `"unlawful"` \| `"downed"` (slice 086; no emergency is `null`) |
| Emitter category | `emitter_category`: `"A0"`–`"D7"` (slice 086; ADS-B emitter category set letter + digit) |
| Emergency source | `emergency_source`: `"squawk"` \| `"decoder"`; `emergency_kind`: the `decoder_emergency` vocabulary (slice 086) |

### 2.9 Path parameter constraints

`{icao}` path parameters are constrained by a `^[0-9a-f]{6}$` validator (lowercase
6-hex-char ICAO 24-bit address). Within the `/api/v1/aircraft/` namespace, the words
`current` and `interesting` are **reserved** and can never collide with an `{icao}`
value; this reservation is part of the documented contract.

### 2.10 OpenAPI

The backend serves OpenAPI for the external surface at `/api/v1/openapi.json`
(interactive docs at `/api/v1/docs`). Internal routes are excluded from the published
schema. Delivered incrementally starting with slice 010.

---

## 3. External Read-Only API (`/api/v1`)

### 3.1 Service health — slice 001

| Method & path | Purpose |
|---|---|
| `GET /api/v1/health` | Liveness: process is up. |
| `GET /api/v1/ready` | Readiness: migrations applied, ingestion loop started. |

```json
{
  "status": "ok",
  "version": "0.1.0",
  "uptime_s": 86211,
  "counters": {
    "ingestion_failures": 0,
    "db_errors": 0,
    "enrichment_failures": 0,
    "ws_disconnects": 0,
    "live_events_dropped": 0
  },
  "demo": false
}
```

`counters` are process-lifetime totals, reset on restart. `demo` reports whether the
backend is running against the simulated decoder rather than real hardware.

`/ready` reports per-subsystem readiness and uses the same body shape on both `200`
and `503`, returning `503` while any subsystem is still false:

```json
{ "ready": true, "subsystems": { "database": true, "ingestion": true } }
```

`subsystems` lists the subsystems that actually registered, so its keys vary with how
the install is running. In particular, a **first-run install reports only
`{"database": true}`** — with no configuration saved there is no decoder to connect
to, ingestion never starts, and it therefore never registers. Treat a missing key as
"not applicable to this install", not as a failure; `ready` is the field to branch on.

Decoder health deliberately never affects readiness. A decoder that goes away leaves
the service ready, because reporting not-ready would invite an orchestrator to
restart a backend whose only problem is on the other end of the network.

### 3.2 Receiver info — slice 010

`GET /api/v1/receiver`

Non-secret receiver identity and configuration snapshot: site name, latitude,
longitude, antenna height, configured timezone, units preference, display/alert
radius, demo-mode flag, T0. `antenna_height_ft` is the antenna's height **above ground
level** (`docs/CONFIGURATION.md`, `location`), `null` when not configured.

```json
{
  "site_name": "Rooftop Pi",
  "latitude": 47.6205,
  "longitude": -122.3493,
  "antenna_height_ft": 120,
  "timezone": "America/Los_Angeles",
  "units": "aviation",
  "display_radius_nm": 250,
  "alert_radius_nm": null,
  "demo_mode": false,
  "t0": "2026-04-02T18:11:09.000Z"
}
```

### 3.3 Current aircraft — slice 010

`GET /api/v1/aircraft/current`

The full live picture: positioned **and** non-positioned aircraft (SPEC §20). Query
params: `positioned=true|false` filter, none required.

Aircraft object (the same shape used by the WebSocket):

```json
{
  "icao": "ae1463",
  "callsign": "RCH492",
  "registration": "05-8153",
  "position": { "lat": 47.91, "lon": -122.02 },
  "position_source": "adsb",
  "altitude_ft": 24975,
  "ground_speed_kt": 442,
  "track_deg": 173.2,
  "vertical_rate_fpm": -640,
  "squawk": "4521",
  "emergency": null,
  "decoder_emergency": null,
  "emitter_category": "A5",
  "selected_altitude_ft": 25000,
  "on_ground": false,
  "distance_nm": 18.4,
  "bearing_deg": 31.7,
  "rssi_db": -12.1,
  "message_count": 4812,
  "seen_s": 0.4,
  "seen_pos_s": 1.1,
  "state": "live",
  "sighting_id": 88213,
  "aircraft_type": "C17",
  "model": "Boeing C-17A Globemaster III",
  "operator": "United States Air Force",
  "operator_group": "US Military",
  "classification": {
    "military": true,
    "government": false,
    "law_enforcement": false,
    "mission": "military",
    "icon_category": "military_transport",
    "confidence": "high"
  },
  "interesting": {
    "severity": "high",
    "reasons": ["Rule: Military aircraft"]
  },
  "route": {
    "origin": "KATL",
    "origin_name": "Hartsfield Jackson Atlanta International Airport",
    "destination": "KSEA",
    "destination_name": "Seattle Tacoma International Airport"
  },
  "provenance": {
    "registration": "mictronics",
    "operator": "mictronics",
    "classification": "mictronics",
    "distance_nm": "derived",
    "route": "aerodatabox"
  }
}
```

- `route`: the current sighting's externally reported route (§2.6 shape) — always
  present, members `null` until enrichment lands (slice 026); never a locally
  inferred value (that is the separate nearest-airport context, slice 027).
  `origin_name`/`destination_name` are the reported idents named from the local
  `airports` table (slice 027, slice 070) and stay `null` until an airports import
  has run.

- `position_source`: `adsb` | `mlat` | `none` | `other` (SPEC §21). Non-positioned
  aircraft have `position: null`, `position_source: "none"`.
- `state`: `live` | `stale` (past the 15 s threshold, not yet removed).
- `emergency`: `null` | `"7500"` | `"7600"` | `"7700"` — the squawk, restated when it
  is an emergency code. It keeps meaning exactly that; the decoder's own emergency
  state is the separate `decoder_emergency`.
- `decoder_emergency` (slice 086): the ADS-B emergency/priority status the aircraft
  broadcasts, independently of its squawk — `general`, `lifeguard`, `minfuel`,
  `nordo` (no communications), `unlawful` or `downed`; `null` when it declares none,
  when the status is a reserved code, or when the decoder has not received one. Not
  sticky: it is the decoder's *current* statement, and a decoder drops the status
  once the aircraft stops broadcasting it. Either field being non-null means the
  aircraft is declaring an emergency; both feed the built-in emergency alert (§3.10).
- `emitter_category` (slice 086): the ADS-B emitter category, `A0`–`D7`, exactly as
  the aircraft transmits it (`null` when never received, including on every
  legacy dump1090-fa feed). Set A is powered aircraft by size/performance, B
  unpowered and lighter-than-air, C surface vehicles and obstacles, D reserved:
  `A0` no category information, `A1` light (< 15 500 lb), `A2` small (15 500–75 000
  lb), `A3` large (75 000–300 000 lb), `A4` high-vortex large (e.g. B757), `A5`
  heavy (> 300 000 lb), `A6` high performance (> 5 g, > 400 kt), `A7` rotorcraft;
  `B0` no information, `B1` glider/sailplane, `B2` lighter-than-air, `B3`
  parachutist/skydiver, `B4` ultralight/hang-glider/paraglider, `B5` reserved, `B6`
  unmanned aerial vehicle, `B7` space/trans-atmospheric vehicle; `C0` no
  information, `C1` surface emergency vehicle, `C2` surface service vehicle, `C3`
  point obstacle, `C4` cluster obstacle, `C5` line obstacle, `C6`–`C7` reserved;
  `D0`–`D7` reserved. Sticky like other decoder fields.
- `selected_altitude_ft` (slice 086): the altitude selected on the autopilot, in
  feet — the mode control panel / flight control unit value when received, else the
  flight management system's target altitude. The MCP value is preferred because it
  is what the crew has actually set and what the aircraft will level at; the FMS
  value is the programmed profile. Sticky; `null` when neither was received.
- `interesting`: `null` when no active alert match (fields populated from phase 6).

### 3.4 Interesting aircraft — slice 038/039

`GET /api/v1/aircraft/interesting`

Currently-matching aircraft, sorted severity → distance, each with match reasons and
severity. Same aircraft object shape, `interesting` always non-null.

### 3.5 Aircraft history — slice 029

| Method & path | Purpose |
|---|---|
| `GET /api/v1/aircraft` | Paginated historical aircraft list. Sort keys: `registration`, `icao`, `type`, `operator`, `classification`, `first_seen`, `last_seen`, `sighting_count`, `closest_approach_nm`, `max_range_nm`. Filters: `classification`, `operator_group`, `type`, `q` (search, below). |
| `GET /api/v1/aircraft/{icao}` | Full aircraft detail: identity, metadata with provenance, classification, lifetime records. |
| `GET /api/v1/aircraft/{icao}/sightings` | Paginated sightings for one aircraft. |

Both the list rows and the detail carry `emitter_category` (slice 086): the last ADS-B
emitter category the airframe transmitted (`A0`–`D7`, §3.3 lists them), or `null` if
it never sent one. It is decoder-reported, so it has no `provenance` entry, and it
answers "what is this" for an airframe no metadata registry describes.

**Search: `q`** (slice 083). Finds airframes whose **ICAO address, registration, any
callsign it has flown, ICAO type designator or operator name** starts with `q`:

- **Prefix, not substring.** `q=G-EZ` finds `G-EZTH`; `q=EZTH` does not.
- **Case-insensitive** for ASCII letters. `q=g-ez`, `q=A1B2` and `q=easyj` all match.
- **Literal.** `%`, `_` and `\` match themselves; there is no pattern syntax.
- **Trimmed**, and a blank `q` is ignored — `?q=%20` is the unfiltered list.
- **At most 32 characters.** A longer `q` is a `422` validation error, not a truncation.
- **Any callsign it has flown** means the first or last callsign of *any* of its
  sightings: an airliner that flew `BAW12` last month and `BAW7` today is found by
  `BAW12`, `BAW7` and `BAW`, and one whose callsign changed mid-sighting by either.

`q` combines with the other filters (`AND`), and sorting and pagination apply to the
filtered set; `total` is the exact count of airframes matching every filter, `q`
included. It is served from indexes (rev 0018), so its cost follows the number of
matching rows rather than the size of history.

`q` filters **this list only**. It is not a global search across aircraft, sightings,
alerts or places — that is a deferred non-goal (SPEC §79); SPEC §37 scopes search to
the list page it is typed on. `GET /api/v1/sightings` has its own `q` (§3.7).

Lifetime record block (SPEC §53):

```json
{
  "first_seen": "2026-04-02T18:11:09Z",
  "last_seen": "2026-08-30T22:41:55Z",
  "sighting_count": 41,
  "cumulative_duration_s": 52803,
  "open_sighting_elapsed_s": 963,
  "closest_approach_nm": 2.1,
  "max_range_nm": 141.8,
  "lowest_altitude_ft": 1250,
  "highest_altitude_ft": 41000
}
```

`cumulative_duration_s` is SPEC §53's cumulative observation duration and **includes
the sighting still running**, if this airframe has one. The stored column behind it
(`aircraft.total_observed_ms`) sums *closed* sightings only — that is deliberate on
the storage side, so a flush of an open sighting cannot double-count it at close —
but publishing it raw told the owner of an aircraft sixteen minutes overhead that
their cumulative observed time was `0s`.

`open_sighting_elapsed_s` is how much of that total is still accruing: the open
sighting's `started_at` to now, or `null` when nothing is open for this airframe.
`null` rather than `0` per §2.7 — "no sighting is open" is not "an open sighting of
zero length" — and published separately so a client can render "14h 40m so far,
still running" instead of inferring an ongoing sighting from a total that moves
between reads.

### 3.6 Map overlays — slices 027/028

| Method & path | Purpose |
|---|---|
| `GET /api/v1/airports` | Airport overlay rows for a map viewport. Query: `bbox`, `min_size` (size class); capped count, largest-first. |
| `GET /api/v1/airspace` | The user-supplied airspace overlay (`airspace.geojson` in the data dir) as a validated FeatureCollection; empty when absent (ADR-0012). |

`bbox` is **`west,south,east,north`** in decimal degrees (WGS-84) — that is
longitude first, matching GeoJSON axis order, not latitude first. For example
`bbox=-123.5,47.0,-121.5,48.0`. Omitting it queries the whole dataset.

`min_size` is one of `large`, `medium`, `small`, `heliport`, and names the *smallest*
size class to include.

### 3.7 Sightings — slice 030

| Method & path | Purpose |
|---|---|
| `GET /api/v1/sightings` | Chronological log. Filters: `icao`, `q`, `preset` (the §3.7 presets, resolved in receiver-local time; ignored when `from`/`to` are given — slice 098), `from`, `to`, `interesting=true`, `open=true` (currently-open sightings). Each row carries `first_sighting`: whether it contains the airframe's first-ever observation. Sort: `started_at` (default desc), `ended_at`, `duration_s`, `tail` (registration, else last callsign), `aircraft_type` (model, else designator), `operator`, `closest_approach_nm`, `max_range_nm`, `lowest_altitude_ft`, `highest_altitude_ft`, `position_count` — one per sortable column of the Sightings page (slice 100). The text keys ignore case. Only `started_at` and `max_range_nm` are index-backed; the others sort the filtered window. |
| `GET /api/v1/sightings/{id}` | Sighting detail: flight context, reception stats, events, simplified path. |

`from` and `to` accept full ISO-8601 datetimes (not only calendar days) and bound
`started_at`. A value without a timezone is interpreted as UTC rather than rejected.

**`icao` and `q`.** `icao` is an **exact** match on a lowercase six-hex-digit address
(`^[0-9a-f]{6}$`; anything else is a `422`), unchanged since slice 030. `q` (slice 083)
is the search the Sightings page's filter box sends: sightings whose **ICAO address,
first callsign or last callsign starts with `q`** (a callsign can change mid-sighting;
rows show the last one), with the same rules as `/aircraft`'s `q` (§3.5) —
prefix, ASCII case-insensitive, literal (`%`, `_`, `\` are not wildcards), trimmed,
blank ignored, at most 32 characters (`422` beyond). `q=BAW` finds `BAW12` and `BAW7`;
`q=ae14` finds every sighting of `ae1463`. Both may be given and combine with `AND`.
Like `/aircraft`'s, this `q` filters this list only and is not a global search (SPEC
§37, §79).

**Open sightings.** Every list row and the detail object carry two fields that say
whether the sighting is still running, and for how long:

| Field | Meaning |
|---|---|
| `open` | `true` while the sighting has not closed. The same fact as `ended_at: null`, said out loud so a client never has to read a state out of an absence. |
| `elapsed_s` | Seconds from `started_at` to the instant the response was built. Present only while `open`; `null` on a closed sighting, whose answer is `duration_s`. |

`duration_s` keeps meaning exactly what it stores: the **recorded** duration of a
finished sighting, and `null` until there is one. What that `null` must *not* be
rendered as is "Unknown" — §2.7 reserves that word for "the decoder never reported
this", and a sighting the same page calls "Ongoing" is not unknown in that sense:
its start time and the current time are both known. "Not closed yet" is a different
fact and gets different fields. Likewise `closure_reason` is `null` because there
has been no closure, not because the reason was lost.

Every row of one page is measured against a single clock reading, so two sightings
that started in the same millisecond always report the same `elapsed_s`.

Sighting detail sketch:

```json
{
  "id": 88213,
  "icao": "ae1463",
  "callsign": "RCH492",
  "squawk": "4521",
  "started_at": "2026-08-30T22:02:10Z",
  "ended_at": "2026-08-30T22:41:55Z",
  "duration_s": 2385,
  "open": false,
  "elapsed_s": null,
  "closure_reason": "gap_timeout",
  "route": {
    "origin": "KTCM",
    "origin_name": "McChord Air Force Base",
    "destination": "PHIK",
    "destination_name": "Hickam Air Force Base"
  },
  "reception": {
    "rssi_peak_db": -3.2,
    "rssi_avg_db": -11.8,
    "rssi_min_db": -27.4,
    "message_count": 48210,
    "position_count": 2210,
    "pct_with_position": 92.4
  },
  "records": {
    "closest_approach_nm": 11.2,
    "max_range_nm": 96.0,
    "lowest_altitude_ft": 21000,
    "highest_altitude_ft": 28000
  },
  "events": [
    { "at": "2026-08-30T22:02:10Z", "type": "sighting_opened", "detail": null },
    { "at": "2026-08-30T22:14:31Z", "type": "route_enriched", "detail": { "source": "aerodatabox" } }
  ],
  "path": [
    { "t": "2026-08-30T22:02:10Z", "lat": 47.11, "lon": -121.80, "altitude_ft": 21000, "source": "adsb" },
    { "t": "2026-08-30T22:03:42Z", "lat": 47.19, "lon": -121.88, "altitude_ft": 21850, "source": "adsb" }
  ],
  "provenance": { "route": "aerodatabox" }
}
```

`path` is the Douglas-Peucker-simplified, timestamp-ordered track (playback-capable,
SPEC §19). Active sightings return the live full-resolution track instead, with
`ended_at: null` and `open: true`.

#### 3.7.1 What was that? — `GET /api/v1/overhead` (slice 090)

"What just flew over?" for any moment: the sightings whose **closest stored position
fix** within `window` minutes either side of `at` came nearest the receiver, nearest
first (issue #233).

| Param | Default | Bounds | Meaning |
|---|---|---|---|
| `at` | now | ISO-8601 | The moment asked about. A value without an offset is UTC (§2.2). |
| `window` | `10` | `1`–`60` | Minutes either side of `at`; the window `[at − window, at + window]` is inclusive. |
| `limit` | `10` | `1`–`50` | Ranked results returned. |

Anything outside those bounds, or an unparseable `at`, is a `422`.

```json
{
  "at": "2026-08-30T22:10:00.000Z",
  "window_minutes": 10,
  "window_start": "2026-08-30T22:00:00.000Z",
  "window_end": "2026-08-30T22:20:00.000Z",
  "method": "closest_position_fix",
  "receiver_configured": true,
  "reason": null,
  "candidates": 14,
  "truncated": false,
  "items": [
    {
      "sighting_id": 88213,
      "icao": "ae1463",
      "callsign": "RCH492",
      "registration": "05-5140",
      "aircraft_type": "C17",
      "model": "C-17A Globemaster III",
      "operator": "United States Air Force",
      "open": false,
      "fix_at": "2026-08-30T22:12:41.000Z",
      "lat": 47.49712,
      "lon": -122.30215,
      "altitude_ft": 4200,
      "distance_nm": 2.968,
      "distance_kind": "slant",
      "ground_distance_nm": 2.831,
      "bearing_deg": 5.12,
      "position_source": "adsb"
    }
  ]
}
```

**Closest position fix, never interpolated.** Every row is one point the sighting
actually stored — a closed sighting's simplified packed track, an open one's
checkpointed tail — with that point's own time (`fix_at`), altitude and
`position_source`. Nothing is interpolated between two stored points or extrapolated
beyond the first or last, which is what keeps this a single-moment lookup rather than
the animated playback SPEC §79 keeps out of scope. `method` is always
`closest_position_fix` so a client can say so beside the numbers. The price, stated
rather than hidden: a straight leg that simplification kept only as its two
endpoints can pass overhead with neither endpoint inside the window, and such a
sighting is left out rather than represented by a position it never reported.

**Distance.** `ground_distance_nm` is the great-circle distance from the receiver,
measured exactly as every other receiver-relative range is. Results are ranked by
`distance_nm`, which is the **slant** (line-of-sight) distance when the fix carries an
altitude — ground distance and height above the receiver as the two legs of a flat
right triangle — and the ground distance when it does not (`distance_kind` says
which). The height is the fix's reported altitude as-is: `antenna_height_ft` is above
*ground* level while the altitude is above *sea* level, and the site's own elevation —
what would reconcile the two — is not stored, so nothing is subtracted (slice 087
corrected an earlier version that subtracted the antenna height). For a site well
above sea level this overstates the vertical leg by the site's elevation, which moves
an aircraft directly overhead by at most that much; a future site-elevation setting
would refine it. A missing altitude is unknown,
not zero (§2.7). Ties go to the earlier fix, then the lower sighting id.

**Which sightings are considered.** Sightings with a position whose span overlaps the
window: any still open that began before the window's end, plus any that began within
24 hours before the window's start and had not ended before it. `candidates` counts
them. A closed sighting that began more than 24 hours earlier — a day of continuous
reception with no ten-minute gap, i.e. a parked, transmitting aircraft — is outside the
lookup. At most 2,000 candidates are considered, keeping those whose recorded closest
approach could come nearest; `truncated: true` says the cap was reached. Open sightings
are read from their stored checkpoints, never from the live picture, so the last flush
interval (about 30 s) of a sighting in progress is not visible yet.

**No receiver location.** With no receiver position set there is nothing to measure
from, and the answer is an empty `200` — `receiver_configured: false`,
`reason: "receiver_location_unset"`, `items: []` — the way every other
receiver-relative field degrades to unknown rather than failing (§2.7). The window is
still echoed.

**Cost.** The lookup's cost follows the traffic around the window, not the length of
history: both candidate reads are bounded index ranges (`ix_sightings_started`,
`ix_sightings_open`), and packed tracks are decoded only for candidates whose recorded
closest approach could still beat the results already found. The analytics query
budget (500 ms, `docs/PERFORMANCE.md`) applies to a ±10-minute window;
`flightsite-storage-qual` probes it on the multi-year synthetic history.

### 3.8 Analytics — slice 031

All analytics endpoints accept `preset=today|7d|30d|ytd|t0` (default `today`), or
explicit `from`/`to` UTC bounds. Day bucketing is receiver-local (DST-correct).

| Path | Returns |
|---|---|
| `GET /api/v1/analytics/summary` | Today-at-a-glance block (SPEC §59). |
| `GET /api/v1/analytics/top-aircraft` | Most frequently seen aircraft. |
| `GET /api/v1/analytics/top-types` | Most frequent types/models. |
| `GET /api/v1/analytics/top-operators` | Most common operators / groups. |
| `GET /api/v1/analytics/classification-activity` | Military/government/police activity over time. |
| `GET /api/v1/analytics/daily` | Daily aircraft count, sighting count, new-aircraft count, max range per day. |
| `GET /api/v1/analytics/hourly` | One receiver-local day, hour by hour (slice 097). Param: `day=YYYY-MM-DD` (default: today in the receiver's timezone). Takes no `preset`. |
| `GET /api/v1/analytics/rarity` | Never-seen-before counts, locally rare aircraft/types. |
| `GET /api/v1/analytics/counts` | A window's four headline figures, counted live: sightings, distinct aircraft, distinct types, new aircraft (slice 098). |
| `GET /api/v1/analytics/aircraft` | Every distinct aircraft heard in the window, most-sighted first. Paginated (`limit`, `offset`, exact `total`); optional `type=<designator>` (slice 098). Sort (slice 100): `sightings` (default desc), `registration` (else the address), `type` (model, else designator), `operator` (else the registered owner), `first_seen`, `last_seen`. |
| `GET /api/v1/analytics/types` | Every distinct ICAO type heard in the window, busiest first. Paginated (slice 098). Sort (slice 100): `sightings` (default desc), `type` (the description, else the designator), `aircraft` (distinct airframes), `first_seen` (first ever), `last_seen`. |

**"Not computed yet" is `null`, never `0`** (issue #205). The rollup pipeline has
real latency — the flush pass runs every 30 s and only for days something touched
— so there is a window in which a day has traffic and no `daily_stats` row.
Rendering that as `0 aircraft, 0 sightings` states a measurement that was never
taken, which is what a young install showed. Every rollup-derived figure is
therefore `null` until its day has been folded, and a `complete` flag says which
state a reader is in:

```jsonc
// GET /api/v1/analytics/daily?preset=7d
{
  "window": { "preset": "7d", "from": "…", "to": "…",
              "first_day": "2026-09-14", "last_day": "2026-09-20",
              "timezone": "America/New_York" },
  "items": [
    {                                  // a day that has been rolled up
      "day": "2026-09-19", "complete": true,
      "unique_aircraft": 112, "new_aircraft": 9, "sightings": 486,
      "interesting": 57, "military": 1, "government": 6, "law_enforcement": 4,
      "max_range_nm": 225.6, "busiest_hour": 21,
      "receiver_messages": 68764, "receiver_positions": 9012,
      "receiver_aircraft_max": 61, "receiver_max_range_nm": 224.9
    },
    {                                  // not computed yet — not a quiet day
      "day": "2026-09-20", "complete": false,
      "unique_aircraft": null, "new_aircraft": 3, "sightings": null,
      "interesting": null, "military": null, "government": null,
      "law_enforcement": null, "max_range_nm": null, "busiest_hour": null,
      "receiver_messages": null, "receiver_positions": null,
      "receiver_aircraft_max": null, "receiver_max_range_nm": null
    }
  ]
}
```

- `complete: false` means **the rollup for that day has not been written yet**.
  A day that *was* rolled up and had no traffic is `complete: true` with zeros —
  the zero is then the measurement, and a chart should draw it as one.
- `new_aircraft` is the one count that is never `null`: it is derived live (see
  below), so it is a real figure on a pending day too.
- The `receiver_*` fields keep their existing meaning — `null` where slice 033
  recorded no activity for that day — and are `null` on a pending day as well.
- `GET /analytics/classification-activity` carries the same rows under `series`
  and adds `complete` beside its totals.
- `GET /analytics/summary` adds `complete`, but its **totals stay numbers**: a
  total over six folded days of seven is a real total, and blanking the card
  would hide six days of history to describe one. `complete: false` means "as far
  as has been computed". `unique_aircraft`, `new_aircraft`, `new_milestones` and
  the first/last sighting instants are live queries and are unaffected.
- `GET /receiver/metrics?metric=unique_aircraft` reads the same rows, so a
  pending day is a point with `"value": null` rather than a zero.

**"Never seen before" has one definition across every surface** (issue #205): an
airframe whose `aircraft.first_seen_ms` — its first-ever observation by this
receiver — falls inside the window, attributed to the receiver-local day that
instant fell in. `rarity.never_seen_before` is that count for the whole window,
`daily[].new_aircraft` is it per day, and `summary.new_aircraft` is the sum; all
three come from one query, so `summary.new_aircraft == rarity.never_seen_before`
always. The figure is **not** read from `daily_stats.new_aircraft`: the stored
column holds the same number but is only as current as the last rollup pass, and
serving both left the Analytics page reporting "never seen before" as `0` on one
card and `99` on the card beside it. It is also the only one of the daily row's
counts that is never `null` — see below.

`top-types` and `top-operators` share one row shape: `key` (the ICAO type
designator, or the operator group id as a string), `label` (what to display),
`sightings`, `unique_aircraft`, `days_seen`, `first_seen_at`/`last_seen_at`, and
`description` (slice 074). `description` is the long form behind a type
designator's shorthand — `"Boeing 737-800"` for `B738` — derived from the imported
metadata as the model string most of that type's known airframes carry, so it
needs no separate designator dataset; it is `null` when no airframe of the type
carries a model, and always `null` for an operator group.

`top-aircraft` and the `rarity` endpoint's `rare_aircraft` share the airframe row
shape (`icao`, `registration`, `type`, `model`, `operator`, `operator_group`, the
classification flags, `sightings`, `first_seen_at`/`last_seen_at`, `max_range_nm`),
plus `owner` (slice 095): the registry owner where a source released one — the FAA
registrant for a US tail — and `null` otherwise. It is the fallback for "who flies
it" when `operator` is unknown, and is as often a leasing trust or a bank as an
airline, which is why it is a separate field rather than folded into `operator`.

**`hourly` is one day at the resolution that shows its shape** (slice 097). A
window of a single day gives the day-granular series exactly one point, which is
no chart; the Analytics page asks for this instead.

```jsonc
// GET /api/v1/analytics/hourly?day=2026-10-05
{
  "day": "2026-10-05", "timezone": "America/New_York",
  "items": [
    { "t": "2026-10-05T04:00:00.000Z", "hour": 0,       // 00:00 local
      "sightings": 3, "unique_aircraft": 2,
      "military": 1, "government": 0, "law_enforcement": 0, "new_aircraft": 2,
      "messages": 41000, "positions": 3200, "max_range_nm": 188.2 },
    { "t": "2026-10-05T05:00:00.000Z", "hour": 1,       // a quiet hour
      "sightings": 0, "unique_aircraft": 0,
      "military": 0, "government": 0, "law_enforcement": 0, "new_aircraft": 0,
      "messages": 12000, "positions": 900, "max_range_nm": null },
    { "t": "2026-10-05T23:00:00.000Z", "hour": 19,      // not begun yet
      "sightings": null, "unique_aircraft": null,
      "military": null, "government": null, "law_enforcement": null,
      "new_aircraft": null,
      "messages": null, "positions": null, "max_range_nm": null }
  ]
}
```

- Buckets are **UTC hours** — the key of `receiver_metrics_hourly` — that begin
  inside the local day, each carrying the local `hour` (0–23) it begins in. That
  is the day's 24 local hours in a whole-hour zone; 23 or 25 across a DST change,
  where a fall-back day names one hour twice. In a half-hour zone the bucket
  straddling local midnight belongs to the day it begins in.
- **Every bucket of the day is returned**, so a client can lay out the whole day
  and fill it as it happens.
- `sightings` counts sightings that **started** in the hour, so a day's buckets
  sum to its sighting count. `unique_aircraft` is the distinct aircraft with a
  sighting **overlapping** the hour — "heard this hour" — and is therefore not
  additive: an aircraft overhead from 09:50 to 10:10 is one aircraft in each hour.
- `military`, `government` and `law_enforcement` (slice 099) are the sightings
  that started in the hour whose airframe carries that classification flag — the
  per-hour form of the daily row's figures of the same names, summing to them
  over the day. `new_aircraft` is the airframes whose first-ever observation fell
  in the hour, summing to the day's "never seen before".
- All of these are live reads: a real number, zero included, for every hour that
  has begun, and `null` only for an hour still in the future.
- `messages`, `positions` and `max_range_nm` come from the hourly receiver
  metrics and are `null` where that table has no row — before recording started,
  or an hour the receiver was not running — never `0`.

**`counts`, `aircraft` and `types` say what a window held** (slice 098) — the
Sightings page's summary line and its two grouped views. All three take the
standard `preset` / `from` / `to`.

```jsonc
// GET /api/v1/analytics/counts?preset=today
{ "window": { "preset": "today", "…": "…" },
  "sightings": 142, "unique_aircraft": 97, "unique_types": 31, "new_aircraft": 12 }

// GET /api/v1/analytics/aircraft?preset=today&limit=50&offset=0
{ "window": { "…": "…" }, "total": 97, "limit": 50, "offset": 0,
  "items": [ { "icao": "a1b2c3", "registration": "N228BZ", "type": "BCS3",
               "model": "Airbus A220-300", "operator": "Breeze Airways",
               "sightings": 4, "new": false, "…": "…" } ] }

// GET /api/v1/analytics/types?preset=today
{ "window": { "…": "…" }, "total": 31, "limit": 50, "offset": 0,
  "items": [ { "type": "BCS3", "description": "Airbus A220-300",
               "sightings": 11, "unique_aircraft": 3,
               "first_seen_at": "2026-09-02T14:10:03.000Z",
               "last_seen_at": "2026-10-05T18:41:20.000Z", "new": false } ] }
```

- **Counted live.** None of the three reads a rollup, so the figures agree with
  the sightings log to the second — unlike `summary`, whose totals are sums over
  `daily_stats` and say so with `complete`. `aircraft.total == counts.unique_aircraft`
  and `types.total == counts.unique_types` for the same window, always.
- **Sorting** follows §2.4 on both lists: `sort` and `order`, unknowns last in
  both directions, text keys case-insensitive, and a stable tie-break (the
  address for `aircraft`, the designator for `types`, ascending either way) so
  paging through a tied key never repeats or skips a row. A key the list does
  not have is a `422`.
- An `aircraft` row is the `top-aircraft` row shape plus `new`; `sightings` is the
  count inside the window. A `types` row's `first_seen_at` is the receiver's
  first-ever observation of the type, not its first in the window.
- **`new`** marks an airframe (or a type) the receiver had never heard before the
  window. For `preset=t0`, which asks for the whole history, it is `false` on
  every row: it would be true of all of them, and a flag set everywhere says
  nothing. Any other window flags honestly even when it happens to reach back to
  T0 — on a day-old install everything heard today is new today, and
  `counts.new_aircraft` says the same.
- `preset=t0` is the whole-history form: `aircraft` is then every discrete
  airframe the receiver has ever heard, with lifetime sighting counts, and
  `types` every discrete type. Both read the `aircraft` table — one row per
  airframe — rather than every sighting.
- An airframe no registry gives a type counts in `unique_aircraft` and appears
  in `aircraft`, and belongs to no row of `types`.

A `rarity` response's `rare_types` rows carry `description` (slice 097), the same
long-form type name a `top-types` row does, `null` when no imported airframe of
the type carries a model.

### 3.9 Receiver statistics — slices 033/034

| Path | Returns |
|---|---|
| `GET /api/v1/receiver/scorecard` | SPEC §61 scorecard (current visible, msgs/s, pos/s, ranges, uniques, uptimes, health summary). |
| `GET /api/v1/receiver/metrics` | One time-series chart. Params: `metric`, `resolution=high\|hourly\|daily` (default `hourly`), `from`/`to`. |
| `GET /api/v1/receiver/range-by-bearing` | Polar max-range histogram (buckets of bearing → max nm). |
| `GET /api/v1/receiver/signal-distribution` | RSSI distribution histogram, derived from per-sighting `rssi_*_db` reception stats over the selected window. |
| `GET /api/v1/receiver/coverage` | Coverage by bearing and altitude band against the radio horizon, plus likely-obstruction findings (slice 087). Param: `window=7d\|30d\|90d\|all` (default `30d`). |
| `GET /api/v1/receiver/lifetime` | SPEC §63 lifetime statistics since T0. |

**The scorecard's "today" figures are null-honest and never rollup-backed**
(issue #205). `max_range_today_nm` reduces `range_by_bearing_daily` for the
receiver-local day and is `null` until a positioned aircraft has been seen
today — "nothing measured yet", never `0` nm. `unique_aircraft_today` and
`unique_aircraft_since_t0` are live counts over `sightings`, so they are exact
whether or not today's analytics rollup has been computed. Every other tile is
either a live reading (`current_visible`, `current_positioned`,
`messages_per_sec`, `positions_per_sec`) or a lifetime record, and all of them
answer `null` when the receiver has nothing to report rather than a zero that
would read as a measurement.

The day these figures are "today" on is the **receiver's**, resolved from live
settings on every request *and* on every write — see `docs/DATA_MODEL.md` §10.

`metric` is one of `messages_per_sec`, `positions_per_sec`, `aircraft_count`,
`max_range_nm`, `messages_total`, `positions_total`, `unique_aircraft`.

A point's `value` is `null` where the tier has no figure for that bucket, which
includes a day whose analytics rollup has not been computed yet
(`metric=unique_aircraft`) — a gap in the series, not a zero.

Not every metric exists at every resolution, and asking for an unavailable
combination is a `400`, not an empty series:

- `unique_aircraft` is `daily` only.
- `messages_total` and `positions_total` are `hourly` or `daily` only.
- `from` later than `to` returns `400 invalid_range`.

#### 3.9.1 Coverage by altitude band — slice 087

`GET /api/v1/receiver/coverage?window=30d`

How far the receiver hears in each 5° direction at each altitude band, compared with
the radio horizon, and which directions look obstructed (issue #230). Read from the
daily rollup `range_by_bearing_band_daily` (`docs/DATA_MODEL.md` §6.3.1).

- **`window`** — `7d`, `30d` (default), `90d` or `all`: whole **receiver-local** days
  ending today (`7d` is today and the six days before it). Anything else is `422`.
  `from_day`/`to_day` echo the local calendar days covered; `from_day` is the first
  stored day for `all`, or `null` when nothing is stored.
- **`bands`** — always three, in order `below_10k` (< 10,000 ft), `10k_25k`
  (10,000–25,000 ft), `above_25k` (≥ 25,000 ft), by barometric altitude; aircraft with
  no altitude are in none. Each carries `min_ft`/`max_ft` (`null` = unbounded),
  `reference_ft`, `horizon_nm`, and always **72 sectors** in bucket order.
- **Sector** — `bearing_deg` (midpoint), `max_range_nm` with the `at`/`icao` that set
  it, `samples` (receiver samples, one per ~15 s, that heard anything in the cell,
  summed over the window), `days` (local days with any data) and `share_of_horizon`
  (`max_range_nm / horizon_nm`, not clamped — above 1 is a real observation). A sector
  nothing was heard in has `max_range_nm`, `at`, `icao` and `share_of_horizon`
  **`null`** and zero counts — never a `0` nm range.
- **Radio horizon** — the 4/3-Earth line-of-sight distance
  `horizon_nm = 1.23 × (√antenna_height_ft + √reference_ft)`, with
  `antenna_height_ft` above ground level (`receiver.location`, echoed as
  `antenna_height_ft`). `reference_ft` is the band's lower edge — 10,000 and 25,000 ft
  — and 3,000 ft for the bottom band, whose 0 ft edge would judge it by the antenna's
  own few-mile horizon: a sector short of the lower-edge horizon is short for every
  aircraft in the band. The aircraft's height should be above the *site's* ground,
  but the site elevation is not stored, so `reference_ft` is used as-is — exact at sea
  level, about 4 nm generous at 25,000 ft for a 1,000 ft site. **With no antenna
  height configured every `horizon_nm` is `null`** (Unknown), every
  `share_of_horizon` is `null` and `findings` is empty.
- **`criteria`** — the documented finding rule: `share_below: 0.6`,
  `min_samples: 30`, `min_days: 3`.
- **`findings`** — runs of adjacent sectors in one band (wrapping through North) in
  which **every** sector has `share_of_horizon < 0.6`, at least `min_samples` samples
  and data on at least `min_days` days. A sector with no data is never part of a
  finding (nothing distinguishes "blocked" from "no traffic" there). Highest band
  first, then by bearing. Each has `band`, `start_deg`/`end_deg` (end exclusive; a run
  through North has `start_deg > end_deg`, e.g. 350 → 10), `compass` (16-point name of
  the middle bearing), `max_range_nm` (the furthest anywhere in the run) and
  `share_of_horizon` from it, `horizon_nm`, `samples` (summed), `days` (the fewest of
  any sector — the weakest evidence) and `message`, a canonical-units sentence such
  as `"NE 40–60° reaches 58 % of the radio horizon above 25,000 ft — likely
  obstruction"`. A run covering all 72 sectors reads as a receiver-wide limit
  (antenna, cable or gain) rather than an obstruction.

```json
{
  "window": "30d",
  "from_day": "2026-09-01",
  "to_day": "2026-09-30",
  "sector_width_deg": 5.0,
  "antenna_height_ft": 25.0,
  "criteria": { "share_below": 0.6, "min_samples": 30, "min_days": 3 },
  "bands": [
    {
      "key": "above_25k", "label": "25,000 ft and above",
      "min_ft": 25000.0, "max_ft": null, "reference_ft": 25000.0,
      "horizon_nm": 200.6,
      "sectors": [
        { "bearing_deg": 2.5, "max_range_nm": 187.4, "at": "2026-09-21T14:03:11.000Z",
          "icao": "a4b2c1", "samples": 1840, "days": 30, "share_of_horizon": 0.934 },
        { "bearing_deg": 7.5, "max_range_nm": null, "at": null, "icao": null,
          "samples": 0, "days": 0, "share_of_horizon": null }
      ]
    }
  ],
  "findings": [
    { "band": "above_25k", "start_deg": 40.0, "end_deg": 60.0, "compass": "NE",
      "max_range_nm": 116.3, "horizon_nm": 200.6, "share_of_horizon": 0.58,
      "samples": 912, "days": 21,
      "message": "NE 40–60° reaches 58 % of the radio horizon above 25,000 ft — likely obstruction" }
  ]
}
```

(Abridged: the real payload has all three bands and 72 sectors in each.)

### 3.10 Activity & alert history — slices 035/038

| Path | Returns |
|---|---|
| `GET /api/v1/activity` | Paginated chronological activity feed. Filter: `type`, `from`, `to`. Event types per SPEC §55 (`alert_triggered`, `first_ever_aircraft`, `new_type`, `range_record`, `receiver_record`, `emergency_squawk`, `receiver_offline`, `receiver_restored`, `metadata_updated`, `milestone`), plus `feeder_offline` (`high`) and `feeder_restored` (`info`) since slice 077, whose payload is `{feeder, label, kind, since_ms, outage_s}` — `outage_s` is `null` on the offline event. Since slice 088, `self_alert_raised` (`high`) and `self_alert_restored` (`info`): a receiver self-alert condition began / ended, payload `{condition, since_ms, duration_s, …detail}` — see below. |
| `GET /api/v1/alerts/matches` | Alert match history. Filters: `severity`, `icao`, `rule_id`, `from`, `to`. |

**Receiver self-alert events (slice 088).** `condition` is `decoder_down` or
`message_rate`; `since_ms` is when the condition *began* (the same on both events of
one episode, and part of both dedupe keys, so an episode is recorded once however
often it is announced); `duration_s` is `null` on the raise and the episode's length
on the restore. The rest is the numbers the condition was judged on:

| `condition` | Detail keys |
|---|---|
| `decoder_down` | `minutes` (the configured threshold), `error` (the decoder's short failure reason; raise only) |
| `message_rate` | `rate_msgs_s`, `baseline_msgs_s` (the hour-of-week median), `share_pct`, `minutes`, `baseline_weeks` |

A feeder going offline is the third self-alert condition, but it has no event of its
own: it *is* slice 077's `feeder_offline` / `feeder_restored`, which the browser turns
into a self-alert notification while `self_alerts.feeder_offline_enabled` is on.
Neither event carries an aircraft or a `match_id`.

An alert match carries `id`, `at` (the match timestamp — not `matched_at`),
`severity`, `reason`, `icao`, `sighting_id`, an identity block for the airframe,
`rule` (null for a built-in match), `builtin_key` (set when the match came from a
built-in rather than a user rule, e.g. `emergency_7600`), and `notified`:

```json
{
  "id": 4,
  "at": "2026-09-01T20:35:29.959Z",
  "severity": "critical",
  "reason": "Emergency squawk 7600 (radio failure)",
  "icao": "56ff74",
  "sighting_id": 70,
  "callsign": "RCH492",
  "registration": "05-5153",
  "aircraft_type": "C17",
  "closest_approach_nm": 11.2,
  "lowest_altitude_ft": 21000,
  "rule": null,
  "builtin_key": "emergency_7600",
  "notified": false
}
```

`callsign`, `registration` and `aircraft_type` name the aircraft in terms a person
recognises. SPEC §48 requires a notification to carry "callsign/tail, aircraft type,
classification, altitude, distance, match reason", and the history is exactly where
someone looks when they *missed* the notification — a row whose only identification
is `56ff74` does not answer that. Each is `null` per §2.7 when it is genuinely
absent: nothing transmitted a callsign, or no metadata source has heard of this
address. The names are the ones §3.5 and §3.7 already use for the same facts, so one
set of client components renders an alert row, a sighting row and an aircraft row.

`closest_approach_nm` and `lowest_altitude_ft` are the **sighting's** records, not a
snapshot taken at the instant of the match: `alert_matches` stores no position of its
own, and these are the nearest true answer to "how close, how low was it". On a
sighting still open they keep moving between reads.

`reason` remains the single statement of *what matched*. A client rendering a row
should not also print `rule.name` beside it — for a rule match the two are the same
string, because the stored reason is `"Rule: " + rule.name`. `rule` is there to link
to the rule and to survive a rename, not to be shown twice.

`rule_id` narrows the history to one user rule — the per-rule drill-down the Alerts
page offers next to each rule. It is a **filter, not a lookup**: an id that names no
rule (including a rule deleted while a page held its id) returns an empty page with
`200`, never a `404`, because "this rule has caught nothing" and "this rule is gone"
render the same. It combines with every other filter and with pagination, and because
a built-in match carries no rule at all (`rule: null`), any `rule_id` excludes the
built-ins. A non-integer or non-positive value is the §2.5 `422`.

`notified` is delivery state, and it means one specific thing: **at least one
FlightSite client actually showed a browser `Notification` for this match**. It is
asserted by that client, once, immediately after the notification was constructed
(`POST /api/internal/alerts/matches/{id}/notified`, §5) — never by the server when it
broadcasts the event. A frame accepted by a socket is not a notification a person
saw: permission may be denied, the severity may be muted, the tab may already have
shown that event. A match that was recorded but never notified therefore stays
`false`, which is the honest answer rather than a missing one.

The `alert_triggered` and `emergency_squawk` activity events carry `match_id` on
their payload — the `alert_matches` row the event is about. It is what lets a client
holding a live event name the match it needs to mark notified; every other payload
member is described where its producer builds it.

**Emergency sources (slice 086).** A built-in emergency is raised by an emergency
squawk *or* by the decoder's emergency state (§3.3 `decoder_emergency`) — an aircraft
declaring `nordo` on an ordinary squawk alerts exactly as 7600 would, at `critical`,
once per sighting. Built-in keys name the emergency's kind, and a kind a squawk also
declares keeps that squawk's key, so the full set is `emergency_7500`,
`emergency_7600`, `emergency_7700`, `emergency_minfuel`, `emergency_lifeguard` and
`emergency_downed`; a squawk and a decoder reporting the same emergency are one match,
never two, and when both declare at once the squawk is the one named. The
`emergency_squawk` event keeps its type for both sources and adds `emergency_source`
(`squawk` | `decoder`) and `emergency_kind` (§2.8) to its payload; its `squawk` is the
emergency code, `null` for a decoder-declared emergency. The match `reason` names the
source: `"Emergency squawk 7600 (radio failure)"` or `"Decoder emergency state: no
radio"`.

### 3.11 Diagnostics — slice 042

`GET /api/v1/diagnostics`

Everything in SPEC §67: decoder connection state and last successful update, database
health/size/row counts, free disk space, backend uptime, versions, metadata source
ages, recent error ring buffers (ingestion/db/enrichment/websocket/feeders), WebSocket
client count. **Never contains secrets** (tested requirement).

Top-level sections: `status` (`ok`/`degraded`/`down`, the roll-up the health banner
renders), `ready` + `subsystems`, `versions`, `uptime`, `decoder`, `live`,
`live_events` (slice 075), `database` (`quick_check`, `storage`, `row_counts`,
`maintenance`, `recovery`), `metadata`, `notifications`, `enrichment`, `websocket`,
`feeders` (slice 077), `self_alerts` (slice 088), `counters`, `recent_errors`.

Read-only in the strong sense: no writer session, and no fresh `quick_check` — that
pragma takes the writer lock, so the endpoint reports the result the maintenance
scheduler already computed rather than imposing a file walk on a running receiver.

Two contract details worth knowing:

- `decoder.state` distinguishes `unconfigured` (a first-run install with no receiver
  yet) from `down` (a receiver that should be answering and is not). Rendering the
  first as an outage would be wrong.
- `feeders` (slice 077) counts the configured feeders by state and reports the
  optional Docker socket — counts only, the per-feeder detail is `GET /api/v1/feeders`:

  ```json
  "feeders": {"configured": 6, "up": 4, "degraded": 1, "down": 0, "unknown": 1,
              "docker_socket": "available"}
  ```

  `up + degraded + down + unknown == configured`. Any `down` rolls `status` up to
  `degraded`, never to `down` — FlightSite itself is still receiving. `docker_socket` is
  `unset` when `feeders.docker_socket` is not configured, otherwise `available` or
  `unreachable`; the path is never published. `recent_errors` gains a `feeders`
  category (loggers under `flightsite.feeders`) and `counters` a
  `feeder_poll_failures` counter.
- `self_alerts` (slice 088) reports each receiver self-alert condition and what is
  active now — thresholds, states and timestamps only:

  ```json
  "self_alerts": {
    "conditions": {
      "decoder_down": {"enabled": true, "state": "ok", "minutes": 5},
      "message_rate": {"enabled": true, "state": "learning", "minutes": 15,
                       "share_pct": 40, "baseline_msgs_s": 84.2, "baseline_weeks": 1},
      "feeder_offline": {"enabled": true, "state": "active", "count": 1}
    },
    "active": [
      {"condition": "feeder_offline", "since": "2026-09-29T02:00:00Z",
       "severity": "high", "subject": "fr24", "label": "FlightRadar24"}
    ]
  }
  ```

  `state` is `disabled`, `ok`, `pending` (a bad run that has not yet lasted its
  minimum), or `active`; `message_rate` reports `learning` (fewer than two weeks of
  this hour-of-week recorded) or `quiet` (a usual rate under 1 msg/s) in place of `ok`.
  `since` is when the condition began. `subject`/`label` name the feeder for
  `feeder_offline` and are `null` otherwise. The block does not move `status`: the
  decoder and feeder sections already do. `null` only from an app built without the
  monitor (a test harness).
- `notifications` carries only what the server can know — the configured severities —
  and `permission_known_by` is always `"client"`. Browser permission is unobservable
  from the backend, so the health page joins this with the frontend notification store
  (slice 040) to show the permission the user actually granted.
- `enrichment` carries `budget` and `cache` alongside the failure counters (slice 070):

  ```json
  "enrichment": {
    "enabled": true, "provider": "aerodatabox", "running": true,
    "circuit_open": false,
    "lookups": 308, "dropped": 0, "pending": 2, "failures": 0,
    "budget": {
      "limit": 500, "used_today": 137, "remaining": 363,
      "resets_at": "2026-09-05T00:00:00.000Z"
    },
    "cache": {
      "hits": 4112, "misses": 308, "learned": 57,
      "stale_served": 0, "directory_hits": 1904
    }
  }
  ```

  `enabled` and `provider` answer two different questions since slice 071. `enabled`
  says route lookup is **operating** — which the offline route directory alone
  satisfies, so an install that has imported the `routes` dataset and holds no API key
  reports `enabled: true, provider: null` and enriches happily from its own tables.
  `provider` names the **online** provider (`"aerodatabox"`) or is `null`. A client that
  reads `enabled` as "an API key is configured" will misreport a directory-only install;
  read `provider` for that.

  `limit` and `remaining` are `null` on an uncapped install (`daily_lookup_budget: 0`,
  the default) — which is not the same as `0`: one means there is no ceiling, the other
  means today's ceiling has been reached. `used_today` counts route-cache rows fetched
  in the current UTC day, so it survives a restart, and `resets_at` is the next UTC
  midnight. The budget, the priority order and the circuit breaker govern **provider
  requests only** — a directory hit is free and is unaffected by a spent budget or an
  open circuit. `cache.learned` is the number of cached routes confirmed on enough
  separate days to be frozen for 30 days ([DATA_MODEL.md §7](DATA_MODEL.md)).

  The three ways a lookup can be answered are counted separately and do not overlap:
  `cache.hits` is the route cache (in memory or in the table), `cache.directory_hits`
  is the offline route directory, and `cache.misses` is what had to reach the provider.
  `directory_hits` is deliberately not folded into `hits` — both are free, but only one
  of them says the imported routes dataset is earning its place. On a key-less install
  it is also the only one that ever counts a *new* answer: `misses` never moves at all,
  and `hits` records only the repeat sightings of what the directory already supplied.

  `cache.stale_served` (slice 071) counts expired routes that were kept on their
  sightings because nothing could refresh them — the day's budget spent, the circuit
  breaker open, a 429, a timeout, or, on an install with no API key, nobody left to ask
  once the directory has come up empty. The routes on screen are still real, but they are
  the last ones a source reported, so a number that climbs is the signal that something
  upstream has been unavailable. Each serve pushes that row's expiry a day out, so this
  counts callsigns rather than observations.
- `live_events` attributes shed live events to the consumer that shed them (slice 075):

  ```json
  "live_events": {
    "published": 1284310,
    "dropped": 18061,
    "subscribers": [
      {"name": "alerts", "dropped": 7200, "pending": 0, "capacity": 4096, "overflowed": false},
      {"name": "persistence", "dropped": 10861, "pending": 3, "capacity": 4096, "overflowed": false},
      {"name": "websocket", "dropped": 0, "pending": 0, "capacity": 4096, "overflowed": false}
    ]
  }
  ```

  Each consumer of the live event stream — `persistence`, `alerts`, `websocket`,
  `enrichment`, `airports`, `metadata-cache` — reads it through a bounded queue and is
  shed rather than waited on when it falls behind
  ([ARCHITECTURE.md §3.1](ARCHITECTURE.md)). `dropped` is that consumer's cumulative
  total, kept **by name** so it survives the service stopping and resubscribing;
  `pending` against `capacity` is the backlog right now; `overflowed` is `true` only
  while the consumer has an unacknowledged gap and is resyncing from a snapshot.
  `subscribers` lists the consumers attached at the moment of the request, sorted by
  name, so a service that has been stopped is absent while its drops remain in
  `dropped`. Shedding is self-healing by design, so nothing in this section moves the
  top-level `status`.

  Since slice 075, `websocket.events_dropped` is the **`websocket` subscriber's own**
  figure, and `0` on an install whose browser feed has never fallen behind. It
  previously carried the process-wide `live_events_dropped` counter, which reported
  every consumer's drops under the one name that had a card on the Health page — on the
  reference Pi that displayed 18 061 events shed by the persistence and alert queues
  during a metadata import as if the browser feed had lost them (issue #185). The
  process total is unchanged and still published twice: as `counters.live_events_dropped`
  (also on `GET /api/v1/health`) and as `live_events.dropped`, which is the sum of the
  per-subscriber tallies.
- `database.maintenance.vacuum_refusal` is `null` unless the guarded `VACUUM` last
  declined to run, and otherwise carries `reason` plus `required_free_bytes` and
  `available_free_bytes`. The free-space guard wants twice the database size, so on a
  multi-year history it can be refused permanently rather than until tonight — the two
  byte counts are what let the Health page say which (issue #116). A refusal does not
  move `database.status`: declining to rewrite a healthy database is the policy
  working, not a degradation.

Secrets are redacted twice on the way out: once as each error is captured into the
ring buffer, and once over the whole assembled payload, both against the configured
`SecretStr` values discovered by type. A secret that reached a log record by mistake
still cannot reach this response.

### 3.12 Feeders — slice 077

| Path | Returns |
|---|---|
| `GET /api/v1/feeders` | Every configured feeder's current state, the receiver's uplink summary, and the local-pages list. |
| `GET /api/v1/feeders/{name}/history` | One feeder's episodes, samples and availability. Param: `window=24h\|7d\|30d` (default `24h`). `404 not_found` for a name that is not configured, `422 invalid_window` for any other window — both in the §2.5 envelope. |

Feeders are the networks the receiver streams to (FlightAware, FlightRadar24, ADS-B
Exchange, AeroDataBox, OpenSky, ...), configured as `feeders.entries[]`
([CONFIGURATION.md](CONFIGURATION.md)) and polled every `feeders.poll_interval_s` by
the feeder service. `GET /feeders` is answered from memory — it is what the last poll
found — so it is cheap to poll at the page's 10-second cadence. An install with no
feeders configured answers `200` with an empty `feeders` list, never `404`.

```json
{
  "generated_at": "2026-09-26T14:13:20.000Z",
  "poll_interval_s": 15.0,
  "docker_socket": "available",
  "receiver": {
    "bytes_out_rate_per_s": 3012.5, "messages_per_min": 31234, "positions_per_min": 5620,
    "aircraft": 49, "aircraft_with_pos": 37, "mlat_inbound": 3, "samples_dropped": 0,
    "max_range_nm": 212.7, "gain_db": 43.9, "signal_db": -17.4, "noise_db": -31.6,
    "uptime_s": 864000.2, "updated_at": "2026-09-26T14:13:19.600Z"
  },
  "feeders": [
    {
      "name": "adsbx", "label": "ADS-B Exchange", "kind": "ultrafeeder",
      "state": "up", "observability": "docker",
      "since": "2026-09-26T09:00:04.000Z",
      "last_polled_at": "2026-09-26T14:13:20.000Z",
      "last_success_at": "2026-09-26T14:13:20.000Z",
      "last_data_sent_at": "2026-09-26T14:13:20.000Z",
      "message": null,
      "mlat": {"peers": 14, "good_sync_pct": 93.4, "bad_sync_timeout_s": 0.0, "last_bad_sync_at": null},
      "adsb_out": {"connected": true, "since": "2026-09-20T09:00:01.000Z"},
      "detail": {"host": "feed.adsbexchange.com", "outlier_pct": 0.8},
      "web_url": null,
      "stats_link": true
    }
  ],
  "local_pages": [{"label": "tar1090", "url": "http://fermi.local:8080/"}]
}
```

- **`state`** is `up`, `degraded`, `down` or `unknown`. `unknown` means FlightSite
  cannot see the feed — no Docker socket for a log-only signal, a statistics block gone
  quiet, a `link_only` entry — and is never a softer `down`. `down` is committed only
  after **two consecutive** `down` readings, so one dropped request never shows as an
  outage. `since` is when the current state began (`null` before the first poll).
- **`observability`** says where the state was read: `http` (the network's own status
  document), `docker` (container logs or health through the opt-in socket), or `none`.
- **`mlat`** and **`adsb_out`** are `null` for kinds that do not have them, and
  `adsb_out` is `null` for `ultrafeeder` entries whenever the Docker socket is unset.
  `adsb_out.connected` is `null` when the socket is set but the state cannot be read:
  no transition line in the container's log, or a log that has gone silent for an hour
  (slice 101 — a months-old "disconnected" or "established" line is not the state when
  ultrafeeder's `LOGLEVEL` stops it logging the next one). The feeder is then judged
  on MLAT and `message` says so; `since` keeps the last transition's time.
  An MLAT client with zero peers reads `degraded` only after three consecutive polls,
  and never `down`. `mlat.good_sync_pct` is a percentage, 0–100, over the client's
  last hour.
- **`detail`** is a flat object of scalars whose keys depend on `kind`; it is built at
  the source from an allowlist, so an identity field never enters it.
- **`docker_socket`** is `unset` (no `feeders.docker_socket`), `available`, or
  `unreachable` (configured but not answering).
- **`receiver`** is `null` unless a `readsb` entry is configured and has answered.
  `bytes_out_rate_per_s` is to all network connectors together and is `null` until two
  polls have been differenced; `aircraft` counts every tracked aircraft and
  `mlat_inbound` those positioned by multilateration results coming back in.
- **`stats_link`** is a boolean: whether the internal stats-link redirect (§5) has
  somewhere to send the browser. The per-network stats URL itself is a secret — it
  names the owner's account — and is **never** part of any `/api/v1` response.

`GET /feeders/{name}/history`:

```json
{
  "episodes": [
    {"state": "up", "started_at": "2026-09-26T13:40:00.000Z", "ended_at": "2026-09-26T14:00:15.000Z"},
    {"state": "down", "started_at": "2026-09-26T14:00:15.000Z", "ended_at": "2026-09-26T14:03:00.000Z"},
    {"state": "up", "started_at": "2026-09-26T14:03:00.000Z", "ended_at": null}
  ],
  "samples": [{"t": "2026-09-26T14:13:00.000Z", "state": "up", "metrics": {"mlat_peers": 14, "good_sync_pct": 93.4, "adsb_out_connected": 1}}],
  "availability_pct": 98.51
}
```

- `episodes` are every stored span overlapping the window, oldest first, with
  `started_at` **unclipped** (a client clips to the window it draws). The current
  episode has `ended_at: null`.
- `samples` are one per feeder per minute, bucketed to at most one point per minute
  (`24h`), 10 minutes (`7d`) or 30 minutes (`30d`) — the latest sample in each bucket.
  Samples are retained 14 days and episodes 90 days
  ([DATA_MODEL.md](DATA_MODEL.md) §6.6), so the `30d` window has samples for its most
  recent fortnight only.
- `metrics` keys by kind: `readsb` — `bytes_out_rate_per_s`, `messages_per_min`,
  `positions_per_min`, `aircraft_with_pos`, `mlat_inbound`; `ultrafeeder` —
  `mlat_peers`, `good_sync_pct`,
  `adsb_out_connected` (1/0); `fr24` — `aircraft_sent`, `messages`; `piaware` —
  `cpu_temp_c`; `opensky_logs` — `bytes_out_rate_per_s`, `availability_pct`,
  `disconnections`. A `null` or missing key is a gap, never a zero.
- `availability_pct` is the share of the **observed** part of the window spent `up` or
  `degraded`. `unknown` time, and time no episode covers (FlightSite not running), is
  excluded rather than counted against the feed; `null` when nothing in the window
  was observed.

---

## 4. WebSocket Protocol — `/api/v1/ws/live` (slice 010)

One WebSocket carries the live picture and activity events. The base protocol
(snapshot, delta, keepalive/resync) ships in slice 010; the activity frame type
(§ 4.4) is added by slice 035 and becomes the batched `activity_batch` in slice 057.

### 4.1 Message envelope

Every server→client frame is JSON:

```json
{ "type": "<message-type>", "seq": 1042, "ts": "2026-08-31T14:03:22.418Z", "data": { ... } }
```

`seq` is a per-connection monotonically increasing integer; a gap tells the client it
missed frames and must resync (§ 4.5).

### 4.2 Connect → snapshot

On connect the server immediately sends:

```json
{ "type": "snapshot", "seq": 1, "ts": "...", "data": {
    "aircraft": [ /* full aircraft objects, § 3.3 shape */ ],
    "receiver": { /* § 3.2 shape */ }
} }
```

### 4.3 Deltas (~1 Hz batches)

```json
{ "type": "delta", "seq": 2, "ts": "...", "data": {
    "updated": [ /* full aircraft objects for new + changed aircraft */ ],
    "stale":   [ "ae1463" ],
    "removed": [ "a9c2f0" ]
} }
```

- `updated` entries are complete aircraft objects (not field patches) — simple,
  robust, and cheap at 500-aircraft scale with batching.
- `stale` lists ICAOs crossing the staleness threshold; `removed` lists ICAOs leaving
  live display. Interesting-status changes arrive as normal `updated` entries plus an
  `activity_batch` frame when an alert fires.

### 4.4 Activity events — added by slice 035, batched by slice 057

```json
{ "type": "activity_batch", "seq": 3, "ts": "...", "data": [
    /* one or more activity events, § 3.9 shape, oldest first */
] }
```

Drives the live activity feed and browser notifications (phase 6). Clients built
against the slice-010 protocol ignore this frame type until they support it (§ 6).

- **One frame per activity-detector pass**, carrying everything that pass recorded,
  the same way a `delta` carries a whole tick. `data` is always an **array**, even
  for a single event; a pass that recorded nothing sends no frame. At most 128
  events go in one frame, so a pathological pass sends a few frames rather than one
  enormous one.
- Batching exists because the per-event form did not survive a first run: on a new
  database every aircraft is a first-ever sighting, so one 5-second pass emitted a
  burst larger than a client's outbound queue and § 4.5's slow-consumer rule evicted
  every connected client (measured in `docs/PERFORMANCE.md` § 6).
- **The singular `activity` frame type is retired.** The server no longer sends it.
  A client written against slice 035 ignores `activity_batch` per § 6 — it stops
  receiving live events until updated, and its `GET /activity` feed (§ 3.9) is
  unaffected, which is precisely the degradation § 6 is written to make safe.
- There is no replay: these frames are not part of the snapshot/delta picture, and a
  reconnecting client refetches `GET /activity` rather than being re-sent them.
- An `alert_triggered` or `emergency_squawk` event carries `match_id` on its payload
  (§ 3.10), which is what a client that showed a browser notification for it posts
  back to `POST /api/internal/alerts/matches/{id}/notified` (§ 5).
- `feeder_offline` and `feeder_restored` (slice 077) arrive in the same frames with the
  § 3.10 vocabulary and payload; they carry no `match_id` and no aircraft. So do
  `self_alert_raised` / `self_alert_restored` (slice 088), from which the client
  composes the receiver self-alert browser notifications — nothing is posted back.

### 4.5 Keepalive, reconnect, slow consumers

- Server pings every 30 s and drops a client that has sent nothing across 2
  consecutive pings.

  The ping is an **application-level JSON frame** layered over — not instead of —
  the transport ping frames, so that it survives an intermediary proxy that answers
  protocol pings on the client's behalf. It uses the same envelope as every other
  frame:

  ```json
  { "type": "ping", "seq": 9, "ts": "...", "data": {} }
  ```

  **A client is expected to answer it**, with either a JSON frame or a bare string:

  ```json
  { "type": "pong" }
  ```

  Any inbound message resets the counter, so a client that talks for other reasons
  will not be dropped. A client may also send `{"type": "ping"}` at any time and gets
  a `pong` envelope back.

- **Reconnect:** clients reconnect with backoff; every new connection receives a
  fresh `snapshot`. There is no delta replay — the snapshot is the resync mechanism.
- **Slow consumers:** if a client's outbound queue exceeds its bound, the server
  drops the connection rather than buffering unboundedly or stalling other clients
  (SPEC §5: ingestion and distribution must never stall). The client's reconnect
  yields a coherent snapshot. A `ws_disconnect` counter records occurrences.

---

## 5. Internal API (`/api/internal`) — unsupported surface

Undocumented externally; shapes shown to frontend developers via the same FastAPI
app but excluded from published OpenAPI. Mutations validate against the same Pydantic
config/domain models the backend uses.

| Group | Endpoints (sketch) | Slice |
|---|---|---|
| Config & first-run | `GET /config` (secrets fully masked as `"•••"`; per-secret set/unset reported via `secrets_set`; carries the `first_run` flag the frontend uses to decide whether to show the wizard), `PUT /config` (masked values ignored unless replaced; secrets never echoed back). There are no dedicated setup endpoints — the wizard reads `GET /config` and finishes with a single `PUT /config`. A successful save is also *applied*: newly ticked alert templates are instantiated, a first-run save starts decoder ingestion and anchors the live store, and route enrichment is started, stopped or re-keyed to match. An apply step that fails is logged and never fails the save — the configuration is validated, written and live before any of it runs. Which settings apply this way and which still need a restart is [CONFIGURATION.md](CONFIGURATION.md) | 004/018/019 |
| Connection test | `POST /decoder/test` → reachability, parse result, sample aircraft count | 007/018 |
| Watchlists | `GET/POST /watchlists`, `PUT/DELETE /watchlists/{id}`, entries CRUD | 037 |
| Alert rules | `GET/POST /alert-rules`, `PUT/DELETE /alert-rules/{id}`, `GET /alert-templates`, `POST /alert-templates/{key}/rules` (instantiates a shipped template as a rule carrying its `template_key`; empty body — the conditions come from the catalogue, never from the caller; `404` unknown key, `409` built-in or already instantiated) | 038/041 |
| Alert matches | `POST /alerts/matches/{id}/notified` (records that a browser notification was actually shown for one match; empty body — the assertion *is* the request; `204` whether this call marked the row or found it already marked, `404` for an unknown id) | #104 |
| Metadata update | `POST /metadata/update` (starts run), `GET /metadata/status` (per-source status, last success, versions) | 025 |
| Reset | `POST /reset/data` (requires `confirm` token), `POST /reset/metadata-cache` | 045 |
| Feeder stats links | `GET /feeders/{name}/stats-link` → `302` to that feeder's per-network stats page (`feeders.stats_urls.<name>` in `secrets.yaml`; for a `piaware` feeder with none configured, the site page piaware itself reports). `404` when there is no link or no such feeder. `Cache-Control: no-store`, `Referrer-Policy: no-referrer`. The only place a stats URL ever leaves the backend, and only as the `Location` of this response — never in `/api/v1`, a log line or the rendered page; `/api/v1/feeders` carries just `stats_link: true\|false` | 077 |

**Alert-rule conditions** (`conditions` in the `/alert-rules` bodies and payloads;
validated by `flightsite.alerts.model.RuleConditions`, the model the stored
`alert_rules.conditions_json` is parsed with — [DATA_MODEL.md](DATA_MODEL.md) §4.2). A
flat object of optional conditions, **all ANDed** (SPEC §43; no OR, no nesting — §79).
Unknown keys are refused with `422`, as is a set that constrains nothing or can never
match (an inverted window). Every error's `loc` names the field.

| Key | Type | Matches when | Since |
|---|---|---|---|
| `classification` | `{military, government, law_enforcement: bool, mission?}` | every required claim is asserted | v1 |
| `type_code` / `model` | string | exact type designator / model substring, ignoring case | v1 |
| `watchlist_id` / `watchlist_any` | int / bool | on that watchlist / on any | v1 |
| `rare_aircraft` / `rare_type` | `{max_sightings: 1..1000}` | seen at most N times / type on at most N airframes here | v1 |
| `min_distance_nm`, `max_distance_nm` | number, nm (0..10000) | inclusive window | v1 |
| `min_alt_ft`, `max_alt_ft` | number, ft (-2000..100000) | inclusive window, barometric | v1 |
| `squawk_in` | array of 1–16 `"[0-7]{4}"` strings | live squawk is one of them | v2 |
| `callsign_glob` / `registration_glob` | string, 1–32 chars, no whitespace | whole callsign / resolved registration matches, ignoring case; `*` = any run, `?` = one character, everything else literal | v2 |
| `min_ground_speed_kt`, `max_ground_speed_kt` | number, kt (0..2000; max > 0) | inclusive window | v2 |
| `min_vertical_rate_fpm`, `max_vertical_rate_fpm` | number, ft/min (-20000..20000), negative descending | inclusive window | v2 |
| `emitter_category_in` | array of 1–32 `"[A-D][0-7]"` strings | decoder emitter category (slice 086) is one of them | v2 |
| `within_area` | GeoJSON `{"type": "Polygon", "coordinates": [[[lon, lat], ...]]}` | live position inside or on the boundary | v2 |
| `applies_on_ground` | bool | not a condition: lets the rule match ground traffic (SPEC §40) | v1 |

An unknown input never satisfies a condition: no squawk, no callsign, no metadata
registration, no speed or no position is not a match. Sets (`squawk_in`,
`emitter_category_in`) are echoed sorted and de-duplicated. `within_area` takes exactly
one ring of 3–64 distinct vertices, `[longitude, latitude]` (GeoJSON order); an
unclosed ring is closed and the echo is always closed. Refused: a second ring (holes),
an edge spanning more than 180° of longitude (antimeridian crossing — draw one rule
each side), crossing or folding edges, repeated vertices and collinear rings. Edges are
straight in longitude/latitude; a point on the boundary is inside.

`version` is `2`. A body may still send `"version": 1` (or omit it) — a v1 document is
a v2 document without the new keys and is upgraded on read — but `"version": 1` with a
v2 key is a `422`, and the response is always `"version": 2`. Stored v1 rows are not
migrated: they read back as v2 and are rewritten as v2 the next time the rule is saved.
`describes` gains one phrase per new condition, after the v1 phrases, in canonical units:
`"squawking 1200 or 7000"`, `"callsign matching 'RCH*'"`, `"registration matching
'N?23AB'"`, `"emitter category A1 or A7"`, `"ground speed at most 250 kt"`, `"vertical
rate at or above -3000 ft/min"`, `"inside a drawn area of 4 vertices"`. A match's
`reason` is still `"Rule: <name>"`.

`GET /metadata/status` reports one row per **registered** source, each with its own
`status`, `last_success_ms`, `dataset_version`, `row_count` and `last_error`, and each
independent of the others (SPEC §27). A stock install registers four —
`airports`, `faa`, `mictronics`, `routes` — and a fifth, `opensky`, appears only where
`metadata.opensky_enabled` is set (ADR-0013). Two of them are not aircraft metadata:
`airports` is slice 027's airport dataset and `routes` is slice 071's offline route
directory ([ADR-0016](adr/0016-offline-route-directory.md)), whose `row_count` is the
number of callsigns it knows a route for and whose `dataset_version` is the SHA-256 of
the archive it was imported from. Clients must tolerate sources they do not recognise:
the list is what this build ships, not a fixed vocabulary.

Backup and restore have **no HTTP surface at all**, internal or external: they are
CLI operations (`flightsite-backup`, see `docs/BACKUP.md`), deliberately, so that a
restore cannot be triggered by anything reachable from a browser.

Note that this surface also carries pure reads (`GET /config`,
`GET /metadata/status`, `GET /watchlists`, `GET /alert-rules`). ADR-0007 splits on
*audience*, not on HTTP method: `/api/internal` is "mutations plus frontend-only
conveniences", and everything under `/api/v1` is read-only. `POST /decoder/test` is
the mirror-image case — a POST that mutates no state, but performs an outbound
network probe on the caller's behalf.

Secret-handling rules (SPEC §29): secret fields are write-only through the API;
reads return masked placeholders; logs and diagnostics never include them.

---

## 6. Compatibility Policy

- Within v1 (`0.x` → `1.0`), `/api/v1` may **add** fields and endpoints freely;
  clients must tolerate unknown fields. Removing/renaming fields or changing
  semantics requires a deprecation note in release notes and is avoided after
  `v1.0.0`.
- The WebSocket message set may add new `type`s; clients must ignore unknown types.
  *Retiring* a `type` follows the field rule above — a note in the release notes,
  and avoided after `v1.0.0`. The singular `activity` frame was retired pre-1.0 by
  slice 057 in favour of `activity_batch` (§ 4.4); ignoring the unknown replacement
  is what makes an un-updated client degrade to its REST feed instead of breaking.
- `/api/internal` carries no compatibility promise.

---

*Slice mapping and delivery order: `planning/roadmap.yaml`. Data shapes derive from
`docs/DATA_MODEL.md`; architecture context in `docs/ARCHITECTURE.md`.*
