"""Coverage by bearing and altitude band — the data half of slice 087.

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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from flightsite.receiver_metrics.model import RangeRecord, better_range


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


__all__ = [
    "ALTITUDE_BANDS",
    "AltitudeBand",
    "BandRange",
    "altitude_band",
    "merge_band_range",
]
