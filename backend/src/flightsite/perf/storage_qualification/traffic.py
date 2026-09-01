"""Synthetic traffic: who flies, when, and what path each one leaves behind.

This is the domain half of the generator, and it touches no database at all.
Everything here is a pure function of a seeded :class:`random.Random`, so the
same seed always produces the same years of history — which is what makes a
growth figure comparable between two runs, and a regression attributable to a
change in the product rather than to a change in the dice.

What "realistic" has to mean here
---------------------------------

A generator that emitted 1,500 identical sightings a day would produce a
database of the right *size* and the wrong *shape*, and shape is what the
queries being qualified are sensitive to. Three properties matter, and each is
modelled explicitly:

**Diurnal rhythm.** Air traffic is not uniform across the day. Sightings are
distributed over the 24 hours by :data:`HOURLY_WEIGHTS` — a trough in the small
hours, a morning ramp, a broad daytime plateau, an evening decline — and
modulated by a mild day-of-week factor. This is what gives ``daily_stats``'s
``busiest_hour`` a real answer rather than an arbitrary one, and what makes an
hourly receiver-metric summary look like a receiver rather than a metronome.

**Aircraft population reuse.** A receiver does not meet 750 strangers a day. It
sees the same based and commuter airframes again and again, a rotating cast of
regional traffic, and a long tail of aircraft it will never see twice.
:class:`AircraftPool` models exactly that with three sources — a bounded
resident fleet, the accumulated historical population, and a trickle of
first-ever contacts sized to ``docs/DATA_MODEL.md`` §9's new-airframes-per-year
figure. The resulting distribution of ``aircraft.sighting_count`` is heavily
skewed, which is the whole basis of SPEC §44 rarity: without a genuine long
tail of airframes seen once or twice, the rarity query would be measured
against data that cannot exercise it.

**Track length.** ``docs/DATA_MODEL.md`` §9 sizes storage on a simplified track
of ~60 points, and §2.4 says the simplification epsilon is tuned for 40-80
retained points on a typical transit. Point count here is derived from the
sighting's own duration at :data:`SECONDS_PER_RETAINED_POINT`, so the mean
lands on §9's figure and the spread comes from the duration distribution rather
than from a second, independent guess.

Tracks are generated already-simplified
---------------------------------------

Production writes ``pack_track(simplify(samples))``: a 1 Hz track is thinned to
its retained points and only then encoded. This module generates the retained
points directly and packs them with the real :func:`~flightsite.sightings.track_codec.pack_track`,
which produces a byte-identical row shape — the blob is ``5 + 21 * n`` bytes
either way, and every point is a real ordered, timestamped fix.

Running Douglas-Peucker over a synthetic 1 Hz track for every one of millions
of sightings would cost hours and change nothing about what is stored. The
assumption it rests on — that simplification really does retain points at about
this rate — is not taken on trust: ``tests/perf/storage/test_traffic.py``
checks it by running the production :func:`~flightsite.sightings.tracks.simplify`
over dense synthetic tracks and asserting the retained count lands in the band
the documents claim.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Final

from flightsite.demo.roster import (
    AIRLINE_CALLSIGN_PREFIXES,
    GOVERNMENT_CALLSIGN_PREFIXES,
    MILITARY_CALLSIGN_PREFIXES,
)
from flightsite.sightings.track_codec import PackedTrack, pack_track
from flightsite.sightings.tracks import TrackSample

#: Relative traffic weight for each local hour, midnight first. A quiet night,
#: a ramp from 05:00, a daytime plateau and an evening decline — the shape of a
#: receiver's day rather than a flat line. Only the ratios matter.
HOURLY_WEIGHTS: Final[tuple[float, ...]] = (
    0.22, 0.15, 0.12, 0.14, 0.28, 0.62,  # 00-05
    1.05, 1.42, 1.58, 1.52, 1.48, 1.50,  # 06-11
    1.55, 1.52, 1.47, 1.51, 1.58, 1.62,  # 12-17
    1.55, 1.38, 1.12, 0.85, 0.58, 0.34,  # 18-23
)  # fmt: skip

#: Day-of-week modulation, Monday first. Business traffic thins at the weekend;
#: the effect is real but modest, so the range is deliberately narrow.
WEEKDAY_WEIGHTS: Final[tuple[float, ...]] = (
    1.05, 1.06, 1.06, 1.07, 1.08, 0.86, 0.82,
)  # fmt: skip

#: Seconds of a sighting per point retained after simplification. A ~15-minute
#: sighting (``docs/DATA_MODEL.md`` §9's mean) therefore keeps ~60 points, which
#: is the figure §9 sizes the packed track against and sits inside the 40-80
#: band §2.4 states for a typical transit.
SECONDS_PER_RETAINED_POINT: Final = 15.0

#: Mean and shape of the sighting-duration lognormal, in seconds. §9 sizes on a
#: ~15-minute mean sighting; the spread covers a distant airliner clipping the
#: edge of range for two minutes and a circling helicopter held for an hour.
MEAN_DURATION_S: Final = 900.0
DURATION_SIGMA: Final = 0.62
MIN_DURATION_S: Final = 45.0
MAX_DURATION_S: Final = 5_400.0

#: Points are clamped to this band. The floor is the two points a packed track
#: needs to be a path; the ceiling matches ADR-0005's note that the roadmap's
#: 2 KB per-sighting ceiling holds to about 95 points, with room above it for
#: the genuinely long-held aircraft that make the distribution's tail.
MIN_TRACK_POINTS: Final = 2
MAX_TRACK_POINTS: Final = 360

#: Share of sightings from aircraft that never report a position — Mode S only.
#: These get no ``sighting_tracks`` row at all (``any_position = 0``), which is
#: a real and load-bearing case: a growth model that assumed every sighting
#: carried a track would over-count. Matches the demo roster's Mode S weight.
MODE_S_SHARE: Final = 0.08

#: Share of the day's unique airframes drawn from the resident fleet.
RESIDENT_SHARE: Final = 0.40

#: The resident fleet is sized as a multiple of the airframes seen on one day,
#: so a resident recurs every few days rather than daily — a based or commuter
#: aircraft, not a fixture.
RESIDENT_FLEET_FACTOR: Final = 1.6

#: Position-report rate while an aircraft is visible, and messages per position.
#: ``pos_count`` counts new position reports (roughly 1 Hz, with gaps); message
#: counters run several times faster.
POSITIONS_PER_SECOND: Final = 0.82
MESSAGES_PER_POSITION: Final = 4.4

#: Emergency squawks, latched by ``sightings.had_emergency`` (SPEC §17).
EMERGENCY_SQUAWKS: Final[tuple[str, ...]] = ("7500", "7600", "7700")

#: How often a sighting carries an emergency squawk. Rare by construction: an
#: emergency on a tenth of flights would make the alert surfaces meaningless.
EMERGENCY_SHARE: Final = 0.0006

#: Alert severities, weakest first — the ladder ``sightings.max_alert_severity``
#: is a monotone maximum over.
ALERT_SEVERITIES: Final[tuple[str, ...]] = ("info", "interesting", "high", "critical")

#: Milliseconds in a second, spelled once.
MS_PER_SECOND: Final = 1_000

#: Receiver-relative range band, in nautical miles (SPEC §66: nothing is
#: discarded for being far away, so the tail runs well past the display radius).
MIN_RANGE_NM: Final = 0.4
MAX_RANGE_NM: Final = 250.0


@dataclass(frozen=True, slots=True)
class Airframe:
    """One physical aircraft the synthetic receiver can hear.

    Args:
        index: dense 0-based id; the database ``aircraft.id`` is assigned from
            it, so the generator never has to read a row back to learn a key.
        icao24: six lowercase hex characters, the identity SPEC §17 keys on.
        callsign_prefix: airline or operator prefix its callsigns are built
            from, so the same airframe does not appear as a different operator
            on every sighting.
        type_code: ICAO type designator, or ``None`` where metadata never
            resolved — real installs do not have complete metadata, and the
            analytics rollups have to cope with that.
        military: feeds ``aircraft_classification`` and the classification
            counts in ``daily_stats``.
        government: as above.
    """

    index: int
    icao24: str
    callsign_prefix: str
    type_code: str | None
    military: bool
    government: bool


@dataclass(frozen=True, slots=True)
class SyntheticSighting:
    """One generated observation period, before it becomes database rows.

    Field names deliberately echo the ``sightings`` columns they end up in, so
    the mapping in :mod:`.generator` is obvious and a column that stops being
    written is easy to spot.
    """

    airframe: int
    started_ms: int
    duration_ms: int
    callsign: str
    squawk: str
    had_emergency: bool
    any_position: bool
    mlat_used: bool
    ground_seen: bool
    track_points: int
    msg_count: int
    pos_count: int
    rssi_peak_db: float
    rssi_avg_db: float
    rssi_min_db: float
    closest_approach_nm: float | None
    max_range_nm: float | None
    lowest_alt_ft: int | None
    highest_alt_ft: int | None
    alert_severity: str | None
    event_count: int

    @property
    def ended_ms(self) -> int:
        """When the aircraft was last heard — the close moment SPEC §18 means."""
        return self.started_ms + self.duration_ms


class AircraftPool:
    """The population the receiver draws from, growing as history accumulates.

    Three sources, blended to produce the skewed ``sighting_count``
    distribution a real receiver has (see the module docstring):

    * a bounded **resident fleet**, seen every few days for the life of the
      dataset;
    * the **historical population** — everything heard before, sampled
      uniformly, so an airframe's chance of a repeat visit does not decay to
      zero but is small;
    * **first-ever contacts**, at the rate ``docs/DATA_MODEL.md`` §9 states.

    The pool never stores per-airframe history: it hands out indices and the
    generator accumulates the aggregates. That keeps memory proportional to the
    airframe count rather than to the sighting count, which is what makes three
    years of the design envelope generable at all.
    """

    def __init__(self, scenario_unique_per_day: int, *, rng: random.Random) -> None:
        self._rng = rng
        self._airframes: list[Airframe] = []
        self._used_icao: set[str] = set()
        self._resident_target = max(1, int(scenario_unique_per_day * RESIDENT_FLEET_FACTOR))
        self._residents: list[int] = []

    @property
    def airframes(self) -> list[Airframe]:
        """Every airframe created so far, in creation order."""
        return self._airframes

    @property
    def size(self) -> int:
        """How many distinct airframes exist."""
        return len(self._airframes)

    def _new_airframe(self) -> Airframe:
        """Mint one airframe with a stable identity and metadata character."""
        while True:
            icao24 = f"{self._rng.getrandbits(24):06x}"
            if icao24 not in self._used_icao:
                self._used_icao.add(icao24)
                break

        roll = self._rng.random()
        military = roll < 0.055
        government = 0.055 <= roll < 0.085
        if military:
            prefix = self._rng.choice(MILITARY_CALLSIGN_PREFIXES)
        elif government:
            prefix = self._rng.choice(GOVERNMENT_CALLSIGN_PREFIXES)
        else:
            prefix = self._rng.choice(AIRLINE_CALLSIGN_PREFIXES)

        # Metadata is resolved for most but not all airframes. An install with
        # complete metadata is not the common case, and the analytics rollups
        # skip unresolved types by design (docs/DATA_MODEL.md §6.5), so a
        # generator that resolved everything would hide that branch.
        type_code = self._rng.choice(TYPE_CODES) if self._rng.random() < 0.78 else None

        airframe = Airframe(
            index=len(self._airframes),
            icao24=icao24,
            callsign_prefix=prefix,
            type_code=type_code,
            military=military,
            government=government,
        )
        self._airframes.append(airframe)
        if len(self._residents) < self._resident_target:
            self._residents.append(airframe.index)
        return airframe

    def draw_day(self, *, unique_today: int, new_today: int) -> list[int]:
        """Pick the airframe indices heard on one day.

        Returns indices rather than airframes because the caller only needs the
        key; ``new_today`` first-ever contacts are minted, the resident share is
        drawn from the fleet, and whatever remains comes from the whole
        historical population.

        The result is deduplicated, so a day's unique count is genuinely unique
        — ``daily_stats.unique_aircraft`` is compared against it.
        """
        chosen: set[int] = set()
        for _ in range(new_today):
            chosen.add(self._new_airframe().index)

        remaining = max(0, unique_today - len(chosen))
        resident_count = int(remaining * RESIDENT_SHARE)

        attempts = 0
        limit = remaining * 8 + 32
        while len(chosen) < unique_today and attempts < limit:
            attempts += 1
            if len(chosen) - new_today < resident_count and self._residents:
                chosen.add(self._rng.choice(self._residents))
            elif self._airframes:
                chosen.add(self._rng.randrange(len(self._airframes)))
            else:  # pragma: no cover - only reachable with an empty first day
                chosen.add(self._new_airframe().index)

        # A young pool can genuinely not offer enough distinct airframes yet;
        # minting the shortfall keeps the day's unique count honest rather than
        # letting the first weeks of history run thin.
        while len(chosen) < unique_today:
            chosen.add(self._new_airframe().index)

        return sorted(chosen)


#: ICAO type designators used for metadata realism. A real receiver's type
#: distribution is long-tailed; this is a representative spread across airliner,
#: regional, business and general-aviation airframes rather than a census.
TYPE_CODES: Final[tuple[str, ...]] = (
    "A20N", "A21N", "A319", "A320", "A321", "A332", "A333", "A339", "A359", "A388",
    "B38M", "B737", "B738", "B739", "B744", "B752", "B763", "B772", "B77W", "B788",
    "B789", "BCS1", "BCS3", "CRJ2", "CRJ7", "CRJ9", "E145", "E170", "E175", "E190",
    "C172", "C182", "C208", "C25A", "C56X", "PC12", "SR22", "TBM9", "GLF5", "GLF6",
    "H60", "C130", "KC35", "P8", "E3TF", "AS50", "EC35", "R44", "B06", "DH8D",
)  # fmt: skip


def _lognormal_duration(rng: random.Random) -> float:
    """A sighting length in seconds, clamped to a plausible band.

    Lognormal because sighting lengths are: a floor near zero, a dense body
    around the mean, and a long right tail for aircraft held in range.
    """
    mu = math.log(MEAN_DURATION_S) - DURATION_SIGMA**2 / 2.0
    value = math.exp(rng.gauss(mu, DURATION_SIGMA))
    return min(MAX_DURATION_S, max(MIN_DURATION_S, value))


def _hour_for(rng: random.Random) -> int:
    """Pick a local hour from the diurnal curve.

    The weekday factor deliberately plays no part here. Scaling every hour of a
    day by the same constant leaves the *distribution* across hours identical —
    ``random.choices`` normalizes its weights — so a day-of-week effect applied
    at this point would be a no-op dressed up as a model. It belongs to how
    many sightings a day carries, which is :func:`sightings_on`.
    """
    return rng.choices(range(24), weights=HOURLY_WEIGHTS, k=1)[0]


def sightings_on(weekday: int, *, daily_average: int) -> int:
    """How many sightings a given weekday carries.

    ``daily_average`` is the scenario's figure, which
    ``docs/DATA_MODEL.md`` §9 states as an average over all days. The weekday
    factors are therefore normalized by their own mean before being applied, so
    a week of generated history still totals seven times the scenario's daily
    traffic — a model that made every day busier than average would silently
    inflate every growth figure measured from it.
    """
    mean_weight = sum(WEEKDAY_WEIGHTS) / len(WEEKDAY_WEIGHTS)
    return max(1, round(daily_average * WEEKDAY_WEIGHTS[weekday] / mean_weight))


def sightings_for_day(
    rng: random.Random,
    *,
    day_start_ms: int,
    airframes: list[int],
    sightings_today: int,
    alert_share: float,
) -> list[SyntheticSighting]:
    """Generate one day's sightings across the airframes heard that day.

    ``alert_share`` is the fraction of sightings that match an alert, taken
    from the scenario's own ``alert_matches_per_day`` rather than fixed here,
    so the ``alert_matches`` row count lands where ``docs/DATA_MODEL.md`` §9
    sizes it.

    Sightings are returned in ascending ``started_ms`` order, which is both the
    order a receiver produces them and the order that keeps the
    ``ix_sightings_started`` index appending rather than splitting as the
    generator writes.
    """
    if not airframes:
        return []

    generated: list[SyntheticSighting] = []
    for index in range(sightings_today):
        # Every airframe heard today gets at least one sighting before any gets
        # a second, so the day's unique count is exactly what was drawn.
        airframe = airframes[index] if index < len(airframes) else rng.choice(airframes)

        hour = _hour_for(rng)
        offset_s = hour * 3_600 + rng.uniform(0.0, 3_600.0)
        duration_s = _lognormal_duration(rng)
        started_ms = day_start_ms + int(offset_s * MS_PER_SECOND)
        duration_ms = int(duration_s * MS_PER_SECOND)

        mode_s_only = rng.random() < MODE_S_SHARE
        any_position = not mode_s_only
        points = 0
        if any_position:
            points = round(duration_s / SECONDS_PER_RETAINED_POINT)
            points = min(MAX_TRACK_POINTS, max(MIN_TRACK_POINTS, points))

        pos_count = int(duration_s * POSITIONS_PER_SECOND) if any_position else 0
        msg_count = int(max(pos_count, 1) * MESSAGES_PER_POSITION * rng.uniform(0.7, 1.4))

        peak = rng.uniform(-14.0, -3.0)
        minimum = peak - rng.uniform(3.0, 14.0)
        average = (peak + minimum) / 2.0 + rng.uniform(-1.0, 1.0)

        far: float | None
        near: float | None
        low: int | None
        high: int | None
        if any_position:
            far = rng.uniform(MIN_RANGE_NM + 5.0, MAX_RANGE_NM)
            near = rng.uniform(MIN_RANGE_NM, far)
            low = int(rng.uniform(500.0, 20_000.0))
            high = low + int(rng.uniform(0.0, 22_000.0))
        else:
            far = near = None
            low = high = None

        emergency = rng.random() < EMERGENCY_SHARE
        squawk = (
            rng.choice(EMERGENCY_SQUAWKS)
            if emergency
            else f"{rng.randrange(0, 8)}{rng.randrange(0, 8)}"
            f"{rng.randrange(0, 8)}{rng.randrange(0, 8)}"
        )

        severity: str | None = None
        if emergency:
            severity = "critical"
        elif rng.random() < alert_share:
            severity = ALERT_SEVERITIES[rng.choices((0, 1, 2), weights=(6, 3, 1), k=1)[0]]

        generated.append(
            SyntheticSighting(
                airframe=airframe,
                started_ms=started_ms,
                duration_ms=duration_ms,
                callsign="",  # filled by the generator, which knows the prefix
                squawk=squawk,
                had_emergency=emergency,
                any_position=any_position,
                mlat_used=any_position and rng.random() < 0.09,
                ground_seen=any_position and rng.random() < 0.06,
                track_points=points,
                msg_count=msg_count,
                pos_count=pos_count,
                rssi_peak_db=peak,
                rssi_avg_db=average,
                rssi_min_db=minimum,
                closest_approach_nm=near,
                max_range_nm=far,
                lowest_alt_ft=low,
                highest_alt_ft=high,
                alert_severity=severity,
                event_count=max(0, int(rng.gauss(3.0, 1.2))),
            )
        )

    generated.sort(key=lambda sighting: sighting.started_ms)
    return generated


class TrackPool:
    """Pre-encoded packed tracks, reused across sightings by point count.

    Encoding every track of a multi-year dataset point by point would dominate
    the generator's run time — three years of the design envelope is upwards of
    a billion points — and would change nothing about what lands on disk: a
    packed row is ``5 + 21 * n`` bytes whatever the geometry inside it. So the
    pool encodes :data:`VARIANTS_PER_LENGTH` genuine tracks for each point count
    it is asked for, with the real
    :func:`~flightsite.sightings.track_codec.pack_track`, and hands them out
    thereafter.

    What is preserved exactly: the blob's size distribution, its byte layout,
    its decodability, and the ``point_count``/``encoding_version`` columns
    beside it. What is not: geometric uniqueness between two sightings that
    happen to have retained the same number of points. Nothing in the storage,
    index or query behaviour under qualification depends on that — no v1
    feature queries inside a blob (ADR-0005 is explicit that SQL cannot) — and
    the trade buys the three-year scale the slice exists to measure.
    """

    #: Distinct encodings kept per point count. Enough that a query returning a
    #: page of tracks decodes several different paths; small enough that the
    #: whole pool is built in seconds.
    VARIANTS_PER_LENGTH: Final = 8

    def __init__(self, *, rng: random.Random, centre: tuple[float, float] = (51.5, -0.45)) -> None:
        self._rng = rng
        self._centre = centre
        self._pool: dict[int, list[PackedTrack]] = {}

    def _build(self, points: int) -> list[PackedTrack]:
        """Encode a handful of real tracks of exactly ``points`` points."""
        variants: list[PackedTrack] = []
        for _ in range(self.VARIANTS_PER_LENGTH):
            latitude, longitude = self._centre
            latitude += self._rng.uniform(-1.6, 1.6)
            longitude += self._rng.uniform(-2.2, 2.2)
            heading = self._rng.uniform(0.0, 360.0)
            speed_kt = self._rng.uniform(120.0, 480.0)
            altitude = float(self._rng.randrange(1_000, 41_000, 25))
            climb = self._rng.uniform(-900.0, 900.0)

            samples: list[TrackSample] = []
            timestamp = 0
            for step in range(points):
                # A gentle, continuous turn and climb: the shape Douglas-Peucker
                # leaves behind, rather than a straight line that would compress
                # unrealistically or a random walk that would not.
                heading = (heading + self._rng.uniform(-0.8, 0.8)) % 360.0
                distance_nm = speed_kt * (SECONDS_PER_RETAINED_POINT / 3_600.0)
                latitude += distance_nm / 60.0 * math.cos(math.radians(heading))
                longitude += (
                    distance_nm
                    / 60.0
                    * math.sin(math.radians(heading))
                    / max(0.2, math.cos(math.radians(latitude)))
                )
                altitude = max(0.0, altitude + climb * (SECONDS_PER_RETAINED_POINT / 60.0) / 10.0)
                samples.append(
                    TrackSample(
                        ts_ms=timestamp,
                        latitude=latitude,
                        longitude=longitude,
                        position_source="adsb",
                        altitude_ft=int(altitude),
                        ground_speed_kt=speed_kt,
                        track_deg=heading,
                    )
                )
                timestamp += int(SECONDS_PER_RETAINED_POINT * MS_PER_SECOND)
                if step == 0 and points == 1:  # pragma: no cover - defensive
                    break
            variants.append(pack_track(tuple(samples)))
        return variants

    def blob_for(self, points: int) -> PackedTrack:
        """A packed track of exactly ``points`` points."""
        if points < MIN_TRACK_POINTS:
            raise ValueError(f"a packed track needs at least {MIN_TRACK_POINTS} points")
        variants = self._pool.get(points)
        if variants is None:
            variants = self._build(points)
            self._pool[points] = variants
        return variants[self._rng.randrange(len(variants))]


__all__ = [
    "ALERT_SEVERITIES",
    "EMERGENCY_SQUAWKS",
    "HOURLY_WEIGHTS",
    "MAX_TRACK_POINTS",
    "MIN_TRACK_POINTS",
    "MODE_S_SHARE",
    "SECONDS_PER_RETAINED_POINT",
    "TYPE_CODES",
    "WEEKDAY_WEIGHTS",
    "AircraftPool",
    "Airframe",
    "SyntheticSighting",
    "TrackPool",
    "sightings_for_day",
    "sightings_on",
]
