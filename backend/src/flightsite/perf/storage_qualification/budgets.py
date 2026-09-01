"""The multi-year storage budget table (SPEC §86, ``docs/PERFORMANCE.md`` §7).

SPEC §86 lists nine things a multi-year qualification must verify: *database
growth; query responsiveness; index behavior; downsampling; retention pruning;
backup size; restore behavior; Pi storage I/O; analytics performance.* Every
row below answers one of them, and :data:`STORAGE_BUDGETS` is the single source
of truth in the same way ``flightsite.perf.budgets.BUDGETS`` is for slice 049 —
``docs/PERFORMANCE.md`` renders it and ``tests/perf/storage/test_docs.py``
checks the rendering still matches.

Why a second table rather than more rows in the first
-----------------------------------------------------

Slice 049's table is a contract with *its own harness*:
``tests/perf/test_harness.py`` asserts that every budget in ``BUDGETS`` is
measured by a run of that harness, with process memory the single documented
exception. A backup duration or a vacuum cost has no meaning in a sixty-tick
load run, so adding those rows to ``BUDGETS`` would either break that assertion
or force it to be weakened into something that no longer notices a metric
quietly ceasing to be collected. Two tables, each complete with respect to the
harness that fills it, keeps both assertions strict.

The types are 049's — :class:`~flightsite.perf.budgets.Budget`,
:class:`~flightsite.perf.budgets.GateKind`,
:class:`~flightsite.perf.budgets.Direction`, the ``CI_HEADROOM`` convention —
because the hybrid gate model is the same model, and a reader who has
understood §1 of ``docs/PERFORMANCE.md`` should not have to learn a second one.

What is hard here, and what is not
----------------------------------

The hard gates are the three claims that make every other figure meaningful or
meaningless:

* **The dataset is real.** ``dataset_days`` is this table's ``live_population``:
  a growth figure from a run that did not actually cover the history it claims
  is arithmetic about nothing.
* **High-resolution telemetry stays bounded.** ADR-0009's entire promise is that
  ``receiver_metrics_raw`` is a fixed-size window rather than a growing table.
  If that fails, multi-year storage is unbounded no matter what any latency
  says, and it fails identically on any hardware — so it is gated everywhere.
* **Downsampling loses nothing.** ADR-0009 again: *"downsampling/pruning can
  never lose a record."* Pruning a day whose summary was never written is data
  loss, and no budget on how *fast* it pruned would notice.

Everything else is a **reference** budget, and deliberately so. Latency,
vacuum, backup and restore are all dominated by storage hardware; slice 049's
§5.3 promotion rule says a reference budget becomes a hard gate when a
Raspberry Pi 4 baseline has been recorded for it, and none has. Qualifying
``db_read_ms`` and ``analytics_query_ms`` at multi-year scale — which is what
049's own table says slice 050 exists to do — is not the same act as promoting
them, and doing the second on a developer machine would be exactly the dressed-
up guess §1 warns against.
"""

from __future__ import annotations

from typing import Final

from flightsite.perf.budgets import CI_HEADROOM, NO_HEADROOM, Budget, Direction, GateKind
from flightsite.perf.measure import Statistic

#: Days of high-resolution receiver telemetry the product retains by default
#: (``config.RetentionSettings.high_res_metric_days``, ADR-0009's 14-day
#: default). The budget below allows a little more than this because the prune
#: boundary is rounded down to an hour start
#: (``ReceiverMetricsService.run_maintenance``), so a correct prune can leave up
#: to an extra hour of raw rows standing.
HIGH_RES_WINDOW_DAYS: Final = 14

#: The slack added to :data:`HIGH_RES_WINDOW_DAYS` for that hour rounding, plus
#: room for the boundary sample itself. One day is generous against a 14-day
#: window and still an order of magnitude tighter than "unbounded", which is the
#: failure this gate exists to catch.
HIGH_RES_WINDOW_SLACK_DAYS: Final = 1

#: Bytes of database per sighting, derived in ``scenarios.py`` from
#: ``docs/DATA_MODEL.md`` §9's own predictions. Both §9 scenarios land within a
#: few percent of 2 KB per sighting, which is what makes this the scale-free
#: form of the growth budget.
BYTES_PER_SIGHTING_BUDGET: Final = 2_000.0

#: The table. Hard gates first, then the reference budgets, as
#: ``docs/PERFORMANCE.md`` presents them.
STORAGE_BUDGETS: Final[tuple[Budget, ...]] = (
    Budget(
        metric="dataset_days",
        title="History actually generated",
        spec_metric="realistic synthetic multi-year dataset",
        unit="days",
        value=1.0,
        statistic=Statistic.MIN,
        direction=Direction.FLOOR,
        gate=GateKind.HARD,
        ci_headroom=NO_HEADROOM,
        rationale=(
            "The floor is one day because the figure is compared against whatever span the "
            "run was asked for; what this gate rejects is a run that generated nothing and "
            "then reported a flattering bytes-per-sighting from an empty file. It is this "
            "table's live_population: every other number here is arithmetic over the dataset, "
            "so a dataset that does not exist makes all of them meaningless rather than good."
        ),
    ),
    Budget(
        metric="metrics_raw_days",
        title="High-resolution telemetry window after maintenance",
        spec_metric="retention pruning",
        unit="days",
        value=float(HIGH_RES_WINDOW_DAYS + HIGH_RES_WINDOW_SLACK_DAYS),
        statistic=Statistic.MAX,
        direction=Direction.CEILING,
        gate=GateKind.HARD,
        ci_headroom=NO_HEADROOM,
        rationale=(
            "ADR-0009 and SPEC §64: receiver_metrics_raw is a rolling window, not a growing "
            "table, and it is the one high-frequency table that would otherwise dominate a Pi's "
            "disk within months. Measured as the span between the oldest and newest raw sample "
            "after a real ReceiverMetricsService.run_maintenance() pass over a dataset "
            "deliberately seeded with a longer backlog. No headroom: this is a row count "
            "against a configured window, and a busy machine does not make a window wider."
        ),
        also_enforced_by=("tests/receiver_metrics/",),
    ),
    Budget(
        metric="downsample_coverage",
        title="Summaries surviving the prune",
        spec_metric="downsampling",
        unit="fraction of pruned days",
        value=1.0,
        statistic=Statistic.MIN,
        direction=Direction.FLOOR,
        gate=GateKind.HARD,
        ci_headroom=NO_HEADROOM,
        rationale=(
            "ADR-0009: 'downsampling/pruning can never lose a record.' Every day whose "
            "high-resolution rows have been pruned must still be represented by hourly and "
            "daily summaries, or the prune destroyed history rather than compacting it. A "
            "budget on how fast the prune ran would not notice this, which is why it is "
            "measured separately and gated at 100%."
        ),
    ),
    Budget(
        metric="db_bytes_per_sighting",
        title="Database growth per sighting",
        spec_metric="database growth",
        unit="bytes/sighting",
        value=BYTES_PER_SIGHTING_BUDGET,
        statistic=Statistic.MAX,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=NO_HEADROOM,
        rationale=(
            "docs/DATA_MODEL.md §9's growth arithmetic, in its scale-free form: both published "
            "scenarios predict ~2 KB of database per sighting, so one budget judges a fortnight "
            "of Scenario A and three years of Scenario B alike. Reference rather than hard "
            "because the consequence of missing it is a storage-sizing correction in the install "
            "documentation and possibly a tiered-track ADR (§9 names that lever explicitly), not "
            "a broken build. No headroom: bytes on disk do not vary with how loaded the machine is."
        ),
    ),
    Budget(
        metric="history_query_ms",
        title="History and sightings queries at multi-year scale",
        spec_metric="query responsiveness",
        unit="ms",
        value=500.0,
        statistic=Statistic.P95,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "Slice 049's db_read_ms budget, restated over a multi-year database instead of a "
            "sixty-tick one — which is the qualification that budget's own rationale defers to "
            "this slice. Covers the documented /api/v1/sightings and /api/v1/aircraft surfaces "
            "including the deep-pagination and unindexed-sort paths that only bite at scale."
        ),
        also_enforced_by=(
            "tests/api/test_sightings_perf.py",
            "tests/api/test_aircraft_history_perf.py",
        ),
    ),
    Budget(
        metric="analytics_scale_ms",
        title="Analytics presets at multi-year scale",
        spec_metric="analytics performance",
        unit="ms",
        value=500.0,
        statistic=Statistic.P95,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "Slice 049's analytics_query_ms, restated across every documented preset and "
            "endpoint on a multi-year dataset. The since-T0 presets are the interesting ones: "
            "most analytics reads are served from daily rollups whose row count scales with "
            "days rather than sightings, but a few still fold over the sightings table itself."
        ),
        also_enforced_by=("tests/analytics/test_perf.py",),
    ),
    Budget(
        metric="rarity_query_ms",
        title="Rarity lookup at multi-year scale",
        spec_metric="query responsiveness",
        unit="ms",
        value=500.0,
        statistic=Statistic.P95,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "SPEC §44's rarity read, measured separately from the other analytics because its "
            "cost shape is different: it filters and sorts the aircraft table on sighting_count, "
            "which no index covers, so it grows with the number of distinct airframes ever heard "
            "rather than with the number of sightings. Multi-year is precisely when those two "
            "quantities stop being similar."
        ),
    ),
    Budget(
        metric="retention_pass_ms",
        title="One maintenance pass over a multi-year database",
        spec_metric="retention pruning",
        unit="ms",
        value=5_000.0,
        statistic=Statistic.MAX,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "Downsampling plus the chunked raw prune, which is the only unbounded catch-up path "
            "in the maintenance cycle (MetricsRepository.prune_raw walks 2,000-row transactions). "
            "The cycle runs hourly, so five seconds leaves it three orders of magnitude of room; "
            "the budget exists to catch a pass whose cost scales with total history rather than "
            "with the backlog it has to clear."
        ),
    ),
    Budget(
        metric="vacuum_s",
        title="Full VACUUM of a multi-year database",
        spec_metric="Pi storage I/O",
        unit="s",
        value=300.0,
        statistic=Statistic.MAX,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "VACUUM rewrites the whole file and holds the single writer lock for the duration "
            "(flightsite.maintenance.service), so on a multi-gigabyte database it is the longest "
            "any write can be stalled. Reference because the number is almost entirely the "
            "storage device: five minutes is a plausible ceiling for a few gigabytes on Pi 4 "
            "SD-card I/O, and the real figure needs that hardware."
        ),
    ),
    Budget(
        metric="backup_create_s_per_gb",
        title="Backup creation, per gigabyte",
        spec_metric="backup size",
        unit="s/GB",
        value=180.0,
        statistic=Statistic.MAX,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "Stated per gigabyte because the cost is linear in database size and the whole point "
            "of a multi-year qualification is that the database is no longer small. Creating a "
            "backup is three full passes over the data (VACUUM INTO, then SHA-256 of the "
            "snapshot, then gzip into the archive), so the budget is against a Pi 4 reading and "
            "writing its own storage three times over."
        ),
    ),
    Budget(
        metric="backup_restore_s_per_gb",
        title="Restore, per gigabyte",
        spec_metric="restore behavior",
        unit="s/GB",
        value=120.0,
        statistic=Statistic.MAX,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=CI_HEADROOM,
        rationale=(
            "Decompress, hash and write the snapshot, then rename it into place — two passes "
            "rather than creation's three, which is why the budget is lower. docs/BACKUP.md "
            "makes restore an operator action taken with FlightSite stopped, so this is downtime "
            "and worth knowing honestly before a Pi owner needs it."
        ),
    ),
    Budget(
        metric="backup_size_ratio",
        title="Archive size against the live database",
        spec_metric="backup size",
        unit="fraction of database bytes",
        value=1.0,
        statistic=Statistic.MAX,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=NO_HEADROOM,
        rationale=(
            "A gzipped archive of a compacted snapshot must be smaller than the database it came "
            "from, or something has gone wrong with either the compaction or the compression. "
            "The interesting question this answers for an operator is how much room a backup "
            "needs beside the live data: docs/BACKUP.md says nothing rotates them. No headroom, "
            "because a ratio does not care how busy the machine was."
        ),
    ),
    Budget(
        metric="wal_bytes_mib",
        title="Write-ahead log after sustained history writes",
        spec_metric="Pi storage I/O",
        unit="MiB",
        value=64.0,
        statistic=Statistic.MAX,
        direction=Direction.CEILING,
        gate=GateKind.REFERENCE,
        ci_headroom=NO_HEADROOM,
        rationale=(
            "The maintenance cycle truncates the WAL once it passes 16 MiB "
            "(maintenance.policy.WAL_CHECKPOINT_THRESHOLD_BYTES), so a log several times that "
            "size means checkpointing is not keeping up with the write volume. Measured after "
            "bulk history writes, which is a far harsher WAL workload than 1 Hz ingestion."
        ),
    ),
)

_BY_METRIC: Final[dict[str, Budget]] = {budget.metric: budget for budget in STORAGE_BUDGETS}


def storage_budget_for(metric: str) -> Budget:
    """The storage budget named ``metric``.

    Raises ``KeyError`` for an unknown id, so a typo in a scenario fails loudly
    instead of silently measuring something nothing gates.
    """
    return _BY_METRIC[metric]


def hard_storage_budgets() -> tuple[Budget, ...]:
    """Just the gates that fail the suite."""
    return tuple(budget for budget in STORAGE_BUDGETS if budget.hard)


def reference_storage_budgets() -> tuple[Budget, ...]:
    """Just the trend-tracked reference budgets."""
    return tuple(budget for budget in STORAGE_BUDGETS if not budget.hard)


__all__ = [
    "BYTES_PER_SIGHTING_BUDGET",
    "HIGH_RES_WINDOW_DAYS",
    "HIGH_RES_WINDOW_SLACK_DAYS",
    "STORAGE_BUDGETS",
    "hard_storage_budgets",
    "reference_storage_budgets",
    "storage_budget_for",
]
