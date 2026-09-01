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
slice 050's scope and is deliberately absent from this table. It has a table of
its own in §7, which restates `db_read_ms` and `analytics_query_ms` above at
multi-year scale and adds the growth, retention, backup and restore budgets
that only mean anything once a database has years in it.

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
scale — is SPEC §86 and roadmap slice 050. Where §2's table judges *one second*
of the product at its stated load, this one judges *three years* of it at rest.

The tool is `backend/src/flightsite/perf/storage_qualification/`, and it is a
maintained command rather than a script somebody ran once: it synthesizes a
realistic multi-year history, measures the nine things SPEC §86 names against
it, and judges them against the table in §7.2.

### 7.1 Why a second budget table

§2's table is a contract with slice 049's load harness:
`tests/perf/test_harness.py` asserts that every budget in it is measured by a
run of that harness. A backup duration or a vacuum cost has no meaning in a
sixty-tick load run, so putting those rows in §2 would either break that
assertion or weaken it into something that no longer notices a metric quietly
ceasing to be collected. Two tables, each complete with respect to the harness
that fills it, keeps both strict.

The *model* is identical — the hard/reference split of §1, the same
`CI_HEADROOM` convention, the same rule that a reference budget is promoted
only once a Pi 4 baseline exists (§5.3). `backend/src/flightsite/perf/storage_qualification/budgets.py`
is the source of truth, and `tests/perf/storage/test_docs.py` checks that this
document still renders it.

Note that slice 050 **qualifies** §2.2's `db_read_ms` and `analytics_query_ms`
at multi-year scale, as those rows' own rationales say it will. Qualifying is
not promoting: a developer machine is not a Pi 4, and stating a Pi 4 budget as
a hard gate on evidence from something else is exactly the dressed-up guess §1
warns against.

### 7.2 The storage budget table

#### 7.2.1 Hard gates

Three claims, and each one makes every other figure in the table either
meaningful or meaningless.

| Metric | SPEC §86 item | Budget | Statistic | In-suite bound | What it protects |
|---|---|---|---|---|---|
| `dataset_days` | realistic synthetic multi-year dataset | ≥ 1 day | min | ≥ 1 | That the run built the history it claims. This table's `live_population`: growth arithmetic over a dataset that does not exist is arithmetic about nothing. |
| `metrics_raw_days` | retention pruning | ≤ 15 days | max | ≤ 15 | ADR-0009 and SPEC §64: `receiver_metrics_raw` is a rolling 14-day window, not a growing table. It is the one high-frequency table that would otherwise dominate a Pi's disk within months. The extra day is the prune boundary's hour rounding. |
| `downsample_coverage` | downsampling | ≥ 1.0 | min | ≥ 1.0 | ADR-0009: *"downsampling/pruning can never lose a record."* Every hour whose raw rows were pruned must still carry an hourly summary. A budget on how *fast* the prune ran would not notice data loss. |

None carries CI headroom: all three are counts against a configured window, and
a busy machine does not make a window wider or a summary disappear.

#### 7.2.2 Reference budgets (trend-tracked)

| Metric | SPEC §86 item | Budget (Pi 4) | Statistic | Why not yet a hard gate |
|---|---|---|---|---|
| `db_bytes_per_sighting` | database growth | ≤ 2000 bytes | max | `docs/DATA_MODEL.md` §9's arithmetic in scale-free form (see §7.3). Missing it is a storage-sizing correction, not a broken build. |
| `history_query_ms` | query responsiveness | ≤ 500 ms | p95 | §2.2's `db_read_ms`, restated over a multi-year database instead of a sixty-tick one. |
| `analytics_scale_ms` | analytics performance | ≤ 500 ms | p95 | §2.2's `analytics_query_ms`, across every documented preset on a multi-year dataset. |
| `rarity_query_ms` | query responsiveness | ≤ 500 ms | p95 | SPEC §44's rarity read. Measured apart because its cost grows with distinct airframes rather than with sightings — quantities that stop being similar at multi-year scale. |
| `retention_pass_ms` | retention pruning | ≤ 5000 ms | max | Downsample plus the chunked raw prune, the only unbounded catch-up path in the maintenance cycle. The cycle runs hourly, so this leaves three orders of magnitude of room. |
| `vacuum_s` | Pi storage I/O | ≤ 300 s | max | `VACUUM` holds the single writer lock for its whole duration, so this is the longest any write can be stalled. Almost entirely a property of the storage device. |
| `backup_create_s_per_gb` | backup size | ≤ 180 s/GB | max | Stated per gigabyte because the cost is linear in database size. Creating a backup is three full passes: `VACUUM INTO`, SHA-256, then gzip. |
| `backup_restore_s_per_gb` | restore behavior | ≤ 120 s/GB | max | Two passes rather than three. `docs/BACKUP.md` makes restore an operator action taken with FlightSite stopped, so this is downtime. |
| `backup_size_ratio` | backup size | ≤ 1.0 | max | A gzipped snapshot must be smaller than the database it came from. Answers how much room a backup needs beside the live data — `docs/BACKUP.md` rotates nothing. |
| `wal_bytes_mib` | Pi storage I/O | ≤ 64 MiB | max | The maintenance cycle truncates the WAL past 16 MiB, so several times that means checkpointing is not keeping up. |

### 7.3 One growth budget for both scenarios

`docs/DATA_MODEL.md` §9 states two calibration receivers and says slice 050
validates both. Their predictions look unrelated until divided by their own
traffic:

| Scenario | Predicted | Sightings/year | Bytes per sighting |
|---|---|---|---|
| A — typical suburban | 1.0–1.2 GB/yr | 547,500 | ~1,830–2,190 |
| B — SPEC §5 envelope | 12–14 GB/yr | 6,570,000 | ~1,830–2,130 |

Both land on **~2 KB per sighting**, because a sighting, its packed track and
its handful of events dominate the total and every other table in §9 is
rounding error beside them. That makes bytes-per-sighting the scale-free form
of the growth budget: one number judging a fortnight of Scenario A and three
years of Scenario B on identical terms, which a per-year budget could not do
without quietly passing every short run.

Growth is stated in decimal **GB** (10⁹), because §9 is, and a figure is only
comparable to the document it is checked against. Memory in §2 is in MiB; the
units differ because the sources differ.

### 7.4 The generator

`storage_qualification/traffic.py` is the domain model and touches no database:
it is a pure function of a seeded `random.Random`, so the same seed always
produces the same years of history and a change in a measured number is
attributable to the product rather than to the dice. Three properties are
modelled explicitly, because a database of the right size and the wrong shape
would flatter every query measured against it:

- **Diurnal rhythm** — sightings follow a 24-hour weight curve, and the
  day-of-week factor scales how many sightings a day carries. (It deliberately
  does *not* reshape the hourly curve: scaling all 24 weights by one constant
  is a no-op once they are normalized, so a weekday effect applied there would
  look like a model and do nothing.)
- **Aircraft population reuse** — a bounded resident fleet, the accumulated
  historical population, and first-ever contacts at §9's stated rate. The
  resulting `sighting_count` distribution is heavily skewed, which is what SPEC
  §44 rarity needs: without a genuine long tail of airframes seen once or
  twice, the rarity query would be timed against data that cannot exercise it.
- **Track length** — derived from each sighting's own duration at one retained
  point per 15 s, so the mean lands on §9's ~60 points.

`storage_qualification/generator.py` writes those rows through the real
`Database`, under the real single-writer discipline, one day per transaction so
the on-disk interleaving is not more clustered than a receiver's. Two things
are deliberately **not** faked: the analytics rollups are built by the real
`AnalyticsBackfill`, and the receiver-metric downsample and prune are performed
by the real `ReceiverMetricsService`. The generator seeds a backlog of
high-resolution telemetry beyond the retention window so that pass has
something real to do.

Two shortcuts are taken, both stated rather than hidden:

- **Tracks are generated already-simplified.** Production writes
  `pack_track(simplify(samples))`; the generator produces the retained points
  directly and packs them with the real codec, which yields a byte-identical
  row shape. `tests/perf/storage/test_traffic.py` puts a dense 1 Hz transit
  through the *production* simplifier and checks the retention rate the
  generator assumes is right in kind.
- **Packed blobs are drawn from a pool** keyed by point count, so geometry
  repeats between two sightings that retained the same number of points. Blob
  size, byte layout and decodability are exact; nothing under qualification
  depends on geometric uniqueness, and ADR-0005 is explicit that no v1 feature
  queries inside a blob.

Fidelity is enforced, not asserted: `tests/perf/storage/test_fidelity.py`
checks the generated rows against the cross-table invariants the production
writer maintains — aggregates equal to their sightings, records equal to their
extremes with the moments that set them, tracks present exactly where a
position was seen, checkpoints deleted at close, `alert_matches` behind every
denormalized severity, rollups that agree with the history.

### 7.5 Running it

#### In the test suite

The hard gates run on **every PR**, over a fortnight of small traffic:

```bash
cd backend && uv run pytest tests/perf/storage
```

They are structural rather than statistical — a retention pass that stopped
pruning, a downsample that lost an hour, or a probe that started returning 500s
fails on a fortnight exactly as on three years.

The **multi-year** run is excluded from the default suite, behind the same
`load` marker slice 049's sustained run uses:

```bash
cd backend && uv run pytest -m load --no-cov
```

#### Standalone, on real hardware

`flightsite-storage-qual` is the same qualification as a command. This is what
§7.8's procedure invokes.

```bash
uv run flightsite-storage-qual --scenario suburban --days 1095 \
                               --data-dir /opt/flightsite/qual \
                               --json /opt/flightsite/qual/report.json
```

| Flag | Meaning |
|---|---|
| `--scenario` | `suburban` (§9 Scenario A) or `envelope` (§9 Scenario B). |
| `--days N` | Days of history. 1095 is the three years the acceptance criterion names. |
| `--data-dir DIR` | Where the database is built. **Point this at the storage being qualified** — on a Pi, the SD card or USB SSD the install uses. A tmpfs answers a question nobody asked. |
| `--seed N` | Traffic seed; the same seed is the same history, forever. |
| `--timezone` | IANA zone the analytics rollups bucket local days by. |
| `--high-res-backlog-days N` | Telemetry seeded beyond the retention window, so the prune has something to clear. |
| `--probe-repeats N` | Timings taken per query. |
| `--skip-backup`, `--skip-vacuum` | Omit the expensive legs; the report marks them *not measured* rather than passed. |
| `--json PATH` | Write the full report for trend tracking across runs. |

Know what it costs before running it: a three-year Scenario A dataset is
several gigabytes written once, read through by the query probes, and read
three more times by the backup leg — plus a full `VACUUM`. Exit status is 0
when every measured hard gate held and 1 when one did not. A reference budget
that was exceeded is reported prominently on stderr and does **not** change the
exit status; that is what makes it a reference budget.

### 7.6 Recorded results

> **No Raspberry Pi 4 storage baseline has been recorded yet.** The procedure
> in §7.8 is documented and the qualification runs standalone, but the hardware
> was not available to the slice that built it. Until a row appears here, every
> reference budget in §7.2.2 remains a stated target rather than a calibrated
> one, and none can be promoted to a hard gate.

| Date | Release | Hardware | Storage | Result |
|---|---|---|---|---|
| — | — | — | — | not yet run |

#### 7.6.1 Development-machine baseline

Recorded for orientation only, and for the same reason as §5.5: a developer
machine is not the reference hardware, but the ratio between these numbers and
a future Pi 4 row is itself useful. What is *not* hardware-dependent here — the
growth figures and the per-table costs — is as true on a Pi as it is here.

**2026-09-01** · Windows 11 (AMD64), Python 3.12.10 · Scenario A (suburban),
**1,095 days**, 1,642,500 sightings, 120,640 airframes, 1,510,946 packed
tracks · 19m50s wall · `flightsite-storage-qual --scenario suburban --days 1095`

Database **5.032 GB**, 3,064 bytes/sighting, 60.0 points/track, page size 4096.

| Metric | Gate | Observed | Budget | In-suite bound | Result |
|---|---|---|---|---|---|
| `dataset_days` | hard | 1095 | ≥ 1 | ≥ 1 | pass |
| `metrics_raw_days` | hard | 14.25 | ≤ 15 | ≤ 15 | pass |
| `downsample_coverage` | hard | 1.00 | ≥ 1.0 | ≥ 1.0 | pass |
| `db_bytes_per_sighting` | reference | 3,064 | ≤ 2000 | ≤ 2000 | **over** |
| `history_query_ms` | reference | 9,125 (p95) | ≤ 500 | ≤ 2500 | **over** |
| `analytics_scale_ms` | reference | 175.9 (p95) | ≤ 500 | ≤ 2500 | pass |
| `rarity_query_ms` | reference | 514.1 (p95) | ≤ 500 | ≤ 2500 | pass |
| `retention_pass_ms` | reference | 2,493 | ≤ 5000 | ≤ 25000 | pass |
| `vacuum_s` | reference | 44.7 | ≤ 300 | ≤ 1500 | pass |
| `backup_create_s_per_gb` | reference | 80.9 | ≤ 180 | ≤ 900 | pass |
| `backup_restore_s_per_gb` | reference | 5.7 | ≤ 120 | ≤ 600 | pass |
| `backup_size_ratio` | reference | 0.220 | ≤ 1.0 | ≤ 1.0 | pass |
| `wal_bytes_mib` | reference | 3.09 | ≤ 64 | ≤ 64 | pass |

**All three hard gates held**, which is the qualification's central result:
high-resolution telemetry stayed inside its 14-day window over three years of
history, and every hour the prune removed still carried an hourly summary.

Per-table growth (each table with its own indexes):

| Table | Rows | Bytes | B/row |
|---|---|---|---|
| `sighting_tracks` | 1,510,946 | 4.334 GB | 2,868 |
| `sightings` | 1,642,500 | 291 MB | 177 |
| `sighting_events` | 4,115,132 | 310 MB | 75 |
| `activity_events` | 219,000 | 31.6 MB | 144 |
| `aircraft_metadata_resolved` | 94,195 | 13.4 MB | 142 |
| `alert_matches` | 110,340 | 13.5 MB | 123 |
| `aircraft` | 120,640 | 12.0 MB | 99 |
| `receiver_metrics_raw` | 120,960 | 8.27 MB | 68 |
| `range_by_bearing_daily` | 78,840 | 3.59 MB | 46 |
| `receiver_metrics_hourly` | 26,112 | 2.89 MB | 111 |
| `aircraft_classification` | 10,369 | 1.24 MB | 120 |
| `receiver_metrics_daily` | 1,088 | 123 KB | 113 |

Four things in this table are worth reading rather than skipping.

**`sighting_tracks` is 86% of the database.** Everything else together is under
700 MB after three years. Storage on this product is packed tracks and a
rounding error, exactly as `docs/DATA_MODEL.md` §9 predicts — which is why the
per-row cost of that one table decides the whole growth figure, and why §7.7's
first finding matters as much as it does.

**Retention works, and it is the reason nothing else grows.**
`receiver_metrics_raw` holds 120,960 rows after three years — the same count it
would hold after three weeks, because it is a fixed window. Its hourly and
daily summaries, retained indefinitely, cost 3 MB for the whole period. That is
ADR-0009 doing precisely what it was designed to do.

**The unindexed sorts are three orders of magnitude slower than the indexed
reads.** 8.0 s against 2 ms, on the same table, in the same run. This is what
drives the `history_query_ms` overrun and it is the whole of it: every other
history read is single-digit milliseconds. See §7.7.

**`rarity_query_ms` lands within 3% of its budget.** 514 ms against 500, on a
developer machine, for a query whose cost grows with distinct airframes —
120,640 of them here. It passes only because of CI headroom, and on Scenario B
the airframe count is roughly five times larger. Worth watching rather than
acting on: SPEC §44's rarity is a scan-and-sort of `aircraft` on a column with
no index, and it is the reference budget most likely to be missed first on a Pi.

Backup and restore of the 5.03 GB database: **create 406.9 s**, verify 26.5 s,
**restore 28.6 s**, producing a **1.11 GB** archive (22% of the live file — the
compression is recovering the overflow-page slack described in §7.7). Restore
is fourteen times faster than create, and §7.7 explains why.

#### 7.6.2 What was not measured

Scenario B at three years — ~72 GB at the growth rate measured above — was not
generated: it needs roughly 230 GB of working space once the backup snapshot,
archive and vacuum copy are accounted for, and several hours. Its per-sighting
cost is the figure that would matter, and that is scale-free by construction
(§7.3), so the Scenario A result above is the load-bearing measurement for both
receivers. A Scenario B run remains the honest way to confirm it, and
`--scenario envelope` exists for whoever has the disk.

### 7.7 Findings for later slices

Things the qualification surfaced that are outside slice 050's scope. Recorded
here rather than acted on, for the same reason as §6: measuring is this slice's
job and changing what it measures is not.

**Packed tracks cost about twice what the design documents state, because they
spill SQLite overflow pages.** This is the qualification's headline result.

`sighting_tracks` is a `WITHOUT ROWID` table (`docs/DATA_MODEL.md` §2.4), and a
`WITHOUT ROWID` row is stored in an index B-tree, whose maximum *inline* payload
is `(page_size - 12) x 64 / 255 - 23`. At the page size the product actually
uses — **4096**, SQLite's default, which `db/engine.py` never overrides — that
limit is **1002 bytes**. A v1 packed track is `5 + 21 x point_count` bytes, and
the row carries `encoding_version`, `point_count` and `started_ms` beside it, so
the record exceeds the limit from about **47 points** onward and the remainder
spills into a dedicated 4 KiB overflow page, nearly all of which is slack.

`docs/DATA_MODEL.md` §9 sizes a typical simplified track at ~60 points and
~1.3 KB of storage, and ADR-0005 states "~1–2 KB in a single clustered row".
Measured over three years, `sighting_tracks` averages **2,868 B/row** for a
mean payload of 1,265 B. A row of exactly 60 points, measured in isolation,
costs 4,682 B; the average is lower only because the shorter half of the
distribution still fits inline:

| Points | Blob | On disk, page 4096 | On disk, page 8192 |
|---|---|---|---|
| 40 | 845 B | 1,025 B | 1,024 B |
| 47 | 992 B | **4,682 B** | 1,171 B |
| 60 | 1,265 B | **4,682 B** | 1,368 B |
| 95 | 2,000 B | **4,682 B** | 2,051 B |
| 120 | 2,525 B | **4,682 B** | **9,363 B** |

(The 47-point row spills although its blob is under 1002 bytes: the limit
applies to the whole record, which is the blob plus the other columns.)

The last row is the warning. Raising the page size raises the inline limit, but
it also makes each *spilled* page twice as wasteful, so it helps only to the
extent that it moves the limit past the actual distribution of track lengths.
That distribution is right-skewed — median 50 points, p90 110, p99 211 — so the
share of tracks that spill, and the cost of a spill, both matter:

| Page size | Inline limit | Tracks that spill | Measured `sighting_tracks` |
|---|---|---|---|
| 4096 (today) | ~46 points | **54.5%** | 2,866 B/row |
| 8192 | ~95 points | 14.8% | 2,282 B/row |
| 16384 | ~193 points | 1.4% | 1,582 B/row |

Those three figures are measured, not projected: the same generated history was
written into databases whose page size was set before migrations ran. Carrying
them onto the three-year run — where `sighting_tracks` is 4.334 GB of a
5.032 GB database, and everything else is a near-constant 0.70 GB — gives:

| | Page 4096 (measured) | Page 8192 | Page 16384 | §9's prediction |
|---|---|---|---|---|
| Three-year database | **5.03 GB** | 4.15 GB | 3.09 GB | 3–4 GB |
| Growth per year | **1.68 GB** | 1.38 GB | 1.03 GB | 1.0–1.2 GB |
| Bytes per sighting | **3,064** | ~2,530 | ~1,880 | ~2,000 |

So doubling the page size is *not* sufficient — it recovers about a third of
the excess — and only a 16 KiB page brings growth inside §9's prediction and
inside the `db_bytes_per_sighting` budget. The packed-track design is sound and
its arithmetic is right; what is wrong is an interaction between a storage
parameter nobody chose deliberately and a track-length distribution with a
genuine tail.

**This slice deliberately changes nothing.** `page_size` is only settable on an
empty database or through a `VACUUM`, it applies to the whole file rather than
one table, and `docs/DATA_MODEL.md` §9 is explicit that a growth overrun is
reconciled by ADR rather than by a silent change. The options a follow-up
should weigh, in the order they seem cheapest:

1. **Give `sighting_tracks` a rowid.** A rowid table's inline limit is
   `page_size - 35`, so at today's page size it is ~4,061 bytes — past the p99
   of the track distribution — and only this one table changes. It costs the
   clustering ADR-0005 chose deliberately, which is the thing to weigh. Not
   measured here, because it needs a schema change and a migration, and this
   slice writes neither.
2. **Set `page_size = 16384`** for new databases, with a documented path for
   existing ones (setting the pragma then `VACUUM`ing rewrites the file). The
   measured option, and the one that reaches §9's prediction — but it applies
   to every table, and a 16 KiB page on a Pi's SD card changes read amplification
   for the small hot tables too. `8192` is the safer half-measure and recovers
   about a third.
3. **Accept it and correct the documentation** — §9's per-year totals and the
   install guide's card sizing, which currently promise a database ~40% smaller
   than the one an install will have.

Each needs an ADR and a re-run of this qualification; the first two also need a
migration story for existing installs. Worth a roadmap entry against storage.

**Two documented sort options have no index and take eight seconds on a
three-year database.** This is the `history_query_ms` overrun in §7.6, and it
is the whole of it.

`/api/v1/sightings?sort=closest_approach_nm` and `sort=max_range_nm` are
published in `docs/API.md` §3.6, and `sightings` carries no index on either
column (`docs/DATA_MODEL.md` §2.3 declares `aircraft_id+started_ms`,
`started_ms`, and the partial open-sighting index). Those sorts therefore read
every matching row and sort them in a temporary B-tree, so their cost grows
linearly with history while every indexed read stays flat:

| Read | 45k sightings | 1.64M sightings |
|---|---|---|
| newest first (indexed) | 4 ms | 2 ms |
| `sort=max_range_nm` | 313 ms | **8,033 ms** |
| `sort=closest_approach_nm` | 334 ms | **7,302 ms** |

The indexed read does not care how much history exists; the unindexed ones are
about 3,500 times slower than it at three years, and would be near a hundred
seconds on Scenario B's 20M sightings. `tests/perf/storage/test_indexes.py`
pins both plans, so the day an index is added, that test fails and points here.

The fix is not obviously "add two indexes": each is written on every sighting
close, for a sort few users choose, trading ingestion cost and disk against a
rare read. `?interesting=true` has the same shape and would be served by a
cheap partial index. The honest options are an index, a cap on the range such a
sort may cover, or keeping it as a documented slow path with the UI saying so.

Worth a roadmap entry against the sightings API.

**`VACUUM`'s free-space guard makes it unreachable on a full disk.**
`maintenance.policy` requires free space of at least twice the database size
before it will vacuum. That is a sound guard — `VACUUM` builds a complete
second copy — but its consequence at multi-year scale deserves stating: a
40 GB Scenario B history on a 128 GB card can only be vacuumed while less than
about half the card is used, and never once it is fuller. The database is not
damaged, but the one mechanism that reclaims freelist space is permanently
refused, and the diagnostics report `insufficient_free_space` without saying
that it will never clear on its own. Worth surfacing in the health area, and
worth a note in the install sizing guidance.

**Backup is dominated by gzip, at a compression level that buys nothing.**
`archive.write_archive` opens the tar with `w:gz`, taking tarfile's default
level of 9. Backing up the 5.03 GB database took **406.9 s**, of which
compression is about 330 s — more than the `VACUUM INTO` that produced the
snapshot and the SHA-256 that verified it, combined. It is also why restore
(28.6 s) is fourteen times faster than create: decompression is cheap and
symmetric compression is not.

Measured on a 419 MB slab of that database:

| gzip level | Throughput | Compression ratio |
|---|---|---|
| 1 | 136.1 MB/s | 0.197 |
| 6 | 41.0 MB/s | 0.188 |
| 9 | 15.2 MB/s | 0.188 |

Level 9 is **2.7× slower than level 6 for an identical ratio** on this data —
SQLite pages of packed integer blobs give deflate nothing extra to find above
level 6. Setting `compresslevel=6` would cut roughly 200 s from a 5 GB backup
and change the archive size by nothing measurable; level 1 would cut ~290 s for
0.9 percentage points of ratio.

Worth a roadmap entry against backup. `docs/BACKUP.md` currently promises
nothing about duration and says only that a large backup "takes a while", which
is the right place to state a real figure once the level is chosen.

### 7.8 Raspberry Pi storage qualification procedure

Run this before a release, alongside §5's load procedure, and whenever a change
is expected to move a figure in §7.2.

1. Prepare the Pi as §5.1 describes, and check there is room: the procedure
   needs **roughly four times** the final database size free — the database,
   the backup's `VACUUM INTO` snapshot, the compressed archive, and the
   restored copy. For three years of Scenario A that is about 20 GB.
2. Decide which scenario the install resembles. `--scenario suburban` is the
   ordinary case; `--scenario envelope` is the SPEC §5 design envelope and, at
   three years, is tens of gigabytes — do not point it at a 32 GB card.
3. Run it against the real storage:

```bash
docker compose exec flightsite-backend \
  flightsite-storage-qual --scenario suburban --days 1095 \
                          --data-dir /opt/flightsite/qual \
                          --json /opt/flightsite/qual/report.json
```

4. Copy the printed table and the JSON off the Pi, and add a row set to §7.6
   with the date, the release, the hardware and the storage device.
5. For each reference budget now backed by a Pi 4 baseline, decide whether to
   promote it: change its `gate` to `GateKind.HARD` in
   `storage_qualification/budgets.py`, set an appropriate `ci_headroom`, and
   update §7.2. `tests/perf/storage/test_docs.py` and
   `tests/perf/storage/test_budgets.py` hold the new invariant.
6. If a measured figure exceeds its budget, that is a finding: record it in
   §7.7 and file it as a roadmap entry or an issue, rather than widening the
   budget to fit. `docs/DATA_MODEL.md` §9 names the lever for a growth overrun
   — tiered track retention — and is explicit that pulling it relaxes SPEC
   §65's retain-indefinitely rule and therefore needs an ADR.
7. **Delete the qualification data directory afterwards.** It is several
   gigabytes of synthetic history sitting beside the real install's, and
   nothing removes it for you.
