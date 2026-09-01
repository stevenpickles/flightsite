"""The measurement primitives, which every budget verdict is computed from.

Cheap, pure tests: if :meth:`Measurement.statistic` is wrong then every figure
in ``docs/PERFORMANCE.md`` is wrong, and no amount of load-running would reveal
it.
"""

from __future__ import annotations

import pytest

from flightsite.perf.measure import MIB, Measurement, Statistic, percentile, rss_bytes


def test_percentile_is_nearest_rank_over_the_sorted_samples() -> None:
    samples = [5.0, 1.0, 4.0, 2.0, 3.0]
    assert percentile(samples, 0.0) == 1.0
    assert percentile(samples, 0.5) == 3.0
    # Nearest-rank clamps to the last element rather than interpolating past it.
    assert percentile(samples, 0.99) == 5.0
    assert percentile(samples, 1.0) == 5.0


def test_percentile_of_nothing_is_an_error_rather_than_a_zero() -> None:
    """A zero would read as a perfect score for a metric nobody measured."""
    with pytest.raises(ValueError, match="empty"):
        percentile([], 0.5)


def test_a_measurement_needs_samples() -> None:
    with pytest.raises(ValueError, match="no samples"):
        Measurement(metric="ingest_apply_ms", unit="ms", samples=())


def test_every_statistic_reads_the_distribution_it_names() -> None:
    measurement = Measurement(
        metric="ingest_apply_ms", unit="ms", samples=tuple(float(n) for n in range(1, 101))
    )
    assert measurement.count == 100
    assert measurement.statistic(Statistic.MIN) == 1.0
    assert measurement.statistic(Statistic.MAX) == 100.0
    assert measurement.statistic(Statistic.MEAN) == pytest.approx(50.5)
    assert measurement.statistic(Statistic.MEDIAN) == pytest.approx(50.5)
    assert measurement.statistic(Statistic.P95) == 96.0
    assert measurement.statistic(Statistic.P99) == 100.0


def test_the_summary_line_names_the_unit_and_the_sample_count() -> None:
    """The figure a reader copies into a report has to carry its own context."""
    measurement = Measurement(metric="ws_fanout_ms", unit="ms", samples=(1.0, 2.0, 3.0))
    summary = measurement.summary
    assert "median 2" in summary
    assert "ms" in summary
    assert "n=3" in summary


def test_resident_memory_is_a_plausible_reading_or_an_honest_none() -> None:
    """RSS is read from the platform, so the contract is "real or None".

    A wrong-but-present number is the failure mode worth guarding: the 1 GB
    budget is a hard gate, and a reader that silently returned zero would make
    it pass forever.
    """
    resident = rss_bytes()
    if resident is None:
        pytest.skip("no RSS source on this platform")
    # A Python process running this suite is tens of megabytes at the very
    # least, and nowhere near a terabyte. The bounds are deliberately absurd:
    # this is checking that the reader read *something real*, not asserting a
    # budget, which is the harness's job.
    assert 8 * MIB < resident < 1024 * 1024 * MIB
