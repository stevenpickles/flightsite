"""Decoder-agnostic ingestion domain types.

These are the *only* shapes the rest of FlightSite ever sees from a decoder
(SPEC §11, [ADR-0003](../../../../docs/adr/0003-decoder-adapter-abstraction.md)).
No decoder-specific field name appears here — that vocabulary lives entirely
in :mod:`flightsite.ingest.readsb`, which translates it into the canonical
names below at the boundary, and a test enforces the split. A future
Beast/SBS/remote adapter, the demo adapter (slice 011) and the replay adapter
(slice 012) all produce these same values, which is what keeps the live store,
sightings, alerts and analytics decoder-agnostic.

Naming follows the canonical vocabulary in ``docs/API.md`` §2.8 and the unit
conventions in §2.3: feet, knots, feet/minute, degrees true, dBFS, UTC.
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal, overload

#: Canonical position-source vocabulary (``docs/API.md`` §2.8, SPEC §21).
#:
#: * ``adsb``  — position received directly from the aircraft over ADS-B.
#: * ``mlat``  — position computed by multilateration, not transmitted.
#: * ``none``  — aircraft tracked without a valid position (Mode S only).
#: * ``other`` — position from another path (TIS-B / ADS-R rebroadcast).
PositionSource = Literal["adsb", "mlat", "none", "other"]

_ICAO_RE = re.compile(r"^[0-9a-f]{6}$")


class DecoderFlavor(StrEnum):
    """Best-effort identification of the decoder behind an endpoint.

    Modern readsb and dump1090-fa deliberately serve a compatible document, so
    :data:`UNKNOWN` is a normal, non-error answer: it means "this is a valid
    aircraft document, but nothing in it distinguishes the two". Only
    positively identifying markers move the guess off :data:`UNKNOWN`.
    """

    READSB = "readsb"
    DUMP1090_FA = "dump1090-fa"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DecoderEndpoint:
    """Where a decoder's aircraft document is served from.

    Mirrors ``receiver.host`` / ``port`` / ``path`` / ``poll_interval_s`` in
    the settings model, but as a plain value object so the ingestion layer does
    not depend on the configuration layer (and so tests, the connection test
    and the setup wizard can construct one freely).
    """

    host: str
    port: int
    path: str
    poll_interval_s: float = 1.0

    @property
    def url(self) -> str:
        """The absolute HTTP URL of the aircraft document."""
        path = self.path if self.path.startswith("/") else f"/{self.path}"
        return f"http://{self.host}:{self.port}{path}"


@dataclass(frozen=True, slots=True)
class Position:
    """A WGS-84 surface position in decimal degrees."""

    latitude: float
    longitude: float


@dataclass(frozen=True, slots=True)
class AircraftStateUpdate:
    """One observation of one aircraft, normalized out of a decoder document.

    Every field except ``icao``, ``timestamp`` and ``position_source`` is
    optional: decoders report sparsely, and FlightSite never fabricates a value
    it was not given (SPEC §39). A missing field is ``None``, not a default.

    ``altitude_ft`` is barometric altitude — the figure aviation uses and the
    one both supported decoders report most often. Geometric (GNSS) altitude,
    when the decoder supplies it, is kept separately in
    ``altitude_geometric_ft`` rather than folded into one ambiguous number.

    ``on_ground`` is the decoder's own airborne/ground determination:
    ``True``/``False`` when the decoder stated one, ``None`` when it did not.
    Inference from other fields is the live store's job (slice 008), so that
    "the decoder said so" and "FlightSite worked it out" stay distinguishable
    for field provenance (SPEC §22).

    The invariants enforced here are the ones the rest of the system relies on:
    a lowercase 6-hex ICAO address (``docs/API.md`` §2.9) and a timezone-aware
    UTC timestamp (SPEC: UTC in storage and APIs). An adapter that builds an
    update from junk therefore gets a :class:`ValueError` it can count and
    skip, instead of leaking a malformed identity downstream.
    """

    icao: str
    timestamp: datetime
    position_source: PositionSource = "none"
    callsign: str | None = None
    squawk: str | None = None
    position: Position | None = None
    altitude_ft: float | None = None
    altitude_geometric_ft: float | None = None
    ground_speed_kt: float | None = None
    track_deg: float | None = None
    vertical_rate_fpm: float | None = None
    on_ground: bool | None = None
    rssi_db: float | None = None
    messages: int | None = None
    seen_s: float | None = None
    seen_pos_s: float | None = None

    def __post_init__(self) -> None:
        if not _ICAO_RE.match(self.icao):
            raise ValueError(f"icao must be a lowercase 6-hex address, got {self.icao!r}")
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware UTC")
        if self.position is None and self.position_source != "none":
            raise ValueError(
                f"position_source {self.position_source!r} requires a position; "
                "use 'none' for aircraft tracked without one"
            )

    @property
    def has_position(self) -> bool:
        """True when this observation carries a usable position."""
        return self.position is not None


@dataclass(frozen=True, slots=True)
class AircraftStateBatch(Sequence[AircraftStateUpdate]):
    """One decoder poll: the decoder's own clock plus the updates it yielded.

    The batch *is* a ``Sequence[AircraftStateUpdate]``, which is the shape
    ``docs/ARCHITECTURE.md`` §3.5 sketches for ``DecoderAdapter.updates()``;
    the extra attributes ride along for consumers that want them. Carrying the
    decoder's ``timestamp`` matters because a decoder's clock is the authority
    on when an observation happened — FlightSite's wall clock may differ, and
    the two only agree by luck on a Pi with no RTC.

    ``skipped`` counts entries dropped as unusable (malformed identity, wrong
    type, unparseable shape). ``skipped_non_icao`` counts entries the decoder
    served under a synthetic, non-ICAO address (TIS-B trackfiles and similar):
    those are well-formed but have no 24-bit airframe identity, and admitting
    them would create permanent aircraft rows for addresses that name no
    aircraft. Both are reported rather than hidden so diagnostics (slice 042)
    can show a decoder producing garbage.
    """

    timestamp: datetime
    updates: tuple[AircraftStateUpdate, ...] = ()
    skipped: int = 0
    skipped_non_icao: int = 0

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None:
            raise ValueError("timestamp must be timezone-aware UTC")

    @overload
    def __getitem__(self, index: int) -> AircraftStateUpdate: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[AircraftStateUpdate]: ...

    def __getitem__(
        self, index: int | slice
    ) -> AircraftStateUpdate | Sequence[AircraftStateUpdate]:
        return self.updates[index]

    def __len__(self) -> int:
        return len(self.updates)

    def __iter__(self) -> Iterator[AircraftStateUpdate]:
        return iter(self.updates)


@dataclass(frozen=True, slots=True)
class DecoderProbe:
    """What a single decoder document tells us about the decoder serving it.

    Produced by the connection test (and reusable by diagnostics): how many
    aircraft the document held, how many of those carried a position, the
    decoder's own timestamp, and the flavor guess with the markers that drove
    it.
    """

    aircraft_count: int
    positioned_count: int
    timestamp: datetime
    flavor: DecoderFlavor
    markers: tuple[str, ...] = ()


__all__ = [
    "AircraftStateBatch",
    "AircraftStateUpdate",
    "DecoderEndpoint",
    "DecoderFlavor",
    "DecoderProbe",
    "Position",
    "PositionSource",
]
