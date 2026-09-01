"""The calibration scenarios ``docs/DATA_MODEL.md`` §9 sizes the product against.

§9 does not merely say "the database grows". It states two named receivers, the
traffic each carries, a per-row cost for every table, and a bottom line in
gigabytes per year — and then says, in as many words, that *"slice 050
(multi-year storage qualification) validates both scenarios synthetically."*
This module is that statement turned into data, so the qualification asserts
against the published arithmetic rather than against a number invented here.

The two scenarios
-----------------

**Scenario A** is the typical suburban receiver: ~1,500 sightings/day from ~750
unique airframes, predicted at 1.0-1.2 GB/year, so a three-year database is
3-4 GB. This is what an ordinary install actually looks like, and it is the one
this slice generates at full three-year scale.

**Scenario B** is the SPEC §5 design envelope: ~18,000 sightings/day from
~4,000 unique airframes, predicted at 12-14 GB/year — 36-42 GB over three
years. §9 is candid that this "fits commodity Pi 4 storage … but *not* a
16-32 GB card".

Why one budget covers both
--------------------------

The two predictions look unrelated until they are divided by their own traffic:

===========  ====================  =======================  ==================
Scenario     Predicted bytes/year  Sightings/year           Bytes per sighting
===========  ====================  =======================  ==================
A            1.0-1.2 GB            1,500 x 365 = 547,500     ~1,830-2,190
B            12-14 GB              18,000 x 365 = 6,570,000  ~1,830-2,130
===========  ====================  =======================  ==================

Both land on **~2 KB per sighting**, which is not a coincidence: a sighting and
its packed track and its handful of events dominate the total, and every other
table in §9 is rounding error beside them. That makes bytes-per-sighting the
scale-free form of the growth budget — one number that judges a fortnight of
Scenario A and three years of Scenario B on identical terms, and that does not
quietly pass merely because a run was short.

Units
-----

§9 states its totals in **GB**, and a growth figure is only comparable to the
document it is being checked against, so this module works in decimal
gigabytes (:data:`BYTES_PER_GB`, 10^9) and says so wherever it prints one.
Memory elsewhere in ``docs/PERFORMANCE.md`` is in MiB; the units differ because
the sources being compared against differ, and silently converting one into the
other would make the comparison wrong rather than tidy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: Decimal gigabyte. ``docs/DATA_MODEL.md`` §9 states its growth totals in GB,
#: and a qualification that answered in GiB would be off by 7% against the very
#: figures it exists to check.
BYTES_PER_GB: Final = 1_000_000_000

#: Days per year used to turn a per-day scenario into the per-year totals §9
#: quotes. §9 itself sizes with ``x 365``.
DAYS_PER_YEAR: Final = 365

#: ``receiver_metrics_raw`` sampling cadence, from
#: ``flightsite.receiver_metrics.sampler.DEFAULT_SAMPLE_INTERVAL_S`` (15 s,
#: deliberately not configurable). 5,760 samples a day, which is the number §9
#: multiplies the high-resolution window by.
METRIC_SAMPLES_PER_DAY: Final = 24 * 60 * 60 // 15


@dataclass(frozen=True, slots=True)
class Scenario:
    """One of ``docs/DATA_MODEL.md`` §9's calibration receivers.

    Every field is a figure §9 states or an immediate consequence of one. The
    generator reads this to decide how much traffic to synthesize; the growth
    check reads it to decide what the result should have cost.

    Args:
        name: stable id used on the command line and in reports.
        label: how §9 describes this receiver.
        sightings_per_day: §9's traffic figure.
        unique_aircraft_per_day: distinct airframes heard on a given day.
        new_aircraft_per_year: airframes never heard before, per year. Drives
            how much of each day's population is a first-ever contact and
            therefore how fast the ``aircraft`` table grows.
        events_per_sighting: mean ``sighting_events`` rows per sighting (§9
            sizes at ~3).
        activity_events_per_day: ``activity_events`` rows per day.
        alert_matches_per_day: ``alert_matches`` rows per day.
        predicted_gb_per_year: §9's stated range for the whole database.
    """

    name: str
    label: str
    sightings_per_day: int
    unique_aircraft_per_day: int
    new_aircraft_per_year: int
    events_per_sighting: float
    activity_events_per_day: int
    alert_matches_per_day: int
    predicted_gb_per_year: tuple[float, float]

    def __post_init__(self) -> None:
        if self.sightings_per_day < 1:
            raise ValueError("sightings_per_day must be at least 1")
        if self.unique_aircraft_per_day < 1:
            raise ValueError("unique_aircraft_per_day must be at least 1")
        if self.unique_aircraft_per_day > self.sightings_per_day:
            raise ValueError(
                "unique_aircraft_per_day cannot exceed sightings_per_day: an airframe "
                "cannot be seen on fewer sightings than once"
            )
        low, high = self.predicted_gb_per_year
        if not 0.0 < low <= high:
            raise ValueError("predicted_gb_per_year must be an ascending positive range")

    @property
    def sightings_per_year(self) -> int:
        """The row count §9 multiplies its per-row costs by."""
        return self.sightings_per_day * DAYS_PER_YEAR

    @property
    def new_aircraft_per_day(self) -> float:
        """First-ever contacts on an average day.

        A fraction, deliberately: Scenario A's 40,000 new airframes a year is
        ~110 a day, and rounding that to an integer per day would drift the
        yearly total by enough to matter over three years.
        """
        return self.new_aircraft_per_year / DAYS_PER_YEAR

    @property
    def predicted_bytes_per_sighting(self) -> tuple[float, float]:
        """§9's yearly prediction expressed per sighting (see module docstring)."""
        low, high = self.predicted_gb_per_year
        return (
            low * BYTES_PER_GB / self.sightings_per_year,
            high * BYTES_PER_GB / self.sightings_per_year,
        )

    def sightings_over(self, days: int) -> int:
        """Total sightings a run of ``days`` days should produce."""
        return self.sightings_per_day * days

    def predicted_bytes(self, days: int) -> tuple[float, float]:
        """§9's predicted database size after ``days`` days of this scenario."""
        low, high = self.predicted_gb_per_year
        years = days / DAYS_PER_YEAR
        return (low * BYTES_PER_GB * years, high * BYTES_PER_GB * years)


#: ``docs/DATA_MODEL.md`` §9, Scenario A: "typical suburban receiver".
#: 40k new airframes a year is §9's own ``aircraft (new)`` row.
SCENARIO_A: Final = Scenario(
    name="suburban",
    label="typical suburban receiver (docs/DATA_MODEL.md §9, Scenario A)",
    sightings_per_day=1_500,
    unique_aircraft_per_day=750,
    new_aircraft_per_year=40_000,
    events_per_sighting=3.0,
    activity_events_per_day=200,
    alert_matches_per_day=100,
    predicted_gb_per_year=(1.0, 1.2),
)

#: ``docs/DATA_MODEL.md`` §9, Scenario B: the SPEC §5 design envelope.
SCENARIO_B: Final = Scenario(
    name="envelope",
    label="SPEC §5 design envelope (docs/DATA_MODEL.md §9, Scenario B)",
    sightings_per_day=18_000,
    unique_aircraft_per_day=4_000,
    new_aircraft_per_year=200_000,
    events_per_sighting=3.0,
    activity_events_per_day=1_200,
    alert_matches_per_day=800,
    predicted_gb_per_year=(12.0, 14.0),
)

#: Both, in the order §9 presents them.
SCENARIOS: Final[tuple[Scenario, ...]] = (SCENARIO_A, SCENARIO_B)

_BY_NAME: Final[dict[str, Scenario]] = {scenario.name: scenario for scenario in SCENARIOS}


def scenario_for(name: str) -> Scenario:
    """The scenario called ``name``.

    Raises ``KeyError`` for an unknown id, so a typo on the command line fails
    loudly rather than quietly qualifying a receiver nobody described.
    """
    return _BY_NAME[name]


__all__ = [
    "BYTES_PER_GB",
    "DAYS_PER_YEAR",
    "METRIC_SAMPLES_PER_DAY",
    "SCENARIOS",
    "SCENARIO_A",
    "SCENARIO_B",
    "Scenario",
    "scenario_for",
]
