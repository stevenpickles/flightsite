"""FlightRadar24 (fr24feed) — the ``fr24`` kind. The only module that speaks it.

fr24feed serves ``monitor.json`` on its web UI port. **Every value is a
string**, numbers and booleans included, so each field is coerced here and
nowhere else.

=============================== ==============================================
Field                           Used as
=============================== ==============================================
``feed_status``                 ``connected`` is feeding; anything else is not
``feed_status_message``         the card message when not connected
``rx_connected``                ``"1"`` when fr24feed has receiver input
``feed_last_ac_sent_time``      epoch seconds → ``last_data_sent``
``feed_last_ac_sent_num``       ``detail.aircraft_sent`` / metric
``feed_last_connected_time``    ``detail.connected_since_ms``
``feed_current_server``         ``detail.server``
``num_messages``                ``detail.messages`` / metric
``timing_source``               ``detail.timing_source``
``time_update_utc``             staleness, when it parses
``build_version``               ``detail.version``
=============================== ==============================================

**Redacted, always:** :data:`REDACTED_FIELDS`. ``fr24key`` is the sharing key
that *is* the owner's FR24 identity, the alias and legacy id name the feeder,
and ``local_ips`` maps the LAN. The detail block is built from an allowlist,
so those fields are never copied in the first place; the list exists so the
test suite can plant sentinels in exactly those fields and prove it
(``tests/feeders/test_redaction.py``). The feeder UI's ``/settings.html`` is
never linked either — it would show the key.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

import httpx

from flightsite.feeders.fetch import FetchError, count, fetch_json, number, text
from flightsite.feeders.model import DetailValue, FeederState, Observability, ProbeResult

#: monitor.json fields that identify the owner or their network. Never read.
REDACTED_FIELDS: Final = ("fr24key", "feed_alias", "feed_legacy_id", "local_ips")

#: While connected, no aircraft sent for this long reads as ``degraded``.
SILENT_AFTER_MS: Final = 5 * 60 * 1000

#: A document not updated for this long reads as ``down`` (fr24feed updates
#: it every few seconds while running).
STALE_AFTER_MS: Final = 2 * 60 * 1000

_CONNECTED: Final = "connected"
_TIME_FORMATS: Final = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S")

#: An update time further than this from the clock, either way, is taken to be
#: a rendering this module misread rather than evidence: a misparsed date must
#: never be what marks a feeder down.
_PLAUSIBLE_SKEW_MS: Final = 24 * 60 * 60 * 1000


def _epoch_ms(value: object) -> int | None:
    """An epoch-seconds string (the ``*_time`` fields) as epoch ms."""
    seconds = number(value)
    if seconds is None or seconds <= 0:
        return None
    return int(seconds * 1000)


def _utc_ms(value: object) -> int | None:
    """``time_update_utc`` in whichever of fr24feed's renderings it arrives."""
    as_number = _epoch_ms(value)
    if as_number is not None:
        return as_number
    if not isinstance(value, str):
        return None
    for fmt in _TIME_FORMATS:
        try:
            return int(datetime.strptime(value.strip(), fmt).replace(tzinfo=UTC).timestamp() * 1000)
        except ValueError:
            continue
    return None


def parse_monitor(document: object, *, now_ms: int) -> ProbeResult:
    """Normalize one ``monitor.json``."""
    if not isinstance(document, dict):
        return ProbeResult(
            state=FeederState.DOWN,
            observability=Observability.HTTP,
            message="FR24 monitor is not a JSON object",
            failed=True,
        )
    doc: dict[str, Any] = document
    status = text(doc.get("feed_status"), limit=40)
    receiver_input = text(doc.get("rx_connected"), limit=8)
    last_sent_ms = _epoch_ms(doc.get("feed_last_ac_sent_time"))
    aircraft_sent = count(doc.get("feed_last_ac_sent_num"))
    messages = count(doc.get("num_messages"))
    updated_ms = _utc_ms(doc.get("time_update_utc"))

    detail: dict[str, DetailValue] = {
        "status": status,
        "server": text(doc.get("feed_current_server"), limit=120),
        "connected_since_ms": _epoch_ms(doc.get("feed_last_connected_time")),
        "receiver_input": None if receiver_input is None else receiver_input == "1",
        "aircraft_sent": aircraft_sent,
        "messages": messages,
        "timing_source": text(doc.get("timing_source"), limit=40),
        "version": text(doc.get("build_version"), limit=60),
    }
    metrics = {"aircraft_sent": aircraft_sent, "messages": messages}

    def result(state: FeederState, message: str | None) -> ProbeResult:
        return ProbeResult(
            state=state,
            observability=Observability.HTTP,
            message=message,
            last_data_sent_ms=last_sent_ms,
            detail=detail,
            metrics=metrics,
        )

    if updated_ms is not None and STALE_AFTER_MS < now_ms - updated_ms < _PLAUSIBLE_SKEW_MS:
        return result(FeederState.DOWN, "fr24feed stopped updating its monitor")
    if status is None or status.lower() != _CONNECTED:
        reason = text(doc.get("feed_status_message")) or f"Feed status: {status or 'unknown'}"
        return result(FeederState.DOWN, reason)
    if receiver_input == "0":
        return result(FeederState.DOWN, "fr24feed has no receiver input")
    if last_sent_ms is not None and now_ms - last_sent_ms > SILENT_AFTER_MS:
        return result(FeederState.DEGRADED, "Connected, but no aircraft sent recently")
    return result(FeederState.UP, None)


class Fr24Probe:
    """Polls fr24feed's ``monitor.json`` (``entry.url`` is the document itself)."""

    __slots__ = ("_client", "_name", "_url")

    kind = "fr24"

    def __init__(self, name: str, *, url: str | None, client: httpx.AsyncClient) -> None:
        self._name = name
        self._url = url
        self._client = client

    @property
    def name(self) -> str:
        return self._name

    async def probe(self, now_ms: int) -> ProbeResult:
        """One poll. Never raises."""
        if self._url is None:
            return ProbeResult(
                state=FeederState.UNKNOWN,
                observability=Observability.NONE,
                message="No monitor URL configured",
            )
        try:
            document = await fetch_json(self._client, self._url)
        except FetchError as exc:
            return ProbeResult(
                state=FeederState.DOWN,
                observability=Observability.HTTP,
                message=str(exc),
                failed=True,
            )
        return parse_monitor(document, now_ms=now_ms)


__all__ = ["REDACTED_FIELDS", "Fr24Probe", "parse_monitor"]
