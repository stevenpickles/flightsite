"""readsb / dump1090-fa ``stats.json`` adapter — the decoder-specific edge.

**This module is the only place in FlightSite that knows the decoder's
statistics vocabulary**, exactly as :mod:`flightsite.ingest.readsb` is the only
place that knows its aircraft vocabulary (SPEC §11, ADR-0003). Everything it
produces is a :class:`~flightsite.receiver_metrics.model.DecoderStats`, and
``tests/receiver_metrics/test_field_isolation.py`` enforces the boundary by
grepping the rest of the package for these spellings.

Where the document lives
------------------------

Beside the aircraft document, which is the only place either decoder puts it:
``/data/aircraft.json`` implies ``/data/stats.json``. So the URL is derived from
the configured receiver path rather than configured again — one endpoint to get
wrong instead of two, and a user who moved their decoder's document root gets
both moved together.

Document shape
--------------

One JSON object of time-window blocks — ``latest``, ``last1min``, ``last5min``,
``last15min``, ``total`` — each with the same inner shape. FlightSite reads
``total`` only: it is the cumulative-since-decoder-start block, and cumulative
counters differenced across two polls give a rate over exactly the interval
FlightSite sampled, rather than over a window the decoder chose. The one-minute
block would be a second, differently-shaped answer to the same question, and
the two would disagree at every boundary.

======================================== ============================================
``total`` field                          Normalized to
======================================== ============================================
``messages``                             ``messages_total``
``cpr.global_ok`` + ``cpr.local_ok``      ``positions_total``
``local.signal``                         ``rssi_avg_db``
``local.peak_signal``                    ``rssi_peak_db``
``max_distance_in_nautical_miles``       ``max_range_nm`` (diagnostics only)
``end`` less ``start``                      ``uptime_s``
======================================== ============================================

What the two decoders differ on
-------------------------------

readsb serves the full set above. dump1090-fa serves a smaller one: no
``max_distance_*`` at all (it does not know the receiver's position), and older
builds no ``peak_signal``. Every one of those simply stays ``None`` and
therefore ``NULL``, which is SPEC §60's *"gracefully hide unsupported decoder
metrics"* implemented as absence rather than as a zero. Nothing about the poll,
the sample or the aggregate changes shape because a decoder is the smaller one.

Positions are ``global_ok + local_ok`` because those are the two CPR decoding
paths that *yield a position*; the ``*_bad``, ``*_skipped`` and ``*_range``
counters beside them count attempts that did not. Surface and airborne counts
are not added in — they classify the same successful decodes a second time, so
summing all four would double every position.

Absence is not failure
----------------------

A decoder with no ``stats.json`` answers 404, and that is a *supported
configuration*, not an error: the endpoint is optional, FlightSite computes the
metrics it can compute itself, and the decoder-supplied columns stay ``NULL``.
So a 404 is reported as :attr:`StatsPoll.absent` and is **not** counted as an
ingestion failure — a permanently missing optional endpoint must not make
``/api/v1/health`` show a rising error count forever. Everything else — an
unreachable host, a 5xx, a truncated or non-JSON body — is a genuine failure,
is counted, and is reported as such.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

import httpx
import structlog

from flightsite.ingest import (
    DecoderEndpoint,
    DecoderError,
    DecoderParseError,
    DecoderUnavailableError,
)
from flightsite.ingest.readsb import decode_json
from flightsite.receiver_metrics.model import DecoderStats

logger = structlog.get_logger(__name__)

#: Filename both decoders serve their statistics document under.
STATS_DOCUMENT_NAME: Final = "stats.json"

#: The cumulative-since-start block. See the module docstring on why the
#: shorter windows are not read.
TOTAL_BLOCK: Final = "total"

#: HTTP statuses that mean "this decoder serves no statistics document" rather
#: than "something went wrong". 410 joins 404 because a decoder behind a proxy
#: that has retired the path answers with it.
ABSENT_STATUSES: Final = frozenset({404, 410})

#: Request timeout for one statistics poll. Shorter than the aircraft poll's:
#: nothing waits on this, and a decoder that cannot answer a few-kilobyte
#: document in three seconds is a decoder to try again in fifteen.
DEFAULT_REQUEST_TIMEOUT_S: Final = 3.0

#: Hard ceiling on one statistics document. Both decoders serve a few kilobytes;
#: a megabyte is three orders of magnitude of headroom and still small enough
#: that a misconfigured URL pointing at something enormous cannot be buffered
#: onto a Pi.
MAX_DOCUMENT_BYTES: Final = 1024 * 1024

ClientFactory = Callable[[], httpx.AsyncClient]


class StatsEndpointAbsent(DecoderError):
    """The decoder answered, but serves no statistics document.

    A supported configuration (SPEC §60), not a fault — see the module
    docstring. Kept inside the :class:`~flightsite.ingest.DecoderError`
    hierarchy so a caller that only wants "the poll did not produce stats" can
    catch one type.
    """


def stats_url_for(endpoint: DecoderEndpoint) -> str:
    """The statistics URL implied by an endpoint's aircraft document URL."""
    directory = endpoint.path.rsplit("/", 1)[0]
    return f"http://{endpoint.host}:{endpoint.port}{directory}/{STATS_DOCUMENT_NAME}"


def _number(value: object) -> float | None:
    """A finite number, or ``None`` for anything else.

    ``bool`` is rejected explicitly: it is an ``int`` in Python, and a decoder
    field that arrived as ``true`` is a shape FlightSite does not understand,
    not the number one.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _count(value: object) -> int | None:
    """A non-negative integer counter, or ``None``.

    Negative is rejected rather than clamped: these are cumulative counters, so
    a negative one is a decoder or a proxy misreporting, and inventing a zero
    would put a fabricated value into a rate.
    """
    number = _number(value)
    if number is None or number < 0:
        return None
    return int(number)


def _block(document: dict[str, Any], name: str) -> dict[str, Any]:
    """A named sub-object of the document, or an empty one if it is missing."""
    value = document.get(name)
    return value if isinstance(value, dict) else {}


def _positions(total: dict[str, Any]) -> int | None:
    """Successful CPR decodes: the global and local paths, and only those."""
    cpr = _block(total, "cpr")
    decoded = [
        count for key in ("global_ok", "local_ok") if (count := _count(cpr.get(key))) is not None
    ]
    return sum(decoded) if decoded else None


def _uptime_s(total: dict[str, Any]) -> float | None:
    """How long the cumulative block has been accumulating, in seconds."""
    start = _number(total.get("start"))
    end = _number(total.get("end"))
    if start is None or end is None or end < start:
        return None
    return end - start


def parse_stats_document(payload: object) -> DecoderStats:
    """Normalize a decoded statistics document.

    Every field is optional and every field is independently recovered, so a
    decoder that omits half of them yields a half-populated
    :class:`~flightsite.receiver_metrics.model.DecoderStats` rather than
    nothing. A document with no recognisable ``total`` block yields an empty
    one, which the caller treats exactly as it treats an absent endpoint.

    Raises:
        DecoderParseError: if the document is not a JSON object at all. That is
            a whole-document problem — a wrong URL, an error page, a proxy
            interposing — and is worth counting rather than silently reading as
            "this decoder reports nothing".
    """
    if not isinstance(payload, dict):
        raise DecoderParseError(
            f"statistics document must be a JSON object, got {type(payload).__name__}"
        )

    total = _block(payload, TOTAL_BLOCK)
    local = _block(total, "local")
    return DecoderStats(
        messages_total=_count(total.get("messages")),
        positions_total=_positions(total),
        rssi_avg_db=_number(local.get("signal")),
        rssi_peak_db=_number(local.get("peak_signal")),
        max_range_nm=_number(total.get("max_distance_in_nautical_miles")),
        uptime_s=_uptime_s(total),
    )


async def fetch_stats_document(client: httpx.AsyncClient, url: str) -> Any:
    """GET ``url`` and return the decoded JSON body.

    Raises:
        StatsEndpointAbsent: the decoder serves no statistics document.
        DecoderUnavailableError: it could not be reached, or answered with
            another error status.
        DecoderParseError: the body was oversized or is not JSON.
    """
    try:
        async with client.stream("GET", url) as response:
            if response.status_code in ABSENT_STATUSES:
                raise StatsEndpointAbsent(f"no statistics document at {url}")
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_DOCUMENT_BYTES:
                    raise DecoderParseError(
                        f"statistics document exceeds {MAX_DOCUMENT_BYTES} bytes"
                    )
                chunks.append(chunk)
    except httpx.HTTPStatusError as exc:
        raise DecoderUnavailableError(
            f"decoder returned HTTP {exc.response.status_code} for {url}"
        ) from exc
    except httpx.HTTPError as exc:
        raise DecoderUnavailableError(f"could not reach {url}: {exc}") from exc

    return decode_json(b"".join(chunks))


@dataclass(frozen=True, slots=True)
class StatsPoll:
    """The outcome of one statistics poll — never an exception.

    The three states are distinct on purpose and the caller treats them
    differently: usable statistics, a decoder that has none to give (expected,
    uncounted), and a decoder that failed to answer (counted).
    """

    stats: DecoderStats | None = None
    #: The decoder serves no statistics document. Expected, not a failure.
    absent: bool = False
    #: Why the poll failed, when it did. ``None`` on success and on absence.
    error: str | None = None

    @property
    def failed(self) -> bool:
        """True only for a genuine failure, so counters can key off it."""
        return self.error is not None


class StatsJsonPoller:
    """Polls a decoder's ``stats.json`` and normalizes what it finds.

    Deliberately *not* a :class:`~flightsite.ingest.protocol.DecoderAdapter`:
    that seam is the aircraft observation stream, whose contract is an infinite
    iterator feeding the live store. This is a one-shot request the metrics
    service makes on its own cadence, and modelling it as a second adapter
    would imply it can affect ingestion. It cannot — it shares no task, no
    client and no state with the aircraft path.

    Args:
        endpoint: the decoder endpoint; the statistics URL is derived from it.
        client_factory: builds the HTTP client. Replaced in tests with one
            wired to a mock transport.
        timeout_s: per-request timeout.
    """

    __slots__ = ("_client", "_client_factory", "_timeout_s", "_url")

    def __init__(
        self,
        endpoint: DecoderEndpoint,
        *,
        client_factory: ClientFactory | None = None,
        timeout_s: float = DEFAULT_REQUEST_TIMEOUT_S,
    ) -> None:
        self._url = stats_url_for(endpoint)
        self._timeout_s = timeout_s
        self._client_factory = client_factory if client_factory is not None else self._build_client
        self._client: httpx.AsyncClient | None = None

    @property
    def url(self) -> str:
        """The statistics URL being polled."""
        return self._url

    def _build_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout_s, follow_redirects=True)

    async def start(self) -> None:
        """Open the HTTP client. Polls nothing."""
        if self._client is None:
            self._client = self._client_factory()

    async def stop(self) -> None:
        """Close the HTTP client. Idempotent, and safe before start."""
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    async def poll(self) -> StatsPoll:
        """Fetch and normalize one reading. Never raises except on cancellation.

        The contract the metrics service depends on: whatever a decoder does —
        refuse the connection, hang until the timeout, serve an HTML error page
        — this returns a :class:`StatsPoll` describing it. A statistics poll
        can degrade the *metrics*; it can never disturb the task that took it,
        and it is nowhere near the task that ingests aircraft.
        """
        await self.start()
        client = self._client
        if client is None:  # pragma: no cover - start() always sets one
            return StatsPoll(error="no HTTP client")
        try:
            payload = await fetch_stats_document(client, self._url)
            stats = parse_stats_document(payload)
        except StatsEndpointAbsent:
            return StatsPoll(absent=True)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            return StatsPoll(error=str(exc) or type(exc).__name__)

        if stats.is_empty:
            # A document that parsed but yielded nothing usable. Reported as
            # absence rather than as failure: the decoder answered, it simply
            # has nothing this version of FlightSite recognises.
            return StatsPoll(absent=True)
        return StatsPoll(stats=stats)


__all__ = [
    "ABSENT_STATUSES",
    "DEFAULT_REQUEST_TIMEOUT_S",
    "MAX_DOCUMENT_BYTES",
    "STATS_DOCUMENT_NAME",
    "StatsEndpointAbsent",
    "StatsJsonPoller",
    "StatsPoll",
    "fetch_stats_document",
    "parse_stats_document",
    "stats_url_for",
]
