"""Running the load, collecting the metrics, and judging them against the table.

:func:`run_harness` is the whole slice in one call: it drives
:class:`~.workload.Workload` for the configured number of 1 Hz ticks, probes the
HTTP surface and process memory while the load is running, measures startup and
unclean-shutdown recovery, and returns a :class:`HarnessReport` that knows which
budgets it met.

The probes run *during* the load on purpose. Every existing perf test in the
suite measures one subsystem on an otherwise idle process — that is the right
shape for a unit-level budget, and those tests are listed in each
:class:`~.budgets.Budget`'s ``also_enforced_by``. What none of them can answer
is SPEC §85's actual question: whether the core APIs stay responsive *while*
500 aircraft are being ingested, alerts evaluated and sightings written. So the
API, database-read and analytics samples here are taken between ticks of a
running pipeline, and the numbers are legitimately worse than the isolated ones
— that is the point of measuring them.
"""

from __future__ import annotations

import platform
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from httpx import AsyncClient

from flightsite.app import create_app
from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.perf.budgets import BUDGETS, Budget
from flightsite.perf.measure import MIB, Measurement, Statistic, rss_bytes
from flightsite.perf.workload import TickCost, Workload, WorkloadConfig
from flightsite.sightings import PersistenceWorker

#: Ticks between HTTP/memory probes. Frequent enough that a default 60-tick run
#: yields ~30 samples, which is the fewest a p95 can be read from without
#: collapsing onto the maximum (nearest-rank needs n >= 20); infrequent enough
#: that the probes do not become the dominant load themselves.
DEFAULT_PROBE_EVERY: Final = 2

#: Ticks of traffic built up before the recovery measurement abandons the
#: database. Enough that a few hundred sightings are open and carrying track
#: checkpoints, which is the state slice 053's repair path exists for; a
#: handful would measure an empty recovery.
DEFAULT_RECOVERY_TICKS: Final = 20

#: Endpoints probed under load, and the metric each answers.
PROBES: Final[tuple[tuple[str, str], ...]] = (
    ("api_live_ms", "/api/v1/aircraft/current"),
    ("db_read_ms", "/api/v1/sightings"),
    ("analytics_query_ms", "/api/v1/analytics/summary"),
)


@dataclass(frozen=True, slots=True)
class Environment:
    """What the numbers were measured on, so a table of them means something."""

    platform: str
    python: str
    processor: str
    rss_available: bool

    @classmethod
    def capture(cls) -> Environment:
        """Read the current machine."""
        return cls(
            platform=f"{platform.system()} {platform.release()} ({platform.machine()})",
            python=sys.version.split()[0],
            processor=platform.processor() or "unknown",
            rss_available=rss_bytes() is not None,
        )


@dataclass(frozen=True, slots=True)
class Verdict:
    """One budget judged against what was actually measured."""

    budget: Budget
    measurement: Measurement | None

    @property
    def measured(self) -> bool:
        """Whether this run produced a value for the budget at all."""
        return self.measurement is not None

    @property
    def observed(self) -> float | None:
        """The statistic the budget names, from this run."""
        if self.measurement is None:
            return None
        return self.measurement.statistic(self.budget.statistic)

    @property
    def passed(self) -> bool:
        """Whether the in-suite bound held.

        An unmeasured budget passes: a metric this run did not collect (memory
        on a platform with no RSS source, startup when the caller asked to skip
        it) is a gap in the report, not a regression. :attr:`measured` is what
        distinguishes the two, and the report prints it.
        """
        observed = self.observed
        if observed is None:
            return True
        return self.budget.satisfied_by(observed)


@dataclass(frozen=True, slots=True)
class HarnessReport:
    """Everything one harness run measured, and how it judged.

    Args:
        measurements: one per metric collected.
        environment: the machine.
        config: the load that was applied.
        duration_s: wall-clock time the whole run took.
    """

    measurements: tuple[Measurement, ...]
    environment: Environment
    config: WorkloadConfig
    duration_s: float

    def measurement(self, metric: str) -> Measurement | None:
        """The measurement for ``metric``, or ``None`` if not collected."""
        for measurement in self.measurements:
            if measurement.metric == metric:
                return measurement
        return None

    def verdicts(self) -> tuple[Verdict, ...]:
        """Every budget in the canonical table, judged against this run."""
        return tuple(Verdict(budget, self.measurement(budget.metric)) for budget in BUDGETS)

    def failures(self) -> tuple[Verdict, ...]:
        """Hard gates this run did not meet."""
        return tuple(
            verdict
            for verdict in self.verdicts()
            if verdict.budget.hard and verdict.measured and not verdict.passed
        )

    @property
    def passed(self) -> bool:
        """True when every hard gate that was measured held."""
        return not self.failures()

    def format_table(self) -> str:
        """The report as a table, for the CLI and for pasting into a doc.

        ASCII only: this is printed to whatever console the machine being
        qualified happens to have, and a Raspberry Pi over a serial console or
        a Windows terminal on a legacy code page should not turn the report
        into mojibake.
        """
        header = (
            f"{'metric':<22} {'gate':<10} {'stat':<7} {'observed':>12} "
            f"{'budget':>10} {'bound':>12} {'unit':<18} {'result':<8}"
        )
        lines = [
            f"FlightSite performance harness - {self.environment.platform}",
            f"Python {self.environment.python} | {self.config.population} aircraft "
            f"| {self.config.ticks} ticks @ {self.config.tick_interval_s:g}s "
            f"| {self.config.ws_clients} WS clients | {self.duration_s:.1f}s wall",
            "",
            header,
            "-" * len(header),
        ]
        for verdict in self.verdicts():
            budget = verdict.budget
            observed = verdict.observed
            if observed is None:
                shown, result = "not measured", "skipped"
            else:
                shown = f"{observed:.3g}"
                result = "pass" if verdict.passed else ("FAIL" if budget.hard else "over")
            lines.append(
                f"{budget.metric:<22} {budget.gate.value:<10} "
                f"{budget.statistic.value:<7} {shown:>12} {budget.value:>10.3g} "
                f"{budget.asserted:>12.3g} {budget.unit:<18} {result:<8}"
            )
        lines.append("")
        for measurement in self.measurements:
            note = f"  [{measurement.note}]" if measurement.note else ""
            lines.append(f"{measurement.metric:<22} {measurement.summary}{note}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serializable form, for trend tracking across runs."""
        return {
            "environment": {
                "platform": self.environment.platform,
                "python": self.environment.python,
                "processor": self.environment.processor,
                "rss_available": self.environment.rss_available,
            },
            "config": {
                "population": self.config.population,
                "ticks": self.config.ticks,
                "warmup_ticks": self.config.warmup_ticks,
                "ws_clients": self.config.ws_clients,
                "seed": self.config.seed,
                "realtime": self.config.realtime,
                "tick_interval_s": self.config.tick_interval_s,
            },
            "duration_s": self.duration_s,
            "passed": self.passed,
            "metrics": {
                measurement.metric: {
                    "unit": measurement.unit,
                    "count": measurement.count,
                    "median": measurement.statistic(Statistic.MEDIAN),
                    "p95": measurement.statistic(Statistic.P95),
                    "max": measurement.statistic(Statistic.MAX),
                    "min": measurement.statistic(Statistic.MIN),
                    "note": measurement.note,
                }
                for measurement in self.measurements
            },
            "verdicts": {
                verdict.budget.metric: {
                    "gate": verdict.budget.gate.value,
                    "bound": verdict.budget.asserted,
                    "observed": verdict.observed,
                    "measured": verdict.measured,
                    "passed": verdict.passed,
                }
                for verdict in self.verdicts()
            },
        }


async def _probe(client: AsyncClient, samples: dict[str, list[float]]) -> None:
    """Time every probed endpoint once, between ticks of the running load."""
    for metric, path in PROBES:
        started = time.perf_counter()
        response = await client.get(path)
        elapsed_ms = (time.perf_counter() - started) * 1_000.0
        if response.status_code != 200:  # pragma: no cover - defensive
            raise RuntimeError(f"{path} answered {response.status_code} under load")
        samples[metric].append(elapsed_ms)


async def run_load(
    config: WorkloadConfig,
    *,
    data_dir: Path | None = None,
    probe_every: int = DEFAULT_PROBE_EVERY,
) -> tuple[Measurement, ...]:
    """Drive the workload and return every metric the load itself produces.

    Startup and recovery are measured separately (:func:`measure_startup`,
    :func:`measure_recovery`): both are about a process that is *not* yet
    serving, so neither belongs inside a loop that is measuring one that is.
    """
    costs: list[TickCost] = []
    samples: dict[str, list[float]] = {metric: [] for metric, _ in PROBES}
    rss_mib: list[float] = []

    async with Workload(config, data_dir=data_dir) as workload:
        await workload.warm_up()
        async with workload.http() as client:
            for index in range(config.ticks):
                costs.append(await workload.run_tick())
                if index % probe_every == 0:
                    await _probe(client, samples)
                    resident = rss_bytes()
                    if resident is not None:
                        rss_mib.append(resident / MIB)
        # Read inside the context manager: leaving it tears the components down.
        wanted = config.ws_clients
        still_connected = workload.clients_connected
        frames_read = workload.frames_read
        reconnects = workload.reconnects

    # Fan-out timed against nobody looks *better* than the truth -- a failure
    # mode this harness hit twice before the clients learned to reconnect -- so
    # ending the run short of the clients it claims is an error rather than a
    # footnote. Reconnects along the way are fine and are reported; ending
    # without a full set is not.
    if still_connected < wanted:
        raise RuntimeError(
            f"the run ended with {still_connected} of {wanted} simulated WebSocket clients "
            f"({frames_read} frames consumed, {reconnects} reconnects); the fan-out "
            "measurement would be for fewer clients than the report claims"
        )

    measurements = [
        Measurement(
            metric="live_population",
            unit="aircraft",
            samples=tuple(float(cost.population) for cost in costs),
            note=f"demo scenario, population={config.population}",
        ),
        Measurement(
            metric="ingest_apply_ms",
            unit="ms",
            samples=tuple(cost.apply_ms for cost in costs),
        ),
        Measurement(
            metric="live_sweep_ms",
            unit="ms",
            samples=tuple(cost.sweep_ms for cost in costs),
        ),
        Measurement(
            metric="ingest_duty_cycle",
            unit="fraction of a poll",
            samples=tuple(cost.duty_cycle(config.tick_interval_s) for cost in costs),
            note=(
                "apply + sweep + alerts + persistence + fan-out, "
                f"against a {config.tick_interval_s:g} s poll"
            ),
        ),
        Measurement(
            metric="db_write_cycle_ms",
            unit="ms",
            samples=tuple(cost.persistence_ms for cost in costs),
        ),
        Measurement(
            metric="ws_fanout_ms",
            unit="ms",
            samples=tuple(cost.broadcast_ms for cost in costs),
            note=(
                f"{still_connected} clients, {frames_read} frames consumed, "
                f"{reconnects} resync reconnects"
            ),
        ),
    ]
    for metric, _path in PROBES:
        if samples[metric]:
            measurements.append(
                Measurement(metric=metric, unit="ms", samples=tuple(samples[metric]))
            )
    if rss_mib:
        measurements.append(
            Measurement(
                metric="memory_rss_mib",
                unit="MiB",
                samples=tuple(rss_mib),
                note="whole process, including the harness itself",
            )
        )
    return tuple(measurements)


async def measure_startup(*, data_dir: Path | None = None, runs: int = 1) -> Measurement:
    """Time a cold start: migrations, wiring, and every subsystem started.

    In-process, so this is the application's own startup cost and excludes the
    interpreter launch and image pull around it. That is the quantity a change
    to FlightSite can regress; the rest belongs to the host and is recorded in
    ``docs/PERFORMANCE.md``'s Pi 4 procedure instead.
    """
    samples: list[float] = []
    for _ in range(runs):
        started = time.perf_counter()
        app = create_app(data_dir) if data_dir is not None else create_app()
        async with app.router.lifespan_context(app):
            elapsed = time.perf_counter() - started
        samples.append(elapsed)
    return Measurement(
        metric="startup_s",
        unit="s",
        samples=tuple(samples),
        note="in-process: migrations, wiring and subsystem start",
    )


async def measure_recovery(
    *, data_dir: Path | None = None, ticks: int = DEFAULT_RECOVERY_TICKS
) -> Measurement:
    """Time the repair of sightings left open by an unclean stop.

    A workload is run and its worker stopped, which by design leaves every
    sighting *open* in the database (``PersistenceWorker.stop``: a clean stop is
    not an observation gap). A fresh worker over that database therefore faces
    exactly the state slice 053's recovery path exists for, and the measured
    quantity is :meth:`~flightsite.sightings.PersistenceWorker.start` — the
    adoption and checkpoint repair — rather than the process launch, which
    :func:`measure_startup` already counts.
    """
    config = WorkloadConfig(ticks=ticks, warmup_ticks=0, ws_clients=1)
    async with Workload(config, data_dir=data_dir) as workload:
        for _ in range(config.ticks):
            await workload.run_tick()
        await workload.worker.process_pending(force_flush=True)
        database_path = workload.app.state.database.path
        open_sightings = workload.worker.active_count

    database = Database(database_path)
    live = LiveStore()
    worker = PersistenceWorker(database=database, live=live)
    started = time.perf_counter()
    await worker.start()
    elapsed = time.perf_counter() - started
    await worker.stop()
    await database.dispose()

    return Measurement(
        metric="recovery_s",
        unit="s",
        samples=(elapsed,),
        note=f"{open_sightings} open sightings adopted and repaired",
    )


async def run_harness(
    config: WorkloadConfig | None = None,
    *,
    data_dir: Path | None = None,
    probe_every: int = DEFAULT_PROBE_EVERY,
    include_startup: bool = True,
    include_recovery: bool = True,
    recovery_ticks: int = DEFAULT_RECOVERY_TICKS,
) -> HarnessReport:
    """Run every scenario and return the judged report.

    Startup runs first, before anything else has touched the data directory, so
    the figure is a genuinely cold start: an empty directory, migrations run
    from nothing. Running it after the load would measure a warm start over an
    existing schema and quietly report a better number than an install gets.

    ``include_startup`` / ``include_recovery`` exist because both build and tear
    down an entire application, which is seconds a fast in-suite smoke should
    not spend. Skipping one leaves its budget marked *not measured* rather than
    silently passed — :attr:`Verdict.measured` carries the difference.
    ``recovery_ticks`` trades the recovery figure's realism for run time the
    same way: fewer ticks means fewer open sightings to repair, so an in-suite
    smoke measures a smaller recovery than a qualification run does, and the
    measurement's note records how many sightings the number covers.
    """
    config = config if config is not None else WorkloadConfig()
    started = time.perf_counter()
    measurements: list[Measurement] = []
    if include_startup:
        measurements.append(await measure_startup(data_dir=data_dir))
    measurements.extend(await run_load(config, data_dir=data_dir, probe_every=probe_every))
    if include_recovery:
        measurements.append(await measure_recovery(data_dir=data_dir, ticks=recovery_ticks))
    return HarnessReport(
        measurements=tuple(measurements),
        environment=Environment.capture(),
        config=config,
        duration_s=time.perf_counter() - started,
    )


__all__ = [
    "DEFAULT_PROBE_EVERY",
    "PROBES",
    "Environment",
    "HarnessReport",
    "Verdict",
    "measure_recovery",
    "measure_startup",
    "run_harness",
    "run_load",
]
