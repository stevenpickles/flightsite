# FlightSite Development Workflow

This document defines how FlightSite is developed. It is derived from the governing
specification ([`planning/SPEC.md`](../planning/SPEC.md)) and applies to every
contributor and agent. The canonical execution plan is
[`planning/roadmap.yaml`](../planning/roadmap.yaml).

## Repository layout

```text
backend/     Python backend (FastAPI, package `flightsite`) — arrives in slice 001
frontend/    React/TypeScript frontend (Vite)               — arrives in slice 002
e2e/         Playwright end-to-end and visual suites        — arrives in slice 020
perf/        Performance harness and storage qualification  — arrives in slice 049
docs/        Project documentation and ADRs (docs/adr/)
planning/    Governing spec and canonical roadmap
.github/     CI workflows, PR template, issue templates
compose.yaml Docker Compose deployment                      — arrives in slice 006
```

## Toolchain

| Area | Tools |
| --- | --- |
| Backend | Python 3.12, [uv](https://docs.astral.sh/uv/), FastAPI, Pydantic, SQLAlchemy 2.x (async, aiosqlite), Alembic |
| Backend quality | ruff (format + lint), mypy (strict), pytest + pytest-asyncio, coverage (≥ 80% global) |
| Frontend | Node 22 LTS, npm, Vite, React 18, TypeScript (strict), Tailwind CSS, shadcn/ui, Lucide, Zustand, TanStack Query, ECharts, MapLibre GL JS |
| Frontend quality | ESLint, Prettier, tsc, Vitest + React Testing Library, coverage (≥ 70% global) |
| E2E | Playwright (Chromium, Firefox, WebKit where practical) |
| CI/CD | GitHub Actions; GHCR for images (`linux/arm64` + `linux/amd64`) |

## Local development quickstart

```bash
# backend (uv fetches Python 3.12 automatically)
cd backend
uv sync                        # install deps
uv run pytest                  # tests + coverage gate (>= 80%)
uv run ruff check . && uv run ruff format --check .
uv run mypy                    # strict type checking
uv run flightsite-serve        # serve on :8000 (or: python -m flightsite)

# frontend (Node >= 22)
cd frontend
npm install
npm run test:coverage          # Vitest + RTL, coverage gate (>= 70%)
npm run lint && npm run format:check && npm run typecheck
npm run dev                    # Vite dev server

# full stack, no hardware required (lands with slices 006 + 011)
FLIGHTSITE_DEMO=1 docker compose up -d      # then browse http://localhost:8090/
```

Three host-side variables steer the compose stack; none of them reach the application
except `FLIGHTSITE_DEMO` (see `docs/CONFIGURATION.md` for the full list):

| Variable | Default | Effect |
|---|---|---|
| `FLIGHTSITE_DEMO` | unset | Runs the simulated decoder — no hardware, no config needed |
| `FLIGHTSITE_HOST_DATA_DIR` | `/opt/flightsite/data` | Host side of the data bind mount; use `./data` locally rather than writing to `/opt` |
| `FLIGHTSITE_HOST_PORT` | `8090` | Published host port. The container always listens on 8080 |

The published port is **8090**, not 8080: decoder web UIs conventionally own 8080 and
FlightSite normally shares a host with one.

`FLIGHTSITE_HOST_PORT` frees the *port* for a second stack, but it is not by itself
enough to run two: `compose.yaml` pins `container_name`, which is global to the
daemon, so a second stack fails with a name conflict even under a different
`docker compose -p` project. Bring one stack down before starting another from
another worktree.

### Running E2E locally

The `e2e/` workspace (Playwright — Chromium, Firefox, WebKit) drives the composed
application in demo mode. It manages its own Docker Compose lifecycle rather than
using Playwright's `webServer` option: each browser gets a **fresh** stack (its own
temp data directory) so the first-run wizard flow means what it says on every
browser, not just the first one to run (see `e2e/playwright.config.ts` and
`e2e/scripts/`).

```bash
docker compose build                   # FIRST — see below; not done for you

cd e2e
npm install
npx playwright install --with-deps    # first run only

npm run e2e                            # Chromium: stack up, full suite, stack down
npm run e2e:firefox                    # same, Firefox
npm run e2e:webkit                     # same, WebKit
```

**Build the images yourself, every time you change the app.** `compose.yaml` names
both services by a published `ghcr.io/...:latest` tag, so `docker compose up` reuses
whatever image already carries that tag in the local daemon and builds only when
there is none. `scripts/stack.mjs` deliberately does not build (CI builds both images
in an earlier step — `.github/workflows/e2e.yml`), so a local run started without the
command above silently exercises whatever was last built on this machine — quite
possibly another branch or another worktree. The failure mode is a confusing one:
every pre-existing spec passes and only the specs covering your new UI fail, on
elements that "should" be there.

`npm run e2e` (etc.) always tears the stack down afterward, pass or fail. To run
against a stack you're keeping up between runs (faster iteration on one spec):

```bash
npm run stack:up                       # FLIGHTSITE_DEMO=1, fresh data dir
npm test                               # Chromium only, against the running stack
npm run stack:down
```

The suite's spec files (`e2e/tests/01-*` … `11-*`) run in that fixed order, serially
(`workers: 1`), against one shared backend within a browser: `01` completes
first-run setup, `02` exercises the decoder connection test against the now-configured
install, and `03`–`11` assume setup is already done. The later files additionally
assume demo traffic has been accumulating since `01` — `07` and `08` read persisted
history, so they poll the API for it rather than assuming the write-behind worker has
flushed — and each one leaves the install as it found it: `06` deletes the alert rule
it arms (and the matches that came with it), `10` never lets a real metadata download
start, and `11` keeps both its backup and its restore outside the live data directory.
Failures produce Playwright traces/screenshots/video under `e2e/test-results/` and
`e2e/playwright-report/` (`npm run report` to view).

### Visual regression suite

A separate Playwright suite (`e2e/visual/`) takes screenshot baselines of five
stable views — Live Map, aircraft detail, Analytics, Receiver, Alerts — in both
dark and light themes (SPEC §83, `docs/TEST_STRATEGY.md` §5). It is **not** part
of `npm run e2e`: different config, different lifecycle, different CI job
(`.github/workflows/visual.yml`).

**Always run it through Docker.** Screenshot baselines depend on the font
renderer, so the suite runs inside `mcr.microsoft.com/playwright` — the same
image CI uses — and refuses to run anywhere else rather than silently producing
pixels that can never match. Both commands below wrap the run in that image; a
working Docker daemon is the only prerequisite.

```bash
cd e2e

npm run visual                         # compare against the committed baselines
npm run visual:update                  # regenerate them after an intended UI change
npm run report:visual                  # open the HTML report from the last run
```

`npm run visual:update` is *the* baseline-regeneration command. It is expected to
be needed whenever a change intentionally alters how these views look — a restyle,
a spacing change, a new field on a card, or another slice's accessibility or
contrast work. Regenerating is cheap and normal; **call baseline updates out in
the PR description** so a reviewer knows the screenshot diff is the point rather
than a surprise.

No backend runs during a visual run. Every `/api/v1` and `/api/internal` response
is replayed from a committed HTTP archive, the live WebSocket is replaced by one
frozen snapshot frame, basemap tiles are blocked, `Date.now()` is frozen and CSS
motion is disabled — so the only thing that can move a screenshot is the frontend
itself. The MapLibre canvas is masked out of the Live Map shots: its pixels come
from a software GL rasterizer with no cross-run guarantee, and a flaky baseline is
worse than no baseline. The map's own behavior is covered by the flow suite and by
unit tests.

The fixtures are regenerated separately, and much less often — only when the API
changes shape or a view starts needing an endpoint the recording does not contain:

```bash
npm run visual:capture                 # re-record e2e/visual/fixtures/ from a demo stack
npm run visual:update                  # then re-take the baselines
```

`visual:capture` brings up its own seeded demo stack, drives all five views, writes
`e2e/visual/fixtures/` (`api.har`, `live-snapshot.json`, `manifest.json`), and tears
the stack down. Do not hand-edit the fixtures — re-capture instead.

### Demo mode and capture/replay are the standard dev environment

No ADS-B hardware is required for development. **Demo mode** (slice 011) provides a
deterministic simulated receiver covering commercial, military, government, police,
MLAT, non-positioned, emergency-squawk, rare, and stale/disappearing traffic. The
**capture/replay tool** (slice 012, `flightsite.devtools`) records normalized decoder
snapshots into compact, gzip-compressed `.fsrec.gz` fixtures and replays them
deterministically — the preferred way to reproduce real-world bugs and build
regression tests. Prefer demo/replay over a live decoder for day-to-day work and for
all automated tests.

```bash
# record 60s of a live decoder to a fixture
uv run flightsite-capture --host 192.168.1.50 --port 8080 \
    --path /data/aircraft.json --duration 60 --out session.fsrec.gz

# replay it as a DecoderAdapter, e.g. from a script or test:
#   ReplayAdapter.from_path("session.fsrec.gz", speed=1.0)   # real-time pacing
#   ReplayAdapter.from_path("session.fsrec.gz", speed=4.0)   # 4x accelerated
#   ReplayAdapter.from_path("session.fsrec.gz", speed=None)  # as fast as possible (tests)
```

## Branch model

Long-lived branches, both protected (no direct pushes, no force pushes, PR required):

- **`main`** — production/released code only. Receives only release branches, with
  required CI/release checks and **human approval**.
- **`dev`** — integrated development branch. Receives only numbered slice branches
  after all quality gates pass. Fable may self-review, approve, and merge.

Feature work never happens directly on `main` or `dev`.

**Slice branches** are numbered and short-lived, cut from current `dev`:

```text
001-backend-skeleton
002-frontend-skeleton
...
```

One slice = one numbered branch = one PR (SPEC §95). Release branches are named
`release/vX.Y.Z` (see [`RELEASE.md`](RELEASE.md)).

**Bootstrap gating:** slices 001/002 merge before CI (slice 003) exists. `dev`
branch protection (PR required, no direct pushes) is applied before any merge; Fable
reviews 001/002 manually against their acceptance criteria, and slice 003
retroactively gates them once its workflows land.

## Slice execution loop (SPEC §121)

Every slice follows this checklist, in order:

1. [ ] Confirm all `depends_on` slices are merged.
2. [ ] Mark the slice `in_progress` in `planning/roadmap.yaml`.
3. [ ] Create the numbered branch from current `dev`.
4. [ ] Create and link the GitHub Issue for the slice.
5. [ ] Assign the appropriate agent (see [Agent model](#agent-model)).
6. [ ] Implement **only** the slice scope.
7. [ ] Add/update tests per the slice's `required_tests`.
8. [ ] Update documentation relevant to the slice.
9. [ ] Run all local quality gates (lint, types, tests, coverage).
10. [ ] Reconcile the branch with current `dev` (merge `dev` in; resolve drift).
11. [ ] Open the PR against `dev`.
12. [ ] Complete every section of the PR template.
13. [ ] Ensure all required CI checks pass.
14. [ ] Perform the Fable self-review (checklist below).
15. [ ] Correct all review findings.
16. [ ] Approve the PR (record the self-review in the PR).
17. [ ] Merge with a **merge commit**.
18. [ ] Verify `dev` remains deployable (build, tests, migrations, compose, demo mode).
19. [ ] Update the roadmap status to `merged`.
20. [ ] Select newly unblocked slices; parallelize where safe.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
feat: add readsb JSON ingestion
fix: recover open sightings after restart
test: cover emergency alert deduplication
docs: document metadata provenance
refactor: isolate aircraft state normalization
chore: bump ruff to 0.6
```

**Never update `CHANGELOG.md` on feature branches or `dev`.** The changelog is
generated and curated only on release branches (SPEC §111; see `RELEASE.md`).

## Merge policy

- **Merge commits only.** Squash merges and rebase merges are prohibited for PR
  integration (SPEC §100). Slice history must be preserved.
- Feature branch → `dev`: merge commit.
- Release branch → `main` and back → `dev`: merge commits.
- Do not weaken branch protections to work around automation (SPEC §99).

## Pull requests

Every slice PR must complete the template in
[`.github/pull_request_template.md`](../.github/pull_request_template.md): slice ID,
roadmap reference, linked issue, objective, implementation summary,
acceptance-criteria checklist, tests, performance/security/data-migration
considerations, documentation updates, known limitations, and follow-up work. The PR
title references the slice (e.g. `Slice 007: decoder ingestion adapter`).

### Fable self-review checklist (SPEC §104)

Fable may open, review, approve, and merge its own slice PRs into `dev` — but only
after inspecting the **complete diff** and verifying every item:

- [ ] Acceptance criteria satisfied
- [ ] No scope creep
- [ ] Tests are meaningful (not coverage filler)
- [ ] Failure cases covered
- [ ] APIs/types coherent
- [ ] Migrations safe
- [ ] Logs/error handling appropriate
- [ ] Security assumptions preserved
- [ ] Privacy expectations preserved
- [ ] Performance acceptable
- [ ] Documentation updated
- [ ] No temporary debug code
- [ ] No untracked TODO/FIXME
- [ ] Branch reconciled with current `dev`
- [ ] All mandatory CI checks passing

If GitHub identity mechanics prevent an approval from counting as a formal reviewer
approval, the quality gates are **not** weakened: the self-review is recorded
explicitly in a PR comment and the repository's approved automation/review identity
model is used.

## GitHub Issues (SPEC §103)

`planning/roadmap.yaml` remains canonical. Each implementation slice gets a GitHub
Issue (template: `Roadmap slice`) created when the slice starts. The PR links the
issue (`Closes #N`); merging closes it; the roadmap status is updated in the same
motion. GitHub Projects is not used for v1.

### Issue labels (slice 067)

Every open issue carries exactly one `severity:*` label, set at triage against the
code on `dev` (not against the issue text alone). The scale ranks every issue, not
only bugs: for an enhancement or documentation item it reads as priority.

| Label | Meaning |
|---|---|
| `severity:critical` | Data loss or corruption, a crash or hang of the running service, or a secret reaching logs, diagnostics, or the API. Blocks any release. |
| `severity:high` | A documented feature does not work for real users and there is no workaround. Blocks v1.0.0 (SPEC §114). |
| `severity:medium` | Wrong or degraded behavior with a workaround or a limited surface. Fix before v1.0.0, or document it as a known limitation and say so on the issue. |
| `severity:low` | Polish, efficiency, test or demo affordances, cosmetic. Never blocks a release. Bundle candidates. |

Two orthogonal labels qualify the severity:

- `release-gate` — the item blocks a SPEC §114 definition-of-done checkbox regardless
  of its severity (for example a documentation gap that makes "architecture
  documentation matches reality" false).
- `decision` — the item needs an owner or ADR decision before any code is written;
  the triage comment states the options.

Type labels (`bug`, `enhancement`, `documentation`) keep their GitHub-default
meaning. SPEC §114's "no known critical/high-severity product bugs remain" is
answered by the query in `docs/RELEASE.md`; a slice that fixes a labeled issue
closes it with `Closes #N` in the PR body so the query stays truthful without a
second triage pass.

## Parallel development (SPEC §96)

- Parallelize only slices with no unresolved dependency conflicts.
- Use **isolated git worktrees** per concurrent slice.
- Never have multiple agents editing the same files concurrently.
- Fable owns merge order and architectural consistency, and reconciles drift
  (merging current `dev` into the branch) before any merge.

## `dev` must always be deployable (SPEC §105)

Hard invariant. After every merge, `dev` is: buildable, testable, startable,
migration-valid, Docker Compose compatible, and demo-mode compatible. Knowingly
incomplete code that breaks merged functionality is never merged.

## Feature flags (SPEC §106)

Permitted sparingly, to land foundations without exposing incomplete features:

- Unfinished features default **off**.
- Flags are local/config-driven only — no external feature-management platform.
- Every temporary flag has a roadmap removal point; obsolete flags are removed
  promptly.

## Database migrations (SPEC §107)

All schema changes go through Alembic. Migrations are non-destructive where possible,
have tests (empty DB + realistic upgrade fixtures), and may be applied automatically
at startup. Adjacent released versions must have a tested upgrade path. Rollback is
supported where practical. Historical data is never casually discarded.

### SQLite DDL is not transactional — write resumable revisions

Alembic marks SQLite as non-transactional DDL, so a revision is **not** all-or-nothing:
every statement before a failing one stays committed while `alembic_version` still
names the *older* revision. A container that restarts after a failed migration re-runs
the whole revision from the top over a half-migrated database.

So each step of a revision must tolerate its own prior completion — create a table only
if absent, add a column only if missing, drop an index only if present, clear a stray
staging table before recreating it. `flightsite.db.migrations.rebuild` provides the
`has_table` / `has_index` / `has_column` predicates for exactly this.

### Rebuilding a table: disable foreign keys, then check them

SQLite cannot alter a `CHECK` (or most constraints) in place, so widening one means
rebuilding the table: create the new shape, copy every row, drop the old table, rename.
Every FlightSite connection — the app writer, the readers, and the engine
`migrations/env.py` builds — runs with `PRAGMA foreign_keys=ON`, and under enforcement
`DROP TABLE` is an implicit `DELETE` of every row, each checked against every child
table that references it. On a table with unindexed children that is a full scan per
parent row, and it fails anyway with `FOREIGN KEY constraint failed`. This took down a
v0.6.0 upgrade (issue #178).

A rebuild therefore goes through `flightsite.db.migrations.rebuild.rebuilding()`, which:

1. issues `PRAGMA foreign_keys=OFF` **and reads it back** — the pragma is silently a
   no-op inside a transaction, and pysqlite has one open whenever a preceding DML
   statement (Alembic's own `UPDATE alembic_version`, for instance) started one, so the
   helper commits to reach a statement boundary and retries rather than assuming;
2. runs the rebuild;
3. runs `PRAGMA foreign_key_check` over the rebuilt table and every table the schema
   says references it, and raises on any row — enforcement is *suspended* for the
   rebuild, not abandoned;
4. restores `PRAGMA foreign_keys=ON` in a `finally`, rolling back first if the rebuild
   raised.

The same applies to `downgrade()`, which rebuilds the same table.

### Measure migrations against populated data

A migration's cost is measured against a database with **rows in the child tables**,
never an empty seed: the v0.6.0 defect was invisible in a "200,000 sightings in 1.02 s"
measurement precisely because the five tables referencing `sightings` were empty. Seed
with the slice-050 synthetic generator (`flightsite.perf.storage_qualification`) or a
fixture that fills every child, and state the measured figure in the revision docstring.
`backend/tests/db/test_migration_0015_children.py` is the worked example: it seeds every
child of `sightings`, asserts each row survives with its reference intact, and bounds
the wall time.

### Parallel migrations & persistence worker

Concurrent worktrees can each add an Alembic revision, producing divergent heads.
Rules:

1. **Single linear head.** Alembic maintains exactly one head at all times. A
   migration-bearing slice may only merge when its revision's `down_revision` is the
   current head of `dev`. During the reconcile-with-`dev` step, Fable rebases the
   revision's `down_revision` onto the current head (or, exceptionally, adds an
   Alembic merge revision) before merging.
2. **Serialization of migration/worker slices.** Slices that add migrations or extend
   the slice-009 persistence worker — **021, 024, 026, 027, 031, 033, 035, 037, 038,
   052** — are serialized against each other even when the dependency graph would
   allow parallelism. Only non-migration slices run in parallel with them.
3. **CI enforcement.** CI runs `alembic check` / multiple-heads detection; a divergent
   head fails the build.

## TODO discipline (SPEC §119)

No unresolved `TODO`, `FIXME`, or `HACK` without a tracked issue or roadmap item
referenced next to it. Temporary workarounds must have an explicit removal path.

## Scope discipline (SPEC §118)

When an implementation question arises: check `planning/roadmap.yaml`, then
`docs/PRODUCT.md`, then `docs/ARCHITECTURE.md`/ADRs; determine whether it is required
for the current slice. Discovered-but-not-needed work becomes a tracked follow-up
issue/slice — never a silent expansion of the active PR.

## Roadmap changes (SPEC §97)

Fable may split slices, add prerequisites, reorder, add discovered technical work, or
defer with justification. Every change updates **both** `planning/roadmap.yaml` and
`docs/ROADMAP.md`, preserves slice history, never repurposes an existing slice ID,
and documents its rationale. v1 scope is not casually expanded; new ideas go to the
roadmap backlog.

## Agent model

- **Fable** orchestrates: planning, decomposition, sequencing, delegation, review,
  quality gates, merges, releases.
- **Opus** handles architecture, ambiguous decisions, data-model/API design,
  concurrency, persistence, performance, security analysis, risky changes, and
  difficult debugging.
- **Sonnet** handles well-specified implementation: routine APIs, React components,
  tests, migrations, documentation, mechanical refactoring, configuration.
- Each roadmap slice records a `preferred_agent`; a Sonnet task is escalated to Opus
  when ambiguity or unexpected complexity is discovered. Opus is not used for routine
  mechanical work.

## Architecture Decision Records

Consequential decisions get an ADR in [`docs/adr/`](adr/) (SPEC §90). Trivial
implementation details do not. If code and ADRs disagree, fix one of them in the same
slice that discovers the disagreement.
