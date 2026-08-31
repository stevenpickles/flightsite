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

- `total` MAY be omitted or approximate on large collections (`/aircraft`,
  `/sightings`) — an exact filtered `COUNT(*)` per page is too expensive at
  multi-year scale on Pi-class hardware. Endpoints that can compute it cheaply
  return it exactly; clients must not rely on `total` for anything beyond display.

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
  "route": { "origin": "KATL", "destination": "KSLC" },
  "provenance": {
    "operator": "mictronics",
    "registration": "faa",
    "route": "aerodatabox",
    "nearest_airport": "heuristic",
    "distance_nm": "derived"
  }
}
```

Provenance values: `decoder` | `derived` | `mictronics` | `faa` | `aerodatabox` |
`heuristic`. Fields without an entry are decoder-direct. Position source is a
separate, always-present field (§ 3.3) because it is safety-relevant display state,
not enrichment.

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
| Provenance values | `decoder` \| `derived` \| `mictronics` \| `faa` \| `aerodatabox` \| `heuristic` |
| Alert severity | `info` \| `interesting` \| `high` \| `critical` |

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
{ "status": "ok", "version": "0.3.1", "uptime_s": 86211 }
```

`/ready` returns `503` with `{"status": "starting"}` until ready.

### 3.2 Receiver info — slice 010

`GET /api/v1/receiver`

Non-secret receiver identity and configuration snapshot: site name, latitude,
longitude, antenna height, configured timezone, units preference, display/alert
radius, demo-mode flag, T0.

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
  "provenance": {
    "registration": "mictronics",
    "operator": "mictronics",
    "classification": "mictronics",
    "distance_nm": "derived"
  }
}
```

- `position_source`: `adsb` | `mlat` | `none` | `other` (SPEC §21). Non-positioned
  aircraft have `position: null`, `position_source: "none"`.
- `state`: `live` | `stale` (past the 15 s threshold, not yet removed).
- `emergency`: `null` | `"7500"` | `"7600"` | `"7700"`.
- `interesting`: `null` when no active alert match (fields populated from phase 6).

### 3.4 Interesting aircraft — slice 038/039

`GET /api/v1/aircraft/interesting`

Currently-matching aircraft, sorted severity → distance, each with match reasons and
severity. Same aircraft object shape, `interesting` always non-null.

### 3.5 Aircraft history — slice 029

| Method & path | Purpose |
|---|---|
| `GET /api/v1/aircraft` | Paginated historical aircraft list. Sort keys: `registration`, `icao`, `type`, `operator`, `classification`, `first_seen`, `last_seen`, `sighting_count`, `closest_approach_nm`, `max_range_nm`. Filters: `classification`, `operator_group`, `type`. |
| `GET /api/v1/aircraft/{icao}` | Full aircraft detail: identity, metadata with provenance, classification, lifetime records. |
| `GET /api/v1/aircraft/{icao}/sightings` | Paginated sightings for one aircraft. |

Lifetime record block (SPEC §53):

```json
{
  "first_seen": "2026-04-02T18:11:09Z",
  "last_seen": "2026-08-30T22:41:55Z",
  "sighting_count": 41,
  "cumulative_duration_s": 51840,
  "closest_approach_nm": 2.1,
  "max_range_nm": 141.8,
  "lowest_altitude_ft": 1250,
  "highest_altitude_ft": 41000
}
```

### 3.6 Sightings — slice 030

| Method & path | Purpose |
|---|---|
| `GET /api/v1/sightings` | Chronological log. Filters: `icao`, `from`, `to`, `interesting=true`. Sort: `started_at` (default desc), `duration_s`, `closest_approach_nm`, `max_range_nm`. |
| `GET /api/v1/sightings/{id}` | Sighting detail: flight context, reception stats, events, simplified path. |

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
  "closure_reason": "gap_timeout",
  "route": { "origin": "KTCM", "destination": "PHIK" },
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
SPEC §19). Active sightings return the live full-resolution track instead and
`ended_at: null`.

### 3.7 Analytics — slice 031

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
| `GET /api/v1/analytics/rarity` | Never-seen-before counts, locally rare aircraft/types. |

### 3.8 Receiver statistics — slices 033/034

| Path | Returns |
|---|---|
| `GET /api/v1/receiver/scorecard` | SPEC §61 scorecard (current visible, msgs/s, pos/s, ranges, uniques, uptimes, health summary). |
| `GET /api/v1/receiver/metrics` | Time-series metrics. Params: `metric` (`messages_per_s`, `positions_per_s`, `aircraft_count`, `max_range_nm`, ...), `resolution=high|hourly|daily`, `from`/`to`. |
| `GET /api/v1/receiver/range-by-bearing` | Polar max-range histogram (buckets of bearing → max nm). |
| `GET /api/v1/receiver/signal-distribution` | RSSI distribution histogram, derived from per-sighting `rssi_*_db` reception stats over the selected window. |
| `GET /api/v1/receiver/lifetime` | SPEC §63 lifetime statistics since T0. |

### 3.9 Activity & alert history — slices 035/038

| Path | Returns |
|---|---|
| `GET /api/v1/activity` | Paginated chronological activity feed. Filter: `type`, `from`, `to`. Event types per SPEC §55 (`alert_triggered`, `first_ever_aircraft`, `new_type`, `range_record`, `receiver_record`, `emergency_squawk`, `receiver_offline`, `receiver_restored`, `metadata_updated`, `milestone`). |
| `GET /api/v1/alerts/matches` | Alert match history: rule, aircraft, sighting, severity, reason, matched_at. |

### 3.10 Diagnostics — slice 042

`GET /api/v1/diagnostics`

Everything in SPEC §67: decoder connection state and last successful update, database
health/size/row counts, free disk space, backend uptime, versions, metadata source
ages, recent error ring buffers (ingestion/db/enrichment/websocket), WebSocket client
count. **Never contains secrets** (tested requirement).

---

## 4. WebSocket Protocol — `/api/v1/ws/live` (slice 010)

One WebSocket carries the live picture and activity events. The base protocol
(snapshot, delta, keepalive/resync) ships in slice 010; the `activity` frame type
(§ 4.4) is added by slice 035.

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
  `activity` frame when an alert fires.

### 4.4 Activity events — added by slice 035

```json
{ "type": "activity", "seq": 3, "ts": "...", "data": { /* activity event, § 3.9 shape */ } }
```

Drives the live activity feed and browser notifications (phase 6). Clients built
against the slice-010 protocol ignore this frame type until they support it (§ 6).

### 4.5 Keepalive, reconnect, slow consumers

- Server pings every 30 s (WebSocket ping frames); a client missing 2 pings is
  dropped.
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
| Setup / first-run | `GET /setup/state`, `POST /setup/complete` | 018 |
| Config | `GET /config` (secrets fully masked as `"•••"`; per-secret set/unset reported via `secrets_set`), `PUT /config` (masked values ignored unless replaced; secrets never echoed back) | 004/019 |
| Connection test | `POST /decoder/test` → reachability, parse result, sample aircraft count | 007/018 |
| Watchlists | `GET/POST /watchlists`, `PUT/DELETE /watchlists/{id}`, entries CRUD | 037 |
| Alert rules | `GET/POST /alert-rules`, `PUT/DELETE /alert-rules/{id}`, `GET /alert-templates` | 038/041 |
| Metadata update | `POST /metadata/update` (starts run), `GET /metadata/status` (per-source status, last success, versions) | 025 |
| Backup status | `GET /backup/info` (last backup manifest summary; backup/restore themselves are CLI operations) | 043 |
| Reset | `POST /reset/data` (requires `confirm` token), `POST /reset/metadata-cache` | 045 |

Secret-handling rules (SPEC §29): secret fields are write-only through the API;
reads return masked placeholders; logs and diagnostics never include them.

---

## 6. Compatibility Policy

- Within v1 (`0.x` → `1.0`), `/api/v1` may **add** fields and endpoints freely;
  clients must tolerate unknown fields. Removing/renaming fields or changing
  semantics requires a deprecation note in release notes and is avoided after
  `v1.0.0`.
- The WebSocket message set may add new `type`s; clients must ignore unknown types.
- `/api/internal` carries no compatibility promise.

---

*Slice mapping and delivery order: `planning/roadmap.yaml`. Data shapes derive from
`docs/DATA_MODEL.md`; architecture context in `docs/ARCHITECTURE.md`.*
