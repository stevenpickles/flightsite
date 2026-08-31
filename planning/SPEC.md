# FlightSite — Governing Specification

> This is the verbatim v1 development specification provided by the project owner
> (2026-08-31). It is the source contract for Phase 0 planning and all v1 development.
> `planning/roadmap.yaml` is the canonical *execution* plan derived from this document.
> If any planning artifact disagrees with this specification, this specification wins
> unless a committed ADR records an approved deviation.

---

# 1. Fable's Role

Fable is the primary orchestrator for development of FlightSite: an open-source,
self-hosted ADS-B observability, visualization, analytics, history, and
interesting-aircraft notification platform intended primarily for homelab users.

Fable owns: architecture, planning, decomposition, sequencing, agent delegation,
implementation coordination, code review, testing, quality gates, pull requests,
integration into `dev`, and release preparation.

Fable may spawn Opus and Sonnet agents as necessary.

**Opus** is preferred for: architecture, ambiguous technical decisions, data-model
design, API design, concurrency, persistence architecture, difficult debugging,
performance work, security analysis, cross-cutting refactoring, design reviews, risky
changes, difficult root-cause analysis.

**Sonnet** is preferred for: well-specified implementation, straightforward APIs, React
components, tests, migrations, documentation, repetitive work, mechanical refactoring,
configuration, routine frontend/backend implementation.

A Sonnet task may be escalated to Opus if ambiguity or unexpected complexity is
discovered. Do not use Opus unnecessarily for routine mechanical work.

# 2. Critical First Instruction

Do not begin feature implementation immediately. The first development phase is
planning only. Before implementation begins, plan the entire FlightSite v1 development
cycle into: phases, numbered vertical slices, dependencies, feature branches, pull
requests, acceptance criteria, testing requirements, expected artifacts, agent
assignments, and integration/release gates.

The complete roadmap must exist before Slice 001 begins. Once Phase 0 planning is
complete, internally reviewed, consistent, and committed, implementation may proceed
without additional human approval. The only mandatory human approval gate in the normal
development lifecycle is the formal release merge into `main`.

# 3. Project Identity

- Project name: **FlightSite**
- Repository: `flightsite`; application name: `FlightSite`; backend package:
  `flightsite`; Docker project: `flightsite`
- Default persistent data directory: `/opt/flightsite/data`
- Container names/images: `flightsite-backend`, `flightsite-frontend`
- Published images use GHCR: `ghcr.io/<owner>/flightsite-backend`,
  `ghcr.io/<owner>/flightsite-frontend`
- License: **MIT**; hosting: **GitHub**; CI/CD: **GitHub Actions**; registry: **GHCR**

# 4. Product Vision

FlightSite should feel like a personal aircraft observatory for the user's own ADS-B
receiver. It is not intended to become another global flight-tracking network.

The core question FlightSite answers: *What is my receiver seeing, what has it seen
historically, how unusual is what I am seeing now, and is anything particularly
interesting happening?*

The application combines: a polished live aircraft map; local receiver visibility; rich
aircraft identification; long-term historical sightings; receiver analytics; aircraft
analytics; rule-based interesting-aircraft detection; browser notifications; local
rarity detection; operator and mission classification; historical receiver-relative
records; system health information.

The application must remain usable when external internet enrichment is unavailable.

# 5. Deployment Target

- Minimum supported target: **Raspberry Pi 4**; official host OS: Raspberry Pi OS
  64-bit. Publish Docker images for `linux/arm64` and `linux/amd64`. Must also run
  naturally on other Linux Docker hosts.
- Target load envelope: ~500 simultaneously visible aircraft; decoder state updates
  ~1 Hz; several years of historical sightings; responsive UI; live ingestion must
  never be blocked by analytics/database work; backend memory comfortably below 1 GB.
- Performance is an architectural constraint, not an afterthought.

# 6. Deployment Architecture

Docker Compose. Two containers: `flightsite-frontend` (React static app + web
server/proxy) → `flightsite-backend` (FastAPI: ingestion, live state, alerts,
analytics, SQLite) → `/opt/flightsite/data`.

No separate database container. All persistent application state lives in a clearly
defined host bind mount under `/opt/flightsite/data`. No opaque anonymous Docker
volumes for important persistent data. The system must be easy to back up, restore,
migrate to another Pi, and migrate to another Linux host.

# 7. Backend Stack

Python, FastAPI, Pydantic, SQLAlchemy 2.x, Alembic, asyncio, pytest, SQLite. Current
stable versions compatible with the architecture. No Rust in v1 unless measurements
demonstrate a genuine requirement and an ADR justifies it.

# 8. Frontend Stack

React, TypeScript, Vite, MapLibre GL JS, TanStack Query, lightweight local UI state
(Zustand or React context), Recharts or ECharts, Vitest, React Testing Library,
Playwright. Styling: Tailwind CSS, shadcn/ui, Lucide. Do not make FlightSite look like
a generic admin-dashboard template.

# 9. Visual Direction

Polished modern aviation instrumentation aesthetic: map-centric; dark by default;
restrained use of color (color primarily communicates status, classification,
selection, or alert severity); subtle radar/aviation visual language; clean typography;
information-dense where useful; never visually chaotic; desktop-first; responsive on
tablets and phones. Support dark and light themes; dark is default; persist theme
preference locally in the browser.

# 10. Navigation Structure

Primary navigation: Live Map, Aircraft, Sightings, Analytics, Receiver, Alerts,
Settings. The Live Map is the primary product experience — FlightSite should feel like
a live radar application with analytics, not an analytics dashboard containing a map.

# 11. ADS-B Decoder Boundary

FlightSite does not decode RF or ADS-B messages itself in v1. It consumes an existing
decoder: `readsb` or `dump1090-fa`, via their compatible HTTP/JSON aircraft output. The
decoder may run on the same host or elsewhere on the LAN.

Configuration must include: host/IP, port, path, polling interval, connection test,
connection health, automatic reconnect.

Design ingestion using an adapter abstraction. Initial adapter: `ReadsbJsonAdapter`.
Future adapters may include `BeastAdapter`, `SbsAdapter`, `RemoteReceiverAdapter`. Do
not allow readsb-specific assumptions to leak throughout the domain model.

# 12. Receiver Scope

v1 supports one receiver per FlightSite deployment. Do not implement multi-receiver
support in v1, but do not design the schema so poorly that future multi-receiver
support becomes impossible.

# 13. Receiver Location

Manually configured during setup. Required: latitude, longitude. Optional: site name,
antenna height. Receiver position is the reference for bearing, distance, range rings,
closest approach, farthest detection, coverage analytics, alert radius, and
receiver-relative records.

# 14. Units

Default units: nautical miles, feet, knots. Support a metric unit mode as an option.

# 15. Time Handling

Store all timestamps internally in UTC. APIs use UTC. The UI displays receiver-local
time according to a configurable timezone. Handle daylight-saving transitions
correctly.

# 16. T0

T0 = timestamp of the first observation persisted to the FlightSite database. T0
anchors lifetime statistics and should not be silently reset.

# 17. Aircraft Identity Model

Keep distinct: **Aircraft** (persistent physical identity, primarily keyed by ICAO hex
address); **Sighting** (one continuous period during which the receiver observes that
aircraft); **Flight Context** (temporary information associated with that sighting:
callsign, route, origin, destination, operator-in-use, squawk, relevant flight state).
Do not mix permanent aircraft properties with temporary flight properties.

# 18. Live Aircraft State

Maintain live aircraft state separately from historical persistence. Default lifecycle
timing (configurable, these values as defaults): 15 s without update → stale; 60 s
without update → remove from live display; 10 min absent → close sighting. A new
sighting begins only after the previous one has been closed.

# 19. Current Sighting Track

While a sighting is active, retain the full current track. When the sighting closes:
do not retain every raw decoder update forever; simplify the historical path using an
appropriate geometry reduction algorithm such as Douglas-Peucker; retain enough
ordered/timestamped path information to enable future historical playback. Do not fit
Bézier curves for storage compression. Historical playback is a future feature, but the
v1 schema must preserve enough information to add it later.

# 20. Non-Positioned Aircraft

Track aircraft even when no valid position is available. Provide a small
non-positioned aircraft list in the live interface. These aircraft may still have ICAO,
callsign, altitude, squawk, signal information, and metadata classification. They must
still participate in alert rules, activity events, and historical sightings.

# 21. Position Source

Clearly distinguish: direct ADS-B position; MLAT-derived position; Mode S/no-position;
unknown/other. The UI must make clear whether a position is directly received versus
externally/multilaterally derived.

# 22. Field Provenance

Track which fields were: directly received from the decoder; locally derived; supplied
by offline metadata; supplied by FAA metadata; supplied by AeroDataBox; determined
heuristically. Do not present enriched or inferred information as though it came
directly from the aircraft. Preserve field-level provenance where practical. Expose
provenance in the aircraft detail UI with unobtrusive indicators/tooltips.

# 23. Aircraft Metadata Requirements

Aircraft detail should aim to provide: callsign; tail number/registration; ICAO hex;
aircraft type; aircraft model; manufacture year; aircraft age; operator; normalized
operator group; owner where available; military classification; government
classification; police/law-enforcement classification; mission/use classification;
altitude; ground speed; heading/track; distance from receiver; bearing from receiver;
squawk; signal strength; message count; last-seen age; first-ever seen; last seen;
lifetime sighting count; cumulative observed time; closest approach; farthest
detection; lowest observed altitude; highest observed altitude; origin; destination;
nearest airport context; arrival/departure inference when confidence is sufficient;
current sighting track; classification provenance; external tracking links.

# 24. External Tracking Links

Provide convenient links to FlightRadar24, FlightAware, ADS-B Exchange, using the best
available identifier.

# 25. Offline Aircraft Metadata

FlightSite must be useful offline. Official primary offline aircraft metadata source
for v1: the Mictronics / tar1090 aircraft database ecosystem. Import upstream data into
FlightSite's own normalized schema. Do not make the rest of FlightSite depend directly
on the upstream file format. Respect and document all attribution/license requirements.

# 26. FAA Supplemental Metadata

Support the FAA releasable aircraft registry as an optional supplemental local source
for U.S.-registered aircraft: registration, manufacture year, owner information,
make/model supplementation. If owner information is unavailable or withheld, `Unknown`
is preferable to speculation. Preserve provenance.

# 27. Aircraft Metadata Updating

v1 uses manual metadata updates. Settings provides one action: **Update Aircraft
Metadata**, which: checks configured metadata sources; downloads each source
independently; validates downloads; imports into normalized FlightSite tables; performs
updates transactionally; preserves the previous working dataset if an import fails;
reports status separately for each source; records last successful update timestamps.
No scheduled metadata updating in v1.

# 28. Online Route Enrichment

The core application must function without internet enrichment. v1 supports one
optional online route enrichment provider: **AeroDataBox** (API key). The provider
abstraction is generic internally, but no user-facing multi-provider plugin selector in
v1. AeroDataBox may provide origin, destination, route/flight context, additional
temporary flight information.

Rules: query only when enough flight context exists; cache aggressively; respect
provider limits; never block live tracking on enrichment; degrade gracefully; display
`Unknown` when uncertain; never fabricate routes; distinguish externally reported route
information from locally inferred airport context; document what information leaves the
user's network.

# 29. Secrets

Canonical non-secret configuration: `/opt/flightsite/data/config.yaml`. Secrets are
separate: `/opt/flightsite/data/secrets.yaml` and/or environment-variable overrides.

Requirements: API keys never appear in logs; API keys never appear in the documented
read-only API; the Settings UI masks stored values; diagnostics must not expose
secrets; backups must clearly document whether secrets are included; never silently
expose secrets in generated support information.

# 30. Configuration

`config.yaml` is the canonical human-readable configuration. The Settings UI edits the
same configuration model. Environment variables may override deployment-specific
settings. Configuration areas include at least: receiver endpoint; receiver location;
units; timezone; display radius; alert radius; sighting timing; retention policy; map
configuration; enrichment configuration; browser notification settings.

# 31. First-Run Setup

Provide a short setup wizard collecting: receiver site name; latitude; longitude;
decoder JSON endpoint; polling interval; units; timezone; browser notification
preference; optional aircraft metadata setup; optional AeroDataBox API key; initial
interesting-aircraft alert categories. After setup, land directly on the Live Map.

# 32. Basemap

Use MapLibre and abstract the tile provider. Requirements: multiple selectable
basemaps; dark aviation-style basemap as default; internet tiles acceptable; core
functionality must not require internet maps; architecture must permit future
self-hosted/offline tile sources. Implement opportunistic caching of recently used
tiles in v1. Do not build a full offline-region downloader or map-management system.

# 33. Aviation Overlays

v1 supports: airports; airspace boundaries; receiver range rings. Do not overload v1
with every possible aviation layer. Airspace/airport data sources must have suitable
open licensing and be documented.

# 34. Aircraft Map Icons

Do not use only one generic aircraft icon. Implement hierarchical aircraft silhouette
selection: (1) specific aircraft-type silhouette when available; (2) category
silhouette; (3) generic fallback. Category examples: airliner, business jet, fighter,
bomber, military transport, helicopter, cargo aircraft, general aviation, glider,
unknown. Rotate icons per heading/track where available. The icon system must be
extensible. Asset licensing must be documented.

# 35. Map Labels

Preferred label content: callsign; tail number if no callsign; operator; altitude;
interesting-status indicator. Use intelligent decluttering. At lower zoom or high
density: suppress operator first; suppress secondary text as needed; keep aircraft
icons visible; prioritize labels for selected aircraft; prioritize labels for
interesting aircraft. Do not cluster aircraft markers.

# 36. Map Styling

Normal aircraft: neutral/default styling. Selected: strong selection highlight.
Interesting/alerting: distinct attention styling. Military/government/police: may use
category-specific styling. Stale aircraft: visually fade. Never rely exclusively on
color to communicate classification or severity.

# 37. Live Map Filtering

Compact filter drawer supporting: altitude range; distance; aircraft category/type;
exact operator; normalized operator group; military/government/police classification;
mission/use category; interesting-only; callsign/tail/ICAO filtering only where it does
not constitute the deferred global search feature; hide non-positioned; hide ground
traffic; age/staleness filtering. Also lightweight quick filters for common operator
groups/categories. No complex faceted-search system in v1.

# 38. Operator Normalization

Operator is a first-class concept. Store exact operator and normalized operator
group/parent brand (e.g., Delta, American, Southwest, United, FedEx, UPS). Preserve
exact legal/operator information while allowing broad grouping for filters and
analytics.

# 39. Mission / Use Categories

Classify aircraft into broad categories where metadata permits: commercial passenger;
cargo; general aviation; business aviation; military; government; law enforcement;
medical/air ambulance; firefighting; training; helicopter; unknown. Classification must
have provenance and should not claim certainty when evidence is weak.

# 40. Airborne vs Ground

Track airborne / on ground / unknown. Prefer decoder-provided state; only infer when
confidence is reasonable. Allow ground traffic to be visually de-emphasized, hidden,
and excluded from relevant alerts. Ground sightings are still retained when actually
received.

# 41. Nearby Airport Context

For an aircraft near an airport, FlightSite may display: nearest airport; likely
arriving; likely departing. Arrival/departure status must be clearly labeled as
inferred. Do not infer a full route locally. No airport-level historical analytics in
v1.

# 42. Watchlists

Support user-defined watchlists in v1. Entries may reference: ICAO hex; registration;
aircraft type; operator; category/tag. Watchlists participate in alert matching. Manual
free-form aircraft notes and custom metadata overrides are future features.

# 43. Interesting Aircraft Rule Engine

Flexible but understandable visual rule builder. v1 conditions: classification;
specific aircraft type/model; watchlist membership; locally rare aircraft; locally rare
aircraft type; distance; altitude. Support simple `AND` combinations. No arbitrary
nested boolean-expression trees in v1.

# 44. Rarity

Rarity is receiver-relative: aircraft never seen before; aircraft seen fewer than N
times; aircraft type seen fewer than N times. Use FlightSite's own history since T0. No
global rarity database dependency in v1.

# 45. Alert Templates

Ship v1 templates for: military; government; police/law enforcement; emergency squawk;
first-ever aircraft; locally rare aircraft/type; watchlist match. During setup, the
user chooses which templates to enable. Do not silently enable every possible
notification.

# 46. Alert Priority

Severity levels: Info, Interesting, High, Critical. Suggested: first-ever sighting →
Info; locally rare → Info/Interesting; watchlist → Interesting;
military/government/police → High; emergency squawk → Critical. Severity affects map
emphasis, interesting-aircraft panel ordering, activity feed, browser notifications.

# 47. Emergency Squawks

Recognize at minimum 7500, 7600, 7700. These become prominent events: visually
emphasized; in the activity feed; support browser notification; do not require an
unrelated interesting-aircraft rule to be matched.

# 48. Browser Notifications

v1 notification mechanism: browser notifications only. No Slack, Home Assistant,
email, or native mobile push. Notifications need to work while FlightSite is open in
the browser, including background/minimized tabs.

Rules: notify once per sighting per rule; do not spam every decoder update; a newly
matched higher-priority condition may create another notification; include useful
information (callsign/tail, aircraft type, classification, altitude, distance, match
reason); clicking should open/select the aircraft in FlightSite where practical.

# 49. Interesting Aircraft Panel

Persistent or easily accessible panel listing currently interesting aircraft. Sort by
severity, then distance or other useful secondary ordering. Show: callsign/tail;
aircraft type; operator; match reason; distance; altitude. Clicking selects the
aircraft.

# 50. Aircraft Detail View

Comprehensive detail: callsign; registration; ICAO; type; model; manufacture year;
age; operator; normalized operator group; owner; classification; mission/use; altitude;
speed; heading; distance; bearing; squawk; signal strength; message count; last-seen
age; position source; field provenance; first seen; last seen; total sightings;
cumulative visible time; closest approach; farthest detection; lowest altitude; highest
altitude; route; origin; destination; nearest airport; arrival/departure inference;
current track; external tracker links.

# 51. Per-Sighting Reception Statistics

Store lightweight reception summaries: peak/average/minimum signal strength; message
count; position count; sighting duration; percentage of sighting with valid position
information. Do not store every raw message indefinitely.

# 52. Meaningful Sighting Events

Preserve meaningful state changes during a sighting: callsign change; squawk change;
emergency status; route enrichment becoming available; classification enrichment
becoming available; important alert transition. Do not store every decoder snapshot as
an event.

# 53. Historical Aircraft Records

Per aircraft, track receiver-relative lifetime records: first seen; last seen; total
sightings; cumulative observation duration; closest approach; farthest detection;
lowest altitude; highest altitude.

# 54. Milestones and Records

Track notable milestones: first military aircraft ever seen; first example of a new
aircraft type; 1,000th unique aircraft; new maximum-range record; busiest day; highest
simultaneous aircraft count; longest sighting; other meaningful receiver records. Keep
this fun and lightweight.

# 55. Activity Feed

Chronological activity feed. Possible events: interesting aircraft detection; alert
triggered; first-ever aircraft sighting; new aircraft type; new range record; new
receiver record; emergency squawk; receiver offline; receiver restored; metadata update
results. Answers: *What happened while I wasn't watching?*

# 56. Aircraft Page

Sortable Aircraft page. No global search in v1. Columns: tail number; ICAO;
type/model; operator; classification; first seen; last seen; sighting count; closest
approach; farthest detection. Rows open aircraft detail.

# 57. Sightings Page

Chronological sightings log. Columns: start; end; duration; tail/callsign; type;
operator; classification; closest approach; maximum range; lowest altitude; highest
altitude; position count; alert/interesting status. Opening a sighting shows its
detailed summary and simplified path. Historical animated playback is not required in
v1.

# 58. Analytics Page

Time presets: Today, Last 7 Days, Last 30 Days, This Year, Since T0. v1 analytics:
most frequently seen aircraft; most frequently seen types/models; most common
operators; military/government/police activity; daily aircraft count; daily sighting
count; maximum detection distance; receiver activity over time; first-seen/last-seen
information; count of aircraft never previously seen; locally rare aircraft/type
information. No period-over-period comparison in v1.

# 59. Today at a Glance

Compact summary on the main experience: unique aircraft today; sightings today;
interesting aircraft today; military/government/police today; maximum range today;
busiest hour; new aircraft today; new milestones/records.

# 60. Receiver Analytics

First-class feature. Consume decoder-native statistics from readsb/dump1090-fa when
available. Also calculate FlightSite-specific metrics. Normalize common fields and
gracefully hide unsupported decoder metrics.

# 61. Receiver Scorecard

Top of Receiver page: aircraft currently visible; positions/sec; messages/sec; max
range today; max range ever; unique aircraft today; unique aircraft since T0; decoder
uptime; FlightSite uptime; receiver health.

# 62. Receiver Charts

v1: messages/sec over time; positions/sec over time; simultaneous aircraft over time;
unique aircraft per day; maximum range over time; signal-strength distribution;
maximum-range-by-bearing polar plot; daily message totals; daily position totals.

# 63. Lifetime Receiver Statistics

Since T0 where possible: unique aircraft; total sightings; total positions; total
messages; maximum detection distance; highest observed message rate; busiest day; most
frequently seen aircraft; common type/model/operator records; relevant receiver
records.

# 64. Receiver Metric Retention

Long-term receiver metrics must be downsampled: retain high-resolution metrics for a
limited recent window (sensible configurable default in the 7–30 day range chosen
during Phase 0); downsample older data to hourly/daily summaries; preserve long-term
aggregate statistics indefinitely; automatically prune obsolete high-resolution rows.
Do not retain high-frequency receiver telemetry forever.

# 65. Historical Sighting Retention

Retain indefinitely unless the user resets the application: sightings; simplified
historical paths; aircraft history; lifetime counters; milestones; important activity
events.

# 66. Geographic Radius

Do not discard detections because they are far away. Store everything the receiver
actually sees. Support independently configurable display radius and alert radius. Far
detections still count toward range records and analytics.

# 67. System Health

Health/diagnostics area showing: decoder connection state; last successful aircraft
update; database health; database size; useful row counts; free disk space; backend
uptime; frontend/backend version; metadata database age; notification
permission/status; recent ingestion errors; recent database errors; enrichment
failures; WebSocket issues. The user should not have to SSH into the Pi to determine
whether FlightSite is healthy.

# 68. Logging and Observability

Structured backend logging; configurable log levels; rotating local logs. Provide:
health endpoint; readiness endpoint; basic internal counters. Track at least:
ingestion failures; database errors; enrichment failures; WebSocket disconnects. No
Prometheus/Grafana requirement in v1.

# 69. SQLite Requirements

SQLite, configured for a long-running application. WAL mode. Requirements: ingestion
not blocked by slow analytics; migrations via Alembic; safe transaction boundaries;
automatic integrity checking; sensible indexing; automatic maintenance; realistic
long-term growth testing.

# 70. Database Maintenance

Automate conservative maintenance: integrity checking; retention pruning;
downsampling; SQLite optimization; VACUUM only when justified and safe; useful
diagnostics; no routine user babysitting.

# 71. Unclean Shutdown Recovery

FlightSite must tolerate unexpected host power loss. Design for: SQLite WAL recovery;
startup integrity checks; no assumption that shutdown hooks always execute;
recovery/closure of previously open sightings; minimal loss of unpersisted in-memory
state; diagnostics when recovery problems occur.

# 72. Backup and Restore

First-class v1 features. Provide: documented backup command; documented restore
command; SQLite-safe backup behavior; preservation of application
state/config/metadata per documented policy; clearly defined backup location;
transportability to another host.

Backups are version-aware. Backup manifest includes: FlightSite version; database
schema revision; creation time; checksums; relevant metadata/source versions. Restore
must: validate checksums; validate schema compatibility; refuse a newer-schema backup
on an incompatible older FlightSite version; allow older backups to be restored into
newer FlightSite and migrated normally. Destructive restore operations must be
deliberate.

# 73. Data Reset

No routine per-aircraft historical deletion in v1. Settings may provide: Reset
FlightSite Data; Clear Metadata Cache. Reset requires explicit confirmation and
strongly suggests backup first.

# 74. Read-Only External API

The frontend requires APIs internally. The supported/documented external API is
read-only in v1. Expose read-only resources: current aircraft; interesting aircraft;
aircraft history; sightings; analytics; receiver statistics; activity; health. Use REST
and WebSockets where appropriate. Configuration/rule/watchlist mutation endpoints
needed by the frontend are not part of the supported external API contract in v1.
Document the API.

# 75. Authentication

No built-in authentication in v1. Assumption: trusted LAN deployment. Clearly document
that exposing FlightSite directly to the public internet is not supported securely by
default. Future reverse-proxy or application authentication may be added later.

# 76. Demo Mode

v1 must include deterministic demo/mock mode simulating enough traffic to exercise:
normal commercial aircraft; military; government; police/law enforcement;
non-positioned Mode S; MLAT; emergency squawks; rare aircraft; first-ever aircraft;
stale aircraft; disappearing aircraft; tracks; alerts; analytics. Demo mode should
allow meaningful development without ADS-B hardware.

# 77. Developer Capture / Replay

Developer-only tool: capture normalized decoder snapshots for a bounded period; save
compact fixture data; replay fixtures deterministically; reproduce real-world bugs;
create regression tests. Not an end-user historical playback feature.

# 78. Provider Architecture

Clean internal provider interfaces for: aircraft metadata; route enrichment; future
ownership providers; future photo providers; future notification providers. No
user-installable plugin ecosystem in v1.

# 79. Explicit v1 Non-Goals

Out of v1 unless required as infrastructure for an approved feature: multi-receiver
deployments; built-in authentication; Slack notifications; Home Assistant; email
notifications; native mobile push; global aircraft overlay; aircraft photos; historical
animated playback; free-form global search; data export; manual aircraft notes; manual
aircraft metadata overrides; full offline map-region download manager; weather
integration; airport-level historical analytics; period-over-period analytics;
aircraft-follow mode; advanced circling detection; loitering detection; repeated-pass
behavioral detection; complex nested boolean alert expressions; user-installable
plugins; Prometheus/Grafana requirement; automatic self-updater. Keep these in a
future/backlog section of the roadmap.

# 80. Accessibility

Practical accessibility baseline: keyboard navigation; visible focus; semantic HTML;
sufficient contrast; labels/tooltips; ARIA where necessary; severity communicated by
text/icon as well as color; main flows covered by automated accessibility checks. Do
not claim formal WCAG certification unless actually qualified.

# 81. Browser Support

Current and previous major versions of Chrome, Edge, Firefox, Safari. Chromium may be
the primary development target. CI should exercise Chromium, Firefox, and WebKit where
practical.

# 82. Testing Strategy

Testing is mandatory, multi-layered. Backend: unit, domain, ingestion, persistence,
migration, API, integration tests. Frontend: component, state, API integration,
interaction tests. E2E (Playwright) critical flows: first-run setup; decoder connection
test; demo-mode live map; aircraft selection; aircraft detail; interesting-aircraft
alert; browser notification permission flow; Aircraft page; Sightings page; Analytics
windows; metadata update; backup/restore smoke path.

# 83. Visual Regression

Use deterministic demo data for a narrowly scoped visual regression suite covering
stable views: Live Map; aircraft detail; Analytics; Receiver; Alerts. Do not make tests
brittle because of dynamic internet map tiles or changing timestamps; mock or stabilize
external visual inputs.

# 84. Coverage Requirements

Minimum global targets: Backend 80%, Frontend 70%. Critical logic materially higher:
sighting lifecycle; alert evaluation; metadata precedence; migrations; backup/restore;
retention; unclean-shutdown recovery. No meaningless tests solely to inflate coverage.
Coverage regressions fail CI unless explicitly justified.

# 85. Performance Testing

Include performance regression testing. Measure: ingestion throughput; live-state
update latency; SQLite write latency; SQLite read/query latency; WebSocket
distribution; memory use; analytics query latency; startup; unclean-shutdown recovery;
multi-year database behavior. Reference hardware: Raspberry Pi 4.

Hybrid gate model. Hard gates: ingestion keeps up; 500-aircraft workload remains
functional; no live-state stalls; memory below agreed budget; core APIs responsive.
Trend-track less critical metrics initially; convert to hard gates once real Pi 4
baselines exist.

# 86. Long-Term Storage Qualification

Before v1.0.0, test against a realistic synthetic multi-year dataset. Verify: database
growth; query responsiveness; index behavior; downsampling; retention pruning; backup
size; restore behavior; Pi storage I/O; analytics performance.

# 87. Security Baseline

Maintain `docs/SECURITY.md` documenting at least: trusted-LAN assumption; risks of
public exposure; API-key handling; browser notification permissions;
malicious/malformed decoder input; SQLite corruption risks; container boundaries;
dependency/supply-chain risks; read-only external API expectations; backup/secrets
considerations.

# 88. CI Security Checks

CI includes: Python dependency vulnerability scanning; npm dependency auditing;
container scanning; secret scanning; dependency update automation; license
compatibility checks. Enable Dependabot or equivalent. Material high/critical findings
block releases.

# 89. Phase 0 Planning Deliverables

Before feature implementation, create and commit at minimum: `docs/PRODUCT.md`,
`docs/ARCHITECTURE.md`, `docs/DATA_MODEL.md`, `docs/API.md`, `docs/ROADMAP.md`,
`docs/DEVELOPMENT.md`, `docs/TEST_STRATEGY.md`, `docs/SECURITY.md`, `docs/RISKS.md`,
`docs/RELEASE.md`, `docs/adr/`, `planning/roadmap.yaml`, plus supporting
templates/configuration such as `.github/pull_request_template.md` and issue templates
if useful. Phase 0 may establish planning and repository-governance files. Do not
implement FlightSite product features during Phase 0.

# 90. Architecture Decision Records

Use ADRs for consequential decisions (e.g., replacing SQLite; changing ingestion
architecture; changing container topology; changing public API strategy; adding major
external services; changing persistence semantics; changing security assumptions;
substantial retention changes). No ADRs for trivial implementation details.

# 91. Risk Register

Maintain `docs/RISKS.md` tracking material risks with description, likelihood, impact,
mitigation, status, relevant slice/owner. Likely risks: upstream metadata source
changes; AeroDataBox limits/outages; Raspberry Pi 4 performance; SQLite growth;
corruption/power loss; browser notification limitations; map tile/provider changes;
decoder format differences; external dataset licensing. Update as risks appear or are
retired.

# 92. Canonical Roadmap

The canonical execution plan is `planning/roadmap.yaml`. `docs/ROADMAP.md` is the
human-readable representation. If the two disagree, fix them immediately. Do not allow
parallel planning documents to become competing sources of truth.

# 93. Roadmap Schema

Each slice includes fields conceptually equivalent to: id, title, phase, branch,
status, depends_on, objective, scope, out_of_scope, acceptance_criteria,
required_tests, expected_artifacts, preferred_agent, risk_level, notes. Statuses:
planned, ready, in_progress, review, merged, blocked, deferred. The exact schema may be
refined during Phase 0.

# 94. Development Phases

Fable determines the final decomposition during Phase 0. The roadmap broadly covers:
repository/development foundation; configuration; decoder ingestion; normalized
aircraft state; sighting lifecycle; SQLite persistence; API/WebSocket foundation;
demo/replay tooling; live map; aircraft rendering; metadata ingestion; aircraft detail;
historical sightings; watchlists; alert engine; browser notifications; analytics;
receiver analytics; activity/milestones; backup/restore; diagnostics; hardening;
performance; release qualification. This is not a prescribed final slice list.

# 95. Vertical Slice Rule

One slice = one numbered feature branch = one pull request. Branch naming:
`001-short-description`, `002-short-description`, … Prefer coherent, testable vertical
slices. Avoid enormous branches. A slice should be small enough for rigorous review and
large enough to represent a coherent increment. Minimal foundational slices are
acceptable where unavoidable, but should be clearly justified.

# 96. Parallel Development

Parallelize slices when dependencies permit: no unresolved dependency conflict;
preferably isolated worktrees; avoid multiple agents editing the same files
concurrently; Fable owns merge order and architectural consistency; Fable reconciles
drift before merging. Parallelism should reduce elapsed work without destabilizing
`dev`.

# 97. Roadmap Changes

Fable may revise the roadmap during implementation: split a slice; add a prerequisite;
reorder; add discovered technical work; defer when justified. Requirements: update
`planning/roadmap.yaml` and `docs/ROADMAP.md`; preserve slice history; do not silently
repurpose slice IDs; document rationale; do not casually expand v1 scope.

# 98. Git Branches

Long-lived branches: `main` (production/released code only) and `dev` (integrated
development). Feature work does not occur directly on either branch.

# 99. Branch Protection

Protect both branches. `main`: no direct pushes; PR required; required CI/release
checks; human approval required; no force pushes. `dev`: no direct pushes; PR required;
required slice quality gates; Fable may self-review, approve, and merge; no force
pushes. Do not weaken branch protections merely to work around automation.

# 100. Merge Strategy

No squash merges. No rebase merges for PR integration. Use merge commits. Feature
slice: feature branch → `dev` via merge commit. Release: release branch → `main` and
release branch → `dev` via merge commits. Preserve the development history of the
slice.

# 101. Conventional Commits

Use Conventional Commits (feat, fix, test, docs, refactor, …). The changelog is not
updated during normal feature development.

# 102. Pull Request Template

Every numbered slice PR includes: Slice ID; roadmap reference; objective;
implementation summary; acceptance criteria checklist; tests added/run; performance
considerations; security considerations; data/migration considerations; documentation
updates; known limitations; follow-up work. PR title references the slice. Each PR
links to its corresponding GitHub Issue.

# 103. GitHub Issues

Mirror roadmap slices into GitHub Issues: `planning/roadmap.yaml` remains canonical;
each implementation slice gets an issue; PR links to the issue; merge closes the issue;
roadmap status updated accordingly. GitHub Projects not required for v1.

# 104. Fable Self-Review

Fable may open, review, approve, and merge its own slice PRs into `dev`, only after
all requirements are satisfied. Before approval, Fable inspects the complete diff and
verifies: acceptance criteria satisfied; no scope creep; tests meaningful; failure
cases covered; APIs/types coherent; migrations safe; logs/error handling appropriate;
security assumptions preserved; privacy expectations preserved; performance acceptable;
documentation updated; no temporary debug code; no untracked TODO/FIXME; branch
reconciled with current `dev`; all mandatory CI checks passing.

If GitHub identity mechanics prevent an approval from counting as a formal reviewer
approval, do not weaken quality gates: record the self-review clearly and use the
configured automation/review identity model approved for the repository.

# 105. `dev` Must Always Be Deployable

Hard invariant. Every merged slice leaves `dev`: buildable; testable; startable;
migration-valid; Docker Compose compatible; demo-mode compatible. Do not merge
knowingly incomplete code that breaks already merged functionality.

# 106. Feature Flags

Permitted sparingly, to land foundations without exposing incomplete functionality.
Rules: unfinished features disabled by default; local/config-driven; no external
feature-management platform; every temporary flag has a roadmap removal point; remove
obsolete flags promptly.

# 107. Database Migrations

All schema changes use Alembic. Non-destructive where possible; migration tests;
realistic upgrade fixtures; startup may automatically apply pending migrations;
adjacent released versions must have a tested upgrade path; rollback support where
practical; historical data must not be casually discarded.

# 108. CI Quality Gates

A feature PR may not merge until all applicable gates pass. Python: formatting,
linting, static/type checking, unit tests, integration tests, coverage.
TypeScript/React: formatting, linting, type checking, unit/component tests, coverage.
Integration: API contract tests, migration tests, Docker builds, smoke test, demo-mode
validation. Security: dependency scans, secret scans, license checks, container scans.
Use required GitHub status checks.

# 109. Release Versioning

Semantic Versioning. During development: `0.x.y`; first usable integrated releases
around `v0.1.0`. Use `v1.0.0` only when the complete agreed v1 scope is qualified and
stable.

# 110. Release Branch Workflow

Formal release preparation on a release branch (e.g., `release/v0.4.0`) created from
the qualified `dev` state. Only the release branch performs release-specific changes:
version bump; CHANGELOG update; final release notes; release metadata.

# 111. Changelog Rule

Do not update `CHANGELOG.md` on normal feature branches or continuously on `dev`. The
changelog is updated only during release preparation on the release branch, generated
from accumulated Conventional Commits, merged PR information, and roadmap/slice
history, curated into useful human-facing release notes.

# 112. Release Qualification

Every release branch executes the checklist in `docs/RELEASE.md`: version selection;
version bump; changelog; migration validation; full CI; E2E suite; visual regression;
security scan review; dependency scan review; fresh installation; Docker Compose
deployment; backup test; restore test; adjacent-version upgrade test; demo-mode
validation; live-decoder validation where appropriate; Raspberry Pi 4 qualification
where required; documentation review; known issue review; release notes.

# 113. Release Approval

Fable may autonomously prepare the release but may not autonomously perform the final
production release merge. Flow: `dev` → `release/vX.Y.Z` → full release qualification →
PR → `main`. The `main` PR requires human approval. After human approval, Fable may:
merge release branch to `main`; tag the release; create the GitHub Release; publish
GHCR images; merge the release branch back into `dev`. Both merges use merge commits.

# 114. v1.0.0 Definition of Done

Fable may propose v1.0.0 only when: every v1 roadmap slice is complete; all mandatory
tests pass; all required CI gates pass; Raspberry Pi 4 performance qualification
passes; multi-year storage qualification passes; fresh install works from
documentation; backup works; restore works; upgrade path works; demo mode works; live
readsb/dump1090-fa ingestion is validated; no known critical/high-severity product bugs
remain; architecture documentation matches reality; API documentation matches reality;
deployment documentation matches reality; security assumptions are documented; release
checklist passes completely.

# 115. Upgrade Model

No in-app self-updater in v1. User upgrade workflow: `docker compose pull && docker
compose up -d`. Database migrations run safely during startup. Document backup
recommendations before major changes.

# 116. User Data Portability

Data ownership is a core design principle. The user should always understand where
FlightSite stores its persistent state. No critical state in obscure Docker volumes. A
FlightSite installation should be reasonably portable by moving the data directory plus
deployment configuration to another compatible system.

# 117. Coding Philosophy

Favor: clarity; explicit domain models; testability; deterministic behavior; small
cohesive modules; type safety; readable code; clear interfaces; bounded
responsibilities; resilient failure handling; measured optimization. Avoid: premature
microservices; unnecessary abstractions; speculative plugin frameworks; hidden global
state; duplicated domain logic between frontend/backend; cleverness that hurts
maintainability; dependencies that do not provide meaningful value.

# 118. Scope Discipline

When an implementation question arises: check `planning/roadmap.yaml`; check
`docs/PRODUCT.md`; check architecture/ADRs; determine whether it is required for the
current slice; avoid adding unrelated functionality. If useful work is discovered but
not necessary now: create a tracked follow-up issue/slice; update the roadmap if
warranted; do not silently expand the active PR.

# 119. TODO Discipline

Do not introduce unresolved TODO/FIXME/HACK without a corresponding tracked issue or
roadmap item. Temporary workarounds must have an explicit removal path.

# 120. Phase 0 Review Gate

Before Slice 001, conduct a planning review verifying: every v1 requirement in this
specification appears in the planning package; explicit non-goals captured;
architecture internally consistent; data model supports future playback without
implementing it; provider boundaries defined; storage model realistic for Pi 4; roadmap
dependencies acyclic; slices appropriately sized; acceptance criteria testable; test
strategy maps to features; release workflow represented; security risks documented;
licensing risks documented; no major feature category omitted. Use Opus for this
review. Correct the planning package before implementation if inconsistencies are
found.

# 121. Slice Execution Loop

For every slice: confirm dependencies merged; mark `in_progress`; create numbered
branch; create/link GitHub Issue; assign appropriate agent; implement only slice scope;
add/update tests; update relevant documentation; run local quality gates; reconcile
with current `dev`; open PR; complete PR template; run full required CI; perform Fable
self-review; correct review findings; approve PR; merge with a merge commit; verify
`dev` remains deployable; update roadmap status to `merged`; select newly unblocked
slices; parallelize where safe. Repeat until all planned v1 slices are complete.

# 122. Failure Handling

If a slice becomes unexpectedly difficult: do not force a low-quality implementation
through; invoke Opus for root-cause/design assistance; revise the plan if a hidden
dependency exists; document significant architecture changes; keep `dev` stable; keep
scope explicit. If an upstream API/dataset is unavailable: preserve offline core
functionality; degrade gracefully; test the failure case.

# 123. Human Interaction Policy

Do not interrupt the user for routine implementation choices resolvable from this
specification, repository conventions, documented architecture, or established best
practices. Make disciplined engineering decisions; use an ADR for consequential
choices. Request human input when: a product requirement is genuinely contradictory; a
decision materially changes v1 scope; a legal/licensing issue requires owner judgment;
the production release is ready for `main`; a destructive or irreversible choice cannot
reasonably be made autonomously.

# 124. Initial Task

Begin with Phase 0: Planning. Inspect repository state; establish
planning/documentation structure; translate this specification into planning artifacts;
design architecture; define domain/data model; define APIs; define test strategy;
define security model; define risk register; define release process; decompose the v1
lifecycle into phases and numbered slices; encode `planning/roadmap.yaml`; generate
`docs/ROADMAP.md`; identify parallel execution opportunities; assign Opus/Sonnet
responsibilities; run an Opus planning review; correct inconsistencies; commit the
Phase 0 package. Only after the Phase 0 gate passes should implementation begin, then
proceed through the roadmap autonomously — one numbered slice per branch and PR,
parallelizing safely, self-reviewing and merging qualified slice PRs into `dev`. Do not
merge a formal release into `main` without human approval. Build FlightSite
deliberately, incrementally, and to production-quality standards.
