"""readsb / dump1090-fa ``aircraft.json`` adapter — the decoder-specific edge.

**This module is the only place in FlightSite that knows readsb's field
names.** Everything it produces is
:mod:`flightsite.ingest.types`, and a test
(``tests/ingest/test_no_field_leakage.py``) enforces the boundary by grepping
the rest of the package for these spellings (SPEC §11, ADR-0003).

Document shape
--------------

Both decoders serve one JSON object per poll::

    {"now": 1758124800.1, "messages": 41822193, "aircraft": [ ... ]}

``now`` is the decoder's own clock in Unix seconds and is authoritative for
"when": a Raspberry Pi without an RTC and the machine running FlightSite are
not guaranteed to agree, and every downstream timestamp derives from the
decoder's view. Each aircraft's ``seen`` (seconds since it was last heard)
is subtracted from ``now`` to date that specific observation, rather than
stamping a whole batch with a single moment.

Field vocabulary
----------------

Modern readsb and dump1090-fa (PiAware 4+) share a vocabulary; dump1090-fa 3.x
and dump1090-mutability used older spellings. Both are accepted:

======================= ======================= ============================
Modern                  Legacy                  Normalized to
======================= ======================= ============================
``hex``                 ``hex``                 ``icao``
``flight``              ``flight``              ``callsign``
``alt_baro``            ``altitude``            ``altitude_ft`` / ``on_ground``
``alt_geom``            —                       ``altitude_geometric_ft``
``gs``                  ``speed``               ``ground_speed_kt``
``track``               ``track``               ``track_deg``
``baro_rate``           ``vert_rate``           ``vertical_rate_fpm``
``geom_rate``           —                       ``vertical_rate_fpm`` (fallback)
``squawk``              ``squawk``              ``squawk``
``lat`` / ``lon``       ``lat`` / ``lon``       ``position``
``seen`` / ``seen_pos`` ``seen`` / ``seen_pos`` ``seen_s`` / ``seen_pos_s``
``rssi``                ``rssi``                ``rssi_db``
``messages``            ``messages``            ``messages``
``type`` / ``mlat``     ``mlat``                ``position_source``
======================= ======================= ============================

Fields FlightSite does not consume yet (``category``, ``nav_*``, ``nic``,
``sil``, ``r``, ``t``, ``emergency``) are ignored rather than rejected;
metadata and emergency handling arrive in slices 021 and 038.

Normalization decisions
-----------------------

* **Altitude.** ``alt_baro`` carries either a number of feet or the string
  ``"ground"``. The sentinel means the decoder itself determined the aircraft
  is on the surface, so it becomes ``on_ground=True`` with no altitude — never
  an altitude of zero, which would be a fabricated measurement. A *numeric*
  barometric altitude is the same field saying "airborne", so it yields
  ``on_ground=False``; when the field is absent or unusable, ``on_ground``
  stays ``None`` and slice 008 may infer it.
* **Vertical rate.** ``baro_rate`` is preferred and ``geom_rate`` is the
  fallback, matching the barometric-first choice for altitude.
* **Position source** (SPEC §21, ``docs/API.md`` §2.8): no usable position at
  all yields ``none`` — a ``mode_s`` aircraft, typically; a position listed in
  the ``mlat`` array, or a ``type`` of ``mlat``, yields ``mlat``; a position
  from a rebroadcast path (``tisb_icao``, ``tisb_trackfile``, ``adsr_icao``
  and their ``_other`` variants, or one listed in the ``tisb`` array) yields
  ``other``; anything else with a position — ``adsb_icao`` and friends — is
  ``adsb``. Classification is
  driven by the position's own provenance, not the aircraft's: an aircraft
  whose *altitude* is multilaterated but whose position is direct ADS-B is
  ``adsb``.
* **Non-ICAO addresses.** readsb prefixes synthetic addresses with ``~``
  (TIS-B trackfiles, anonymised targets). They are counted separately and
  dropped: FlightSite's permanent aircraft identity is the ICAO 24-bit address
  (``docs/DATA_MODEL.md`` §2.2 ``icao24 UNIQUE``), and a synthetic address
  names no airframe.
* **Squawk.** Kept only when it is a well-formed 4-digit octal code, so
  emergency detection (slice 038) never has to defend against ``"9999"``.

Plausibility bounds and type coercion live in :mod:`flightsite.ingest.bounds`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import httpx
import structlog

from flightsite.counters import CounterRegistry, counters
from flightsite.ingest import bounds
from flightsite.ingest.health import AdapterHealth, HealthState, HealthTracker
from flightsite.ingest.protocol import DecoderError, DecoderParseError, DecoderUnavailableError
from flightsite.ingest.types import (
    AircraftStateBatch,
    AircraftStateUpdate,
    DecoderEndpoint,
    DecoderFlavor,
    DecoderProbe,
    Position,
    PositionSource,
)

logger = structlog.get_logger(__name__)

#: Value ``alt_baro`` / ``altitude`` takes when the decoder has determined the
#: aircraft is on the surface.
GROUND_SENTINEL: Final = "ground"

#: ``type`` values that mean the position was multilaterated.
MLAT_TYPES: Final = frozenset({"mlat"})

#: ``type`` prefixes for positions that reached us by rebroadcast rather than
#: directly from the aircraft (TIS-B ground stations, ADS-R relays).
REBROADCAST_TYPE_PREFIXES: Final = ("tisb_", "adsr_")

#: readsb marks synthetic, non-ICAO addresses with this prefix.
NON_ICAO_ADDRESS_PREFIX: Final = "~"

#: Keys emitted only by readsb; their presence identifies the decoder.
READSB_MARKER_FIELDS: Final = (
    "dbFlags",
    "calc_track",
    "rr_lat",
    "rr_lon",
    "gpsOkBefore",
    "lastPosition",
    "receiverCount",
)

#: Keys emitted only by the older dump1090-fa / dump1090-mutability field set.
DUMP1090_LEGACY_MARKER_FIELDS: Final = ("altitude", "speed", "vert_rate", "nucp")

#: Request timeout for one poll. Deliberately not configurable: it is short
#: enough that a wedged decoder cannot stall ingestion past a couple of poll
#: intervals, and long enough for a busy Pi serving a 400-aircraft document
#: over wifi.
DEFAULT_REQUEST_TIMEOUT_S: Final = 5.0

#: Hard ceiling on one aircraft document. A healthy decoder serves well under
#: a megabyte even with a thousand aircraft; anything past this is not an
#: aircraft feed, and buffering it on a Pi would be the wrong kind of failure.
MAX_DOCUMENT_BYTES: Final = 16 * 1024 * 1024

ClientFactory = Callable[[], httpx.AsyncClient]


def _octal_squawk(value: object) -> str | None:
    """Return a well-formed 4-digit octal squawk, else ``None``."""
    text = bounds.as_text(value)
    if text is None or len(text) != 4 or any(character not in "01234567" for character in text):
        return None
    return text


def _address(value: object) -> tuple[str | None, bool]:
    """Normalize an aircraft address.

    Returns ``(icao, is_non_icao)``: a lowercase 6-hex address when the entry
    identifies a real airframe, ``(None, True)`` for a ``~``-prefixed synthetic
    address, and ``(None, False)`` when the field is missing or malformed.
    """
    text = bounds.as_text(value)
    if text is None:
        return None, False
    if text.startswith(NON_ICAO_ADDRESS_PREFIX):
        return None, True
    lowered = text.lower()
    if len(lowered) != 6 or any(character not in "0123456789abcdef" for character in lowered):
        return None, False
    return lowered, False


def _string_list(value: object) -> tuple[str, ...]:
    """Return the string members of a JSON array, ignoring anything else."""
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _classify_position_source(entry: dict[str, Any], *, has_position: bool) -> PositionSource:
    """Decide where this aircraft's position came from (SPEC §21)."""
    if not has_position:
        return "none"

    decoder_type = bounds.as_text(entry.get("type"))
    normalized_type = decoder_type.lower() if decoder_type else ""

    if normalized_type in MLAT_TYPES or "lat" in _string_list(entry.get("mlat")):
        return "mlat"
    if normalized_type.startswith(REBROADCAST_TYPE_PREFIXES) or "lat" in _string_list(
        entry.get("tisb")
    ):
        return "other"
    return "adsb"


def _altitude_and_ground(entry: dict[str, Any]) -> tuple[float | None, bool | None]:
    """Resolve barometric altitude and the decoder's ground determination."""
    raw = entry.get("alt_baro", entry.get("altitude"))
    if isinstance(raw, str):
        return (None, True) if raw.strip().lower() == GROUND_SENTINEL else (None, None)
    altitude = bounds.altitude_ft(raw)
    if altitude is None:
        return None, None
    return altitude, False


def _vertical_rate(entry: dict[str, Any]) -> float | None:
    """Barometric vertical rate, falling back to the geometric one."""
    for key in ("baro_rate", "vert_rate", "geom_rate"):
        if key in entry:
            rate = bounds.vertical_rate_fpm(entry[key])
            if rate is not None:
                return rate
    return None


def _position(entry: dict[str, Any]) -> Position | None:
    """Resolve a position, requiring both coordinates to be plausible."""
    latitude = bounds.latitude(entry.get("lat"))
    longitude = bounds.longitude(entry.get("lon"))
    if latitude is None or longitude is None:
        return None
    return Position(latitude=latitude, longitude=longitude)


def _observation_time(reference: datetime, seen_s: float | None) -> datetime:
    """Date this observation from the decoder's clock and the entry's age."""
    if seen_s is None:
        return reference
    return reference - timedelta(seconds=seen_s)


def _build_update(
    entry: dict[str, Any], icao: str, reference_time: datetime
) -> AircraftStateUpdate:
    """Normalize one validated aircraft entry into a domain update."""
    position = _position(entry)
    altitude, on_ground = _altitude_and_ground(entry)
    seen_s = bounds.age_s(entry.get("seen"))

    return AircraftStateUpdate(
        icao=icao,
        timestamp=_observation_time(reference_time, seen_s),
        position_source=_classify_position_source(entry, has_position=position is not None),
        callsign=bounds.as_text(entry.get("flight")),
        squawk=_octal_squawk(entry.get("squawk")),
        position=position,
        altitude_ft=altitude,
        altitude_geometric_ft=bounds.altitude_ft(entry.get("alt_geom")),
        ground_speed_kt=bounds.ground_speed_kt(entry.get("gs", entry.get("speed"))),
        track_deg=bounds.track_deg(entry.get("track")),
        vertical_rate_fpm=_vertical_rate(entry),
        on_ground=on_ground,
        rssi_db=bounds.rssi_db(entry.get("rssi")),
        messages=bounds.message_count(entry.get("messages")),
        seen_s=seen_s,
        seen_pos_s=bounds.age_s(entry.get("seen_pos")),
    )


def _document_parts(payload: object) -> tuple[dict[str, Any], list[Any]]:
    """Validate the document envelope, returning it and its aircraft list."""
    if not isinstance(payload, dict):
        raise DecoderParseError(
            f"aircraft document must be a JSON object, got {type(payload).__name__}"
        )
    raw_aircraft = payload.get("aircraft")
    if raw_aircraft is None:
        raise DecoderParseError("aircraft document has no 'aircraft' array")
    if not isinstance(raw_aircraft, list):
        raise DecoderParseError(f"'aircraft' must be an array, got {type(raw_aircraft).__name__}")
    return payload, raw_aircraft


def document_timestamp(payload: dict[str, Any], received_at: datetime) -> datetime:
    """Return the decoder's own clock, falling back to ``received_at``.

    A decoder whose clock is unset (a Pi that booted without an RTC or
    network) reports a 1970 timestamp; rather than dating every observation to
    the Unix epoch, an implausible ``now`` falls back to FlightSite's clock.
    """
    seconds = bounds.unix_time_s(payload.get("now"))
    if seconds is None:
        return received_at
    return datetime.fromtimestamp(seconds, UTC)


def parse_document(payload: object, *, received_at: datetime) -> AircraftStateBatch:
    """Normalize a decoded aircraft document into a batch.

    Whole-document problems raise :class:`DecoderParseError`; a bad individual
    aircraft entry is skipped and counted, so one corrupt record cannot cost
    the poll its other several hundred aircraft.
    """
    document, raw_aircraft = _document_parts(payload)
    timestamp = document_timestamp(document, received_at)

    updates: list[AircraftStateUpdate] = []
    skipped = 0
    skipped_non_icao = 0

    for entry in raw_aircraft:
        if not isinstance(entry, dict):
            skipped += 1
            continue
        icao, is_non_icao = _address(entry.get("hex"))
        if is_non_icao:
            skipped_non_icao += 1
            continue
        if icao is None:
            skipped += 1
            continue
        try:
            updates.append(_build_update(entry, icao, timestamp))
        except (ValueError, TypeError, OverflowError):
            # A field combination the domain type rejects, or arithmetic that
            # overflowed on an absurd age. Neither is worth losing the batch.
            skipped += 1

    return AircraftStateBatch(
        timestamp=timestamp,
        updates=tuple(updates),
        skipped=skipped,
        skipped_non_icao=skipped_non_icao,
    )


def probe_document(payload: object, *, received_at: datetime) -> DecoderProbe:
    """Summarize a document for the connection test.

    The flavor guess is best-effort by design: modern readsb and dump1090-fa
    serve a deliberately compatible document, so an honest answer is often
    :data:`~flightsite.ingest.types.DecoderFlavor.UNKNOWN`. Only fields unique
    to one decoder move the guess, and the ones that did are returned as
    ``markers`` so a wizard can explain itself.
    """
    document, raw_aircraft = _document_parts(payload)
    entries = [entry for entry in raw_aircraft if isinstance(entry, dict)]

    markers = sorted(
        {field for entry in entries for field in READSB_MARKER_FIELDS if field in entry}
    )
    flavor = DecoderFlavor.READSB
    if not markers:
        markers = sorted(
            {
                field
                for entry in entries
                for field in DUMP1090_LEGACY_MARKER_FIELDS
                if field in entry
            }
        )
        flavor = DecoderFlavor.DUMP1090_FA if markers else DecoderFlavor.UNKNOWN

    positioned = sum(1 for entry in entries if _position(entry) is not None)
    return DecoderProbe(
        aircraft_count=len(raw_aircraft),
        positioned_count=positioned,
        timestamp=document_timestamp(document, received_at),
        flavor=flavor,
        markers=tuple(markers),
    )


def decode_json(raw: bytes) -> Any:
    """Decode a response body, raising :class:`DecoderParseError` on garbage."""
    try:
        return json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DecoderParseError(f"response body is not valid JSON: {exc}") from exc


async def fetch_document(client: httpx.AsyncClient, url: str) -> Any:
    """GET ``url`` and return the decoded JSON body.

    Raises :class:`DecoderUnavailableError` when the decoder cannot be reached
    or answers with an error status, and :class:`DecoderParseError` when the
    body is oversized or is not JSON.
    """
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_DOCUMENT_BYTES:
                    raise DecoderParseError(f"aircraft document exceeds {MAX_DOCUMENT_BYTES} bytes")
                chunks.append(chunk)
    except httpx.HTTPStatusError as exc:
        raise DecoderUnavailableError(
            f"decoder returned HTTP {exc.response.status_code} for {url}"
        ) from exc
    except httpx.HTTPError as exc:
        raise DecoderUnavailableError(f"could not reach {url}: {exc}") from exc

    return decode_json(b"".join(chunks))


def build_client(timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S) -> httpx.AsyncClient:
    """Build the default HTTP client for decoder polling."""
    return httpx.AsyncClient(timeout=timeout_s, follow_redirects=True)


class ReadsbJsonAdapter:
    """Polls a readsb / dump1090-fa ``aircraft.json`` endpoint.

    Implements :class:`~flightsite.ingest.protocol.DecoderAdapter`. Polling is
    the v1 transport (ADR-0003): it matches the ~1 Hz product cadence and is
    stateless across decoder restarts, which is what makes "reconnect" here
    simply "keep polling on a backoff" rather than a socket dance.

    Nothing a decoder does escapes :meth:`updates`. Failures are counted into
    ``ingestion_failures``, folded into the health state machine, and retried
    with exponential backoff plus jitter. On the transition into ``down`` the
    HTTP client is rebuilt, so a pool full of half-open connections to a
    decoder that has since restarted cannot keep the adapter failing.

    Args:
        endpoint: where to poll and how often.
        client_factory: builds the HTTP client; replaced in tests with one
            returning a client wired to a mock transport. Called again each
            time the client is rebuilt.
        health_tracker: injectable so tests can seed the jitter RNG and clock.
        counter_registry: where ``ingestion_failures`` is counted.
        sleep: awaited between polls and between retries; injectable so
            reconnect tests run against a simulated clock rather than in real
            time.
        now: clock used to date documents whose own timestamp is unusable.
    """

    def __init__(
        self,
        endpoint: DecoderEndpoint,
        *,
        client_factory: ClientFactory | None = None,
        health_tracker: HealthTracker | None = None,
        counter_registry: CounterRegistry | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._client_factory = client_factory if client_factory is not None else build_client
        self._counters = counter_registry if counter_registry is not None else counters
        self._sleep = sleep if sleep is not None else asyncio.sleep
        self._now = now if now is not None else _utc_now
        self._health = (
            health_tracker
            if health_tracker is not None
            else HealthTracker(on_transition=self._log_transition)
        )
        self._client: httpx.AsyncClient | None = None
        self._stopped = False

    @property
    def endpoint(self) -> DecoderEndpoint:
        """The endpoint being polled."""
        return self._endpoint

    async def start(self) -> None:
        """Open the HTTP client. Does not poll — :meth:`updates` does that."""
        self._stopped = False
        self._ensure_client()
        logger.info("decoder_adapter_started", url=self._endpoint.url)

    async def stop(self) -> None:
        """Stop the poll loop and close the HTTP client. Idempotent."""
        self._stopped = True
        await self._close_client()
        logger.info("decoder_adapter_stopped", url=self._endpoint.url)

    def health(self) -> AdapterHealth:
        """Return the current connection health snapshot."""
        return self._health.health

    async def updates(self) -> AsyncIterator[AircraftStateBatch]:
        """Yield one batch per successful poll until the adapter is stopped."""
        while not self._stopped:
            try:
                batch = await self._poll()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # The contract in protocol.py is that no decoder misbehaviour
                # escapes this stream. DecoderError covers the anticipated
                # failures; the broad catch covers the ones a future decoder
                # build invents.
                await self._record_failure(exc)
                await self._sleep(self._health.health.next_retry_delay_s or 0.0)
                continue

            self._health.record_success()
            yield batch
            await self._sleep(self._endpoint.poll_interval_s)

    async def _poll(self) -> AircraftStateBatch:
        payload = await fetch_document(self._ensure_client(), self._endpoint.url)
        return parse_document(payload, received_at=self._now())

    async def _record_failure(self, exc: BaseException) -> None:
        previous = self._health.health.state
        reason = str(exc) or type(exc).__name__
        health = self._health.record_failure(reason)
        self._counters.increment("ingestion_failures")
        if health.state is HealthState.DOWN and previous is not HealthState.DOWN:
            # Drop connections pooled against a decoder that is evidently gone;
            # the next poll dials fresh.
            await self._close_client()
        if not isinstance(exc, DecoderError):
            logger.warning(
                "decoder_poll_unexpected_error",
                url=self._endpoint.url,
                error=reason,
                error_type=type(exc).__name__,
            )

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = self._client_factory()
        return self._client

    async def _close_client(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    def _log_transition(
        self, previous: HealthState, current: HealthState, health: AdapterHealth
    ) -> None:
        logger.info(
            "decoder_health_changed",
            url=self._endpoint.url,
            previous=str(previous),
            current=str(current),
            consecutive_failures=health.consecutive_failures,
            error=health.last_error,
        )


def _utc_now() -> datetime:
    return datetime.now(UTC)


__all__ = [
    "DEFAULT_REQUEST_TIMEOUT_S",
    "MAX_DOCUMENT_BYTES",
    "ReadsbJsonAdapter",
    "build_client",
    "fetch_document",
    "parse_document",
    "probe_document",
]
