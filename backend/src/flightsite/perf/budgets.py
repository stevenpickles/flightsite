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
``docs/PERFORMANCE.md`` carries a recorded Pi baseline for it.

Five of the original six were promoted on the two on-hardware baselines in
``docs/PERFORMANCE.md`` §5.4 (Pi 4, SD card, contended) and §5.5 (Pi 5, NVMe,
all twelve gates passed): each was inside its budget on both, and a figure that
*met* its budget on a contended machine met it with the worst case included.
``db_write_cycle_ms`` is the one that remains, because those two runs disagree
about it by an order of magnitude — the storage device sets it, and the clean
Pi 4 run on non-SD storage that would calibrate it is issue #153.

CI headroom
-----------

Hard gates that measure *time* are asserted against ``budget x ci_headroom``.
The default multiplier is :data:`CI_HEADROOM`, five — the convention
``tests/alerts/test_perf.py`` also uses: a shared runner under coverage
instrumentation is slow and noisy, and a bound five times the budget still
catches every structural regression (a hot-path await, a per-aircraft query, a
superlinear scan) while never failing on a busy machine.

Budgets that measure a *quantity* rather than a duration get
:data:`NO_HEADROOM`. A 1 GB memory ceiling relaxed five-fold is not a gate, and
the live population a deterministic scenario produces does not vary with how
loaded the machine is.

Two gates carry a multiplier sized from their own CI history instead of the
default, because the default was not the right number for either (issues #166
and #170). The reference-hardware budgets are untouched — 0.5 of a poll and
100 ms, exactly as before — and ``docs/PERFORMANCE.md`` §5 reads every figure
against the budget at face value on the hardware being qualified; what moved is
only the bound the shared-runner suite asserts.

``ingest_duty_cycle`` gets :data:`DUTY_CYCLE_CI_HEADROOM`, 1.8, so 0.9 of a
poll. It was the one hard gate with no headroom at all, and across the v0.4.0
and v0.5.0 release trains it flaked at p95 0.539, 0.542, 0.645 and 0.73 against
0.5, beside medians of 0.08-0.11 — every time on a commit whose other 4,400
tests passed and which passed this gate on re-run. 0.9 clears the worst of the
four by 1.23x. The multiplier is fractional, and cannot be larger, because this
budget is a fraction of a poll rather than a duration: at 1.0 the tick consumes
the whole poll, so a multiplier of 2 or more would assert a bound that a
pipeline losing ground could still pass, and "ingestion keeps up" would stop
meaning anything.

``ingest_apply_ms`` gets :data:`APPLY_CI_HEADROOM`, 8, so 800 ms. The default
five bounded it at 500 ms and shared runners crossed that twice, at p95 585 ms
and 658 ms beside medians of 37-41 ms, on the same kind of otherwise-green run.
800 ms clears the worse of the two by 1.22x, and stays inside
``ingest_duty_cycle``'s 900 ms: the apply is one term of that sum, so its own
bound has no business exceeding the sum's.

Neither widening hides a regression, because what those runs show is one
contended tick beside a healthy median rather than a slower pipeline. A
regression that doubled the median *and* carried the tail with it in the same
proportion would put ``ingest_apply_ms`` near 1.2 s and ``ingest_duty_cycle``
near 1.4 of a poll — outside the new bounds by half again and more. Nor do the
new bounds rewrite the record: §5.4's Pi 4 duty cycle of 0.99 fails at 0.9
exactly as it failed at 0.5, so issue #132's finding stands.

``startup_s`` and ``recovery_s`` are durations that also carry
:data:`NO_HEADROOM`. Slice 065 promoted both at their stated 30 s rather than
relaxing them to 150 s on promotion, because a promotion that loosens the bound
it enforces is not one. Their margins are not alike, though, and the difference
matters more than the shared constant: startup measured 0.547 s on a contended
Pi 4 and 0.112 s on a Pi 5, while recovery measured **9.3 s** on that Pi 4's SD
card against 0.0755 s on the Pi 5. Recovery therefore sits 3.2x inside its
ceiling on the reference hardware, on a path already reported as load-sensitive
(issue #100) — the tightest of the five gates §5.5 promotes. On slow storage the
rows that actually go red first are ingest_duty_cycle and db_write_cycle_ms
(issues #132/#153); recovery_s is the promoted gate worth watching beside them.
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

#: ``ingest_apply_ms``'s own allowance, sized from the shared-runner p95s that
#: crossed the default multiplier's 500 ms bound (see the module docstring).
APPLY_CI_HEADROOM: Final = 8

#: ``ingest_duty_cycle``'s own allowance, and the only fractional one in the
#: table: the budget is a fraction of a poll, so the multiplier has to leave the
#: asserted bound below 1.0 for the gate to keep meaning "ingestion keeps up".
DUTY_CYCLE_CI_HEADROOM: Final = 1.8

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
            Usually :data:`CI_HEADROOM` or :data:`NO_HEADROOM`; two gates carry
            an allowance sized from their own CI history, which is why this is a
            float rather than an int.
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
    ci_headroom: float
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
#: SPEC §85 names, then the rows promoted to hard gates on the §5.4/§5.5
#: baselines, then what remains trend-tracked.
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
        ci_headroom=APPLY_CI_HEADROOM,
        rationale=(
            "docs/ARCHITECTURE.md §3.3: the adapter normalizes and applies a batch between "
            "polls, so an apply approaching the 1 s poll interval turns the live picture into "
            "a backlog. A tenth of a poll leaves room for every other consumer. In-suite it "
            "carries 8x rather than the default 5x: shared runners twice put the p95 at 585 "
            "and 658 ms beside medians of 37-41 ms, so the 500 ms the default asserted sat "
            "below the runner noise headroom exists to absorb (issues #166, #170)."
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
        ci_headroom=DUTY_CYCLE_CI_HEADROOM,
        rationale=(
            "The whole synchronous hot path — apply, event dispatch, every live consumer — "
            "measured against one 1 Hz poll. Above 1.0 the pipeline is losing ground; the "
            "budget is half a poll so a Pi 4 at several times dev-machine cost still keeps up. "
            "In-suite it asserts 0.9 of a poll: it ran with no headroom at all and flaked four "
            "times on shared runners at p95 0.539, 0.542, 0.645 and 0.73 beside medians of "
            "0.08-0.11 (issue #166). The multiplier is fractional and can be no larger, "
            "because a bound at or above one whole poll would tolerate a pipeline that is "
            "losing ground. Gated on the p95 rather "
            "than the maximum because the sum assumes the stages run serially, as this harness "
            "drives them: in the product the write-behind worker is a separate task and cannot "
            "block live.apply (ADR-0008), so the periodic 30 s flush spike delays the next "
            "write rather than the next observation."
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
        gate=GateKind.HARD,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "One delta built and delivered to every connected client, once per ~1 Hz tick "
            "(docs/API.md §4.3). Promoted from a reference budget on the on-hardware baselines "
            "in docs/PERFORMANCE.md §5.5: 68.1 ms p95 on a contended Pi 4 and 28.2 ms on a "
            "Pi 5, both inside the 100 ms budget."
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
        gate=GateKind.HARD,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "History and sightings endpoints served while ingestion runs, i.e. a reader "
            "competing with the single writer for the WAL. Promoted on the baselines in "
            "docs/PERFORMANCE.md §5.5: 26.2 ms p95 on a contended Pi 4 and 9.16 ms on a Pi 5, "
            "against a 500 ms budget. Slice 050 qualifies it again at multi-year scale."
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
        gate=GateKind.HARD,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "Roadmap slice 031's stated budget, restated here under concurrent ingestion "
            "rather than on an idle process. Promoted on the baselines in "
            "docs/PERFORMANCE.md §5.5: 48.2 ms p95 on a contended Pi 4 and 13.8 ms on a Pi 5, "
            "against a 500 ms budget. Slice 050 qualifies it on a multi-year dataset."
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
        gate=GateKind.HARD,
        ci_headroom=NO_HEADROOM,
        rationale=(
            "Migrations, wiring and the first ready report. Dominated by disk on a Pi, so the "
            "budget is stated for that hardware. Promoted on the baselines in "
            "docs/PERFORMANCE.md §5.5 — 0.547 s on a contended Pi 4, 0.112 s on a Pi 5 — and "
            "kept at NO_HEADROOM: multiplying a 30 s ceiling by five would assert a bound no "
            "machine could fail, and a promotion that loosens its own bound is not one."
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
        gate=GateKind.HARD,
        ci_headroom=NO_HEADROOM,
        rationale=(
            "Repairing every sighting left open by a power cut, from checkpoint rows "
            "(slice 053). Bounded by the open-sighting count, which the harness records, and "
            "by the storage device. Promoted on the baselines in docs/PERFORMANCE.md §5.5 and "
            "kept at NO_HEADROOM, the narrowest margin among the five §5.5 promotions: 539 open "
            "sightings were repaired in 9.3 s on a contended Pi 4 SD card — 3.2x inside the "
            "30 s ceiling — against 0.0755 s on a Pi 5, and the path is already reported as "
            "load-sensitive (issue #100). Promoted knowingly on that figure: the budget bounds "
            "exactly the disk cost that consumed it."
        ),
        also_enforced_by=("tests/sightings/test_kill_drill.py",),
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
            "correctness limit. The one row the two on-hardware baselines disagree about — "
            "678 ms p95 on a Pi 4 SD card against 57.7 ms on a Pi 5 NVMe — so it stays a "
            "reference budget: the storage device, not the code, sets it, and the clean Pi 4 "
            "run on non-SD storage that would calibrate it is issue #153."
        ),
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
    "APPLY_CI_HEADROOM",
    "BUDGETS",
    "CI_HEADROOM",
    "DUTY_CYCLE_CI_HEADROOM",
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
