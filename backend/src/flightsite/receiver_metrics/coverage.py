"""Coverage by bearing and altitude band, and the obstruction finder (slice 087).

Issue #230 asks a question the slice-033 polar plot cannot answer: *is that
short sector a hill, or just an empty sky?* ``range_by_bearing_daily`` keeps
the furthest aircraft per 5° sector regardless of altitude, so a sector where
the receiver only ever hears light aircraft at 5,000 ft looks exactly like one
where a ridge cuts off airliners at cruise. Splitting the same record by
altitude band, and comparing each band with the radio horizon an aircraft at
that altitude *could* be heard to, is what separates the two.

Bands
-----

Three bands by **barometric** altitude (:data:`ALTITUDE_BANDS`): below
10,000 ft, 10,000 to 25,000 ft, and 25,000 ft and above — the low/medium/high
split ``docs/design/080-feature-program.md`` §4 names. Barometric because it
is the altitude every aircraft reports and the one the map shows; an aircraft
with **no** barometric altitude (on the ground, or a decoder that reported
none) is in no band and is not counted, because an unknown altitude is not
zero (``docs/API.md`` §2.7) and guessing a band for it would put a taxiing
aircraft into the low-band horizon comparison. Edges are half-open: exactly
10,000 ft is the middle band and exactly 25,000 ft is the high band.

What a cell records
-------------------

One cell is (receiver-local day, sector, band). It keeps the furthest
detection with the moment and airframe that set it — the same indivisible
:class:`~flightsite.receiver_metrics.model.RangeRecord` the unbanded table
keeps, compared with the same
:func:`~flightsite.receiver_metrics.model.better_range` — plus a
``samples`` count: how many receiver samples (one per ~15 s) saw anything in
the cell. The count is the evidence the obstruction finder weighs.

The sampler produces one :class:`BandRange` per occupied cell per sample with
``samples=1``; the service folds them per day with :func:`merge_band_range`
between flushes, and the repository folds each flush into the stored row the
same way in SQL. Because the fold is "keep the further record, add the
counts", the order the folds happen in does not matter.

The radio horizon
-----------------

How far an aircraft *could* be heard is set by the curvature of the Earth
before it is set by anything about the receiver. With standard atmospheric
refraction (the 4/3-Earth-radius model), the line-of-sight distance between
an antenna ``h₁`` feet up and an aircraft ``h₂`` feet up is

    d ≈ 1.23 x (√h₁ + √h₂)   nautical miles

(:func:`radio_horizon_nm`). ``h₁`` is ``receiver.location.antenna_height_ft``,
which is height **above ground level** (owner decision, 2026-09-30).
``h₂`` should be the aircraft's height above the *site's ground*, but
FlightSite does not store the site's elevation, so the band's reference
altitude — a barometric altitude, i.e. above sea level — is used as-is. That
overstates the horizon for a site well above sea level by
``1.23 x (√h₂ - √(h₂ - elevation))``: about 4 nm for a 1,000 ft site judged
at 25,000 ft, so the finder errs towards *more* findings on a high site. A
future site-elevation setting would subtract it here and nowhere else.

Each band is judged at its **lower edge** (``reference_ft``): an aircraft in
the band is at least that high, so its true horizon is at least this far, and
a sector that falls short of even the lower-edge horizon is short for every
aircraft in the band. The bottom band has no useful lower edge — 0 ft would
judge it by the antenna's own horizon, a few miles — so it uses a stated
3,000 ft floor, a typical approach and departure altitude.

An unset antenna height leaves every horizon ``None`` (Unknown) and produces
no findings: comparing coverage with a horizon nobody configured would be a
fabricated finding (SPEC §39).

Findings
--------

A finding is a run of adjacent sectors in one band where the receiver
reaches less than :data:`FINDING_SHARE_THRESHOLD` (60 %) of that band's
horizon *and* has heard enough to say so — at least
:data:`MIN_FINDING_SAMPLES` receiver samples on at least
:data:`MIN_FINDING_DAYS` different days in every sector of the run. The
evidence rule is what keeps a quiet sky from reading as a hill: a sector that
saw one aircraft once at 40 % of its horizon says nothing about what blocks
it. A sector with **no** data is never a finding either, because nothing
distinguishes "obstructed" from "no traffic" there.

60 % is deliberately generous. Real coverage is limited by transmitter power,
antenna gain and traffic geography as well as terrain, so most receivers
reach 70 to 90 % of the horizon in open sectors; a sector under 60 % with a
neighbour well above it is the shape of an obstruction (a building, a ridge,
a mast), and that is the sentence the finding says — *likely* obstruction,
never certain.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from flightsite.receiver_metrics.model import (
    BEARING_BUCKETS,
    BEARING_SECTOR_DEG,
    RangeRecord,
    better_range,
)

#: Nautical miles of 4/3-Earth radio horizon per √foot of height.
HORIZON_NM_PER_SQRT_FT: Final = 1.23

#: Share of the radio horizon below which a well-observed sector is a finding.
FINDING_SHARE_THRESHOLD: Final = 0.60

#: Receiver samples (one per ~15 s) a sector must have in the band — summed
#: over the window — before it may be a finding: 30 is 7.5 minutes of traffic.
MIN_FINDING_SAMPLES: Final = 30

#: Distinct receiver-local days a sector must have data on before it may be a
#: finding, so one unusual day (a quiet Sunday, a decoder outage) cannot make
#: one.
MIN_FINDING_DAYS: Final = 3

#: The range dash of a finding's bearing span ("40\u201360°"), spelled as an
#: escape so the source carries no ambiguous character.
_EN_DASH: Final = "\u2013"

#: The 16 compass points, clockwise from north.
_COMPASS: Final[tuple[str, ...]] = (
    "N",
    "NNE",
    "NE",
    "ENE",
    "E",
    "ESE",
    "SE",
    "SSE",
    "S",
    "SSW",
    "SW",
    "WSW",
    "W",
    "WNW",
    "NW",
    "NNW",
)


@dataclass(frozen=True, slots=True)
class AltitudeBand:
    """One altitude band of the coverage analysis.

    ``min_ft`` is inclusive and ``max_ft`` exclusive; ``None`` is unbounded.
    ``reference_ft`` is the altitude the band's radio horizon is computed for
    — see :mod:`flightsite.api.receiver_coverage` for why it is the band's
    lower edge (or a stated floor for the bottom band).
    """

    index: int
    key: str
    label: str
    #: The band as a phrase that completes "… of the radio horizon ___".
    phrase: str
    min_ft: float | None
    max_ft: float | None
    reference_ft: float


#: The three bands, in storage order — ``altitude_band`` is the index here.
ALTITUDE_BANDS: Final[tuple[AltitudeBand, ...]] = (
    AltitudeBand(
        index=0,
        key="below_10k",
        label="Below 10,000 ft",
        phrase="below 10,000 ft",
        min_ft=None,
        max_ft=10_000.0,
        # The bottom band has no useful lower edge — 0 ft would make its
        # horizon the antenna's own, a few miles — so it is judged at a
        # stated floor instead: a typical approach/departure altitude.
        reference_ft=3_000.0,
    ),
    AltitudeBand(
        index=1,
        key="10k_25k",
        label="10,000 to 25,000 ft",
        phrase="between 10,000 and 25,000 ft",
        min_ft=10_000.0,
        max_ft=25_000.0,
        reference_ft=10_000.0,
    ),
    AltitudeBand(
        index=2,
        key="above_25k",
        label="25,000 ft and above",
        phrase="above 25,000 ft",
        min_ft=25_000.0,
        max_ft=None,
        reference_ft=25_000.0,
    ),
)


def altitude_band(altitude_ft: float | None) -> int | None:
    """The band index ``altitude_ft`` falls in, or ``None`` when it is unknown.

    Total over every reported value: a barometric altitude below sea level
    (a low airfield on a high-pressure day) is the bottom band, not an error.
    """
    if altitude_ft is None:
        return None
    for band in ALTITUDE_BANDS:
        if band.max_ft is None or altitude_ft < band.max_ft:
            return band.index
    return None  # pragma: no cover - the last band is unbounded above


@dataclass(frozen=True, slots=True)
class BandRange:
    """The furthest detection in one sector and band, and how often it was seen.

    ``samples`` is the number of receiver samples that saw at least one
    aircraft in this cell — ``1`` straight out of the sampler, a running sum
    once folded.
    """

    band: int
    record: RangeRecord
    samples: int = 1

    @property
    def bearing_bucket(self) -> int:
        """The 5° sector this cell covers (``0..71``)."""
        return self.record.bearing_bucket

    @property
    def key(self) -> tuple[int, int]:
        """``(band, bearing_bucket)`` — the cell within one day."""
        return self.band, self.record.bearing_bucket


def merge_band_range(current: BandRange | None, candidate: BandRange) -> BandRange:
    """Fold ``candidate`` into ``current``: the further record, the summed count.

    Both must describe the same cell; the record comparison is
    :func:`~flightsite.receiver_metrics.model.better_range`, so a tie keeps
    the earlier detection exactly as the unbanded table does.
    """
    if current is None:
        return candidate
    return BandRange(
        band=current.band,
        record=better_range(current.record, candidate.record),
        samples=current.samples + candidate.samples,
    )


# ------------------------------------------------------------------ horizon


def radio_horizon_nm(antenna_height_ft: float | None, aircraft_height_ft: float) -> float | None:
    """The 4/3-Earth radio horizon between an antenna and an aircraft, in nm.

    ``None`` when the antenna height is unknown. A negative height (the
    setting accepts down to -1,400 ft) contributes nothing rather than an
    imaginary root: an antenna below its surroundings has no horizon of its
    own, which is the conservative reading.
    """
    if antenna_height_ft is None:
        return None
    return HORIZON_NM_PER_SQRT_FT * (
        math.sqrt(max(antenna_height_ft, 0.0)) + math.sqrt(max(aircraft_height_ft, 0.0))
    )


def band_horizons(antenna_height_ft: float | None) -> dict[int, float | None]:
    """Each band's horizon at its reference altitude, keyed by band index."""
    return {
        band.index: radio_horizon_nm(antenna_height_ft, band.reference_ft)
        for band in ALTITUDE_BANDS
    }


# ------------------------------------------------------------------- window


@dataclass(frozen=True, slots=True)
class CoverageCell:
    """One sector and band reduced over a window of days.

    ``record`` is the furthest detection of the window, ``samples`` the sum of
    the daily counts and ``days`` how many days had any data. A cell with no
    data has ``record=None`` and zero counts — and is a *real* answer the API
    reports as ``null`` range, never as a zero range.
    """

    band: int
    bearing_bucket: int
    record: RangeRecord | None = None
    samples: int = 0
    days: int = 0

    def share_of(self, horizon_nm: float | None) -> float | None:
        """Observed range as a share of ``horizon_nm``, or ``None`` if either is unknown.

        Not clamped: a share above 1 is a real observation (an aircraft above
        the band's lower edge, or anomalous propagation) and hiding it would
        misstate what was heard.
        """
        if self.record is None or horizon_nm is None or horizon_nm <= 0.0:
            return None
        return self.record.max_range_nm / horizon_nm


def reduce_window(rows: Iterable[tuple[str, BandRange]]) -> dict[tuple[int, int], CoverageCell]:
    """Fold stored day rows into one :class:`CoverageCell` per occupied cell.

    ``rows`` should be oldest day first, as
    :meth:`~flightsite.receiver_metrics.repository.MetricsRepository.band_ranges_from`
    returns them, so a tie keeps the earlier detection. Keyed by
    ``(band, bearing_bucket)``; cells that never had data are absent.
    """
    cells: dict[tuple[int, int], CoverageCell] = {}
    for _day, entry in rows:
        current = cells.get(entry.key)
        if current is None or current.record is None:
            cells[entry.key] = CoverageCell(
                band=entry.band,
                bearing_bucket=entry.bearing_bucket,
                record=entry.record,
                samples=entry.samples,
                days=1,
            )
            continue
        cells[entry.key] = CoverageCell(
            band=entry.band,
            bearing_bucket=entry.bearing_bucket,
            record=better_range(current.record, entry.record),
            samples=current.samples + entry.samples,
            days=current.days + 1,
        )
    return cells


# ----------------------------------------------------------------- findings


@dataclass(frozen=True, slots=True)
class Finding:
    """A run of adjacent sectors in one band that look obstructed.

    ``first_bucket``..``last_bucket`` is inclusive and may wrap through north
    (``71`` then ``0``). ``max_range_nm`` is the furthest detection anywhere
    in the run and ``share`` that range over the horizon, so the sentence
    states the *best* the run achieved — the conservative claim. ``samples``
    sums the run; ``days`` is the fewest days any sector of it was heard on,
    the weakest evidence the finding rests on.
    """

    band: AltitudeBand
    first_bucket: int
    last_bucket: int
    max_range_nm: float
    horizon_nm: float
    share: float
    samples: int
    days: int

    @property
    def sector_count(self) -> int:
        """How many 5° sectors the run covers."""
        return (self.last_bucket - self.first_bucket) % BEARING_BUCKETS + 1

    @property
    def start_deg(self) -> float:
        """The run's first bearing, degrees true."""
        return self.first_bucket * BEARING_SECTOR_DEG

    @property
    def end_deg(self) -> float:
        """The run's last bearing (exclusive), degrees true — ``360`` rather than ``0``."""
        end = ((self.last_bucket + 1) * BEARING_SECTOR_DEG) % 360.0
        return 360.0 if end == 0.0 else end

    @property
    def compass(self) -> str:
        """The 16-point compass name of the run's middle bearing."""
        middle = (self.start_deg + self.sector_count * BEARING_SECTOR_DEG / 2.0) % 360.0
        return compass_point(middle)

    @property
    def message(self) -> str:
        """The plain sentence the Receiver page lists, in canonical units.

        e.g. ``"NE 40\u201360° reaches 58 % of the radio horizon above 25,000 ft —
        likely obstruction"``.
        """
        percent = round(self.share * 100)
        if self.sector_count == BEARING_BUCKETS:
            return (
                f"Every bearing reaches at most {percent} % of the radio horizon "
                f"{self.band.phrase} — likely a receiver-wide limit (antenna, cable or "
                "gain) rather than an obstruction"
            )
        return (
            f"{self.compass} {self.start_deg:g}{_EN_DASH}{self.end_deg:g}° reaches {percent} % "
            f"of the radio horizon {self.band.phrase} — likely obstruction"
        )


def compass_point(bearing_deg: float) -> str:
    """The 16-point compass name nearest ``bearing_deg``."""
    return _COMPASS[round((bearing_deg % 360.0) / 22.5) % len(_COMPASS)]


def qualifies(cell: CoverageCell, horizon_nm: float | None) -> bool:
    """Whether one sector is, on its own, evidence of an obstruction.

    Enough samples on enough days, and a share of a *known* horizon below
    :data:`FINDING_SHARE_THRESHOLD`. See the module docstring.
    """
    share = cell.share_of(horizon_nm)
    return (
        share is not None
        and share < FINDING_SHARE_THRESHOLD
        and cell.samples >= MIN_FINDING_SAMPLES
        and cell.days >= MIN_FINDING_DAYS
    )


def _runs(flags: Sequence[bool]) -> list[tuple[int, int]]:
    """Inclusive ``(first, last)`` runs of ``True`` around a circular sequence."""
    count = len(flags)
    if all(flags):
        return [(0, count - 1)]
    # Start scanning just after a False so a run through north stays whole.
    start = next(index for index, flag in enumerate(flags) if not flag) + 1
    runs: list[tuple[int, int]] = []
    first: int | None = None
    for step in range(count):
        index = (start + step) % count
        if flags[index]:
            if first is None:
                first = index
            last = index
        elif first is not None:
            runs.append((first, last))
            first = None
    if first is not None:
        runs.append((first, last))
    return sorted(runs)


def find_obstructions(
    cells: Mapping[tuple[int, int], CoverageCell],
    horizons: Mapping[int, float | None],
) -> list[Finding]:
    """Every finding across the bands, highest band first, then by bearing.

    Adjacent qualifying sectors of one band merge into one finding, so a
    ridge spanning 20° reads as one sentence rather than four. A band with
    no horizon (antenna height unset) produces nothing.
    """
    findings: list[Finding] = []
    for band in reversed(ALTITUDE_BANDS):
        horizon = horizons.get(band.index)
        if horizon is None:
            continue
        row = [
            cells.get((band.index, bucket), CoverageCell(band.index, bucket))
            for bucket in range(BEARING_BUCKETS)
        ]
        for first, last in _runs([qualifies(cell, horizon) for cell in row]):
            members = [
                row[(first + step) % BEARING_BUCKETS]
                for step in range((last - first) % BEARING_BUCKETS + 1)
            ]
            furthest = max(cell.record.max_range_nm for cell in members if cell.record is not None)
            findings.append(
                Finding(
                    band=band,
                    first_bucket=first,
                    last_bucket=last,
                    max_range_nm=furthest,
                    horizon_nm=horizon,
                    share=furthest / horizon,
                    samples=sum(cell.samples for cell in members),
                    days=min(cell.days for cell in members),
                )
            )
    return findings


__all__ = [
    "ALTITUDE_BANDS",
    "FINDING_SHARE_THRESHOLD",
    "HORIZON_NM_PER_SQRT_FT",
    "MIN_FINDING_DAYS",
    "MIN_FINDING_SAMPLES",
    "AltitudeBand",
    "BandRange",
    "CoverageCell",
    "Finding",
    "altitude_band",
    "band_horizons",
    "compass_point",
    "find_obstructions",
    "merge_band_range",
    "qualifies",
    "radio_horizon_nm",
    "reduce_window",
]
