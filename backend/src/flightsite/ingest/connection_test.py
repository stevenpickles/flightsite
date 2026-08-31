"""One-shot decoder connection test.

SPEC §11 requires the receiver configuration to include a connection test.
This is it: a single request against a candidate endpoint that answers the
question the setup wizard (slice 018) and the Settings UI (slice 019) actually
ask — *"if I save this, will FlightSite see aircraft?"* — and answers it
without touching the running ingestion loop, so testing a new endpoint never
disturbs the one currently feeding the live map.

The result deliberately separates *why* a test failed into
:class:`ConnectionTestError` kinds, because the remedies differ: an
unreachable host is a network or address problem, an HTTP 404 is a wrong path
(the two decoders serve ``/data/aircraft.json`` and ``/dump1090-fa/data/
aircraft.json`` respectively), and a valid response that is not an aircraft
document usually means the port belongs to something else entirely.

A successful test also reports how many aircraft the decoder was tracking and
its best-effort flavor guess, which is what lets the wizard say "found
readsb, 37 aircraft (24 with positions)" instead of a bare green tick.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final

import httpx
import structlog

from flightsite.ingest.protocol import DecoderParseError, DecoderUnavailableError
from flightsite.ingest.readsb import ClientFactory, build_client, fetch_document, probe_document
from flightsite.ingest.types import DecoderEndpoint, DecoderFlavor

logger = structlog.get_logger(__name__)

#: Timeout for a connection test. Longer than a poll's, because a human is
#: waiting for a definite answer and a slow "yes" beats a fast "maybe".
CONNECTION_TEST_TIMEOUT_S: Final = 8.0


class ConnectionTestError(StrEnum):
    """Why a connection test failed, in terms that map to a user remedy."""

    UNREACHABLE = "unreachable"
    """No HTTP response: wrong host/port, host down, or firewalled."""

    HTTP_ERROR = "http_error"
    """The server answered with an error status — usually a wrong path."""

    INVALID_DOCUMENT = "invalid_document"
    """Something answered, but it is not a decoder aircraft document."""


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    """The outcome of one connection test."""

    ok: bool
    url: str
    elapsed_ms: float
    error: ConnectionTestError | None = None
    detail: str | None = None
    aircraft_count: int | None = None
    positioned_count: int | None = None
    flavor: DecoderFlavor | None = None
    decoder_time: datetime | None = None


async def check_connection(
    endpoint: DecoderEndpoint,
    *,
    client_factory: ClientFactory | None = None,
    timeout_s: float = CONNECTION_TEST_TIMEOUT_S,
) -> ConnectionTestResult:
    """Probe ``endpoint`` once and describe what was found.

    Never raises for a decoder-side problem: an unreachable host, an error
    status and a nonsense body all come back as an ``ok=False`` result, since
    the caller is a UI that must render every one of them.

    Args:
        endpoint: candidate host/port/path. ``poll_interval_s`` is ignored.
        client_factory: builds the HTTP client; injected by tests.
        timeout_s: request timeout applied when building the default client.
    """
    url = endpoint.url
    factory = client_factory if client_factory is not None else (lambda: build_client(timeout_s))
    started = time.monotonic()

    client = factory()
    try:
        payload = await fetch_document(client, url)
        probe = probe_document(payload, received_at=datetime.now(UTC))
    except DecoderUnavailableError as exc:
        return _failure(url, started, _unavailable_kind(exc), str(exc))
    except DecoderParseError as exc:
        return _failure(url, started, ConnectionTestError.INVALID_DOCUMENT, str(exc))
    except Exception as exc:  # a UI must be able to render every failure
        return _failure(url, started, ConnectionTestError.UNREACHABLE, _describe(exc))
    finally:
        await client.aclose()

    logger.info(
        "decoder_connection_test_ok",
        url=url,
        aircraft_count=probe.aircraft_count,
        flavor=str(probe.flavor),
    )
    return ConnectionTestResult(
        ok=True,
        url=url,
        elapsed_ms=_elapsed_ms(started),
        aircraft_count=probe.aircraft_count,
        positioned_count=probe.positioned_count,
        flavor=probe.flavor,
        decoder_time=probe.timestamp,
    )


def _unavailable_kind(exc: DecoderUnavailableError) -> ConnectionTestError:
    """Split "no answer" from "an error answer"."""
    cause = exc.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        return ConnectionTestError.HTTP_ERROR
    return ConnectionTestError.UNREACHABLE


def _describe(exc: BaseException) -> str:
    return str(exc) or type(exc).__name__


def _elapsed_ms(started: float) -> float:
    return round((time.monotonic() - started) * 1000.0, 3)


def _failure(
    url: str, started: float, kind: ConnectionTestError, detail: str
) -> ConnectionTestResult:
    logger.info("decoder_connection_test_failed", url=url, error=str(kind), detail=detail)
    return ConnectionTestResult(
        ok=False,
        url=url,
        elapsed_ms=_elapsed_ms(started),
        error=kind,
        detail=detail,
    )


__all__ = [
    "CONNECTION_TEST_TIMEOUT_S",
    "ConnectionTestError",
    "ConnectionTestResult",
    "check_connection",
]
