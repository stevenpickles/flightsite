# FlightSite — v1 Roadmap

> **Canonical source:** [`planning/roadmap.yaml`](../planning/roadmap.yaml). This
> document is the human-readable representation. If the two disagree, the YAML wins
> and the disagreement must be fixed immediately (SPEC §92). Slice IDs are stable and
> never repurposed.

Every slice is one numbered feature branch (`<id>-<short-description>`) and one PR
into `dev`, merged with a merge commit after CI gates and Fable self-review. `dev`
must remain deployable after every merge.

## Phases

| # | Phase | Goal |
|---|---|---|
| 0 | Planning | Planning package, architecture, data model, API design, roadmap, review gate |
| 1 | Foundation | Repo, backend/frontend skeletons, CI, configuration, database, Docker |
| 2 | Ingestion & Live Domain | Decoder ingestion, live state, sighting lifecycle, live API/WS, demo/replay |
| 3 | Live Map Experience | Map, aircraft rendering, labels, detail, filters, wizard, settings, E2E foundation |
| 4 | Metadata & Enrichment | Offline metadata, FAA, classification, route enrichment, airports, overlays |
| 5 | History & Analytics | Aircraft/Sightings pages, analytics, receiver analytics, activity, milestones |
| 6 | Alerts & Notifications | Watchlists, rule engine, interesting surfaces, notifications, alerts page |
| 7 | Operations | Health/diagnostics, backup/restore, maintenance, data reset |
| 8 | Hardening & Release Qualification | Full E2E, visual regression, a11y, performance, storage qualification, docs |

## Release Checkpoints

Releases are prepared on `release/vX.Y.Z` branches from qualified `dev`; the merge to
`main` requires human approval (SPEC §113).

| Version | After Phase | Theme |
|---|---|---|
| v0.1.0 | 3 | Live radar MVP: ingestion, sightings, live map, demo mode, setup wizard |
| v0.2.0 | 8 | Consolidated release: identity completion, history & analytics, alerts & notifications, operations, and the Phase 8 hardening pass (the planned v0.2–v0.5 themes shipped together; recorded 2026-09-01) |
| v0.3.0 | 8 | Fresh-install polish and live-picture correctness from the first real deployment (slices 056–062; recorded 2026-09-02) |
| v0.3.1 | 8 | Same-day patch: aircraft label stability and the honest position-fix anchor (slices 063–064; recorded 2026-09-02) |
| v0.3.2 | 8 | Military filter activation on real metadata availability + the clean Pi 5 performance baseline with five budgets promoted to hard gates (slices 065–066; recorded 2026-09-03) |
| v0.4.0 | 8 | Settings that apply on save and alerts that reach every tab: enrichment hot-apply, stats-poller hot-start, app-shell-owned live socket, Notified marker write path, fix-dated track points, ADR-0014/0015, severity-triaged tracker (slices 067–069; recorded 2026-09-04) |
| v0.5.0 | 8 | Route enrichment credit economy: week-long callsign cache, learned schedules, daily lookup budget with priority, restricted flights cached, airport names beside route idents (slice 070; migration 0014; recorded 2026-09-04) |
| v0.6.0 | 8 | Offline route directory: VRS standing-data routes as the primary origin/destination source (SPEC §28 amended, ADR-0016), AeroDataBox only for misses, inferred route end, last-known route, CI perf-gate headroom (slice 071; migration 0015; recorded 2026-09-05) |
| v0.6.1 | 8 | Same-day hotfix superseding v0.6.0: migration 0015's sightings rebuild runs with foreign keys off and checked, resumable from a failed v0.6.0 attempt (slice 072; recorded 2026-09-05) |
| v1.0.0 | 8 | Qualified stable release per SPEC §114 definition of done |

## Slices

### Phase 1 — Foundation

| ID | Title | Depends on | Agent | Risk | Objective |
|---|---|---|---|---|---|
| 001 | Backend skeleton | — | sonnet | low | Python backend package with app factory, health/readiness, structured logging, quality tooling |
| 002 | Frontend skeleton | — | sonnet | low | React/TS frontend with nav shell, theming, quality tooling |
| 003 | CI pipeline | 001, 002 | sonnet | low | GitHub Actions quality gates and security scanning as required checks |
| 004 | Configuration system | 001 | opus | medium | config.yaml / secrets.yaml / env-override configuration model |
| 005 | Database foundation | 001, 004 | opus | medium | SQLite via SQLAlchemy 2.x async, Alembic, WAL, integrity checks |
| 006 | Docker packaging | 003, 004, 005 | sonnet | medium | Two multi-arch containers, Compose deployment, GHCR publishing |

### Phase 2 — Ingestion & Live Domain

| ID | Title | Depends on | Agent | Risk | Objective |
|---|---|---|---|---|---|
| 007 | Decoder ingestion adapter | 004 | opus | medium | DecoderAdapter abstraction + ReadsbJsonAdapter polling normalized state updates |
| 008 | Live aircraft state store | 007 | opus | high | In-memory live registry with lifecycle timing, derived fields, provenance |
| 009 | Sighting persistence core | 005, 008 | opus | high | Write-behind worker, sighting open/close lifecycle, flight context, lifetime records, T0 |
| 052 | Sighting tracks & reception stats | 009 | opus | high | Track checkpointing, DP-simplified packed tracks, reception stats, sighting events |
| 053 | Unclean-shutdown recovery | 052 | opus | high | Power-loss recovery of open sightings with bounded loss and diagnostics |
| 010 | Live API & WebSocket | 005, 008, 009 | opus | medium | Versioned REST + snapshot/delta WebSocket for live state |
| 011 | Demo mode | 007, 008 | sonnet | medium | Deterministic demo adapter simulating rich traffic |
| 012 | Capture & replay tooling | 007 | sonnet | low | Developer capture of normalized snapshots + deterministic replay |

> Slices 052/053 carry out-of-sequence IDs: they were split from the original slice
> 009 at the Phase 0 review gate, and existing IDs are never renumbered (SPEC §97).

### Phase 3 — Live Map Experience

| ID | Title | Depends on | Agent | Risk | Objective |
|---|---|---|---|---|---|
| 013 | Map foundation | 002 | sonnet | medium | MapLibre with basemap registry, dark default, range rings, receiver marker |
| 014 | Live aircraft rendering | 010, 013 | opus | high | WS-driven aircraft layer with hierarchical icons, selection, stale fade |
| 015 | Map labels & decluttering | 014 | sonnet | medium | Priority-based aircraft labels |
| 016 | Aircraft detail panel | 014 | sonnet | low | Comprehensive detail panel with provenance and external links |
| 017 | Live filters & non-positioned list | 014 | sonnet | medium | Filter drawer, quick filters, non-positioned aircraft panel |
| 018 | First-run setup wizard | 002, 004, 007, 013 | sonnet | medium | Guided first-run configuration landing on the Live Map |
| 019 | Settings page | 002, 004, 007 | sonnet | medium | Settings UI over the canonical config model with masked secrets |
| 020 | E2E foundation | 006, 011, 014, 016, 018 | sonnet | medium | Playwright infrastructure over demo mode + first critical flows |

### Phase 4 — Metadata & Enrichment

| ID | Title | Depends on | Agent | Risk | Objective |
|---|---|---|---|---|---|
| 021 | Metadata framework | 005 | opus | high | Normalized metadata schema, provider interface, transactional imports |
| 022 | Mictronics/tar1090 importer | 021 | sonnet | medium | Primary offline metadata source import with attribution |
| 023 | FAA registry importer | 021 | sonnet | low | Optional supplemental U.S. registry import |
| 024 | Classification & operator normalization | 021, 022 | opus | high | Military/gov/police + mission classification and operator groups with provenance |
| 025 | Metadata update action | 019, 022, 023 | sonnet | low | Manual per-source metadata update with independent status |
| 026 | Route enrichment (AeroDataBox) | 009, 016, 052 | opus | medium | Optional route enrichment: caching, rate limiting, provenance, graceful degradation |
| 027 | Airport data & context | 009, 016, 021, 025, 026 | opus | medium | Airport dataset + nearest-airport and labeled arrival/departure inference |
| 028 | Aviation overlays | 013, 027 | sonnet | medium | Airport and airspace map overlays with documented licensing |

### Phase 5 — History & Analytics

| ID | Title | Depends on | Agent | Risk | Objective |
|---|---|---|---|---|---|
| 029 | Aircraft page | 009, 016, 024 | sonnet | medium | Sortable historical Aircraft page over paginated APIs |
| 030 | Sightings page | 009, 013, 016, 024, 052 | sonnet | medium | Chronological sightings log with per-sighting detail and path |
| 031 | Analytics backend | 009, 024 | opus | high | Daily rollups and aggregation APIs with time presets |
| 032 | Analytics page | 031, 033 | sonnet | low | Analytics UI with presets and themed charts |
| 033 | Receiver metrics & retention | 005, 007 | opus | high | Decoder + FlightSite metrics with downsampling and pruning |
| 034 | Receiver page | 031, 033, 052 | sonnet | medium | Scorecard, charts, range-by-bearing polar plot, lifetime stats |
| 035 | Activity feed & milestones | 009, 010, 024, 025 | opus | medium | Persistent activity events, milestone/record detection, feed UI |
| 036 | Today at a glance | 031, 033, 035 | sonnet | low | Compact daily summary on the Live Map experience |

### Phase 6 — Alerts & Notifications

| ID | Title | Depends on | Agent | Risk | Objective |
|---|---|---|---|---|---|
| 037 | Watchlists | 009, 024 | sonnet | low | User-defined watchlists with CRUD and live matching |
| 038 | Alert rule engine | 024, 031, 037 | opus | high | AND-combined rule evaluation, rarity, emergency squawks, templates, dedup |
| 039 | Interesting aircraft surfaces | 038, 014, 035 | sonnet | medium | Interesting panel, map emphasis, label indicator, feed integration |
| 040 | Browser notifications | 038, 039 | sonnet | medium | Notification API delivery with permission handling and dedup |
| 041 | Alerts page & rule builder | 038, 037 | sonnet | medium | Visual rule builder, templates, alert history |

### Phase 7 — Operations

| ID | Title | Depends on | Agent | Risk | Objective |
|---|---|---|---|---|---|
| 042 | Health & diagnostics | 010, 019, 025, 026, 033, 040 | sonnet | medium | Full health/diagnostics UI and API — no SSH required |
| 043 | Backup & restore | 004, 005, 021 | opus | high | Version-aware, checksum-validated, SQLite-safe backup/restore |
| 044 | Database maintenance | 005, 009, 033, 053 | opus | high | Automated integrity checks, pruning, optimization, recovery hardening |
| 045 | Data reset actions | 019, 043 | sonnet | medium | Confirmed Reset FlightSite Data and Clear Metadata Cache |

### Phase 8 — Hardening & Release Qualification

| ID | Title | Depends on | Agent | Risk | Objective |
|---|---|---|---|---|---|
| 046 | E2E expansion | 020, 025, 030, 032, 040, 043, 045 | sonnet | medium | Complete SPEC §82 critical-flow E2E suite |
| 047 | Visual regression suite | 020, 032, 034, 039, 041 | sonnet | medium | Deterministic screenshot regression over stable views |
| 048 | Accessibility baseline | 032, 034, 039, 041 | sonnet | medium | SPEC §80 accessibility baseline verified across main flows |
| 049 | Performance harness & Pi gates | 009, 010, 011, 012, 038, 053 | opus | high | SPEC §85 performance regression harness with hard gates |
| 050 | Multi-year storage qualification | 031, 043, 044, 049 | opus | high | Synthetic multi-year dataset qualification of growth, queries, retention |
| 051 | Documentation & install polish | 042, 045, 046 | sonnet | low | Docs complete enough for a fresh install from documentation alone |
| 054 | Live map motion correctness | 014, 039 | opus | medium | Anchor dead reckoning to the last position change so markers stop creeping forward then teleporting back (issue #119) |
| 055 | Alert template instantiation fixes | 038, 041, 046 | opus | medium | Instantiate newly enabled alert templates on config save, and fix the wizard/catalogue template-key mismatch (issues #110, #111) |
| 056 | First-run ingestion hot-start | 007, 019, 055 | opus | medium | Start decoder ingestion on the config save that ends the first-run state, so a fresh install needs no backend restart (issue #122) |
| 057 | Activity WebSocket batching | 012, 035, 049 | opus | medium | Batch a detector pass's activity events into one WebSocket frame so a fresh install's backlog stops evicting every client (issue #99) |
| 058 | Quick wins bundle | 031, 042, 043, 050 | opus | low | Six small tracked fixes on one branch: max-range sort index, FAA User-Agent, VACUUM refusal surfaced, backup gzip 6, pagination noun, demo-mode "today" (issues #107, #112, #115, #116, #117, #121) |
| 059 | OpenSky metadata source | 021, 022, 023, 042 | opus | medium | Opt-in, default-off OpenSky aircraft database as a fill-gaps-only source under an ambiguous license (ADR-0013) |
| 060 | Raspberry Pi 4 performance baseline | 049, 050 | opus | low | Record the first Pi 4 baseline in docs/PERFORMANCE.md §5.4 and defer §5.3 promotion to the pending clean re-run (issues #101, #132) |
| 061 | Selected aircraft track backfill | 014, 052 | opus | low | Backfill the selected aircraft's track from its open sighting so a click draws the whole current sighting, not just what arrives after it (issue #133) |
| 062 | Live-set ghost expiry | 007, 008, 009 | opus | medium | Age live records by the decoder's own "last heard" report so dump1090's ~5-minute retention window stops inflating the live count and the 15 s / 60 s thresholds fire on time (issue #134) |
| 063 | Aircraft label stability | 014, 015 | opus | low | Stop aircraft labels blinking: a hysteresis band on the density tier, and variable anchoring so a colliding label relocates before it hides (issue #143) |
| 064 | Honest position-fix anchor | 054 | opus | low | Date each position fix by the decode age the frame reports rather than by its arrival, so dead reckoning hands over between fixes without the periodic backwards step (issue #144) |
| 065 | Raspberry Pi 5 clean performance baseline | 049, 060 | opus | low | Record the first fully-passing on-hardware run in docs/PERFORMANCE.md §5.5 and apply §5.3's promotion rule: five reference budgets become hard gates, SQLite write latency does not (closes issue #132; the clean Pi 4 run that would calibrate it is issue #153) |
| 066 | Military chip metadata gate | 017, 025 | opus | low | Gate the live map's Military quick-filter chip on whether this install has imported aircraft metadata instead of on the long-lifted slice-017 gate, and refresh the drawer's stale metadata notes (issue #151) |
| 067 | Open-issue severity triage | 066 | opus | low | Re-verify every open issue against dev, close the ones merged slices already fixed, and label the rest by severity (plus release-gate / decision) so the SPEC §114 bug gate is a label query; records the Pi 5 + SSD runtime environment (issue #157) |
| 068 | Medium-severity fix bundle | 040, 056, 061, 064, 067 | opus | medium | Five single-concern commits: poller attach after first-run hot-start (#129), fix-dated live track points and no stale seen_pos_s inheritance (#145), a write path for the alert-match 'Notified' marker (#104), the live socket hoisted to the app shell per ADR-0015 (#105), and ADR-0014 accepting the measured track storage cost (#114); tracking issue #159 |
| 069 | Enrichment hot-apply & honest restart badges | 026, 055, 056, 068 | opus | low | Apply enrichment settings on config save so AeroDataBox route lookup starts, stops or re-keys without a backend restart, and badge every Settings section that still needs one (issue #161) |
| 070 | Route enrichment credit economy & airport names | 026, 027, 042, 069 | opus | medium | Week-long per-callsign route cache, learned schedules, a daily lookup budget spent in priority order, restricted flights cached instead of retried (#165), and airport names beside route idents from the local airports table (issue #167) |
| 071 | Offline route directory (VRS standing data) & enrichment resilience | 021, 027, 049, 070 | opus | medium | VRS standing-data routes as the primary origin/destination source (SPEC §28 amended, ADR-0016), AeroDataBox only for misses, inferred route end shown where no source knows the callsign, last known route served when a refresh cannot happen, CI headroom for the flaky perf gates (issue #173; #166, #170) |
| 072 | Migration 0015 rebuild fix | 071 | opus | high | Hotfix: run the `sightings` rebuild with foreign keys off and checked afterwards, resumable from the v0.6.0 partial state, with migration tests that seed every child table (issue #178; v0.6.1) |

## Parallelization Guide

Dependency-derived waves; Fable owns merge order and reconciles drift before merging.
Parallel slices use isolated worktrees and must not edit the same files concurrently.
Slices adding Alembic migrations or extending the slice-009 persistence worker (021,
024, 026, 027, 031, 033, 035, 037, 038, 052) are additionally serialized against each
other per the parallel-migration rule in `docs/DEVELOPMENT.md`, even where the graph
would allow parallelism.

- **Wave A:** 001 ∥ 002
- **Wave B:** 003, 004 (after 001) ∥ 013 (after 002)
- **Wave C:** 005, 007 (after 004)
- **Wave D:** 006 ∥ 012 ∥ 019 ∥ 018 ∥ 008 → {011, 009 → {052 → 053, 010}}
- **Wave E:** 014 (after 010, 013) → {015, 016, 017} ∥ 021 → {022, 023} ∥ 033 (serialized vs 021 on migrations)
- **Wave F:** 024 → {025, 029, 031, 037} ∥ 020 (after 014/016/018)
- **Wave G:** 026 → 027 → 028 ∥ 030, 032, 034 ∥ 035 (after 025) → 036 ∥ 038 (after 031/037) → {039, 041} → 040
- **Wave H:** 042 (after 040) ∥ 043 → 045 ∥ 044
- **Wave I:** phase-8 qualification, largely sequential on feature completeness

Bootstrap gating note: slices 001/002 merge before CI (003) exists. `dev` branch
protection (PR required, no direct pushes) is applied before any merge; Fable reviews
001/002 manually against their acceptance criteria, and 003 retroactively gates them.

## Future / Backlog (v1 Non-Goals)

Tracked here per SPEC §79; never implemented silently during v1:

multi-receiver deployments · built-in authentication · Slack/Home Assistant/email/
native push notifications · global aircraft overlay · aircraft photos · historical
animated playback · free-form global search · data export · manual aircraft notes and
metadata overrides · full offline map-region download manager · weather integration ·
airport-level historical analytics · period-over-period analytics · aircraft-follow
mode · circling/loitering/repeated-pass detection · complex nested boolean alert
expressions · user-installable plugins · Prometheus/Grafana integration · automatic
self-updater · additional decoder adapters (Beast, SBS, remote receiver) · scheduled
metadata updates · packed-track on-disk layout revisit (rowid / page_size 16384 with a
migration path; deferred by ADR-0014)
