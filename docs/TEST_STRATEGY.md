# FlightSite Test Strategy

Testing is mandatory and multi-layered (SPEC §82–§86). This document defines the
layers, gates, determinism rules, and the mapping from roadmap slices to required test
types. `planning/roadmap.yaml` lists per-slice `required_tests`; this document is the
strategy those entries implement.

---

## 1. Test Pyramid and Layers

### 1.1 Backend (pytest + pytest-asyncio, coverage via coverage.py)

| Layer | Purpose | Notes |
|---|---|---|
| Unit | Pure functions, small modules (geodesy, formatting, config precedence, icon-category derivation) | Fast, no I/O |
| Domain | Live-state lifecycle, sighting open/close, alert evaluation, classification, rarity, milestones | Simulated clock; no wall-clock sleeps |
| Ingestion | Adapter normalization, malformed-input hardening, reconnect behavior | Real-world readsb/dump1090-fa fixtures + fuzzed payloads |
| Persistence | Writer discipline, track checkpointing + packed-track round-trips, rollups, downsampling, pruning | Real SQLite (temp file, WAL), never mocked at the SQL layer |
| Migration | Alembic upgrade paths from empty and fixture databases | Adjacent released versions must have a tested upgrade path (SPEC §107) |
| API | REST + WebSocket contracts, OpenAPI accuracy, error cases | httpx/ASGI transport; WS integration incl. reconnect and slow-consumer |
| Integration | Cross-subsystem flows (ingest → live → persist → API) driven by demo/replay adapters | Deterministic seeds |

### 1.2 Frontend (Vitest + React Testing Library)

| Layer | Purpose |
|---|---|
| Component | Rendering, props, empty/Unknown states, unit and timezone formatting |
| State | Zustand stores, WS client store transitions, filter composition, declutter priority |
| API integration | TanStack Query hooks against mocked HTTP/WS (MSW or equivalent) |
| Interaction | Selection, filtering, wizard steps, settings edits, keyboard navigation |

### 1.3 End-to-End (Playwright)

Runs against the composed application (Docker Compose) in deterministic demo mode.
Chromium, Firefox, and WebKit where practical (SPEC §81). Delivered incrementally:
infrastructure and first flows in slice 020, full critical-flow coverage in slice 046.

### 1.4 Visual Regression (Playwright screenshots)

Narrowly scoped, deterministic screenshot suite over stable views (slice 047). See §5.

### 1.5 Accessibility Checks

Automated axe checks integrated into E2E for main flows (slice 048), CI-gated
(SPEC §80).

### 1.6 Performance Harness

Repeatable load harness measuring the SPEC §85 metric list with hybrid gates
(slice 049). See §6.

### 1.7 Storage Qualification

Multi-year synthetic dataset qualification before v1.0.0 (slice 050). See §6.3.

---

## 2. Coverage Gates

Global minimums (SPEC §84), enforced in CI from slice 003 onward:

```text
Backend:  >= 80% line coverage
Frontend: >= 70% line coverage
```

**Critical domains require materially higher effective coverage** — the goal is
exhaustive branch/edge coverage of the decision logic, not a numeric vanity target:

- Sighting lifecycle (slices 009, 052) — open/close/gap semantics, track
  simplification + pack/unpack round-trips, reception stats
- Alert evaluation (slice 038) — condition matrix, dedup, severity upgrades, rarity
- Metadata precedence (slices 021–023) — source priority, provenance, overlap cases
- Migrations (all schema slices) — empty + fixture upgrade paths
- Backup/restore (slice 043) — manifest validation, refusal paths, cross-version
- Retention/downsampling (slices 033, 044) — aggregate correctness, pruning bounds
- Unclean-shutdown recovery (slices 053, 044) — kill-during-write and double-crash
  drills

**Enforcement rule:** a PR that reduces coverage below the gate fails CI. A justified
exception requires an explicit note in the PR's "Known limitations" section and Fable
self-review sign-off; the gate itself is never lowered to admit a PR.

**Anti-goal:** tests written solely to inflate coverage numbers are rejected in review.
Every test must assert meaningful behavior; snapshot-everything and
assert-it-doesn't-throw tests do not count as coverage of critical domains.

---

## 3. Determinism Policy

Flaky tests are treated as defects. Rules:

1. **Simulated clocks.** All lifecycle timing (15 s stale / 60 s remove / 10 min close,
   downsampling windows, maintenance schedules) is tested against injected/simulated
   time. No `sleep()`-based timing assertions.
2. **Seeded demo mode.** The demo adapter (slice 011) is deterministic: same seed +
   elapsed simulated time ⇒ identical update sequences. E2E and visual suites pin the
   seed.
3. **Captured fixtures.** The capture/replay tool (slice 012) turns real-world decoder
   behavior into compact fixtures; regression tests for real-world bugs replay them
   deterministically.
4. **Frozen visual inputs.** Visual regression freezes the clock, pins the demo seed,
   and stubs basemap tiles (no live internet tiles in any test) so diffs reflect real
   UI changes only (SPEC §83).
5. **No external network in tests.** Enrichment, metadata downloads, and tiles are
   mocked/stubbed in all automated suites; offline behavior is itself a tested path.

---

## 4. E2E Critical Flows (SPEC §82)

| Flow | Delivered by slice |
|---|---|
| First-run setup wizard | 020 |
| Decoder connection test | 020 |
| Demo-mode live map renders aircraft | 020 |
| Aircraft selection | 020 |
| Aircraft detail | 020 |
| Interesting-aircraft alert | 046 |
| Browser notification permission flow | 046 |
| Aircraft page | 046 |
| Sightings page | 046 |
| Analytics windows (all presets) | 046 |
| Metadata update | 046 |
| Backup/restore smoke path | 046 |

E2E is a required CI check from slice 020 onward. Failures produce traces and
screenshots as CI artifacts.

---

## 5. Visual Regression (SPEC §83)

Scope (dark and light themes): Live Map, aircraft detail, Analytics, Receiver, Alerts.

Stabilization rules: fixed demo seed; frozen clock (timestamps render identically);
stubbed offline tiles; animations disabled or settled before capture; font rendering
pinned by running in the CI container image. Intentional UI changes update baselines
through a reviewable diff workflow — baseline updates are called out in the PR.

Anti-goal: do not chase pixel-perfect coverage of every state; cover the stable,
high-value views only.

---

## 6. Performance and Scale (SPEC §85–§86)

### 6.1 Hybrid gate model

Reference hardware: Raspberry Pi 4. CI runs the harness on dev-class runners with
calibrated budgets; Pi 4 qualification is a documented procedure executed for releases
(slice 049 establishes baselines).

**`docs/PERFORMANCE.md` is the canonical budget table**, rendered from
`backend/src/flightsite/perf/budgets.py`, which is what the harness actually enforces.
The lists below are the strategy those budgets implement; the numbers live there.

How the harness runs:

- **Hard gates run on every PR.** A short smoke run of the whole pipeline at 500
  aircraft lives in `backend/tests/perf/` and executes as part of the ordinary backend
  suite, so a regression fails the required check on the PR that causes it.
- **The sustained run is behind the `load` marker**, which — uniquely among this repo's
  markers — is *excluded* from the default suite (`-m 'not load'` in `addopts`). A
  sustained run is minutes of wall clock. `.github/workflows/perf.yml` runs it on a
  schedule and on demand, and is deliberately not a required check.
- **`flightsite-perf`** is the same harness standalone, for qualifying real hardware.

**Hard gates (fail CI/release):**

- Ingestion keeps up with a sustained 500-aircraft, 1 Hz workload
- No live-state stalls (live update latency bounded)
- Backend memory below the 1 GB budget under the reference workload
- Core APIs remain responsive under load

**Trend-tracked initially (converted to hard gates once Pi 4 baselines exist):**

- SQLite write/read latency, WebSocket fan-out latency, analytics query latency,
  startup time, unclean-shutdown recovery time

### 6.2 Measured metrics

Ingestion throughput; live-state update latency; SQLite write latency; SQLite
read/query latency; WebSocket distribution; memory use; analytics query latency;
startup; unclean-shutdown recovery; multi-year database behavior.

### 6.3 Storage qualification (slice 050)

Before v1.0.0, a realistic synthetic multi-year (≥3 years) dataset validates: database
growth, query responsiveness, index behavior, downsampling, retention pruning, backup
size/duration, restore behavior, Pi storage I/O, analytics performance. Results are
recorded in `docs/PERFORMANCE.md`.

---

## 7. Browser Matrix (SPEC §81)

Current and previous major versions of Chrome, Edge, Firefox, Safari are supported.
Chromium is the primary development target. CI exercises Chromium, Firefox, and WebKit
where practical; engine-specific exceptions must be documented in the E2E config.

---

## 8. Slice → Required Test Types

Per-slice detail lives in `planning/roadmap.yaml` (`required_tests`); this table is the
phase-level summary and must stay consistent with it.

| Phase | Slices | Required test types |
|---|---|---|
| 1 Foundation | 001–006 | Backend/frontend unit + component; migration harness; pragma verification; CI workflow validation; compose smoke test |
| 2 Ingestion & Live Domain | 007–012, 052, 053 | Ingestion fixtures + fuzz; simulated-clock domain tests; persistence, migration, backpressure tests (009); simplification property + pack/unpack round-trip tests (052); recovery drill + double-crash tests (053); API + WS integration; determinism + scenario-coverage tests; capture/replay round-trip |
| 3 Live Map | 013–020 | Component/state tests; icon-selection + declutter unit tests; tile-failure tests; formatting (units/timezone); wizard + settings API integration; E2E foundation flows |
| 4 Metadata & Enrichment | 021–028 | Import transactionality + fault injection; parser fixtures; precedence/provenance; classification matrix over curated fixtures; mocked-provider enrichment tests incl. secret-leak checks; inference fixtures; overlay component tests |
| 5 History & Analytics | 029–036 | API tests on large fixture DBs; rollup-vs-brute-force property tests; DST bucketing; downsampling/pruning property tests; chart component + a11y checks; day-boundary tests |
| 6 Alerts & Notifications | 037–041 | Rule-evaluation matrix; dedup/severity-upgrade; rarity thresholds; matching per entry type; notification dispatch (mocked API) + permission/dedup E2E; builder round-trip |
| 7 Operations | 042–045 | Diagnostics degraded-state fixtures; secret-absence tests; live-backup consistency; cross-version restore; corruption drills; contention tests; confirmation-flow E2E |
| 8 Hardening | 046–051 | Full E2E suite; visual regression; axe a11y checks; perf harness + gates; storage qualification; docs-driven fresh-install validation |

---

## 9. Test Data Assets

- **Decoder fixtures:** sampled real readsb and dump1090-fa outputs (positioned, MLAT,
  non-positioned, malformed) — slice 007 onward.
- **Captured replays:** compact fixtures from the capture tool — regression tests.
- **Fixture databases:** generated multi-thousand-aircraft / multi-year SQLite files
  for history, analytics, migration, and qualification tests.
- **Curated classification set:** known military/government/law-enforcement/airline/GA
  aircraft with expected classifications — slice 024.
- **Geodesic fixtures:** known distance/bearing pairs for derived-field verification.

All fixtures are versioned in-repo (or generated deterministically by seeded code) —
no test depends on external network state.
