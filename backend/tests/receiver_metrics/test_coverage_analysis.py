"""The radio horizon, the window fold and the obstruction finder (slice 087).

All pure: :mod:`flightsite.receiver_metrics.coverage` takes stored cells and a
configured antenna height and returns numbers and sentences, so every rule
the API documents — the 4/3-Earth formula, the reference altitudes, the 60 %
threshold and the evidence minimums — is asserted here against hand-built
cells rather than through a database.
"""

from __future__ import annotations

import math

import pytest

from flightsite.receiver_metrics.coverage import (
    ALTITUDE_BANDS,
    FINDING_SHARE_THRESHOLD,
    MIN_FINDING_DAYS,
    MIN_FINDING_SAMPLES,
    BandRange,
    CoverageCell,
    band_horizons,
    compass_point,
    find_obstructions,
    qualifies,
    radio_horizon_nm,
    reduce_window,
)
from flightsite.receiver_metrics.model import RangeRecord

HIGH = 2
MID = 1
LOW = 0


def record(bucket: int, nm: float, at_ms: int = 1, icao: str = "abc123") -> RangeRecord:
    return RangeRecord(bearing_deg=bucket * 5.0 + 2.5, max_range_nm=nm, at_ms=at_ms, icao24=icao)


def well_observed(band: int, bucket: int, nm: float) -> CoverageCell:
    """A cell with exactly the evidence the finder asks for."""
    return CoverageCell(
        band=band,
        bearing_bucket=bucket,
        record=record(bucket, nm),
        samples=MIN_FINDING_SAMPLES,
        days=MIN_FINDING_DAYS,
    )


def ring(band: int, nm: float) -> dict[tuple[int, int], CoverageCell]:
    """Every sector of ``band`` well observed at ``nm``."""
    return {(band, bucket): well_observed(band, bucket, nm) for bucket in range(72)}


# ----------------------------------------------------------------- horizon


def test_the_horizon_is_the_4_3_earth_formula_in_nautical_miles() -> None:
    # 1.23 x (sqrt(25) + sqrt(25,000)) for a 25 ft mast and an airliner.
    assert radio_horizon_nm(25.0, 25_000.0) == pytest.approx(1.23 * (5.0 + math.sqrt(25_000.0)))
    assert radio_horizon_nm(25.0, 25_000.0) == pytest.approx(200.6, abs=0.1)


def test_a_taller_antenna_hears_further() -> None:
    low = radio_horizon_nm(10.0, 10_000.0)
    high = radio_horizon_nm(100.0, 10_000.0)
    assert low is not None and high is not None
    assert high > low


def test_an_unset_antenna_height_is_an_unknown_horizon() -> None:
    assert radio_horizon_nm(None, 25_000.0) is None
    assert band_horizons(None) == {0: None, 1: None, 2: None}


def test_a_negative_antenna_height_contributes_no_horizon_of_its_own() -> None:
    assert radio_horizon_nm(-300.0, 10_000.0) == pytest.approx(1.23 * 100.0)


def test_each_band_is_judged_at_its_reference_altitude() -> None:
    """Lower edge for the upper bands; a stated 3,000 ft floor for the bottom one."""
    assert [band.reference_ft for band in ALTITUDE_BANDS] == [3_000.0, 10_000.0, 25_000.0]
    horizons = band_horizons(0.0)
    assert horizons[LOW] == pytest.approx(1.23 * math.sqrt(3_000.0))
    assert horizons[MID] == pytest.approx(123.0)
    assert horizons[HIGH] == pytest.approx(1.23 * math.sqrt(25_000.0))


# ------------------------------------------------------------------ window


def test_the_window_fold_keeps_the_furthest_and_counts_days_and_samples() -> None:
    rows = [
        ("2026-09-01", BandRange(HIGH, record(8, 150.0, at_ms=1, icao="first"), samples=10)),
        ("2026-09-02", BandRange(HIGH, record(8, 190.0, at_ms=2, icao="best"), samples=12)),
        ("2026-09-03", BandRange(HIGH, record(8, 120.0, at_ms=3, icao="later"), samples=5)),
        ("2026-09-03", BandRange(LOW, record(8, 40.0), samples=2)),
    ]

    cells = reduce_window(rows)

    high = cells[(HIGH, 8)]
    assert high.record is not None
    assert (high.record.icao24, high.record.max_range_nm) == ("best", 190.0)
    assert (high.samples, high.days) == (27, 3)
    assert (cells[(LOW, 8)].samples, cells[(LOW, 8)].days) == (2, 1)
    assert (MID, 8) not in cells


def test_an_empty_cell_has_no_share_rather_than_a_zero_one() -> None:
    assert CoverageCell(band=HIGH, bearing_bucket=0).share_of(200.0) is None
    assert well_observed(HIGH, 0, 100.0).share_of(None) is None
    assert well_observed(HIGH, 0, 100.0).share_of(200.0) == pytest.approx(0.5)


def test_a_share_above_one_is_reported_not_clamped() -> None:
    assert well_observed(LOW, 0, 120.0).share_of(80.0) == pytest.approx(1.5)


# ---------------------------------------------------------------- findings


def test_a_well_observed_short_sector_qualifies() -> None:
    assert qualifies(well_observed(HIGH, 0, 100.0), 200.0)


@pytest.mark.parametrize(
    ("samples", "days"),
    [
        (MIN_FINDING_SAMPLES - 1, MIN_FINDING_DAYS),
        (MIN_FINDING_SAMPLES * 10, MIN_FINDING_DAYS - 1),
    ],
)
def test_a_sector_without_enough_evidence_never_qualifies(samples: int, days: int) -> None:
    cell = CoverageCell(
        band=HIGH, bearing_bucket=0, record=record(0, 10.0), samples=samples, days=days
    )
    assert not qualifies(cell, 200.0)


def test_the_threshold_is_strictly_below_sixty_percent() -> None:
    assert FINDING_SHARE_THRESHOLD == 0.60
    assert not qualifies(well_observed(HIGH, 0, 120.0), 200.0)
    assert qualifies(well_observed(HIGH, 0, 119.9), 200.0)


def test_no_antenna_height_means_no_findings() -> None:
    cells = ring(HIGH, 20.0)
    assert find_obstructions(cells, band_horizons(None)) == []


def test_sectors_with_no_data_are_never_findings() -> None:
    horizons = band_horizons(25.0)
    assert find_obstructions({}, horizons) == []


def test_adjacent_short_sectors_merge_into_one_sentence() -> None:
    horizons = band_horizons(25.0)
    horizon = horizons[HIGH]
    assert horizon is not None
    cells = ring(HIGH, horizon * 0.9)
    # 40-60 degrees: buckets 8, 9, 10, 11 — the best of them reaches 58 %.
    for bucket, share in ((8, 0.40), (9, 0.58), (10, 0.50), (11, 0.45)):
        cells[(HIGH, bucket)] = well_observed(HIGH, bucket, horizon * share)

    [finding] = find_obstructions(cells, horizons)

    assert (finding.first_bucket, finding.last_bucket) == (8, 11)
    assert (finding.start_deg, finding.end_deg) == (40.0, 60.0)
    assert finding.compass == "NE"
    assert finding.share == pytest.approx(0.58)
    assert finding.samples == 4 * MIN_FINDING_SAMPLES
    assert finding.days == MIN_FINDING_DAYS
    assert finding.message == (
        "NE 40\u201360° reaches 58 % of the radio horizon above 25,000 ft — likely obstruction"
    )


def test_a_run_through_north_stays_one_finding() -> None:
    horizons = band_horizons(25.0)
    horizon = horizons[MID]
    assert horizon is not None
    cells = ring(MID, horizon * 0.95)
    for bucket in (70, 71, 0, 1):
        cells[(MID, bucket)] = well_observed(MID, bucket, horizon * 0.3)

    [finding] = find_obstructions(cells, horizons)

    assert (finding.first_bucket, finding.last_bucket) == (70, 1)
    assert (finding.start_deg, finding.end_deg) == (350.0, 10.0)
    assert finding.compass == "N"
    assert finding.message.startswith("N 350\u201310° reaches 30 % of the radio horizon between")


def test_an_evidence_gap_splits_a_run() -> None:
    horizons = band_horizons(25.0)
    horizon = horizons[HIGH]
    assert horizon is not None
    cells = ring(HIGH, horizon * 0.9)
    for bucket in (20, 21, 23, 24):
        cells[(HIGH, bucket)] = well_observed(HIGH, bucket, horizon * 0.3)
    # Bucket 22 is as short, but seen on too few days to say so.
    cells[(HIGH, 22)] = CoverageCell(
        band=HIGH, bearing_bucket=22, record=record(22, horizon * 0.3), samples=500, days=1
    )

    findings = find_obstructions(cells, horizons)

    assert [(f.first_bucket, f.last_bucket) for f in findings] == [(20, 21), (23, 24)]


def test_a_receiver_short_everywhere_reads_as_a_receiver_wide_limit() -> None:
    horizons = band_horizons(25.0)
    horizon = horizons[HIGH]
    assert horizon is not None

    [finding] = find_obstructions(ring(HIGH, horizon * 0.4), horizons)

    assert finding.sector_count == 72
    assert "receiver-wide limit" in finding.message


def test_findings_list_the_highest_band_first() -> None:
    horizons = band_horizons(25.0)
    cells: dict[tuple[int, int], CoverageCell] = {}
    for band in (LOW, HIGH):
        horizon = horizons[band]
        assert horizon is not None
        cells.update(ring(band, horizon * 0.9))
        cells[(band, 30)] = well_observed(band, 30, horizon * 0.2)

    assert [f.band.key for f in find_obstructions(cells, horizons)] == ["above_25k", "below_10k"]


@pytest.mark.parametrize(
    ("bearing", "name"),
    [(0.0, "N"), (50.0, "NE"), (359.0, "N"), (191.0, "S"), (292.5, "WNW")],
)
def test_compass_points(bearing: float, name: str) -> None:
    assert compass_point(bearing) == name
