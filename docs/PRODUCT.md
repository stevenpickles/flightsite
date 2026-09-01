# FlightSite — Product Definition

> Derived from the governing specification, [`planning/SPEC.md`](../planning/SPEC.md).
> Section references (§) point to that document. The canonical execution plan is
> [`planning/roadmap.yaml`](../planning/roadmap.yaml).

## 1. Vision

FlightSite is an open-source, self-hosted ADS-B observability, visualization,
analytics, history, and interesting-aircraft notification platform for homelab users
(§4). It is a **personal aircraft observatory for the user's own ADS-B receiver** — not
another global flight-tracking network.

The core question FlightSite answers:

> **What is my receiver seeing, what has it seen historically, how unusual is what I am
> seeing now, and is anything particularly interesting happening?**

FlightSite should feel like a live radar application with analytics, not an analytics
dashboard that happens to contain a map (§10).

## 2. Target User & Deployment

- Homelab operator running their own ADS-B receiver with `readsb` or `dump1090-fa`
  (§11). FlightSite does not decode RF itself in v1.
- Minimum supported hardware: **Raspberry Pi 4** on Raspberry Pi OS 64-bit; also runs
  on any Linux Docker host. Images published for `linux/arm64` and `linux/amd64` (§5).
- Deployed via Docker Compose as two containers (frontend, backend) with all
  persistent state in a host bind mount at `/opt/flightsite/data` (§6). No separate
  database container; SQLite is the only store (§7, §69).
- One receiver per deployment in v1 (§12); receiver location is manually configured
  and anchors all receiver-relative measurements (§13).
- Trusted-LAN deployment; no built-in authentication in v1. Direct public-internet
  exposure is not supported securely by default (§75).
- Load envelope: ~500 simultaneously visible aircraft at ~1 Hz decoder updates,
  several years of history, backend memory comfortably below 1 GB (§5).

## 3. Product Pillars

1. **Live Map** — the primary experience: polished, map-centric live radar (§10, §32–§37).
2. **Aircraft identity & metadata** — rich identification from offline metadata (Mictronics/tar1090, optional FAA), classification, operator normalization, optional online route enrichment (§23–§28, §38–§39).
3. **History** — long-term sightings, simplified tracks, lifetime aircraft records, retained indefinitely (§17–§19, §51–§53, §65).
4. **Analytics** — aircraft and traffic analytics over configurable time windows since T0 (§58–§59).
5. **Receiver analytics** — first-class receiver performance visibility: scorecard, charts, range-by-bearing, lifetime statistics (§60–§64).
6. **Interesting-aircraft detection** — watchlists, a visual rule engine, receiver-relative rarity, emergency squawks, severity levels, browser notifications (§42–§49).
7. **Records & activity** — milestones, receiver records, and a chronological activity feed answering "what happened while I wasn't watching?" (§54–§55).
8. **Health & operations** — diagnostics without SSH, backup/restore, maintenance, unclean-shutdown tolerance (§67–§73).

## 4. v1 Feature Inventory

### 4.1 First-Run Setup (§31)

A short wizard collecting: receiver site name, latitude, longitude, decoder JSON
endpoint with live connection test, polling interval, units, timezone, browser
notification preference, optional aircraft metadata setup, optional AeroDataBox API
key, and initial interesting-aircraft alert template selections. Lands directly on the
Live Map when complete.

### 4.2 Live Map (§10, §18, §20–§21, §32–§37, §47, §49, §59)

- MapLibre-based map with abstracted tile provider, multiple selectable basemaps, dark
  aviation-style default, opportunistic caching of recently used tiles; core function
  survives tile outage (§32).
- Aviation overlays: airports, airspace boundaries, receiver range rings (§33).
- Live aircraft with hierarchical silhouette icons (specific type → category →
  generic), rotated to heading; extensible, license-documented icon set (§34).
- Labels (callsign → tail fallback, operator, altitude, interesting indicator) with
  priority-based decluttering; no marker clustering (§35).
- Styling: neutral default, strong selection highlight, distinct attention styling for
  interesting/alerting aircraft, optional category styling for
  military/government/police, stale-aircraft fading; severity never communicated by
  color alone (§36).
- Live lifecycle defaults (configurable): 15 s → stale, 60 s → removed from live
  display, 10 min absent → sighting closed (§18).
- Position source clearly distinguished: direct ADS-B, MLAT-derived, Mode
  S/no-position, unknown/other (§21).
- Non-positioned aircraft list: aircraft without valid positions remain first-class —
  visible in a compact list with ICAO, callsign, altitude, squawk, signal; they
  participate in alerts, activity events, and historical sightings (§20).
- Filter drawer: altitude range, distance, category/type, exact operator, operator
  group, military/government/police classification, mission category,
  interesting-only, live-set callsign/tail/ICAO narrowing, hide non-positioned, hide
  ground traffic, staleness; plus quick filter chips (§37).
- Interesting-aircraft panel sorted by severity then distance, click-to-select (§49).
- Today at a Glance summary: unique aircraft, sightings, interesting count,
  military/government/police, max range, busiest hour, new aircraft, new
  milestones/records (§59).
- Activity feed access (§55).

### 4.3 Aircraft Detail (§22–§24, §41, §50)

Comprehensive detail for any selected aircraft: callsign, registration, ICAO, type,
model, manufacture year, age, operator, normalized operator group, owner,
classification, mission/use, altitude, speed, heading, distance, bearing, squawk,
signal strength, message count, last-seen age, position source, field provenance,
first/last seen, total sightings, cumulative visible time, closest approach, farthest
detection, lowest/highest altitude, route, origin, destination, nearest airport,
arrival/departure inference (clearly labeled as inferred, §41), current sighting
track, and external tracker links to FlightRadar24, FlightAware, and ADS-B Exchange
using the best available identifier (§24). Unknown values render as `Unknown` — never
fabricated. Field provenance is exposed with unobtrusive indicators/tooltips (§22).

### 4.4 Aircraft Page (§56)

Sortable table (no global search in v1): tail number, ICAO, type/model, operator,
classification, first seen, last seen, sighting count, closest approach, farthest
detection. Rows open aircraft detail.

### 4.5 Sightings Page (§51–§52, §57)

Chronological log: start, end, duration, tail/callsign, type, operator,
classification, closest approach, maximum range, lowest/highest altitude, position
count, alert/interesting status. Opening a sighting shows its detailed summary,
per-sighting reception statistics (§51), meaningful sighting events (§52), and the
simplified path. No animated playback in v1 (schema preserves enough for it later,
§19).

### 4.6 Analytics Page (§58)

Time presets: Today, Last 7 Days, Last 30 Days, This Year, Since T0. Analytics: most
frequently seen aircraft; most frequently seen types/models; most common operators;
military/government/police activity; daily aircraft count; daily sighting count;
maximum detection distance; receiver activity over time; first-seen/last-seen
information; count of never-previously-seen aircraft; locally rare aircraft/type
information. No period-over-period comparison in v1.

### 4.7 Receiver Page (§60–§64, §67)

- Scorecard: aircraft currently visible, positions/sec, messages/sec, max range
  today/ever, unique aircraft today/since T0, decoder uptime, FlightSite uptime,
  receiver health (§61).
- Charts: messages/sec and positions/sec over time, simultaneous aircraft, unique
  aircraft per day, maximum range over time, signal-strength distribution,
  maximum-range-by-bearing polar plot, daily message/position totals (§62).
- Lifetime statistics since T0 (§63). Decoder-native statistics consumed when
  available; unsupported metrics gracefully hidden (§60).
- Metric retention: high-resolution window (14-day default, configurable 7–30 days)
  downsampled to hourly/daily; lifetime aggregates kept forever (§64).

### 4.8 Alerts (§42–§49)

- **Watchlists**: user-defined lists referencing ICAO hex, registration, aircraft
  type, operator, or category/tag; participate in alert matching (§42).
- **Rule engine**: visual rule builder; v1 conditions — classification, specific
  type/model, watchlist membership, locally rare aircraft, locally rare type,
  distance, altitude — combined with simple AND; no nested boolean trees (§43).
- **Rarity** is receiver-relative, computed from FlightSite's own history since T0:
  never seen, seen fewer than N times, type seen fewer than N times (§44).
- **Templates** shipped in v1: military, government, police/law enforcement, emergency
  squawk, first-ever aircraft, locally rare aircraft/type, watchlist match; user
  chooses which to enable during setup — nothing silently enabled (§45).
- **Severity**: Info, Interesting, High, Critical; affects map emphasis, panel
  ordering, activity feed, and notifications (§46).
- **Emergency squawks** 7500/7600/7700 are always prominent events requiring no user
  rule (§47).
- **Browser notifications** (the only v1 channel): once per sighting per rule, with a
  higher-priority re-notification allowed; include callsign/tail, type,
  classification, altitude, distance, match reason; clicking focuses the tab and
  selects the aircraft; works while FlightSite is open, including background and
  minimized tabs (§48). "Open" means a tab on the Live Map, which is where the
  connection that carries live alerts lives; permission is asked for once, from the
  setup wizard or Settings, and never on load (`docs/SECURITY.md` §5).

### 4.9 Activity & Records (§16, §53–§55)

- Lifetime per-aircraft records: first/last seen, total sightings, cumulative
  observation duration, closest approach, farthest detection, lowest/highest altitude
  (§53).
- Milestones: first military aircraft, first of a new type, 1,000th unique aircraft,
  range records, busiest day, highest simultaneous count, longest sighting — fun and
  lightweight (§54).
- Chronological activity feed: interesting detections, alerts, first-evers, new types,
  records, emergency squawks, receiver offline/restored, metadata update results
  (§55).
- All lifetime statistics anchor to **T0**, the timestamp of the first observation
  ever persisted; T0 is never silently reset (§16).

### 4.10 Settings (§14–§15, §19, §27, §29–§30, §64, §66, §73)

Settings edit the same canonical configuration model stored in
`/opt/flightsite/data/config.yaml`, with secrets kept separately and always masked
(§29–§30). Areas: receiver endpoint and location, units, timezone, display radius,
alert radius, sighting timing, retention policy, map configuration, enrichment
configuration (AeroDataBox key), browser notification settings. Additional actions:

- **Update Aircraft Metadata** — manual, per-source download/validate/import with
  independent status reporting and transactional safety (§27).
- **Reset FlightSite Data** and **Clear Metadata Cache** — explicit confirmation
  required; backup strongly suggested first (§73).

### 4.11 Health & Diagnostics (§67–§68)

A health area showing decoder connection state, last successful aircraft update,
database health/size/row counts, free disk space, backend uptime, versions, metadata
database age, notification permission status, and recent
ingestion/database/enrichment/WebSocket errors. The user should never need SSH to
determine whether FlightSite is healthy. Structured logging, rotating logs,
health/readiness endpoints, and internal counters are provided; Prometheus/Grafana are
not required (§68).

### 4.12 Backup & Restore (§72, §115–§116)

First-class documented backup and restore commands with SQLite-safe behavior,
version-aware manifests (version, schema revision, creation time, checksums, metadata
source versions), checksum and schema-compatibility validation on restore, and
deliberate confirmation for destructive operations. An installation is portable by
moving the data directory plus deployment configuration (§116). Upgrades are
`docker compose pull && docker compose up -d` with automatic safe migrations (§115).

### 4.13 Demo Mode & Developer Tooling (§76–§77)

- **Demo mode**: deterministic simulated traffic exercising commercial, military,
  government, police, non-positioned Mode S, MLAT, emergency squawks, rare and
  first-ever aircraft, stale/disappearing aircraft, tracks, alerts, and analytics —
  full development without ADS-B hardware (§76).
- **Capture/replay**: developer-only tool capturing normalized decoder snapshots into
  compact fixtures for deterministic replay and regression tests (§77). Not a user
  playback feature.

### 4.14 External Read-Only API (§74)

The supported, documented external API is read-only in v1: current aircraft,
interesting aircraft, aircraft history, sightings, analytics, receiver statistics,
activity, health — via REST and WebSocket. Mutation endpoints used internally by the
frontend are not part of the supported external contract.

## 5. Key Product Behaviors

| Behavior | Policy |
|---|---|
| **Units** (§14) | Defaults: nautical miles, feet, knots. Metric mode available. |
| **Time** (§15) | All storage and APIs in UTC; UI displays receiver-local time per configurable timezone; DST handled correctly. |
| **T0** (§16) | First persisted observation anchors all lifetime statistics; never silently reset. |
| **Identity model** (§17) | Aircraft (permanent, ICAO-keyed) ≠ Sighting (one continuous observation period) ≠ Flight Context (temporary: callsign, route, squawk…). Never mixed. |
| **Tracks** (§19) | Full-resolution track while a sighting is live; Douglas-Peucker-simplified, timestamped, ordered path on close — playback-capable schema. |
| **Non-positioned aircraft** (§20) | Tracked, listed, alertable, and persisted even without a position. |
| **Position source** (§21) | ADS-B vs MLAT vs Mode S/no-position vs unknown always distinguished in the UI. |
| **Provenance honesty** (§22, §26, §28, §39) | Every enriched/inferred field carries provenance; weak evidence yields `Unknown`, never speculation or fabricated routes. |
| **Airborne vs ground** (§40) | Decoder state preferred; conservative inference only; ground traffic can be de-emphasized/hidden/excluded from alerts but is still recorded. |
| **Rarity** (§44) | Receiver-relative, computed from local history since T0 only. |
| **Offline-first** (§4, §25, §28, §32) | Core product fully functional without internet; enrichment and internet tiles are optional extras that degrade gracefully. |
| **Geographic radius** (§66) | Everything received is stored regardless of distance; display radius and alert radius are independent, configurable filters. Far detections count toward records and analytics. |
| **Retention** (§64–§65) | Sightings, simplified paths, aircraft history, lifetime counters, milestones, and important events kept indefinitely; only high-frequency receiver telemetry is downsampled/pruned. |
| **Privacy** (§28–§29) | Documented exactly what leaves the network (enrichment queries, tile requests); secrets never in logs, APIs, or diagnostics. |

## 6. Visual Direction (§9, §34–§36)

Polished **modern aviation instrumentation**: map-centric, dark by default with a
supported light theme (preference persisted in the browser), restrained color used for
status/classification/selection/severity, subtle radar/aviation visual language, clean
typography, information-dense but never chaotic. Desktop-first, responsive on tablets
and phones. Explicitly not a generic admin-dashboard look (§8). Accessibility baseline
per §80: keyboard navigation, visible focus, semantic HTML, contrast, non-color
severity signaling, automated checks on main flows.

## 7. Explicit v1 Non-Goals (§79)

Out of v1 unless required as infrastructure for an approved feature — tracked in the
roadmap backlog, never implemented silently:

- Multi-receiver deployments
- Built-in authentication
- Slack notifications, Home Assistant, email notifications, native mobile push
- Global aircraft overlay
- Aircraft photos
- Historical animated playback
- Free-form global search
- Data export
- Manual aircraft notes; manual aircraft metadata overrides
- Full offline map-region download manager
- Weather integration
- Airport-level historical analytics
- Period-over-period analytics
- Aircraft-follow mode
- Advanced circling detection, loitering detection, repeated-pass behavioral detection
- Complex nested boolean alert expressions
- User-installable plugins
- Prometheus/Grafana requirement
- Automatic self-updater

## 8. Glossary

| Term | Definition |
|---|---|
| **Aircraft** | Persistent physical aircraft identity, primarily keyed by ICAO hex address (§17). |
| **Sighting** | One continuous period during which the receiver observes an aircraft; closed after the configured absence gap (default 10 min); a new sighting begins only after the previous one closes (§17–§18). |
| **Flight Context** | Temporary information tied to a sighting: callsign, route, origin, destination, operator-in-use, squawk, flight state (§17). |
| **T0** | Timestamp of the first observation ever persisted; anchor for all lifetime statistics (§16). |
| **Rarity (local)** | Receiver-relative scarcity computed from this installation's own history since T0 (§44). |
| **Interesting** | An aircraft currently matching an enabled alert rule (or emergency squawk), carrying a severity of Info/Interesting/High/Critical (§43–§47). |
| **Provenance** | The recorded origin of a field's value: decoder, locally derived, offline metadata, FAA, AeroDataBox, or heuristic (§22). |
| **Operator group** | Normalized parent brand grouping of exact operators (e.g., Delta, FedEx) used for filtering and analytics while the exact operator is preserved (§38). |
| **Mission category** | Broad use classification: commercial passenger, cargo, general aviation, business aviation, military, government, law enforcement, medical, firefighting, training, helicopter, unknown (§39). |
| **Position source** | How a position was obtained: direct ADS-B, MLAT-derived, Mode S/no-position, unknown/other (§21). |
| **Demo mode** | Deterministic simulated decoder traffic enabling full development and testing without hardware (§76). |
