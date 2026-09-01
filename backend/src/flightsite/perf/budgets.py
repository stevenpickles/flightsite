"""The canonical performance budget table (SPEC §85, ``docs/PERFORMANCE.md``).

This module is the single source of truth. ``docs/PERFORMANCE.md`` renders it,
``tests/perf/test_budgets.py`` checks the rendering still matches, and roadmap
slice 050 asserts its multi-year results against it. A budget that lives only
in a doc drifts from the test that enforces it; a budget that lives only in a
test is invisible to the person deciding whether a Pi 4 is fast enough. Keeping
it as data means both are views of one table.

Two kinds of budget, and the difference is the whole point of SPEC §85's
"hybrid gate model":

**Hard gates** (:attr:`GateKind.HARD`) fail the suite. SPEC §85 names them:
ingestion keeps up, the 500-aircraft workload stays functional, no live-state
stalls, memory below the agreed budget, core APIs responsive. These are
correctness-critical — crossing one means the live picture is a backlog, or the
process is heading for the OOM killer — so they are enforced on whatever
hardware the suite runs on.

**Reference budgets** (:attr:`GateKind.REFERENCE`) are measured, reported and
trended, but do not fail the suite. SPEC §85: *"trend-track less critical
metrics initially; convert to hard gates once real Pi 4 baselines exist."* They
are stated against the reference hardware (Raspberry Pi 4), and a dev machine
beating them by an order of magnitude proves nothing about the Pi. Promoting
one to :attr:`GateKind.HARD` is a deliberate edit here once
``docs/PERFORMANCE.md`` carries a recorded Pi 4 baseline for it.

CI headroom
-----------

Hard gates that measure *time* are asserted against ``budget x ci_headroom``,
the convention already used by ``tests/alerts/test_perf.py`` and
``tests/metadata/test_cache_latency.py``: a shared runner under coverage
instrumentation is slow and noisy, and a bound five times the budget still
catches every structural regression (a hot-path await, a per-aircraft query, a
superlinear scan) while never failing on a busy machine.

Budgets that measure a *quantity* rather than a duration get
:data:`NO_HEADROOM`. A 1 GB memory ceiling relaxed five-fold is not a gate, and
the live population a deterministic scenario produces does not vary with how
loaded the machine is.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from flightsite.perf.measure import Statistic

#: The established allowance for a shared CI runner (see the module docstring).
CI_HEADROOM: Final = 5

#: Applied to budgets a loaded machine cannot legitimately miss.
NO_HEADROOM: Final = 1

#: The load envelope every scenario runs at (SPEC §5): concurrent aircraft.
TARGET_AIRCRAFT: Final = 500

#: The decoder cadence the envelope is stated at (SPEC §5): 1 Hz.
TICK_INTERVAL_S: Final = 1.0


class GateKind(StrEnum):
    """Whether crossing a budget fails the suite."""

    HARD = "hard"
    REFERENCE = "reference"


class Direction(StrEnum):
    """Whether the budget is an upper or a lower bound."""

    #: Measured value must stay at or below the budget (latency, memory).
    CEILING = "ceiling"
    #: Measured value must stay at or above the budget (throughput, population).
    FLOOR = "floor"


@dataclass(frozen=True, slots=True)
class Budget:
    """One row of the canonical table.

    Args:
        metric: stable id; the :class:`~.measure.Measurement` that answers it
            carries the same string.
        title: the human name used in ``docs/PERFORMANCE.md``.
        spec_metric: which item of SPEC §85's measurement list this covers.
        unit: what the value counts.
        value: the budget itself, on reference hardware (Raspberry Pi 4).
        statistic: which summary statistic of the distribution is compared.
        direction: ceiling or floor.
        gate: hard gate or trend-tracked reference.
        ci_headroom: multiplier (ceiling) or divisor (floor) applied in-suite.
        rationale: why this number, in one sentence.
        also_enforced_by: existing suite tests that already guard some part of
            this budget in isolation, so the table shows what is new here and
            what is a whole-pipeline restatement of an existing check.
    """

    metric: str
    title: str
    spec_metric: str
    unit: str
    value: float
    statistic: Statistic
    direction: Direction
    gate: GateKind
    ci_headroom: int
    rationale: str
    also_enforced_by: tuple[str, ...] = ()

    @property
    def hard(self) -> bool:
        """True when crossing this budget fails the suite."""
        return self.gate is GateKind.HARD

    @property
    def asserted(self) -> float:
        """The bound actually asserted in-suite, after CI headroom."""
        if self.direction is Direction.CEILING:
            return self.value * self.ci_headroom
        return self.value / self.ci_headroom

    def satisfied_by(self, observed: float) -> bool:
        """Whether ``observed`` meets the in-suite bound."""
        if self.direction is Direction.CEILING:
            return observed <= self.asserted
        return observed >= self.asserted


#: The table. Ordered as ``docs/PERFORMANCE.md`` presents it: the hard gates
#: SPEC §85 names, then the reference budgets awaiting Pi 4 baselines.
BUDGETS: Final[tuple[Budget, ...]] = (
    Budget(
        metric="live_population",
        title="Sustained live population",
        spec_metric="500-aircraft workload remains functional",
        unit="aircraft",
        value=float(TARGET_AIRCRAFT),
        statistic=Statistic.MIN,
        direction=Direction.FLOOR,
        gate=GateKind.HARD,
        ci_headroom=NO_HEADROOM,
        rationale=(
            "SPEC §5's envelope is ~500 simultaneously visible aircraft; a run that never "
            "reached it measured something easier than the product's stated load."
        ),
    ),
    Budget(
        metric="ingest_apply_ms",
        title="Live-state update latency (batch apply)",
        spec_metric="live-state update latency",
        unit="ms",
        value=100.0,
        statistic=Statistic.P95,
        direction=Direction.CEILING,
        gate=GateKind.HARD,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "docs/ARCHITECTURE.md §3.3: the adapter normalizes and applies a batch between "
            "polls, so an apply approaching the 1 s poll interval turns the live picture into "
            "a backlog. A tenth of a poll leaves room for every other consumer."
        ),
        also_enforced_by=("tests/live/test_perf.py",),
    ),
    Budget(
        metric="ingest_duty_cycle",
        title="Ingestion keeps up (poll interval consumed)",
        spec_metric="ingestion throughput",
        unit="fraction of a poll",
        value=0.5,
        statistic=Statistic.P95,
        direction=Direction.CEILING,
        gate=GateKind.HARD,
        ci_headroom=NO_HEADROOM,
        rationale=(
            "The whole synchronous hot path — apply, event dispatch, every live consumer — "
            "measured against one 1 Hz poll. Above 1.0 the pipeline is losing ground; the "
            "budget is half a poll so a Pi 4 at several times dev-machine cost still keeps up. "
            "No headroom: this is already expressed as a ratio to the poll, so a slow machine "
            "is the thing being measured, not noise to be forgiven."
        ),
    ),
    Budget(
        metric="live_sweep_ms",
        title="Lifecycle sweep over the full live set",
        spec_metric="live-state update latency",
        unit="ms",
        value=100.0,
        statistic=Statistic.MAX,
        direction=Direction.CEILING,
        gate=GateKind.HARD,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "The sweep runs every second over the whole live set, so it shares the batch-apply "
            "budget: together they must stay well inside one poll."
        ),
        also_enforced_by=("tests/live/test_perf.py",),
    ),
    Budget(
        metric="api_live_ms",
        title="Core API responsiveness under load",
        spec_metric="core APIs responsive",
        unit="ms",
        value=250.0,
        statistic=Statistic.P95,
        direction=Direction.CEILING,
        gate=GateKind.HARD,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "/api/v1/aircraft/current answers from memory (docs/ARCHITECTURE.md §3.1), so under "
            "sustained ingestion it is serialization cost and nothing else. A quarter second is "
            "the point past which the map feels stalled rather than live."
        ),
    ),
    Budget(
        metric="memory_rss_mib",
        title="Backend resident memory",
        spec_metric="memory use",
        unit="MiB",
        value=1024.0,
        statistic=Statistic.MAX,
        direction=Direction.CEILING,
        gate=GateKind.HARD,
        ci_headroom=NO_HEADROOM,
        rationale=(
            "SPEC §5: backend memory comfortably below 1 GB. An absolute ceiling on a 4 GB Pi "
            "shared with the frontend container and the decoder — relaxing it for CI noise "
            "would make it meaningless."
        ),
    ),
    Budget(
        metric="ws_fanout_ms",
        title="WebSocket fan-out per tick",
        spec_metric="WebSocket distribution",
        unit="ms",
        value=100.0,
        statistic=Statistic.P95,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "One delta built and delivered to every connected client, once per ~1 Hz tick "
            "(docs/API.md §4.3). Reference until a Pi 4 baseline exists: fan-out cost is "
            "serialization-bound and scales with client count, which the harness records "
            "alongside the figure."
        ),
    ),
    Budget(
        metric="db_write_cycle_ms",
        title="SQLite write latency (persistence cycle)",
        spec_metric="SQLite write latency",
        unit="ms",
        value=250.0,
        statistic=Statistic.P95,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "One write-behind cycle committing a tick's accumulated sighting work. It is off "
            "the hot path by construction (ADR-0008), so this is a health figure rather than a "
            "correctness limit — reference until Pi 4 SD-card I/O sets the real number."
        ),
    ),
    Budget(
        metric="db_read_ms",
        title="SQLite read/query latency",
        spec_metric="SQLite read/query latency",
        unit="ms",
        value=500.0,
        statistic=Statistic.P95,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "History and sightings endpoints served while ingestion runs, i.e. a reader "
            "competing with the single writer for the WAL. Reference until Pi 4 storage is "
            "characterized; slice 050 qualifies it at multi-year scale."
        ),
        also_enforced_by=(
            "tests/api/test_sightings_perf.py",
            "tests/api/test_aircraft_history_perf.py",
        ),
    ),
    Budget(
        metric="analytics_query_ms",
        title="Analytics query latency",
        spec_metric="analytics query latency",
        unit="ms",
        value=500.0,
        statistic=Statistic.P95,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "Roadmap slice 031's stated budget, restated here under concurrent ingestion "
            "rather than on an idle process. Slice 050 qualifies it on a multi-year dataset."
        ),
        also_enforced_by=("tests/analytics/test_perf.py",),
    ),
    Budget(
        metric="startup_s",
        title="Startup to ready",
        spec_metric="startup",
        unit="s",
        value=30.0,
        statistic=Statistic.MAX,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=NO_HEADROOM,
        rationale=(
            "Migrations, wiring and the first ready report. Dominated by disk on a Pi 4, so the "
            "budget is stated for that hardware and carries no CI headroom — a dev machine "
            "should be nowhere near it."
        ),
    ),
    Budget(
        metric="recovery_s",
        title="Unclean-shutdown recovery",
        spec_metric="unclean-shutdown recovery",
        unit="s",
        value=30.0,
        statistic=Statistic.MAX,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=NO_HEADROOM,
        rationale=(
            "Repairing every sighting left open by a power cut, from checkpoint rows "
            "(slice 053). Bounded by the open-sighting count, which the harness records; "
            "reference until Pi 4 SD-card I/O sets the real number."
        ),
        also_enforced_by=("tests/sightings/test_kill_drill.py",),
    ),
)

#: Metric id -> budget, built once.
_BY_METRIC: Final[dict[str, Budget]] = {budget.metric: budget for budget in BUDGETS}


def budget_for(metric: str) -> Budget:
    """The budget named ``metric``.

    Raises ``KeyError`` for an unknown id, so a typo in a scenario fails loudly
    instead of silently measuring something nothing gates.
    """
    return _BY_METRIC[metric]


def hard_budgets() -> tuple[Budget, ...]:
    """Just the gates that fail the suite."""
    return tuple(budget for budget in BUDGETS if budget.hard)


def reference_budgets() -> tuple[Budget, ...]:
    """Just the trend-tracked reference budgets."""
    return tuple(budget for budget in BUDGETS if not budget.hard)


__all__ = [
    "BUDGETS",
    "CI_HEADROOM",
    "NO_HEADROOM",
    "TARGET_AIRCRAFT",
    "TICK_INTERVAL_S",
    "Budget",
    "Direction",
    "GateKind",
    "budget_for",
    "hard_budgets",
    "reference_budgets",
]
