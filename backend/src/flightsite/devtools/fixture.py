"""The ``.fsrec.gz`` fixture format: capture/replay's on-disk representation.

A fixture is a **gzip-compressed JSON Lines** document. Line 1 is a header
object; every following line is one captured :class:`~flightsite.ingest.types.AircraftStateBatch`.
JSON Lines (rather than one JSON array) keeps writing streaming-friendly —
:func:`write_fixture` still buffers a whole capture in this slice, but the
format itself never requires holding the full file in memory — and it makes a
fixture diffable and greppable after ``gunzip``.

Only :mod:`~flightsite.ingest.types` normalized values are serialized, never a
decoder's raw JSON: a fixture recorded from readsb replays identically through
a future Beast or SBS adapter's own captures, and nothing here needs to know a
decoder's field names (ADR-0003).

Header line
-----------

::

    {"format_version": 1, "created_at": "2026-08-31T12:00:00+00:00",
     "source": "readsb@http://192.168.1.50:8080/data/aircraft.json",
     "duration_s": 60.02, "batch_count": 58, "update_count": 3120,
     "generator": "flightsite-capture"}

Batch line
----------

One line per captured batch, in capture order::

    {"t": 1.004, "ts": "2026-08-31T12:00:01.004000+00:00",
     "skipped": 0, "skipped_non_icao": 0,
     "updates": [{"icao": "4ca87c", "ts": "...", "src": "adsb", ...}]}

``t`` is the batch's decoder timestamp expressed as seconds elapsed since
``created_at``, rounded to millisecond precision — it exists purely as a
pacing hint for :class:`~flightsite.devtools.replay.ReplayAdapter` and for a
human skimming the file. ``ts`` (batch and per-update) is the full-precision
UTC timestamp and is what round-trips exactly: replaying a fixture must
reproduce byte-for-byte identical :class:`AircraftStateUpdate` values, and a
millisecond-rounded offset alone cannot guarantee that.

Update objects use the canonical field names from
:class:`~flightsite.ingest.types.AircraftStateUpdate`, abbreviated (``src``
for ``position_source``, ``alt_ft`` for ``altitude_ft``, ...) to keep fixtures
compact; a field holding its dataclass default is omitted from the object
entirely rather than written as ``null``, which is where most of a fixture's
compactness comes from.

Determinism
-----------

Given the same batches, :func:`write_fixture` produces byte-identical output
on every call: object keys are sorted, JSON separators are minimal, and the
gzip header's mtime is pinned to ``0`` (gzip otherwise stamps the wall-clock
second, which would make two captures of identical content differ on disk).
This is what lets a fixture be committed to version control and diffed like
any other text asset after decompression.

Format version
---------------

:data:`FORMAT_VERSION` is bumped whenever the header or line shape changes
incompatibly; :func:`read_fixture` rejects a file whose ``format_version`` it
does not recognize rather than guessing.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from flightsite.ingest.types import (
    AircraftStateBatch,
    AircraftStateUpdate,
    Position,
    PositionSource,
)

#: The only fixture format this module reads and writes. Bump on any
#: incompatible change to the header or line shape.
FORMAT_VERSION: Final = 1

#: Default value of the header's ``generator`` field when the caller does not
#: name a more specific tool.
DEFAULT_GENERATOR: Final = "flightsite.devtools.fixture"

#: Conventional filename suffix. Not enforced by this module (a caller may
#: name a fixture whatever it likes), but every tool in ``devtools`` uses it.
FIXTURE_SUFFIX: Final = ".fsrec.gz"

_JSON_SEPARATORS = (",", ":")


class FixtureError(Exception):
    """A fixture file could not be read: unsupported version or bad shape."""


@dataclass(frozen=True, slots=True)
class FixtureHeader:
    """The first line of a fixture: metadata about the whole capture."""

    format_version: int
    created_at: datetime
    source: str
    duration_s: float
    batch_count: int
    update_count: int
    generator: str = DEFAULT_GENERATOR

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("created_at must be timezone-aware UTC")


@dataclass(frozen=True, slots=True)
class FixtureRecord:
    """One captured batch plus the pacing offset it was recorded at."""

    relative_s: float
    batch: AircraftStateBatch


@dataclass(frozen=True, slots=True)
class Fixture:
    """A fixture fully read into memory: header plus every record in order."""

    header: FixtureHeader
    records: tuple[FixtureRecord, ...]


def _dumps(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=_JSON_SEPARATORS)


def _update_to_dict(update: AircraftStateUpdate) -> dict[str, Any]:
    """Normalize an update into its compact, omit-defaults JSON shape."""
    data: dict[str, Any] = {"icao": update.icao, "ts": update.timestamp.isoformat()}
    if update.position_source != "none":
        data["src"] = update.position_source
    if update.callsign is not None:
        data["callsign"] = update.callsign
    if update.squawk is not None:
        data["squawk"] = update.squawk
    if update.position is not None:
        data["lat"] = update.position.latitude
        data["lon"] = update.position.longitude
    if update.altitude_ft is not None:
        data["alt_ft"] = update.altitude_ft
    if update.altitude_geometric_ft is not None:
        data["alt_geom_ft"] = update.altitude_geometric_ft
    if update.ground_speed_kt is not None:
        data["gs_kt"] = update.ground_speed_kt
    if update.track_deg is not None:
        data["track_deg"] = update.track_deg
    if update.vertical_rate_fpm is not None:
        data["vrate_fpm"] = update.vertical_rate_fpm
    if update.on_ground is not None:
        data["on_ground"] = update.on_ground
    if update.rssi_db is not None:
        data["rssi_db"] = update.rssi_db
    if update.messages is not None:
        data["messages"] = update.messages
    if update.seen_s is not None:
        data["seen_s"] = update.seen_s
    if update.seen_pos_s is not None:
        data["seen_pos_s"] = update.seen_pos_s
    return data


def _update_from_dict(data: dict[str, Any]) -> AircraftStateUpdate:
    position: Position | None = None
    if "lat" in data or "lon" in data:
        position = Position(latitude=data["lat"], longitude=data["lon"])
    position_source: PositionSource = data.get("src", "none")
    return AircraftStateUpdate(
        icao=data["icao"],
        timestamp=datetime.fromisoformat(data["ts"]),
        position_source=position_source,
        callsign=data.get("callsign"),
        squawk=data.get("squawk"),
        position=position,
        altitude_ft=data.get("alt_ft"),
        altitude_geometric_ft=data.get("alt_geom_ft"),
        ground_speed_kt=data.get("gs_kt"),
        track_deg=data.get("track_deg"),
        vertical_rate_fpm=data.get("vrate_fpm"),
        on_ground=data.get("on_ground"),
        rssi_db=data.get("rssi_db"),
        messages=data.get("messages"),
        seen_s=data.get("seen_s"),
        seen_pos_s=data.get("seen_pos_s"),
    )


def _batch_to_line(batch: AircraftStateBatch, *, relative_s: float) -> str:
    line: dict[str, Any] = {
        "t": round(relative_s, 3),
        "ts": batch.timestamp.isoformat(),
        "updates": [_update_to_dict(update) for update in batch.updates],
    }
    if batch.skipped:
        line["skipped"] = batch.skipped
    if batch.skipped_non_icao:
        line["skipped_non_icao"] = batch.skipped_non_icao
    return _dumps(line)


def _batch_from_line(line: dict[str, Any]) -> FixtureRecord:
    batch = AircraftStateBatch(
        timestamp=datetime.fromisoformat(line["ts"]),
        updates=tuple(_update_from_dict(entry) for entry in line["updates"]),
        skipped=line.get("skipped", 0),
        skipped_non_icao=line.get("skipped_non_icao", 0),
    )
    return FixtureRecord(relative_s=line["t"], batch=batch)


def _header_to_dict(header: FixtureHeader) -> dict[str, Any]:
    return {
        "format_version": header.format_version,
        "created_at": header.created_at.isoformat(),
        "source": header.source,
        "duration_s": round(header.duration_s, 3),
        "batch_count": header.batch_count,
        "update_count": header.update_count,
        "generator": header.generator,
    }


def _header_from_dict(data: dict[str, Any]) -> FixtureHeader:
    version = data.get("format_version")
    if version != FORMAT_VERSION:
        raise FixtureError(
            f"unsupported fixture format_version {version!r}; expected {FORMAT_VERSION}"
        )
    return FixtureHeader(
        format_version=version,
        created_at=datetime.fromisoformat(data["created_at"]),
        source=data["source"],
        duration_s=data["duration_s"],
        batch_count=data["batch_count"],
        update_count=data["update_count"],
        generator=data.get("generator", DEFAULT_GENERATOR),
    )


def write_fixture(
    path: str | Path,
    *,
    batches: Sequence[AircraftStateBatch],
    source: str,
    duration_s: float,
    created_at: datetime | None = None,
    generator: str = DEFAULT_GENERATOR,
) -> FixtureHeader:
    """Write ``batches`` to ``path`` as a gzip-compressed fixture.

    ``created_at`` is the pacing reference every batch's ``t`` offset is
    computed against; it defaults to the first batch's own timestamp, or
    "now" when ``batches`` is empty. ``duration_s`` is the caller's own
    measurement of how long the capture ran — it is recorded as-is rather
    than derived from batch timestamps, so an empty or short capture still
    reports an honest duration.
    """
    if created_at is None:
        created_at = batches[0].timestamp if batches else datetime.now(UTC)

    update_count = sum(len(batch) for batch in batches)
    header = FixtureHeader(
        format_version=FORMAT_VERSION,
        created_at=created_at,
        source=source,
        duration_s=duration_s,
        batch_count=len(batches),
        update_count=update_count,
        generator=generator,
    )

    lines = [_dumps(_header_to_dict(header))]
    for batch in batches:
        relative_s = (batch.timestamp - created_at).total_seconds()
        lines.append(_batch_to_line(batch, relative_s=relative_s))
    payload = ("\n".join(lines) + "\n").encode("utf-8")

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 pins the gzip header's embedded timestamp so byte-identical
    # input always produces a byte-identical file (see module docstring).
    with (
        target.open("wb") as raw,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz,
    ):
        gz.write(payload)
    return header


def read_fixture(path: str | Path) -> Fixture:
    """Read and fully decode a fixture written by :func:`write_fixture`."""
    with gzip.open(Path(path), mode="rt", encoding="utf-8") as gz:
        raw_lines = [line for line in gz.read().splitlines() if line]
    if not raw_lines:
        raise FixtureError(f"fixture {path} is empty")

    header = _header_from_dict(json.loads(raw_lines[0]))
    records = tuple(_batch_from_line(json.loads(line)) for line in raw_lines[1:])
    return Fixture(header=header, records=records)


__all__ = [
    "DEFAULT_GENERATOR",
    "FIXTURE_SUFFIX",
    "FORMAT_VERSION",
    "Fixture",
    "FixtureError",
    "FixtureHeader",
    "FixtureRecord",
    "read_fixture",
    "write_fixture",
]
