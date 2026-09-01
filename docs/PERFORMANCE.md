# FlightSite Performance

Performance is an architectural constraint, not an afterthought (SPEC §4). This
document is the canonical statement of what FlightSite must achieve, how each
figure is measured, and which figures are enforced versus tracked. Roadmap
slice 050 (long-term storage qualification) asserts its results against the
budget table below.

**Reference hardware: Raspberry Pi 4** (Raspberry Pi OS 64-bit, Docker
Compose). **Load envelope (SPEC §5):** ~500 simultaneously visible aircraft,
decoder state updates ~1 Hz, several years of history, backend memory
comfortably below 1 GB.

---

## 1. The hybrid gate model

SPEC §85 does not ask for every metric to block a merge, and there is a good
reason for that. Some limits are correctness-critical: cross one and the live
picture becomes a backlog, or the process heads for the OOM killer. Others are
questions of comfort whose real answer depends on hardware nobody has measured
yet — and a budget calibrated on a developer laptop tells you nothing about an
SD card on a Pi.

So budgets come in two kinds, and every row of the table below is labelled.

| | **Hard gate** | **Reference budget** |
|---|---|---|
| Enforced | Fails the test suite, on every PR | Measured, reported, trended; never fails a run |
| Stated for | Any hardware the suite runs on | Raspberry Pi 4 |
| Why | Correctness-critical: crossing it breaks the product | Comfort or headroom; the real limit needs Pi 4 data |
| Becomes hard when | — | A Pi 4 baseline is recorded here (§5) and the row is promoted |

A reference budget is not a weaker budget. It is a budget that has not yet been
calibrated against the hardware it is stated for, and reporting it as a hard
gate on a developer machine would be dressing up a guess.

### CI headroom

Hard gates that measure *time* are asserted against `budget x CI_HEADROOM`,
where `CI_HEADROOM` is 5 — the convention already used by
`tests/alerts/test_perf.py` and `tests/metadata/test_cache_latency.py`. A
shared runner under coverage instrumentation is slow and noisy, and a bound
five times the budget still catches every structural regression (a hot-path
await, a per-aircraft query, a superlinear scan) while never failing on a busy
machine. In practice the measured figures sit one to two orders of magnitude
inside the asserted bound; see §5.5.

Budgets that measure a *quantity* rather than a duration get no headroom at
all. A 1 GB memory ceiling relaxed fivefold is not a gate, and the live
population a deterministic scenario produces does not vary with how loaded the
machine is.

---

## 2. The budget table

The table is generated from `backend/src/flightsite/perf/budgets.py`, which is
the single source of truth — `tests/perf/test_budgets.py` guards its integrity,
and the harness judges every run against it. A budget that lives only in a
document drifts from the test enforcing it; a budget that lives only in a test
is invisible to whoever is deciding whether a Pi 4 is fast enough.

### 2.1 Hard gates

These are SPEC §85's own list: *ingestion keeps up; 500-aircraft workload
remains functional; no live-state stalls; memory below agreed budget; core APIs
responsive.*

| Metric | SPEC §85 item | Budget | Statistic | In-suite bound | What it protects |
|---|---|---|---|---|---|
| `live_population` | 500-aircraft workload remains functional | ≥ 500 aircraft | min | ≥ 500 | That the run applied the load it claims to. Everything else is meaningless otherwise. |
| `ingest_apply_ms` | live-state update latency | ≤ 100 ms | p95 | ≤ 500 ms | `docs/ARCHITECTURE.md` §3.3: an apply approaching the 1 s poll turns the live picture into a backlog. |
| `ingest_duty_cycle` | ingestion throughput | ≤ 0.5 of a poll | p95 | ≤ 0.5 | The whole per-tick hot path against one 1 Hz poll. Above 1.0 the pipeline is losing ground; half a poll leaves a Pi 4 room at several times dev-machine cost. |
| `live_sweep_ms` | live-state update latency | ≤ 100 ms | max | ≤ 500 ms | The lifecycle sweep runs every second over the whole live set, so it shares the apply budget. |
| `api_live_ms` | core APIs responsive | ≤ 250 ms | p95 | ≤ 1250 ms | `/api/v1/aircraft/current` answers from memory, so under load this is serialization and nothing else. Past a quarter second the map feels stalled. |
| `memory_rss_mib` | memory use | ≤ 1024 MiB | max | ≤ 1024 MiB | SPEC §5. An absolute ceiling on a 4 GB Pi shared with the frontend container and the decoder. |

### 2.2 Reference budgets (trend-tracked)

SPEC §85: *trend-track less critical metrics initially; convert to hard gates
once real Pi 4 baselines exist.*

| Metric | SPEC §85 item | Budget (Pi 4) | Statistic | Why not yet a hard gate |
|---|---|---|---|---|
| `ws_fanout_ms` | WebSocket distribution | ≤ 100 ms | p95 | Serialization-bound and scales with client count, which the harness records alongside the figure. |
| `db_write_cycle_ms` | SQLite write latency | ≤ 250 ms | p95 | Off the hot path by construction (ADR-0008), so this is a health figure rather than a correctness limit. Pi 4 SD-card I/O sets the real number. |
| `db_read_ms` | SQLite read/query latency | ≤ 500 ms | p95 | A reader competing with the single writer for the WAL. Pi 4 storage is uncharacterized; slice 050 qualifies it at multi-year scale. |
| `analytics_query_ms` | analytics query latency | ≤ 500 ms | p95 | Slice 031's stated budget, restated under concurrent ingestion. Slice 050 qualifies it on a multi-year dataset. |
| `startup_s` | startup | ≤ 30 s | max | Dominated by disk on a Pi 4. |
| `recovery_s` | unclean-shutdown recovery | ≤ 30 s | max | Bounded by the open-sighting count, which the harness records. Pi 4 SD-card I/O sets the real number. |

Multi-year database behavior — the tenth item on SPEC §85's list — is roadmap
slice 050's scope and is deliberately absent here.

### 2.3 Where else these are enforced

Several budgets are also guarded in isolation by subsystem tests that predate
this harness. Those tests measure one component on an otherwise idle process,
which is the right shape for a unit-level budget. What none of them can answer
is whether the core APIs stay responsive *while* 500 aircraft are being
ingested, alerts evaluated and sightings written — which is what this harness
adds.

| Metric | Also enforced by |
|---|---|
| `ingest_apply_ms`, `live_sweep_ms` | `backend/tests/live/test_perf.py` |
| `db_read_ms` | `backend/tests/api/test_sightings_perf.py`, `backend/tests/api/test_aircraft_history_perf.py` |
| `analytics_query_ms` | `backend/tests/analytics/test_perf.py` |
| `recovery_s` | `backend/tests/sightings/test_kill_drill.py` |

Related budgets outside this table, enforced by their own slices' tests:
alert-engine evaluation cycle (`tests/alerts/test_perf.py`, ≤ 50 ms over 500
aircraft) and metadata appear-resolution (`tests/metadata/test_cache_latency.py`,
≤ 1 ms p99 per event).

---

## 3. The harness

`backend/src/flightsite/perf/` builds the **real application** —
`create_app`, its database, live store, persistence worker, alert engine,
WebSocket broadcaster and HTTP surface — and drives deterministic demo traffic
(SPEC §76) through it one 1 Hz tick at a time. Nothing is mocked: every
component is the object the container runs.

### 3.1 What one tick does

The stage order is the pipeline's own, and each stage is timed separately so a
regression names itself:

1. `live.apply(batch)` — the exact callback production registers as ingestion's
   sole consumer → `ingest_apply_ms`
2. `live.sweep()` — lifecycle ageing → `live_sweep_ms`
3. `alerts.engine.process_pending()` — evaluation over the new picture
4. `persistence.process_pending()` — one write-behind cycle → `db_write_cycle_ms`
5. `broadcaster.broadcast_once()` — one delta to every client → `ws_fanout_ms`

Their sum against the poll interval is `ingest_duty_cycle`. That sum, not any
single stage, is what "ingestion keeps up" means: everything a tick must do has
to fit inside one poll.

Each stage's background task is stood down to a one-hour interval and driven
explicitly instead. A task firing whenever the loop happens to schedule it would
put its cost into whichever measurement was running at the time; driving them
means `db_write_cycle_ms` is the persistence cycle and nothing else.

The decoder poll itself is excluded on purpose. A load harness measures this
pipeline, not the network round trip to a decoder that is not under test.

### 3.2 What is probed under load

Between ticks, the harness issues real HTTP requests against the running app
and samples process memory:

| Probe | Metric |
|---|---|
| `GET /api/v1/aircraft/current` | `api_live_ms` |
| `GET /api/v1/sightings` | `db_read_ms` |
| `GET /api/v1/analytics/summary` | `analytics_query_ms` |
| resident set size | `memory_rss_mib` |

These numbers are legitimately worse than the isolated ones in §2.3. That is
the point of measuring them.

Memory is read from the platform without adding a dependency: `/proc/self/statm`
on Linux, `GetProcessMemoryInfo` on Windows, `getrusage` elsewhere. Where no
source exists the harness reports *not measured* rather than substituting a
different quantity — a zero would read as a perfect score.

### 3.3 Startup and recovery

Both concern a process that is not yet serving, so neither is measured inside
the tick loop.

- **`startup_s`** times a genuinely cold start — an empty data directory,
  migrations run from nothing, every subsystem started — and runs before
  anything else has touched the directory. It is in-process, so it excludes the
  interpreter launch and image pull around it; those belong to the host and are
  covered by the Pi 4 procedure in §5.
- **`recovery_s`** times the repair of sightings left open by an unclean stop.
  A workload is run and its worker stopped, which by design leaves every
  sighting open in the database, so a fresh worker faces exactly the state
  slice 053's recovery path exists for. The measured quantity is
  `PersistenceWorker.start()` — adoption and checkpoint repair — and the
  reported figure carries the number of sightings it covered.

### 3.4 The sustained window

The demo scenario is a pure function of `(seed, tick_index)` with a 30-minute
period, and the population inside it is a bell: it climbs, plateaus, then thins
out. At `population=500` the batch first exceeds 520 aircraft at tick 560 and
holds until about tick 1170, so the harness draws from inside that band and
wraps back to its start for longer runs. Wrapping makes a large slice of the
live set disappear and reappear at once — a harder tick than any inside the
window, not an easier one.

The margin above 500 is deliberate: the population floor is read off the
*minimum* sample, so a window that merely touched 500 would fail on its own
first tick, reporting the scenario's shape rather than the pipeline's health.

---

## 4. Running it

### 4.1 In the test suite

The hard gates run on **every PR**, as part of the ordinary backend test run:

```bash
cd backend && uv run pytest tests/perf
```

`tests/perf/test_harness.py` drives a short smoke run of the whole pipeline at
the full 500-aircraft population and asserts every hard gate. The gates are
structural rather than statistical — a database round trip on the hot path or a
lost delta batching blows through them on fifteen ticks exactly as on six
hundred — so a regression fails the required check on the PR that causes it.

The **sustained** run is excluded from the default suite (`-m 'not load'`), and
is the one marker in this repo that is. It catches what a short run cannot see
even in principle: memory drift, a queue filling slowly, a worst tick that only
appears after the scenario wraps.

```bash
cd backend && uv run pytest -m load --no-cov
```

`.github/workflows/perf.yml` runs it weekly and on demand. It is deliberately
not a required status check: its budgets are stated for a Pi 4, and a shared
runner is neither that hardware nor a quiet one.

### 4.2 Standalone, on real hardware

`flightsite-perf` is the same harness as a command. This is what §5's
qualification procedure invokes.

```bash
uv run flightsite-perf --realtime --ticks 600 --data-dir /opt/flightsite/perf
```

| Flag | Meaning |
|---|---|
| `--realtime` | Pace ticks to the product's 1 Hz cadence. **Use this on real hardware** — without it the harness runs as fast as the CPU allows, which measures what each stage costs but not whether the machine sustains 1 Hz. |
| `--ticks N` | Measured ticks after warm-up. At `--realtime`, N seconds. |
| `--data-dir DIR` | Where the harness database lives. **Point this at the storage being qualified** — on a Pi, the SD card or USB SSD the install actually uses. Measuring against a tmpfs answers a question nobody asked. |
| `--population N` | Concurrent aircraft. Defaults to the SPEC §5 envelope of 500. |
| `--ws-clients N` | Simulated WebSocket clients. Defaults to 4. |
| `--json PATH` | Write the full report for trend tracking across runs. |

Exit status is 0 when every measured hard gate held and 1 when one did not, so
the command drops straight into a release check.

---

## 5. Raspberry Pi 4 qualification procedure

Run this before a release (SPEC §107's release checklist names Pi 4 performance
qualification), and whenever a change is expected to move any figure in §2.

### 5.1 Prepare

1. A Raspberry Pi 4 (4 GB or better) on Raspberry Pi OS 64-bit, with the
   storage the install actually uses — SD card or USB SSD, not a tmpfs.
2. Deploy the release candidate with Docker Compose per `docs/DEVELOPMENT.md`.
3. Stop anything else competing for the machine. A decoder feeding the Pi is
   fine and realistic; a desktop session is not.
4. Note the hardware: `cat /proc/cpuinfo | grep Model`, the storage device, and
   the RAM size. These go in the results table.

### 5.2 Measure

```bash
docker compose exec flightsite-backend \
  flightsite-perf --realtime --ticks 600 \
                  --data-dir /opt/flightsite/perf \
                  --json /opt/flightsite/perf/report.json
```

Ten minutes of genuinely sustained 500-aircraft load at 1 Hz. Copy the printed
table and the JSON off the Pi.

### 5.3 Record and promote

1. Add a row set to §5.4 with the date, the release, the hardware and every
   measured figure.
2. For each **reference** budget now backed by a Pi 4 baseline, decide whether
   to promote it to a hard gate: change its `gate` to `GateKind.HARD` in
   `backend/src/flightsite/perf/budgets.py`, set an appropriate `ci_headroom`,
   and update §2 above. `tests/perf/test_budgets.py` will hold the new
   invariant.
3. If a measured figure exceeds its budget, that is a finding: file it as a
   roadmap entry or an issue rather than widening the budget to fit.

### 5.4 Recorded baselines

> **No Raspberry Pi 4 baseline has been recorded yet.** The procedure above is
> documented and the harness runs standalone, but the hardware was not
> available to the slice that built it. Until a row appears here, every
> reference budget in §2.2 remains a stated target rather than a calibrated
> one, and none of them can be promoted to a hard gate. This is the outstanding
> item for slice 049's second acceptance criterion.

| Date | Release | Hardware | Storage | Result |
|---|---|---|---|---|
| — | — | — | — | not yet run |

### 5.5 Development-machine baseline

Recorded for orientation only. A developer machine is not the reference
hardware, and a figure here says nothing about a Pi 4 beyond ruling out gross
regressions. It is included because the ratio between these numbers and a
future Pi 4 row is itself useful.

**2026-09-01** · Windows 11 (AMD64), Python 3.12.10 · 500 aircraft, 600 ticks,
4 WebSocket clients, 59 s wall · `flightsite-perf --ticks 600`

| Metric | median | p95 | max | Gated statistic | Bound | Result |
|---|---|---|---|---|---|---|
| `live_population` | 706 | 788 | 791 (min 526) | min 526 | ≥ 500 | pass |
| `ingest_apply_ms` | 14.2 | 17.3 | 314 | p95 17.3 | ≤ 500 | pass |
| `ingest_duty_cycle` | 0.038 | 0.058 | 1.86 | p95 0.058 | ≤ 0.5 | pass |
| `live_sweep_ms` | 0.242 | 0.395 | 0.656 | max 0.656 | ≤ 500 | pass |
| `api_live_ms` | 20.0 | 27.0 | 328 | p95 27.0 | ≤ 1250 | pass |
| `memory_rss_mib` | 183 | 221 | 223 | max 223 | ≤ 1024 | pass |
| `ws_fanout_ms` | 12.7 | 15.8 | 366 | p95 15.8 | ≤ 500 | pass |
| `db_write_cycle_ms` | 5.58 | 15.8 | 1840 | p95 15.8 | ≤ 1250 | pass |
| `db_read_ms` | 4.81 | 6.17 | 61.9 | p95 6.17 | ≤ 2500 | pass |
| `analytics_query_ms` | 8.92 | 10.9 | 57.5 | p95 10.9 | ≤ 2500 | pass |
| `startup_s` | 0.146 | — | — | max 0.146 | ≤ 30 | pass |
| `recovery_s` | 2.33 (539 open sightings) | — | — | max 2.33 | ≤ 30 | pass |

Every gated statistic sits one to two orders of magnitude inside its bound.
Three features of this run are worth reading rather than skipping:

**The live set is larger than the batch.** The scenario delivers ~520–600
aircraft per tick, but an aircraft stays in the live store for 60 s after it
stops transmitting, so the resident population settles around 700. That is
correct and is the number the memory and apply figures are actually against.

**`db_write_cycle_ms` spikes to 1.84 s, and the duty cycle with it.** The
persistence worker rewrites running values every `flush_interval_s` (30 s), so
one cycle in thirty commits several hundred sightings instead of a handful.
This is why `ingest_duty_cycle` has a maximum of 1.86 against a p95 of 0.058 —
one tick in thirty does a great deal more work than the others.

It is also why that budget is gated on the p95 and not the maximum. The duty
cycle sums the stages because *this harness* drives them serially; in the
running product the write-behind worker is a separate task and cannot block
`live.apply` (ADR-0008, `docs/ARCHITECTURE.md` §3.1). A flush that takes longer
than a poll therefore delays the next *write*, not the next *observation* — the
live path is memory-only and does not wait for it. The aggregate is kept
because it is the honest worst case, and the p95 is gated because the maximum
measures a bounded periodic flush rather than a stall.

**16 resync reconnects.** On a new database every one of 500 aircraft is a
first-ever sighting, and the activity service publishes one WebSocket frame per
event with no await between them. Each of its 5-second passes therefore emits a
burst larger than a client's 32-frame queue, and the broadcaster sheds every
client with close code 1013 — the documented slow-consumer rule
(`docs/API.md` §4.5), doing exactly what it should. The simulated clients
reconnect as a browser would. This is first-run behaviour that decays as
aircraft stop being novel, but it is worth knowing that a fresh install with a
busy receiver will resync its clients every few seconds for a while; see §6.

---

## 6. Observations for later slices

Findings the harness surfaced that are outside slice 049's scope. Recorded here
rather than acted on, because measuring is this slice's job and changing what
it measures is not.

**Activity bursts overflow WebSocket client queues on a fresh install.** The
activity service publishes one frame per event, synchronously, with no await
between them (`LiveBroadcaster.publish_activity`). A pass that detects more
events than a client's outbound queue holds — 32 by default — evicts every
connected client in a single call. On a new database at 500 aircraft this
happens on essentially every 5-second pass, because every aircraft is a
first-ever sighting.

The behaviour is correct in the sense that it is the documented slow-consumer
rule and the client is told to resync rather than left stalled. Whether it is
*desirable* on a first run is a product question: a browser reconnecting every
five seconds for the first hours of an install is not a good first impression,
and coalescing a pass's events into fewer frames, or capping the burst, would
avoid it. Worth a roadmap entry against the activity or WebSocket slice.

---

## 7. Long-term storage qualification

Multi-year database behavior — growth, index behavior, downsampling, retention
pruning, backup size and duration, restore, Pi storage I/O, and analytics at
scale — is SPEC §86 and roadmap slice 050. It qualifies against the budget
table in §2 and records its results in this document.
