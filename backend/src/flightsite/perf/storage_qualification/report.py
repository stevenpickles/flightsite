"""The qualification report: measurements, verdicts, and the printed table.

Shaped deliberately like :class:`flightsite.perf.harness.HarnessReport`, and
reusing its :class:`~flightsite.perf.harness.Verdict`, because the two reports
are read by the same person for the same reason. What differs is only what is
being judged: slice 049 reports one load run against
:data:`~flightsite.perf.budgets.BUDGETS`, and this reports one multi-year
dataset against :data:`~flightsite.perf.storage_qualification.budgets.STORAGE_BUDGETS`.

Findings
--------

One thing this report carries that 049's does not: a list of **findings**.
SPEC §86 asks a qualification to *verify* nine properties, and the useful
output of verifying something is not only a pass or a fail — it is the sentence
explaining what was seen. A row that reads ``db_bytes_per_sighting 3617 over``
tells an operator that storage costs more than the documents predict; it does
not tell them that the cause is overflow pages under a 4 KiB page size, which
is the part somebody can act on. Findings are where that sentence goes, and
:func:`~.qualify.run_qualification` derives them from the measurements rather
than from a human writing prose into a document that then drifts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from flightsite.perf.harness import Environment, Verdict
from flightsite.perf.measure import Measurement, Statistic
from flightsite.perf.storage_qualification.budgets import STORAGE_BUDGETS
from flightsite.perf.storage_qualification.generator import GenerationResult


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """One timed request against the multi-year dataset.

    Kept beside the aggregated :class:`~flightsite.perf.measure.Measurement`
    because the aggregate answers "is the surface fast enough" and this answers
    "which query is the slow one" — and at multi-year scale those have
    different answers for different reasons, which is exactly what an index or
    a missing whole-history shortcut looks like from the outside.

    Args:
        metric: which budget this probe feeds.
        label: a short human name for the query.
        path: the URL that was requested.
        samples_ms: every timing taken for it.
    """

    metric: str
    label: str
    path: str
    samples_ms: tuple[float, ...]

    @property
    def median_ms(self) -> float:
        ordered = sorted(self.samples_ms)
        return ordered[len(ordered) // 2]

    @property
    def max_ms(self) -> float:
        return max(self.samples_ms)


@dataclass(frozen=True, slots=True)
class StorageReport:
    """Everything one qualification run measured, and how it judged.

    Args:
        measurements: one per metric collected.
        generation: what the synthetic history cost to build and what it holds.
        probes: per-query timings behind the latency measurements.
        findings: derived observations worth a human reading.
        environment: the machine.
        duration_s: wall-clock time for the whole qualification.
    """

    measurements: tuple[Measurement, ...]
    generation: GenerationResult
    probes: tuple[ProbeResult, ...]
    findings: tuple[str, ...]
    environment: Environment
    duration_s: float

    def measurement(self, metric: str) -> Measurement | None:
        """The measurement for ``metric``, or ``None`` if not collected."""
        for measurement in self.measurements:
            if measurement.metric == metric:
                return measurement
        return None

    def verdicts(self) -> tuple[Verdict, ...]:
        """Every storage budget, judged against this run."""
        return tuple(Verdict(budget, self.measurement(budget.metric)) for budget in STORAGE_BUDGETS)

    def failures(self) -> tuple[Verdict, ...]:
        """Hard gates this run did not meet."""
        return tuple(
            verdict
            for verdict in self.verdicts()
            if verdict.budget.hard and verdict.measured and not verdict.passed
        )

    def overruns(self) -> tuple[Verdict, ...]:
        """Reference budgets this run exceeded.

        These do not fail anything — that is what makes them reference budgets
        — but they are the rows a qualification exists to surface, so they are
        addressable rather than buried in the table.
        """
        return tuple(
            verdict
            for verdict in self.verdicts()
            if not verdict.budget.hard and verdict.measured and not verdict.passed
        )

    @property
    def passed(self) -> bool:
        """True when every hard gate that was measured held."""
        return not self.failures()

    def slowest_probes(self, limit: int = 10) -> tuple[ProbeResult, ...]:
        """The slowest queries by median, worst first."""
        return tuple(sorted(self.probes, key=lambda probe: -probe.median_ms)[:limit])

    def format_table(self) -> str:
        """The report as a table, for the CLI and for pasting into a doc.

        ASCII only, for the same reason slice 049's is: this gets printed to
        whatever console the machine being qualified happens to have.
        """
        generation = self.generation
        header = (
            f"{'metric':<26} {'gate':<10} {'stat':<7} {'observed':>12} "
            f"{'budget':>10} {'bound':>12} {'unit':<26} {'result':<8}"
        )
        lines = [
            f"FlightSite storage qualification - {self.environment.platform}",
            f"Python {self.environment.python} | {generation.config.scenario.name} scenario "
            f"| {generation.days} days | {generation.sightings} sightings "
            f"| {generation.aircraft} airframes | {self.duration_s:.1f}s wall",
            f"database {generation.db_bytes / 1e9:.3f} GB "
            f"| {generation.bytes_per_sighting:.0f} bytes/sighting "
            f"| {generation.mean_track_points:.1f} points/track "
            f"| page size {generation.page_size}",
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
                shown = f"{observed:.4g}"
                result = "pass" if verdict.passed else ("FAIL" if budget.hard else "over")
            lines.append(
                f"{budget.metric:<26} {budget.gate.value:<10} "
                f"{budget.statistic.value:<7} {shown:>12} {budget.value:>10.4g} "
                f"{budget.asserted:>12.4g} {budget.unit:<26} {result:<8}"
            )

        lines.append("")
        lines.append("per-table growth (table and its indexes)")
        lines.append(f"{'table':<30} {'rows':>12} {'bytes':>14} {'B/row':>10}")
        lines.append("-" * 68)
        for entry in generation.growth:
            lines.append(
                f"{entry.table:<30} {entry.rows:>12} {entry.bytes:>14} {entry.bytes_per_row:>10.0f}"
            )

        slowest = self.slowest_probes()
        if slowest:
            lines.append("")
            lines.append("slowest queries (median of repeats)")
            lines.append(f"{'query':<44} {'median ms':>10} {'max ms':>10}")
            lines.append("-" * 66)
            for probe in slowest:
                lines.append(f"{probe.label:<44} {probe.median_ms:>10.1f} {probe.max_ms:>10.1f}")

        if self.findings:
            lines.append("")
            lines.append("findings")
            for finding in self.findings:
                lines.append(f"  * {finding}")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serializable form, for trend tracking across runs."""
        generation = self.generation
        return {
            "environment": {
                "platform": self.environment.platform,
                "python": self.environment.python,
                "processor": self.environment.processor,
            },
            "scenario": {
                "name": generation.config.scenario.name,
                "label": generation.config.scenario.label,
                "sightings_per_day": generation.config.scenario.sightings_per_day,
                "days": generation.days,
            },
            "dataset": {
                "sightings": generation.sightings,
                "aircraft": generation.aircraft,
                "tracks": generation.tracks,
                "track_points": generation.track_points,
                "mean_track_points": generation.mean_track_points,
                "db_bytes": generation.db_bytes,
                "wal_bytes": generation.wal_bytes,
                "page_size": generation.page_size,
                "bytes_per_sighting": generation.bytes_per_sighting,
                "generate_s": generation.duration_s,
                "rollup_s": generation.rollup_s,
                "rollup_days": generation.rollup_days,
            },
            "growth": {
                entry.table: {
                    "rows": entry.rows,
                    "bytes": entry.bytes,
                    "bytes_per_row": entry.bytes_per_row,
                }
                for entry in generation.growth
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
            "probes": [
                {
                    "metric": probe.metric,
                    "label": probe.label,
                    "path": probe.path,
                    "median_ms": probe.median_ms,
                    "max_ms": probe.max_ms,
                }
                for probe in self.probes
            ],
            "findings": list(self.findings),
        }


__all__ = ["ProbeResult", "StorageReport"]
