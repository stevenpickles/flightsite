"""The calibration scenarios must keep saying what ``docs/DATA_MODEL.md`` §9 says.

§9 is the published growth arithmetic, and :mod:`.scenarios` is a transcription
of it. A transcription that drifts is worse than no transcription: the
qualification would go on reporting "within budget" against numbers the
document no longer contains. These tests pin the transcription to the document
and check the arithmetic derived from it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flightsite.perf.storage_qualification.scenarios import (
    BYTES_PER_GB,
    DAYS_PER_YEAR,
    METRIC_SAMPLES_PER_DAY,
    SCENARIO_A,
    SCENARIO_B,
    SCENARIOS,
    Scenario,
    scenario_for,
)
from flightsite.receiver_metrics.sampler import DEFAULT_SAMPLE_INTERVAL_S

#: backend/tests/perf/storage/test_scenarios.py -> repo root.
DATA_MODEL = Path(__file__).resolve().parents[4] / "docs" / "DATA_MODEL.md"


@pytest.fixture(scope="module")
def document() -> str:
    assert DATA_MODEL.exists(), f"{DATA_MODEL} is missing"
    return DATA_MODEL.read_text(encoding="utf-8")


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_each_scenarios_traffic_appears_in_the_document(scenario: Scenario, document: str) -> None:
    """The sightings-per-day figure is §9's, not one invented here."""
    rendered = f"{scenario.sightings_per_day:,}"
    compact = str(scenario.sightings_per_day)
    assert rendered in document or compact in document or f"{compact[:2]}k" in document, (
        f"{scenario.name}'s {scenario.sightings_per_day} sightings/day is not in DATA_MODEL.md §9"
    )


def test_the_documented_yearly_predictions_are_the_ones_encoded() -> None:
    """§9's two bottom lines, verbatim: 1.0-1.2 GB and 12-14 GB per year."""
    assert SCENARIO_A.predicted_gb_per_year == (1.0, 1.2)
    assert SCENARIO_B.predicted_gb_per_year == (12.0, 14.0)


def test_both_scenarios_predict_about_two_kilobytes_a_sighting() -> None:
    """The claim ``budgets.py`` rests its scale-free growth budget on.

    If this stopped holding, one budget could no longer judge both scenarios
    and ``db_bytes_per_sighting`` would have to become two numbers. It is
    asserted rather than assumed because the whole design of that budget
    depends on it.
    """
    for scenario in SCENARIOS:
        low, high = scenario.predicted_bytes_per_sighting
        assert 1_700 <= low <= 2_300, f"{scenario.name} predicts {low:.0f} bytes/sighting"
        assert 1_700 <= high <= 2_300, f"{scenario.name} predicts {high:.0f} bytes/sighting"


def test_the_two_scenarios_agree_with_each_other_within_a_few_percent() -> None:
    """The coincidence that makes one budget legitimate, stated as a bound."""
    a_low, a_high = SCENARIO_A.predicted_bytes_per_sighting
    b_low, b_high = SCENARIO_B.predicted_bytes_per_sighting
    a_mid = (a_low + a_high) / 2
    b_mid = (b_low + b_high) / 2
    assert abs(a_mid - b_mid) / a_mid < 0.10


def test_yearly_totals_follow_from_the_daily_traffic() -> None:
    """``sightings_per_year`` is §9's own ``x 365``."""
    assert SCENARIO_A.sightings_per_year == 1_500 * DAYS_PER_YEAR
    assert SCENARIO_B.sightings_per_year == 18_000 * DAYS_PER_YEAR


def test_predicted_bytes_scale_with_the_span_requested() -> None:
    """Three years of Scenario A is §9's "a 3-year database is ~3-4 GB"."""
    low, high = SCENARIO_A.predicted_bytes(3 * DAYS_PER_YEAR)
    assert 2.9 <= low / BYTES_PER_GB <= 3.1
    assert 3.5 <= high / BYTES_PER_GB <= 3.7


def test_new_airframes_per_day_is_a_fraction() -> None:
    """Rounding 40,000 a year to an integer per day would drift over 3 years.

    109.6 a day rounded to 110 is 146 extra airframes a year; rounded to 109 it
    is 219 too few. Over three years either error is thousands of rows in the
    table the rarity query scans.
    """
    assert SCENARIO_A.new_aircraft_per_day == pytest.approx(40_000 / 365)
    assert not float(SCENARIO_A.new_aircraft_per_day).is_integer()


def test_the_metric_cadence_matches_the_sampler() -> None:
    """5,760 samples a day is 15-second sampling, and the sampler owns that.

    §9 multiplies the retention window by this number, so if the sampler's
    cadence ever changed, §9's ``receiver_metrics_raw`` row count and this
    module's would both be wrong — and this is where that is noticed.
    """
    assert int(24 * 60 * 60 / DEFAULT_SAMPLE_INTERVAL_S) == METRIC_SAMPLES_PER_DAY
    assert METRIC_SAMPLES_PER_DAY == 5_760


def test_lookup_by_name_rejects_a_typo() -> None:
    """A misspelled ``--scenario`` must fail loudly, not qualify something else."""
    assert scenario_for("suburban") is SCENARIO_A
    assert scenario_for("envelope") is SCENARIO_B
    with pytest.raises(KeyError):
        scenario_for("subrban")


def test_a_scenario_cannot_describe_an_impossible_receiver() -> None:
    """More unique airframes than sightings is not a receiver, it is a bug."""
    with pytest.raises(ValueError, match="cannot exceed"):
        Scenario(
            name="broken",
            label="",
            sightings_per_day=10,
            unique_aircraft_per_day=20,
            new_aircraft_per_year=1,
            events_per_sighting=1.0,
            activity_events_per_day=1,
            alert_matches_per_day=1,
            predicted_gb_per_year=(1.0, 2.0),
        )
