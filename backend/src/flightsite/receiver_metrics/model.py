"""Receiver-metric domain types — decoder-agnostic, storage-agnostic, pure.

These are the only shapes the rest of the package moves around, and the reason
they exist is the same one :mod:`flightsite.ingest.types` exists for (SPEC §11,
ADR-0003): the decoder's statistics vocabulary stops at
:mod:`flightsite.receiver_metrics.statsjson`, and SQL starts at
:mod:`flightsite.receiver_metrics.repository`. Everything between the two —
sampling, aggregation, retention arithmetic — is expressed here and is
therefore testable without a decoder and without a database.

Absence is a first-class value
------------------------------

Every measurement is ``X | None``. SPEC §60 requires unsupported decoder
metrics to be *gracefully absent* and SPEC §39 forbids fabricating values, so
"the decoder does not report signal level" and "the signal level was 0 dB" must
never be the same value. That rule holds all the way down: a ``None`` here
becomes a ``NULL`` column, is skipped by every aggregate, and renders as "—"
rather than as a number nobody measured.

Units follow ``docs/API.md`` §2.3: nautical miles, degrees true, dBFS, and UTC
epoch milliseconds for every instant (``docs/DATA_MODEL.md`` §Conventions).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: Width of one bearing sector in degrees (``docs/DATA_MODEL.md`` §6.3).
BEARING_SECTOR_DEG: Final = 5.0

#: Number of sectors covering the compass: 360 / 5.
BEARING_BUCKETS: Final = 72


def bearing_bucket(bearing_deg: float) -> int:
    """The 5° sector ``bearing_deg`` falls in, as ``0..71``.

    Total by construction: the modulo folds 360°, negative bearings and the
    float noise of a great-circle azimuth back into range, so no caller can
    produce a bucket the schema does not describe. Sector ``n`` covers
    ``[5n, 5n + 5)`` degrees true, which is what the polar plot (SPEC §62)
    draws.
    """
    return int(bearing_deg // BEARING_SECTOR_DEG) % BEARING_BUCKETS


#: Cumulative messages accepted by the decoder since T0.
LIFETIME_TOTAL_MESSAGES: Final = "total_messages"
#: Cumulative positions decoded since T0.
LIFETIME_TOTAL_POSITIONS: Final = "total_positions"
#: Greatest range ever observed, and the moment, bearing and airframe that set
#: it. The four move together or not at all — see :class:`RangeRecord`.
LIFETIME_MAX_RANGE_NM: Final = "max_range_nm"
LIFETIME_MAX_RANGE_AT_MS: Final = "max_range_at_ms"
LIFETIME_MAX_RANGE_ICAO24: Final = "max_range_icao24"
LIFETIME_MAX_RANGE_BEARING: Final = "max_range_bearing_deg"
#: Receiver-local day with the greatest message total, and that total.
LIFETIME_BUSIEST_DAY: Final = "busiest_day"
LIFETIME_BUSIEST_DAY_COUNT: Final = "busiest_day_count"
#: Highest simultaneous aircraft count ever sampled.
LIFETIME_MAX_SIMULTANEOUS: Final = "max_simultaneous"
#: Highest message and position rates ever sampled.
LIFETIME_PEAK_MSG_RATE: Final = "peak_msg_rate"
LIFETIME_PEAK_POS_RATE: Final = "peak_pos_rate"

#: Every key this slice writes (``docs/DATA_MODEL.md`` §6.4). Declared as a
#: tuple so slice 034's stats API and the tests read the same list rather than
#: each spelling the strings again.
LIFETIME_KEYS: Final[tuple[str, ...]] = (
    LIFETIME_TOTAL_MESSAGES,
    LIFETIME_TOTAL_POSITIONS,
    LIFETIME_MAX_RANGE_NM,
    LIFETIME_MAX_RANGE_AT_MS,
    LIFETIME_MAX_RANGE_ICAO24,
    LIFETIME_MAX_RANGE_BEARING,
    LIFETIME_BUSIEST_DAY,
    LIFETIME_BUSIEST_DAY_COUNT,
    LIFETIME_MAX_SIMULTANEOUS,
    LIFETIME_PEAK_MSG_RATE,
    LIFETIME_PEAK_POS_RATE,
)


@dataclass(frozen=True, slots=True)
class DecoderStats:
    """One normalized reading of a decoder's own statistics endpoint.

    The counters are **cumulative since the decoder started**, not rates: a
    rate is a difference between two of these divided by the time between
    them, and computing it is :mod:`flightsite.receiver_metrics.sampler`'s job
    because only it knows what the previous reading was.

    ``max_range_nm`` is the decoder's own furthest-ever figure where it reports
    one (readsb does, dump1090-fa does not). FlightSite does not store it: its
    own range records come from positions it actually saw, which is the figure
    SPEC §63 asks for and the only one it can attribute to an aircraft and a
    bearing. It is carried here for diagnostics and for the decoder-vs-us
    comparison a support question needs.
    """

    messages_total: int | None = None
    positions_total: int | None = None
    rssi_avg_db: float | None = None
    rssi_peak_db: float | None = None
    max_range_nm: float | None = None
    #: How long the decoder says it has been running, seconds (SPEC §61).
    uptime_s: float | None = None

    @property
    def is_empty(self) -> bool:
        """True when the document yielded nothing FlightSite can use.

        A decoder serving a statistics document in a shape this version does
        not recognise is indistinguishable, from here, from one serving no
        document at all — and both degrade the same way (SPEC §60).
        """
        return all(
            value is None
            for value in (
                self.messages_total,
                self.positions_total,
                self.rssi_avg_db,
                self.rssi_peak_db,
                self.max_range_nm,
                self.uptime_s,
            )
        )


@dataclass(frozen=True, slots=True)
class MetricSample:
    """One high-resolution sample — a ``receiver_metrics_raw`` row (§6.1).

    Half of it is the decoder's (signal levels, and the counters the rates are
    differenced from) and half is FlightSite's own (how many aircraft were up,
    how far the furthest one was). Which half a field came from is not recorded
    per row: the columns are the normalized vocabulary, and a decoder that
    cannot supply one leaves it ``None``.
    """

    ts_ms: int
    messages_per_sec: float | None = None
    positions_per_sec: float | None = None
    aircraft_visible: int | None = None
    aircraft_with_pos: int | None = None
    max_range_nm: float | None = None
    rssi_avg_db: float | None = None
    rssi_peak_db: float | None = None


@dataclass(frozen=True, slots=True)
class RangeRecord:
    """The furthest aircraft seen in one direction at one moment (§6.3).

    The fields are a single fact and are never merged separately: a range that
    belonged to a different aircraft at a different time would be a record of
    nothing. :func:`better_range` is the only comparison.

    The record carries the **exact bearing** and derives its sector, rather
    than storing the sector alone. ``range_by_bearing_daily`` persists the
    sector, because 72 buckets is what the polar plot draws; the lifetime
    max-range record persists the bearing, because "the furthest aircraft ever
    heard was 243 nm out on 037°" is a better answer than one rounded to a 5°
    bin. Both come from the same observation, so they cannot disagree.
    """

    bearing_deg: float
    max_range_nm: float
    at_ms: int
    icao24: str | None = None

    @property
    def bearing_bucket(self) -> int:
        """The 5° sector this observation belongs to (``0..71``)."""
        return bearing_bucket(self.bearing_deg)


def better_range(current: RangeRecord | None, candidate: RangeRecord) -> RangeRecord:
    """Whichever of the two reached further, keeping its whole attribution.

    Ties keep ``current``. A later observation at exactly the same range is not
    a new record, and preferring the earlier one makes "when did the receiver
    first reach this far" the answer a record row gives.
    """
    if current is None or candidate.max_range_nm > current.max_range_nm:
        return candidate
    return current


@dataclass(frozen=True, slots=True)
class MetricSummary:
    """An aggregated bucket — one hourly or daily row (§6.2).

    The same shape for both tiers, because §6.2 defines the daily table as the
    hourly one keyed by local calendar day. ``sample_count`` is the number of
    raw samples the bucket was folded from and is the only value that is always
    known.

    ``messages_total`` and ``positions_total`` are **counts over the bucket**,
    not rates: the integral of the sampled rate, reconstructed from each
    sample's own rate and the interval it was measured over. See
    :mod:`flightsite.receiver_metrics.aggregate`.
    """

    sample_count: int
    messages_total: int | None = None
    positions_total: int | None = None
    msgs_per_sec_avg: float | None = None
    msgs_per_sec_max: float | None = None
    pos_per_sec_avg: float | None = None
    pos_per_sec_max: float | None = None
    aircraft_avg: float | None = None
    aircraft_max: int | None = None
    max_range_nm: float | None = None
    rssi_avg_db: float | None = None
    rssi_peak_db: float | None = None


__all__ = [
    "BEARING_BUCKETS",
    "BEARING_SECTOR_DEG",
    "LIFETIME_BUSIEST_DAY",
    "LIFETIME_BUSIEST_DAY_COUNT",
    "LIFETIME_KEYS",
    "LIFETIME_MAX_RANGE_AT_MS",
    "LIFETIME_MAX_RANGE_BEARING",
    "LIFETIME_MAX_RANGE_ICAO24",
    "LIFETIME_MAX_RANGE_NM",
    "LIFETIME_MAX_SIMULTANEOUS",
    "LIFETIME_PEAK_MSG_RATE",
    "LIFETIME_PEAK_POS_RATE",
    "LIFETIME_TOTAL_MESSAGES",
    "LIFETIME_TOTAL_POSITIONS",
    "DecoderStats",
    "MetricSample",
    "MetricSummary",
    "RangeRecord",
    "bearing_bucket",
    "better_range",
]
