"""The normalized airport record, and what counts as an airport.

The ADR-0006 boundary again, for a second kind of dataset. Everything upstream
of this module — OurAirports' column order, its quoting, its empty-string
convention for "unknown" — is
:mod:`flightsite.airports.ourairports`' private problem; everything downstream
deals only in :class:`AirportRecord`.

Normalization is enforced here rather than trusted to the provider, for the
reason :mod:`flightsite.metadata.records` gives: SQLite compares text byte for
byte, so one stray space or lower-case ident would make ``kSEA `` and ``KSEA``
two airports, and the in-memory index would then answer with whichever it
happened to load second. :func:`normalize_airport` is the only supported
constructor and it *rejects* rather than repairs anything it cannot interpret.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

#: Upstream ``type`` values FlightSite imports, and why these four.
#:
#: ``large_airport``, ``medium_airport`` and ``small_airport`` are the fields
#: fixed-wing traffic actually uses, and ``heliport`` is where a great deal of
#: the low, slow traffic a receiver hears is going — police, air ambulance and
#: offshore helicopters are exactly the aircraft nearest-airport context is
#: most useful for.
#:
#: Three upstream types are deliberately excluded:
#:
#: * ``closed`` (~13k rows) — the field is *gone*. Naming one as the airport an
#:   aircraft is arriving at would be a confident statement about a runway that
#:   no longer exists, which is worse than saying nothing (SPEC §39).
#: * ``seaplane_base`` (~1.3k rows) — a stretch of water, often plotted at the
#:   centroid of a lake and frequently overlapping a real field a few miles
#:   away. Including them would let a water landing area outrank the airport an
#:   aircraft is genuinely approaching, on a coordinate that does not name a
#:   runway to begin with.
#: * ``balloonport`` (~60 rows) — not a destination for the transponder-
#:   equipped traffic this heuristic reasons about.
#:
#: The filter is here rather than in a SQL ``CHECK`` so it can change without
#: rebuilding a table; ``docs/DATA_MODEL.md`` §3.6 deliberately constrains the
#: column not at all.
IMPORTED_AIRPORT_TYPES: Final[frozenset[str]] = frozenset(
    {"large_airport", "medium_airport", "small_airport", "heliport"}
)

#: A plausible airport identifier: letters, digits and the hyphen upstream uses
#: for a handful of regional idents, 1 to 12 characters. Deliberately looser than
#: "four letters": OurAirports' ``ident`` is an ICAO code where one exists and a
#: local/GPS code where it does not (``00AK``, ``CA-0001``), and both are
#: legitimate keys.
IDENT_PATTERN: Final = re.compile(r"^[A-Z0-9-]{1,12}$")

#: An IATA code is exactly three letters. Anything else upstream carries in
#: that column is dropped rather than stored: the column exists to be looked up
#: by, and a malformed key answers no lookup.
IATA_PATTERN: Final = re.compile(r"^[A-Z]{3}$")

#: Bounds on a usable field elevation, in feet. The floor sits below the Dead
#: Sea's airstrips (~-1 200 ft) and the ceiling above Daocheng Yading
#: (~14 500 ft), the highest airport on Earth, with room to spare. Outside
#: these an upstream value is a data error, and the record keeps ``None`` — the
#: same thing the ~16% of rows with no elevation at all carry.
MIN_ELEVATION_FT: Final = -2_000
MAX_ELEVATION_FT: Final = 20_000


class AirportRecordError(ValueError):
    """An upstream row could not be normalized into a usable airport.

    Counted as a rejected row by the import pipeline, which carries on: one bad
    row in seventy thousand must not fail an import, and a *lot* of bad rows is
    what the pipeline's reject-ratio tolerance is for.
    """


@dataclass(frozen=True, slots=True)
class AirportRecord:
    """One airport as FlightSite stores and indexes it.

    Four fields are mandatory because without any one of them the row cannot do
    its job: ``ident`` is the key, ``name`` is what the UI shows, and ``lat`` /
    ``lon`` are the whole point. ``iata``, ``elevation_ft`` and ``iso_country``
    are ``None`` when upstream does not know, never a guess.
    """

    ident: str
    name: str
    type: str
    lat: float
    lon: float
    iata: str | None = None
    elevation_ft: int | None = None
    iso_country: str | None = None
    #: OurAirports' own row id, kept as the surrogate primary key so a
    #: re-import produces the same ids for the same airports.
    upstream_id: int | None = None


def _text(raw: object) -> str | None:
    """Collapse a raw field to a clean string, or ``None`` if it says nothing."""
    if raw is None:
        return None
    text = " ".join(str(raw).split())
    return text or None


def normalize_ident(raw: object) -> str:
    """Canonicalize an airport identifier, or raise :class:`AirportRecordError`.

    Upper-cased, because the ident is the join key and a case split would make
    one airport two.
    """
    text = _text(raw)
    if text is None:
        raise AirportRecordError("airport row has no ident")
    ident = text.upper()
    if not IDENT_PATTERN.match(ident):
        raise AirportRecordError(f"not a usable airport ident: {raw!r}")
    return ident


def normalize_iata(raw: object) -> str | None:
    """An IATA code, or ``None`` when the row has none or a malformed one."""
    text = _text(raw)
    if text is None:
        return None
    code = text.upper()
    return code if IATA_PATTERN.match(code) else None


def normalize_coordinate(raw: object, *, limit: float, what: str) -> float:
    """A latitude or longitude in degrees, or raise :class:`AirportRecordError`.

    ``limit`` is 90 for latitude and 180 for longitude. Out-of-range and
    unparseable are the same failure: an airport whose coordinates are wrong is
    an airport the nearest-airport search would place somewhere it is not.
    """
    text = _text(raw)
    if text is None:
        raise AirportRecordError(f"airport row has no {what}")
    try:
        value = float(text)
    except ValueError:
        raise AirportRecordError(f"airport {what} is not a number: {raw!r}") from None
    if not -limit <= value <= limit:
        raise AirportRecordError(f"airport {what} out of range: {value}")
    return value


def normalize_elevation(raw: object) -> int | None:
    """Field elevation in whole feet, or ``None`` when absent or implausible.

    Never raises. A field whose elevation upstream garbled is still an airport
    worth knowing about — the inference simply falls back to treating it as sea
    level, which is what it already does for the rows upstream has no elevation
    for at all.
    """
    text = _text(raw)
    if text is None:
        return None
    try:
        value = round(float(text))
    except ValueError:
        return None
    return value if MIN_ELEVATION_FT <= value <= MAX_ELEVATION_FT else None


def normalize_country(raw: object) -> str | None:
    """An ISO 3166-1 alpha-2 country code, or ``None``.

    Two upper-case letters or nothing; upstream uses a handful of non-standard
    codes for disputed territories, which match the shape and are kept as-is
    rather than judged.
    """
    text = _text(raw)
    if text is None:
        return None
    code = text.upper()
    return code if len(code) == 2 and code.isalpha() else None


def normalize_airport(
    *,
    ident: object,
    name: object,
    type: str,
    lat: object,
    lon: object,
    iata: object = None,
    elevation_ft: object = None,
    iso_country: object = None,
    upstream_id: object = None,
) -> AirportRecord:
    """Build an :class:`AirportRecord` from raw provider values.

    Raises:
        AirportRecordError: if the ident, name or either coordinate is
            unusable — the four fields whose absence makes a row meaningless.
    """
    clean_name = _text(name)
    if clean_name is None:
        raise AirportRecordError("airport row has no name")
    clean_type = _text(type)
    if clean_type is None:
        raise AirportRecordError("airport row has no type")
    return AirportRecord(
        ident=normalize_ident(ident),
        name=clean_name,
        type=clean_type,
        lat=normalize_coordinate(lat, limit=90.0, what="latitude"),
        lon=normalize_coordinate(lon, limit=180.0, what="longitude"),
        iata=normalize_iata(iata),
        elevation_ft=normalize_elevation(elevation_ft),
        iso_country=normalize_country(iso_country),
        upstream_id=_upstream_id(upstream_id),
    )


def _upstream_id(raw: object) -> int | None:
    """OurAirports' row id, or ``None`` when it is absent or unparseable.

    Never raises: the id is a convenience (stable primary keys across
    re-imports), not something the record needs to be useful, and the sink
    assigns one when it is missing.
    """
    text = _text(raw)
    if text is None:
        return None
    try:
        return int(text)
    except ValueError:
        return None


__all__ = [
    "IATA_PATTERN",
    "IDENT_PATTERN",
    "IMPORTED_AIRPORT_TYPES",
    "MAX_ELEVATION_FT",
    "MIN_ELEVATION_FT",
    "AirportRecord",
    "AirportRecordError",
    "normalize_airport",
    "normalize_coordinate",
    "normalize_country",
    "normalize_elevation",
    "normalize_iata",
    "normalize_ident",
]
