# FlightSite Data Model

Status: Phase 0 design (pre-implementation). This document is the authoritative design
for FlightSite's domain model and SQLite schema. Implementation slices write Alembic
migrations from this document; where an implementation slice must deviate, it updates
this document in the same PR (and records an ADR if the deviation is consequential).

**All schema changes ship as Alembic migrations with migration tests** (SPEC §107).
Tables below note the roadmap slice in which they first land.

Related: [`docs/ARCHITECTURE.md`](ARCHITECTURE.md), [`planning/SPEC.md`](../planning/SPEC.md),
[`planning/roadmap.yaml`](../planning/roadmap.yaml).

---

## 1. Domain concepts (SPEC §17)

FlightSite keeps three concepts strictly separate:

| Concept | Lifetime | Keyed by | Holds |
|---|---|---|---|
| **Aircraft** | Permanent | ICAO 24-bit hex address | Physical identity + receiver-relative lifetime records |
| **Sighting** | One continuous observation period | Surrogate id → aircraft | Times, reception statistics, per-sighting extremes, flight context |
| **Flight Context** | Belongs to one sighting | (embedded in sighting + events) | Callsign, squawk, route, origin/destination, operator-in-use, emergency state |

Separation rules:

- Permanent aircraft properties (registration, type, operator-as-registered, records)
  never live on sightings. Temporary flight properties (callsign, squawk, route) never
  live on aircraft.
- A sighting opens on the first observation of an aircraft not currently sighted and
  closes after the configured absence gap (default 10 min). A new sighting for the same
  aircraft begins only after the previous one is closed (SPEC §18).
- Live state (in-memory) is not the database. The tables below are the persistence
  model; the live store is documented in ARCHITECTURE.md.

### Conventions

- **Timestamps**: `INTEGER` Unix epoch **milliseconds, UTC**, column suffix `_ms`
  (SPEC §15). SQLite has no datetime type; integer epoch is compact, indexable, and
  unambiguous. All local-time presentation happens in the UI / rollup bucketing.
- **Units at rest**: nautical miles (`_nm REAL`), feet (`_ft INTEGER`), knots
  (`_kt REAL`), degrees true (`_deg REAL`). Metric display is a UI conversion.
- **ICAO hex**: `TEXT`, 6 lowercase hex chars, column `icao24`.
- **Enums**: `TEXT` with CHECK constraints on low-volume tables (readable dumps,
  cheap in SQLite); **integer codes** on hot high-volume tables
  (`sighting_track_checkpoints` and inside packed track encodings). The canonical
  enum value list (the string forms used by the API) lives in `docs/API.md`
  §Conventions and is authoritative; this document uses the same names.
- **JSON payloads**: `TEXT` columns suffixed `_json`, always schema-validated by
  Pydantic models in code; used only where relational querying is not needed.
- Booleans: `INTEGER` 0/1.

---

## 2. Core identity & sighting tables (slice 005 `meta`; slices 009/052 the rest)

### 2.1 `meta` — slice 005

Application-level key/value state.

```sql
CREATE TABLE meta (
  key      TEXT PRIMARY KEY,
  value    TEXT NOT NULL,
  updated_ms INTEGER NOT NULL
) WITHOUT ROWID;
```

Keys: `t0_ms` (write-once in code — T0 is set exactly when the first observation is
persisted and never silently reset, SPEC §16), `install_id`, `app_started_ms`,
`last_clean_shutdown_ms` (unclean-shutdown detection), `config_schema_note`.

### 2.2 `aircraft` — slice 009

One row per physical aircraft ever observed. Carries the receiver-relative lifetime
records (SPEC §53) denormalized for cheap reads; they are maintained transactionally at
sighting close (and incrementally for the live aircraft where cheap).

```sql
CREATE TABLE aircraft (
  id                  INTEGER PRIMARY KEY,
  icao24              TEXT NOT NULL UNIQUE,
  first_seen_ms       INTEGER NOT NULL,
  last_seen_ms        INTEGER NOT NULL,
  sighting_count      INTEGER NOT NULL DEFAULT 0,
  total_observed_ms   INTEGER NOT NULL DEFAULT 0,
  closest_approach_nm REAL,
  closest_approach_ms INTEGER,
  max_range_nm        REAL,                -- lifetime farthest detection
  max_range_ms        INTEGER,
  lowest_alt_ft       INTEGER,
  lowest_alt_ms       INTEGER,
  highest_alt_ft      INTEGER,
  highest_alt_ms      INTEGER
);
CREATE INDEX ix_aircraft_first_seen ON aircraft(first_seen_ms);
CREATE INDEX ix_aircraft_last_seen  ON aircraft(last_seen_ms);
CREATE INDEX ix_aircraft_sightings  ON aircraft(sighting_count);
```

Surrogate `id` (not `icao24` as PK): compact FKs across high-volume tables, and a
clean escape hatch for the (rare) ICAO reassignment problem and future multi-receiver
work. Record columns carry their `_ms` moments so the UI can say *when* the record was
set. Rarity ("never seen", "seen fewer than N times", SPEC §44) reads
`sighting_count` / `first_seen_ms` directly.

### 2.3 `sightings` — slice 009

One row per continuous observation period. Flight-context fields live here (and in
`sighting_events` for transitions); per-sighting extremes serve the Sightings page
(SPEC §57) and feed lifetime record updates.

```sql
CREATE TABLE sightings (
  id               INTEGER PRIMARY KEY,
  aircraft_id      INTEGER NOT NULL REFERENCES aircraft(id),
  started_ms       INTEGER NOT NULL,
  ended_ms         INTEGER,                -- NULL while active
  duration_ms      INTEGER,                -- set at close
  closure_reason   TEXT CHECK (closure_reason IN
                     ('gap_timeout','shutdown_recovery','data_reset')),

  -- flight context (temporary, per SPEC §17)
  callsign_first   TEXT,
  callsign_last    TEXT,                   -- changes recorded as sighting_events
  squawk_last      TEXT,
  had_emergency    INTEGER NOT NULL DEFAULT 0,
  origin_ident     TEXT,                   -- airport code, enrichment only
  destination_ident TEXT,
  route_source     TEXT CHECK (route_source IN ('aerodatabox')),
  inferred_airport_ident TEXT,             -- local heuristic, kept distinct (SPEC §28,41)
  inferred_phase   TEXT CHECK (inferred_phase IN ('arriving','departing')),

  -- position character
  any_position     INTEGER NOT NULL DEFAULT 0,
  mlat_used        INTEGER NOT NULL DEFAULT 0,
  ground_seen      INTEGER NOT NULL DEFAULT 0,

  -- reception statistics (SPEC §51; populated by slice 052)
  msg_count        INTEGER NOT NULL DEFAULT 0,
  pos_count        INTEGER NOT NULL DEFAULT 0,
  rssi_peak_db     REAL,
  rssi_avg_db      REAL,
  rssi_min_db      REAL,
  pos_time_pct     REAL,                   -- % of sighting with valid position

  -- per-sighting extremes (SPEC §57 columns)
  closest_approach_nm REAL,
  max_range_nm     REAL,
  lowest_alt_ft    INTEGER,
  highest_alt_ft   INTEGER,

  -- denormalized alert outcome for the Sightings page "alert/interesting" column;
  -- source of truth is alert_matches
  max_alert_severity TEXT CHECK (max_alert_severity IN
                     ('info','interesting','high','critical'))
);
CREATE INDEX ix_sightings_aircraft ON sightings(aircraft_id, started_ms);
CREATE INDEX ix_sightings_started  ON sightings(started_ms);
CREATE INDEX ix_sightings_open     ON sightings(ended_ms) WHERE ended_ms IS NULL;
CREATE INDEX ix_sightings_max_range ON sightings(max_range_nm, id);
```

The partial index on open sightings makes unclean-shutdown recovery (SPEC §71) and the
"no new sighting before close" rule cheap. `closure_reason='shutdown_recovery'` marks
sightings closed by startup recovery, giving diagnostics an honest trail.

`ix_sightings_max_range` serves `docs/API.md` §3.6's `sort=max_range_nm` in both
directions (`id` is the list endpoint's pagination tiebreaker). It was added in rev 0013
after slice 050 measured that sort at 8.0 s over 1.64M sightings. The remaining
documented sorts — `duration_s` and `closest_approach_nm` — and the `interesting` filter
stay unindexed on purpose: every index here is rewritten by the single writer on each
30-second flush of an open sighting, and a second sort index measured about 2.6x the
baseline per-sighting write cost again (issue #115; `docs/PERFORMANCE.md` §7.7).

### 2.4 Track storage — slice 052 (`sighting_track_checkpoints`, `sighting_tracks`)

Track storage uses **two structures** (SPEC §19; ADR-0005 — packed row-per-sighting
storage is the v1 design, adopted at the Phase 0 review gate to keep multi-year
storage within Pi 4 budgets):

1. **Active sighting — `sighting_track_checkpoints`**: the full-resolution current
   track lives in memory; the persistence worker checkpoints batches of points every
   ~30 s so a power cut loses at most the checkpoint interval. Checkpointed points are
   lightly thinned (collinear cruise points at unchanged altitude may be skipped —
   crash recovery therefore yields a pre-thinned path; constants finalized in slice
   052). Rows are **deleted at sighting close**, so this table's steady-state size is
   bounded by concurrent traffic, not history.

```sql
CREATE TABLE sighting_track_checkpoints (
  sighting_id  INTEGER NOT NULL REFERENCES sightings(id),
  seq          INTEGER NOT NULL,           -- ordering within sighting
  ts_ms        INTEGER NOT NULL,
  lat          REAL NOT NULL,
  lon          REAL NOT NULL,
  alt_ft       INTEGER,                    -- NULL on ground/unknown
  gs_kt        REAL,
  track_deg    REAL,
  pos_source   INTEGER NOT NULL,           -- integer code (0=adsb,1=mlat,2=none,3=other)
  PRIMARY KEY (sighting_id, seq)
) WITHOUT ROWID;
```

2. **At close — `sighting_tracks`**: the in-memory track is simplified with
   Douglas-Peucker (on the lat/lon/alt polyline, epsilon tuned for ~40–80 retained
   points on typical transits) and written as **one row per sighting** holding a
   compact packed binary encoding of the ordered, timestamped points — per point:
   time delta, lat, lon, altitude, ground speed, track, and position-source code.
   Checkpoint rows are then deleted in the same transaction. This is explicitly
   playback-capable: every retained point keeps its own timestamp, position,
   altitude, speed, track, and position source, so future historical playback needs
   no schema change — only a decoder for the packed format, which ships with it.

```sql
CREATE TABLE sighting_tracks (
  sighting_id      INTEGER PRIMARY KEY REFERENCES sightings(id),
  encoding_version INTEGER NOT NULL,       -- packed-format version for forward compat
  point_count      INTEGER NOT NULL,
  started_ms       INTEGER NOT NULL,       -- absolute base for per-point time deltas
  points_blob      BLOB NOT NULL           -- packed array (delta-encoded ints)
) WITHOUT ROWID;
```

Finalized in slice 052 (encoding v1): 5-byte header (`<BI` version, point_count) +
21 B/point (`<iiiiHHB`): dt_ms int32, lat/lon int32 deltas at 1e-5° (~1 m), altitude
int32 raw feet, ground speed uint16 at 0.1 kt, track uint16 at 0.01°, position-source
uint8; sentinels preserve None, out-of-range values clamp. Simplification epsilon
0.0005° (~56 m cross-track, cos-lat-scaled planar) plus a 100 ft altitude-profile
pass, union retained; checkpoint thinning at a 10× tighter tolerance (0.00005° /
25 ft) so it is invisible in the archive.

The packed encoding (delta-encoded scaled integers) costs ~16–21 B/point, so a typical
simplified track is a ~1–1.5 KB payload in a single clustered row instead of dozens of
b-tree rows. **On disk that row costs more than its payload:** a `WITHOUT ROWID` row
holds at most 1002 bytes inline at SQLite's default 4096-byte page size, so a record
beyond ~46 points spills a whole 4 KiB overflow page — 54.5% of tracks do, and slice
050 measured the table at **2,868 B/row** ([ADR-0014](adr/0014-track-storage-cost.md)
accepts that for v1 and defers the layout remedy; §9 sizes growth from the measured
figure). Reads are always "the whole path for sighting N" (sighting detail, future
playback), which the pack/unpack repository interface serves as points-in/points-out —
callers never see the encoding. `encoding_version` makes future format evolution an
additive migration.

### 2.5 `sighting_events` — slice 052

Meaningful state changes only (SPEC §52) — never one row per decoder snapshot.

```sql
CREATE TABLE sighting_events (
  id           INTEGER PRIMARY KEY,
  sighting_id  INTEGER NOT NULL REFERENCES sightings(id),
  ts_ms        INTEGER NOT NULL,
  type         TEXT NOT NULL CHECK (type IN
                 ('callsign_change','squawk_change','emergency_start',
                  'emergency_end','route_enriched','classification_available',
                  'alert_matched','alert_severity_upgraded')),
  payload_json TEXT                        -- e.g. {"from":"7000","to":"7700"}
);
CREATE INDEX ix_sevents_sighting ON sighting_events(sighting_id, ts_ms);
```

---

## 3. Metadata, classification, operators (slices 021–024)

### 3.1 `metadata_sources` — slice 021

```sql
CREATE TABLE metadata_sources (
  source          TEXT PRIMARY KEY,        -- 'mictronics' | 'faa' | 'airports' | 'opensky'
  last_attempt_ms INTEGER,
  last_success_ms INTEGER,
  status          TEXT NOT NULL DEFAULT 'never_run'
                    CHECK (status IN ('never_run','ok','failed')),
  dataset_version TEXT,                    -- upstream version/hash
  row_count       INTEGER,
  last_error      TEXT
) WITHOUT ROWID;
```

Per-source status reporting (SPEC §27) reads straight from this table; it also feeds
"metadata database age" in health (SPEC §67) and backup manifests (SPEC §72).

### 3.2 `aircraft_metadata` — slice 021 (rows from 022/023)

**One row per (icao24, source)** — sources never overwrite each other; imports replace
only their own rows, transactionally (staging table → validate → swap inside one
transaction; a failed import leaves prior rows untouched).

```sql
CREATE TABLE aircraft_metadata (
  icao24           TEXT NOT NULL,
  source           TEXT NOT NULL REFERENCES metadata_sources(source),
  registration     TEXT,
  type_code        TEXT,                   -- ICAO type designator, e.g. B738
  model            TEXT,
  manufacture_year INTEGER,
  operator_name    TEXT,
  owner            TEXT,                   -- FAA; 'Unknown' handling in code
  military_flag    INTEGER,                -- upstream flags, normalized
  flags_json       TEXT,                   -- remaining source-specific flags
  updated_ms       INTEGER NOT NULL,
  PRIMARY KEY (icao24, source)
) WITHOUT ROWID;
```

### 3.3 `aircraft_metadata_resolved` — slice 021

Field-level precedence is resolved **at import time** into one row per icao24, with a
source tag beside every resolved field. Rationale: the Aircraft page sorts and filters
on resolved type/operator in SQL, so resolution must be materialized; a generic
per-field EAV provenance table was rejected as slow and unqueryable at this scale.
Rebuilt inside the import transaction; also refreshed for a single aircraft when a
better source arrives.

```sql
CREATE TABLE aircraft_metadata_resolved (
  icao24            TEXT PRIMARY KEY,
  registration      TEXT,  registration_src TEXT,
  type_code         TEXT,  type_code_src    TEXT,
  model             TEXT,  model_src        TEXT,
  manufacture_year  INTEGER, year_src       TEXT,
  operator_name     TEXT,  operator_src     TEXT,
  operator_group_id INTEGER REFERENCES operator_groups(id),
  owner             TEXT,  owner_src        TEXT,
  updated_ms        INTEGER NOT NULL
) WITHOUT ROWID;
CREATE INDEX ix_amr_registration ON aircraft_metadata_resolved(registration);
CREATE INDEX ix_amr_type         ON aircraft_metadata_resolved(type_code);
CREATE INDEX ix_amr_opgroup      ON aircraft_metadata_resolved(operator_group_id);
```

`*_src` values: `mictronics | faa`, plus `opensky` on installs that enabled the
opt-in OpenSky source (ADR-0013) — and there only in `model_src`, `year_src`,
`operator_src` or `owner_src`, since it is ranked below both other sources and never
claims a registration or type code. Together with the three-tier provenance model
(§8), this satisfies SPEC §22 without a per-field provenance table.

The `operator_groups` FK is valid from birth: `operators`/`operator_groups` are
**created in slice 021's migration** (see §3.5) even though their curated content
arrives in slice 024 — with `foreign_keys=ON` (ADR-0001) the referenced table must
exist when this table is created.

### 3.4 `aircraft_classification` — slice 024

Computed classification with per-claim provenance and confidence (SPEC §39: weak
evidence ⇒ `unknown`, never false certainty). Recomputed at metadata import; keyed by
icao24 so classification exists even before first observation.

```sql
CREATE TABLE aircraft_classification (
  icao24            TEXT PRIMARY KEY,
  military          INTEGER NOT NULL DEFAULT 0,
  military_src      TEXT, military_conf REAL,
  government        INTEGER NOT NULL DEFAULT 0,
  government_src    TEXT, government_conf REAL,
  law_enforcement   INTEGER NOT NULL DEFAULT 0,
  law_enforcement_src TEXT, law_enforcement_conf REAL,
  mission_category  TEXT NOT NULL DEFAULT 'unknown' CHECK (mission_category IN
                      ('commercial_passenger','cargo','general_aviation',
                       'business_aviation','military','government',
                       'law_enforcement','medical','firefighting','training',
                       'helicopter','unknown')),
  mission_src       TEXT, mission_conf REAL,
  icon_category     TEXT NOT NULL DEFAULT 'unknown',  -- map icon hierarchy input
  updated_ms        INTEGER NOT NULL
) WITHOUT ROWID;
CREATE INDEX ix_class_mil ON aircraft_classification(military) WHERE military = 1;
CREATE INDEX ix_class_gov ON aircraft_classification(government) WHERE government = 1;
CREATE INDEX ix_class_law ON aircraft_classification(law_enforcement) WHERE law_enforcement = 1;
CREATE INDEX ix_class_mission ON aircraft_classification(mission_category);
```

`*_src` values: `mictronics | faa | heuristic`.

### 3.5 `operator_groups`, `operators` — created in slice 021, populated in slice 024

Curated normalization data (versioned data file in the repo, loaded into tables so SQL
can join/filter). The **tables are created by slice 021's migration** so
`aircraft_metadata_resolved`'s FK is valid from the first metadata migration; the
curated content and normalization logic land in slice 024. Exact operator strings are
always preserved on the metadata rows; grouping is additive (SPEC §38).

```sql
CREATE TABLE operator_groups (
  id    INTEGER PRIMARY KEY,
  slug  TEXT NOT NULL UNIQUE,              -- 'delta', 'fedex', ...
  name  TEXT NOT NULL
);
CREATE TABLE operators (
  name     TEXT PRIMARY KEY,               -- exact operator string
  group_id INTEGER NOT NULL REFERENCES operator_groups(id)
) WITHOUT ROWID;
```

### 3.6 `airports` — slice 027

From OurAirports (public domain). ~80k rows.

```sql
CREATE TABLE airports (
  id           INTEGER PRIMARY KEY,
  ident        TEXT NOT NULL UNIQUE,       -- ICAO/GPS ident
  iata         TEXT,
  name         TEXT NOT NULL,
  type         TEXT NOT NULL,              -- large_airport ... heliport
  lat          REAL NOT NULL,
  lon          REAL NOT NULL,
  elevation_ft INTEGER,
  iso_country  TEXT
);
CREATE INDEX ix_airports_lat ON airports(lat, lon);
CREATE INDEX ix_airports_iata ON airports(iata) WHERE iata IS NOT NULL;
```

Nearest-airport lookup: bounding-box on the `(lat, lon)` index, refine by great-circle
in code. At 80k rows this needs no R*Tree dependency.

---

## 4. Watchlists & alerts (slices 037–038)

### 4.1 `watchlists`, `watchlist_entries` — slice 037

```sql
CREATE TABLE watchlists (
  id          INTEGER PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  description TEXT,
  created_ms  INTEGER NOT NULL
);
CREATE TABLE watchlist_entries (
  id           INTEGER PRIMARY KEY,
  watchlist_id INTEGER NOT NULL REFERENCES watchlists(id) ON DELETE CASCADE,
  kind         TEXT NOT NULL CHECK (kind IN
                 ('icao24','registration','type_code','operator','category')),
  value        TEXT NOT NULL,              -- normalized (lowercase icao24, upper reg)
  note         TEXT,
  created_ms   INTEGER NOT NULL,
  UNIQUE (watchlist_id, kind, value)
);
CREATE INDEX ix_wentries_kind_value ON watchlist_entries(kind, value);
```

Live matching loads entries into an in-memory index; the table index serves CRUD and
future audit queries.

### 4.2 `alert_rules` — slice 038

Conditions are an **embedded, Pydantic-validated JSON document**, not a child table.
Justification: v1 conditions are a small closed set combined with AND only (SPEC §43) —
they are evaluated in memory against live state, never queried relationally; a
conditions table would add joins and migration surface for zero query benefit. The JSON
schema is versioned (`conditions_json.version`) so a future nested-expression feature
migrates explicitly.

```sql
CREATE TABLE alert_rules (
  id              INTEGER PRIMARY KEY,
  name            TEXT NOT NULL,
  description     TEXT,
  severity        TEXT NOT NULL CHECK (severity IN
                    ('info','interesting','high','critical')),
  enabled         INTEGER NOT NULL DEFAULT 1,
  template_key    TEXT,                    -- non-null if instantiated from a template
  conditions_json TEXT NOT NULL,
  created_ms      INTEGER NOT NULL,
  updated_ms      INTEGER NOT NULL
);
```

Condition kinds (each optional, all AND-ed): `classification` (mil/gov/law/mission),
`type_code`, `model`, `watchlist_id`, `rare_aircraft {max_sightings}`,
`rare_type {max_sightings}`, `max_distance_nm`, `min_distance_nm`, `max_alt_ft`,
`min_alt_ft`. Emergency-squawk detection is built in and rule-independent (SPEC §47).

### 4.3 `alert_matches` — slice 038

```sql
CREATE TABLE alert_matches (
  id           INTEGER PRIMARY KEY,
  rule_id      INTEGER REFERENCES alert_rules(id),   -- NULL for built-ins
  builtin_key  TEXT,                                 -- e.g. 'emergency_7700'
  sighting_id  INTEGER NOT NULL REFERENCES sightings(id),
  aircraft_id  INTEGER NOT NULL REFERENCES aircraft(id),
  matched_ms   INTEGER NOT NULL,
  severity     TEXT NOT NULL CHECK (severity IN
                 ('info','interesting','high','critical')),
  reason       TEXT NOT NULL,              -- human-readable match reason
  notified     INTEGER NOT NULL DEFAULT 0,
  CHECK (rule_id IS NOT NULL OR builtin_key IS NOT NULL)
);
CREATE UNIQUE INDEX ux_amatch_rule_sighting
  ON alert_matches(rule_id, sighting_id) WHERE rule_id IS NOT NULL;
CREATE UNIQUE INDEX ux_amatch_builtin_sighting
  ON alert_matches(builtin_key, sighting_id) WHERE builtin_key IS NOT NULL;
CREATE INDEX ix_amatch_matched ON alert_matches(matched_ms);
```

The unique indexes are the once-per-sighting-per-rule dedupe guarantee (SPEC §48) at
the storage layer, surviving restarts. Severity upgrades of built-ins use distinct
`builtin_key`s, which is exactly the allowed "higher-priority condition may notify
again" path.

---

## 5. Activity & milestones (slice 035)

```sql
CREATE TABLE activity_events (
  id          INTEGER PRIMARY KEY,
  ts_ms       INTEGER NOT NULL,
  type        TEXT NOT NULL,               -- first_aircraft, new_type, range_record,
                                           -- alert, emergency, receiver_offline,
                                           -- receiver_restored, metadata_update,
                                           -- milestone, maintenance_issue, data_reset
  severity    TEXT NOT NULL DEFAULT 'info' CHECK (severity IN
                ('info','interesting','high','critical')),
  aircraft_id INTEGER REFERENCES aircraft(id),
  sighting_id INTEGER REFERENCES sightings(id),
  payload_json TEXT,
  dedupe_key  TEXT UNIQUE                  -- restart/replay idempotency
);
CREATE INDEX ix_activity_ts ON activity_events(ts_ms DESC);
CREATE INDEX ix_activity_type_ts ON activity_events(type, ts_ms);

CREATE TABLE milestones (
  key         TEXT PRIMARY KEY,            -- 'first_military', 'unique_aircraft_1000',
                                           -- 'first_type_B52', ...
  achieved_ms INTEGER NOT NULL,
  aircraft_id INTEGER REFERENCES aircraft(id),
  value_num   REAL,
  payload_json TEXT
) WITHOUT ROWID;
```

One-time milestones live here (PK = natural key ⇒ fire-once for free). Rolling records
(max range ever, busiest day, highest simultaneous count) live in `lifetime_stats`
(§6.4) with their achievement moments; both emit `activity_events`.

---

## 6. Receiver metrics (slice 033) & analytics rollups (slice 031)

### 6.1 `receiver_metrics_raw` — windowed high-resolution samples

One wide row per sample (~15 s cadence). Decoder-native fields normalized; NULL where
a decoder doesn't supply a metric (SPEC §60).

```sql
CREATE TABLE receiver_metrics_raw (
  ts_ms             INTEGER PRIMARY KEY,
  messages_per_sec  REAL,
  positions_per_sec REAL,
  aircraft_visible  INTEGER,
  aircraft_with_pos INTEGER,
  max_range_nm      REAL,
  rssi_avg_db       REAL,
  rssi_peak_db      REAL
) WITHOUT ROWID;
```

Retention: pruned past the configured high-resolution window (**default 14 days**,
configurable 7–30 — Phase 0 decision per SPEC §64) after downsampling.

### 6.2 `receiver_metrics_hourly`, `receiver_metrics_daily`

```sql
CREATE TABLE receiver_metrics_hourly (
  hour_start_ms     INTEGER PRIMARY KEY,
  messages_total    INTEGER, positions_total INTEGER,
  msgs_per_sec_avg  REAL, msgs_per_sec_max REAL,
  pos_per_sec_avg   REAL, pos_per_sec_max  REAL,
  aircraft_avg      REAL, aircraft_max     INTEGER,
  max_range_nm      REAL,
  rssi_avg_db       REAL, rssi_peak_db     REAL,
  sample_count      INTEGER NOT NULL
) WITHOUT ROWID;
-- receiver_metrics_daily: identical shape keyed by local calendar day
CREATE TABLE receiver_metrics_daily (
  day               TEXT PRIMARY KEY,      -- 'YYYY-MM-DD' receiver-local (§10)
  messages_total    INTEGER, positions_total INTEGER,
  msgs_per_sec_avg  REAL, msgs_per_sec_max REAL,
  pos_per_sec_avg   REAL, pos_per_sec_max  REAL,
  aircraft_avg      REAL, aircraft_max     INTEGER,
  max_range_nm      REAL,
  rssi_avg_db       REAL, rssi_peak_db     REAL,
  sample_count      INTEGER NOT NULL
) WITHOUT ROWID;
```

Hourly retained indefinitely (~8.8k rows/yr), daily indefinitely (365/yr). The signal
*distribution* chart (SPEC §62) is **not** derived from these tables: a histogram of
sample-averaged receiver RSSI is not a signal-strength distribution. It is computed
from the **per-sighting reception stats** (`sightings.rssi_avg_db` /
`rssi_peak_db`, slice 052 data) over the selected window — a real, already-stored
per-aircraft population — by slices 033/034.

### 6.3 `range_by_bearing_daily`

72 buckets of 5°; feeds the polar plot and coverage lifetime records. Kept
indefinitely (72 × 365 ≈ 26k rows/yr, trivial).

```sql
CREATE TABLE range_by_bearing_daily (
  day            TEXT NOT NULL,
  bearing_bucket INTEGER NOT NULL,         -- 0..71 (bucket * 5 deg)
  max_range_nm   REAL NOT NULL,
  at_ms          INTEGER NOT NULL,
  icao24         TEXT,                     -- who set it (fun + verification)
  PRIMARY KEY (day, bearing_bucket)
) WITHOUT ROWID;
```

### 6.4 `lifetime_stats`

Rolling since-T0 aggregates and records (SPEC §63) that must survive all pruning.

```sql
CREATE TABLE lifetime_stats (
  key        TEXT PRIMARY KEY,             -- 'total_messages','total_positions',
                                           -- 'max_range_nm','max_range_at_ms',
                                           -- 'max_range_icao24','busiest_day',
                                           -- 'busiest_day_count','max_simultaneous',
                                           -- 'peak_msg_rate', ...
  value_num  REAL,
  value_text TEXT,
  updated_ms INTEGER NOT NULL
) WITHOUT ROWID;
```

### 6.5 Analytics daily rollups — slice 031

Maintained incrementally by the persistence worker at sighting close / day boundary,
with a backfill job for correctness repair. Property-tested against brute-force
recomputation.

```sql
CREATE TABLE daily_stats (
  day              TEXT PRIMARY KEY,       -- receiver-local date
  unique_aircraft  INTEGER NOT NULL DEFAULT 0,
  new_aircraft     INTEGER NOT NULL DEFAULT 0,   -- first-ever seen this day
  sightings        INTEGER NOT NULL DEFAULT 0,
  interesting      INTEGER NOT NULL DEFAULT 0,
  military         INTEGER NOT NULL DEFAULT 0,
  government       INTEGER NOT NULL DEFAULT 0,
  law_enforcement  INTEGER NOT NULL DEFAULT 0,
  max_range_nm     REAL,
  busiest_hour     INTEGER                 -- 0-23 local; closed-day value (see below)
) WITHOUT ROWID;

CREATE TABLE daily_type_stats (
  day        TEXT NOT NULL,
  type_code  TEXT NOT NULL,
  sightings  INTEGER NOT NULL,
  unique_aircraft INTEGER NOT NULL,
  PRIMARY KEY (day, type_code)
) WITHOUT ROWID;

CREATE TABLE daily_operator_stats (
  day        TEXT NOT NULL,
  operator_group_id INTEGER NOT NULL,
  sightings  INTEGER NOT NULL,
  unique_aircraft INTEGER NOT NULL,
  PRIMARY KEY (day, operator_group_id)
) WITHOUT ROWID;

CREATE TABLE type_stats (                  -- since-T0 per type; rarity + first-of-type
  type_code       TEXT PRIMARY KEY,
  unique_aircraft INTEGER NOT NULL DEFAULT 0,
  total_sightings INTEGER NOT NULL DEFAULT 0,
  first_seen_ms   INTEGER NOT NULL,
  last_seen_ms    INTEGER NOT NULL
) WITHOUT ROWID;
```

"Most frequently seen aircraft" over a window is deliberately **not** rolled up per
(day, aircraft): it is a `GROUP BY aircraft_id` over `ix_sightings_started` (≤ ~45k
rows for a 30-day window on a busy receiver — measured budget in slice 031); the
Since-T0 variant reads `aircraft.sighting_count`.

**Busiest hour has two sources by time range:** `daily_stats.busiest_hour` (slice
031) is the finalized **closed-day** value, written at the day boundary. The
**in-progress day's** busiest hour — needed by Today-at-a-Glance (slice 036) — is
served from slice 033's hourly metric table (`receiver_metrics_hourly.aircraft_max` /
counts for today's hours), since rollups for the current day are not yet final.

---

## 7. Enrichment cache (slice 026)

```sql
CREATE TABLE route_cache (
  cache_key    TEXT PRIMARY KEY,           -- normalized callsign (+date bucket)
  status       TEXT NOT NULL CHECK (status IN ('ok','not_found','error')),
  origin_ident TEXT,
  destination_ident TEXT,
  payload_json TEXT,                       -- provider extras, schema-validated
  fetched_ms   INTEGER NOT NULL,
  expires_ms   INTEGER NOT NULL
) WITHOUT ROWID;
CREATE INDEX ix_route_cache_expiry ON route_cache(expires_ms);
```

Negative results (`not_found`, `error`) are cached with shorter TTLs — "cache
aggressively, respect provider limits" (SPEC §28). Pruned by expiry during maintenance.

---

## 8. Provenance model (SPEC §22)

Three tiers, matched to how each datum actually flows — chosen over a generic
per-field provenance table (unbounded growth, join-heavy reads, no query need):

1. **Live/decoder fields** (position, altitude, speed, squawk, signal): provenance is
   structural — the ingest layer tags each live field `decoder` or `derived`
   (distance/bearing, ground inference) and `position_source` distinguishes
   `adsb | mlat | none | other` per SPEC §21 (canonical values in API.md
   §Conventions). Persisted per track point (checkpoints and packed tracks); not
   stored per decoder update elsewhere.
2. **Aircraft metadata**: per-source rows (`aircraft_metadata`) plus `_src` columns on
   every resolved field (`aircraft_metadata_resolved`, `aircraft_classification`),
   giving true field-level provenance for everything enrichment-derived.
3. **Sighting flight context**: `route_source` (external provider) vs
   `inferred_*` columns (local heuristic) keep externally-reported routes and local
   inference structurally separate; enrichment arrival is also a `sighting_event`.

The API composes these into per-field provenance for the detail UI.

---

## 9. Retention & growth model (SPEC §64–66)

| Table | Retention |
|---|---|
| aircraft, sightings, sighting_tracks, sighting_events, milestones, activity_events, lifetime_stats, daily_* rollups, type_stats, range_by_bearing_daily | **Indefinite** (until user reset) |
| sighting_track_checkpoints | Deleted at sighting close / recovery (bounded by concurrent traffic) |
| receiver_metrics_raw | High-res window, default **14 days** (7–30 configurable) |
| receiver_metrics_hourly/daily | Indefinite |
| route_cache | TTL-pruned |
| aircraft_metadata* | Replaced per source at import |

**Growth arithmetic — two calibration scenarios.** The first models a typical
suburban receiver; the second models the SPEC §5 design envelope (peak ~500
simultaneously visible aircraft). A receiver peaking near 500 plausibly averages
150–200 concurrent aircraft around the clock; with a ~15-minute mean sighting that
implies roughly 15,000–20,000 sightings/day (we size at 18,000). Both use the packed
track design (§2.4): a simplified track averages ~60 points and ~1.3 KB of packed
payload, which costs **~2,870 B on disk** once SQLite's overflow pages are counted
(§2.4 and [ADR-0014](adr/0014-track-storage-cost.md) explain why; that row is 86% of
the database, so it decides these totals).

**The figures below are the ones slice 050 measured** — see
[PERFORMANCE.md §7.6](PERFORMANCE.md) for the runs behind them. The original design
estimate was 1.0–1.2 GB/year for Scenario A and 12–14 GB/year for Scenario B, sized
on ~1.3 KB per track row; ADR-0014 records why that was 2.2× too low per row, accepts
the measured cost for v1, and defers the layout remedy. The estimate is quoted here
and in `perf/storage_qualification/scenarios.py` only so the size of the gap stays
visible.

*Scenario A — typical suburban receiver (~1,500 sightings/day, ~750 unique/day):*

| Table | Rows/yr | Bytes/row measured (incl. overhead) | ~Size/yr |
|---|---|---|---|
| sightings | 1,500 × 365 ≈ **550k** | ~180 B | ~100 MB |
| sighting_tracks (packed) | ≈ **505k** (~92% of sightings carry a track) | **~2,870 B** | **~1.45 GB** |
| sighting_events (~2.5/sighting) | ≈ **1.4M** | ~75 B | ~105 MB |
| aircraft (new) | ~40k/yr | ~100 B | ~4 MB |
| activity_events (~200/day) | ~73k | ~145 B | ~11 MB |
| alert_matches (~100/day) | ~37k | ~125 B | ~5 MB |
| receiver_metrics_raw | steady-state 14 d × 5,760/day ≈ 81k rows | ~70 B | ~6 MB steady |
| hourly + daily + rollups + bearing | < 60k | small | < 5 MB |

**Scenario A total ≈ 1.7 GB/year** (measured: **1.68**) → a 3-year database is
**~5 GB** (measured: 5.03 GB). Comfortable on any Pi 4 storage, but not the 3–4 GB
the design estimate promised.

*Scenario B — SPEC §5 envelope (~18,000 sightings/day, ~4,000+ unique/day):*

| Table | Rows/yr | ~Size/yr |
|---|---|---|
| sightings | 18k × 365 ≈ **6.6M** | ~1.2 GB |
| sighting_tracks (packed) | ≈ **6.1M** | **~17.4 GB** |
| sighting_events (~2.5/sighting) | ≈ **16.5M** | ~1.2 GB |
| aircraft (new) | ~200k/yr | ~20 MB |
| everything else | — | < 100 MB |

**Scenario B total ≈ 20 GB/year** (measured over 30 days and projected: **20.06**) →
**~60 GB over 3 years**, not the 36–42 GB the design estimate promised. Storage
sizing follows from that: such a site wants **128 GB or more, and realistically a
USB SSD or NVMe rather than an SD card** — a 64 GB card no longer holds three years,
and `maintenance.policy` refuses to `VACUUM` without free space of twice the database
size, so a 60 GB history on a 128 GB card can never be compacted (PERFORMANCE.md
§7.7). A 16–32 GB card is out of the question for this scenario; the install
documentation states this sizing honestly. Without the packed design, Scenario B's
track points alone would exceed 25 GB/year, which is why packing is the v1 design,
not a contingency (ADR-0005) — the overflow-page cost is a storage-layout defect on
top of a design that is otherwise doing exactly what it was chosen for.

Per-sighting cost does **not** depend on traffic density: Scenario A measured 3,064
bytes/sighting over three years and Scenario B 3,042 over 30 days, a twelvefold
difference in density and a 0.7% difference in cost. Any receiver's multi-year size
can therefore be projected from its sightings/day alone.

**The lever, if this ever needs one, is the inline payload limit — not retention.**
Giving `sighting_tracks` a rowid, or raising `page_size` (measured: 16384 brings the
same three-year history to 3.09 GB, 1.03 GB/year), moves the limit past the retained-
point distribution. ADR-0014 defers both, with the migration cost of each and the
triggers that would reopen the question. A tiered track retention policy — which
would relax SPEC §65's retain-indefinitely rule and therefore needs its own ADR plus
explicit reconciliation with the spec — is explicitly **not** the lever to reach for
first: the overrun is slack in a storage parameter, not too much data. Simplification
epsilon remains the accuracy knob, benchmarked in slice 052, and is likewise not a
storage remedy.

---

## 10. Time & timezone rules

- Every stored instant is UTC epoch milliseconds (§ Conventions).
- `day`-keyed rollup tables use the **receiver-local calendar date** computed with the
  configured IANA timezone at write time — day boundaries are DST-correct (a 23- or
  25-hour local day rolls up as such; tested with DST fixtures in slice 031).
- Changing the configured timezone applies to new rollups only; historical buckets are
  not rewritten (documented behavior; a rebuild job is possible later since sightings
  retain full UTC timestamps).
- "Today at a Glance" and analytics presets resolve their ranges in receiver-local
  time, then query UTC columns via computed boundaries.

---

## 11. Future-proofing

**Multi-receiver (explicit non-goal, must not be precluded — SPEC §12):** every
observation-derived table hangs off `aircraft`/`sightings` surrogate ids; receiver
identity lives only in configuration and `meta`. An honest assessment of the
migration: for `sightings`, `receiver_metrics_*`, `range_by_bearing_daily`, and the
daily rollups, adding a `receivers` table and `receiver_id` FK columns (defaulting to
receiver 1) is genuinely additive. But the **receiver-relative** data is broader than
that: the `aircraft` row's lifetime records (`closest_approach_nm`, `max_range_nm`,
first/last seen, sighting count, cumulative duration) are receiver-relative and would
move out of the global airframe row into a new `aircraft_receiver_stats` table, and
`type_stats`, `milestones`, `lifetime_stats`, `activity_events`, and `alert_matches`
are equally receiver-relative and would need the same treatment. Nothing here
*precludes* multi-receiver — surrogate keys and clearly named receiver-relative
columns make the restructuring mechanical — but for those tables it is a
restructuring migration, not a column add. That meets SPEC §12's bar (do not make it
impossible) without overclaiming.

**Historical playback (deferred feature, schema-ready — SPEC §19):** packed
`sighting_tracks` rows keep ordered per-point timestamps, position, altitude, speed,
track, and position source (decoded by the shipping pack/unpack layer);
`sighting_events` supplies callsign/squawk/emergency transitions on the same
timeline. Playback is therefore an API + UI feature over existing data.

**Adapter neutrality (SPEC §11):** nothing in this schema references readsb-specific
field names; ingest normalizes before anything is persisted.

---

## 12. Slice landing map

| Slice | Tables |
|---|---|
| 005 | `meta` (+ Alembic baseline) |
| 009 | `aircraft`, `sightings` |
| 052 | `sighting_track_checkpoints`, `sighting_tracks`, `sighting_events` (+ populates the reception-stat columns on `sightings`) |
| 021 | `metadata_sources`, `aircraft_metadata`, `aircraft_metadata_resolved`, `operators`, `operator_groups` (created empty; populated in 024) |
| 024 | `aircraft_classification` (+ populates `operators`/`operator_groups`) |
| 026 | `route_cache` |
| 027 | `airports` |
| 031 | `daily_stats`, `daily_type_stats`, `daily_operator_stats`, `type_stats` |
| 033 | `receiver_metrics_*`, `range_by_bearing_daily`, `lifetime_stats` |
| 035 | `activity_events`, `milestones` |
| 037 | `watchlists`, `watchlist_entries` |
| 038 | `alert_rules`, `alert_matches` |
