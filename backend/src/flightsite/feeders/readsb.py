"""The receiver itself (readsb / ultrafeeder) — the ``readsb`` kind.

The one module in :mod:`flightsite.feeders` that reads the decoder's own
documents. It is the second, deliberately separate reader of ``stats.json``
beside :mod:`flightsite.receiver_metrics.statsjson`: that one records the
receiver's *reception* history (ADR-0009); this one reports the receiver's
*uplink* — what it is sending onward to every network, right now — and the two
share neither a cadence nor a failure mode. Both are named in
``tests/receiver_metrics/test_field_isolation.py`` as the modules allowed to
speak the statistics vocabulary.

``entry.url`` is the decoder's web root (``http://host:8080/``); the documents
are ``data/status.json`` (refreshed every second) and ``data/stats.json``.

================================================ ============================
Field                                            Normalized to
================================================ ============================
status ``now``                                   staleness
status ``uptime``                                ``uptime_s``
status ``aircraft_with_pos`` (+ ``_without_pos``)  ``aircraft_with_pos`` / ``aircraft``
status ``aircraft_count_by_type.mlat``           ``mlat_inbound``
stats ``gain_db``                                ``gain_db``
stats ``last1min.messages``                      ``messages_per_min``
stats ``last1min.position_count_total``          ``positions_per_min`` (else
                                                 ``cpr.global_ok + local_ok``)
stats ``last1min.local.signal`` / ``noise``      ``signal_db`` / ``noise_db``
stats ``last1min.local.samples_dropped``         ``dropped_samples``
stats ``total.remote.bytes_out``                 ``bytes_out_rate_per_s`` (differenced)
stats ``total.max_distance_in_nautical_miles``   ``max_range_nm`` (or
                                                 ``max_distance`` metres)
================================================ ============================

``bytes_out`` is cumulative since the decoder started and counts bytes to
*all* connectors together, so the rate is the difference between two polls —
``None`` on the first poll after a start and after a counter reset, never an
invented figure (SPEC §39). **The receiver's coordinates are never read**: the
detail block is built from the fields above and nothing else.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Final

import httpx

from flightsite.feeders.fetch import FetchError, block, count, fetch_json, join_url, number
from flightsite.feeders.model import (
    DetailValue,
    FeederState,
    MetricValue,
    Observability,
    ProbeResult,
    ReceiverUplink,
)

STATUS_PATH: Final = "data/status.json"
STATS_PATH: Final = "data/stats.json"

#: ``status.json`` older than this means the decoder stopped writing it.
STALE_AFTER_MS: Final = 60 * 1000

METRES_PER_NM: Final = 1852.0


def _max_range_nm(total: dict[str, Any]) -> float | None:
    nautical = number(total.get("max_distance_in_nautical_miles"))
    if nautical is not None:
        return nautical
    metres = number(total.get("max_distance"))
    return None if metres is None else metres / METRES_PER_NM


def _positions(minute: dict[str, Any]) -> int | None:
    """Positions decoded in the last minute: readsb's own total, else the CPR paths."""
    total = count(minute.get("position_count_total"))
    if total is not None:
        return total
    cpr = block(minute, "cpr")
    decoded = [n for key in ("global_ok", "local_ok") if (n := count(cpr.get(key))) is not None]
    return sum(decoded) if decoded else None


def parse_documents(
    status: object, stats: object | None, *, now_ms: int
) -> tuple[ReceiverUplink, int | None, int | None]:
    """Normalize the two documents.

    Returns the uplink summary (its ``bytes_out_rate_per_s`` left for the caller to
    fill, since only the caller has the previous poll), the cumulative
    bytes-out counter, and the status document's own timestamp.
    """
    status_doc: dict[str, Any] = status if isinstance(status, dict) else {}
    stats_doc: dict[str, Any] = stats if isinstance(stats, dict) else {}
    minute = block(stats_doc, "last1min")
    local = block(minute, "local")
    total = block(stats_doc, "total")

    with_pos = count(status_doc.get("aircraft_with_pos"))
    without_pos = count(status_doc.get("aircraft_without_pos"))
    written_s = number(status_doc.get("now"))
    uplink = ReceiverUplink(
        messages_per_min=count(minute.get("messages")),
        positions_per_min=_positions(minute),
        aircraft=(
            with_pos + without_pos if with_pos is not None and without_pos is not None else None
        ),
        aircraft_with_pos=with_pos,
        mlat_inbound=count(block(status_doc, "aircraft_count_by_type").get("mlat")),
        dropped_samples=count(local.get("samples_dropped")),
        max_range_nm=_max_range_nm(total),
        gain_db=number(stats_doc.get("gain_db")),
        signal_db=number(local.get("signal")),
        noise_db=number(local.get("noise")),
        uptime_s=number(status_doc.get("uptime")),
        updated_ms=int(written_s * 1000) if written_s is not None else now_ms,
    )
    bytes_out = count(block(total, "remote").get("bytes_out"))
    return uplink, bytes_out, None if written_s is None else int(written_s * 1000)


class ReadsbProbe:
    """Polls the decoder's ``status.json`` and ``stats.json``."""

    __slots__ = ("_client", "_last_sent_ms", "_name", "_previous", "_url")

    kind = "readsb"

    def __init__(self, name: str, *, url: str | None, client: httpx.AsyncClient) -> None:
        self._name = name
        self._url = url
        self._client = client
        #: (poll ms, cumulative bytes out) of the previous successful poll.
        self._previous: tuple[int, int] | None = None
        self._last_sent_ms: int | None = None

    @property
    def name(self) -> str:
        return self._name

    def _rate(self, now_ms: int, bytes_out: int | None) -> float | None:
        previous, self._previous = (
            self._previous,
            ((now_ms, bytes_out) if bytes_out is not None else None),
        )
        if previous is None or bytes_out is None:
            return None
        then_ms, then_bytes = previous
        if now_ms <= then_ms or bytes_out < then_bytes:
            return None
        if bytes_out > then_bytes:
            self._last_sent_ms = now_ms
        return (bytes_out - then_bytes) * 1000.0 / (now_ms - then_ms)

    async def probe(self, now_ms: int) -> ProbeResult:
        """One poll of both documents. Never raises."""
        if self._url is None:
            return ProbeResult(
                state=FeederState.UNKNOWN,
                observability=Observability.NONE,
                message="No receiver URL configured",
            )
        try:
            status = await fetch_json(self._client, join_url(self._url, STATUS_PATH))
        except FetchError as exc:
            self._previous = None
            return ProbeResult(
                state=FeederState.DOWN,
                observability=Observability.HTTP,
                message=str(exc),
                failed=True,
            )
        stats: object | None
        stats_error: str | None = None
        try:
            stats = await fetch_json(self._client, join_url(self._url, STATS_PATH))
        except FetchError as exc:
            stats, stats_error = None, str(exc)

        uplink, bytes_out, written_ms = parse_documents(status, stats, now_ms=now_ms)
        rate = self._rate(now_ms, bytes_out)
        uplink = replace(uplink, bytes_out_rate_per_s=rate)
        metrics: dict[str, MetricValue] = {
            "bytes_out_rate_per_s": rate,
            "messages_per_min": uplink.messages_per_min,
            "positions_per_min": uplink.positions_per_min,
            "aircraft_with_pos": uplink.aircraft_with_pos,
            "mlat_inbound": uplink.mlat_inbound,
        }
        detail: dict[str, DetailValue] = {
            "uptime_s": uplink.uptime_s,
            "messages_per_min": uplink.messages_per_min,
            "aircraft_with_pos": uplink.aircraft_with_pos,
        }

        state, message = FeederState.UP, stats_error
        if written_ms is not None and now_ms - written_ms > STALE_AFTER_MS:
            state, message = FeederState.DOWN, "The decoder stopped updating its status"
        elif uplink.messages_per_min == 0:
            state, message = FeederState.DEGRADED, "No messages decoded in the last minute"
        return ProbeResult(
            state=state,
            observability=Observability.HTTP,
            message=message,
            last_data_sent_ms=self._last_sent_ms,
            detail=detail,
            metrics=metrics,
            receiver=uplink,
        )


__all__ = ["STATS_PATH", "STATUS_PATH", "ReadsbProbe", "parse_documents"]
