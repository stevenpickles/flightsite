"""FlightAware (piaware) — the ``piaware`` kind. The only module that speaks it.

piaware writes a ``status.json`` beside SkyAware every ``interval`` (5000 ms)
with an absolute ``expiry`` in epoch milliseconds: a document read after its
expiry is one piaware stopped refreshing, which is the best evidence there is
that piaware itself is not running.

======================== =================================================
Field                    Used as
======================== =================================================
``piaware``              service light → ``detail.service``
``adept``                FlightAware connection light → ``detail.connection``
``mlat``                 multilateration light → ``detail.mlat``
``radio``                receiver-input light → ``detail.radio``
``expiry`` / ``time``    staleness; ``time`` also ``last_data_sent`` while
                         the connection light is green
``piaware_version``      ``detail.version``
``cpu_temp_celcius``     ``detail.cpu_temp_c`` (piaware's spelling)
``system_uptime``        ``detail.system_uptime_s``
``site_url``             **never serialized** — held as
                         :attr:`PiawareProbe.stats_fallback` only
======================== =================================================

Each light is ``{status: green|amber|red, message}``. The connection, the
service and the radio being red each mean nothing reaches FlightAware, so any
of them is ``down``; an amber light, or MLAT not green, is ``degraded``.

``site_url`` names the owner's FlightAware user and site. It is exactly the
per-feeder stats page the Feeders page links to, so it is used as the stats
link when the owner has not configured one — but only through the internal
302 redirect, the same as a configured link (``docs/SECURITY.md``).
"""

from __future__ import annotations

from typing import Any, Final

import httpx

from flightsite.feeders.fetch import FetchError, block, count, fetch_json, number, text
from flightsite.feeders.model import DetailValue, FeederState, Observability, ProbeResult

#: The lights, in the order a message is chosen from, most fundamental first.
_LIGHTS: Final = (("adept", "connection"), ("piaware", "service"), ("radio", "radio"))
_MLAT_LIGHT: Final = "mlat"

_GREEN: Final = "green"
_RED: Final = "red"


def _light(document: dict[str, Any], key: str) -> tuple[str | None, str | None]:
    light = block(document, key)
    status = light.get("status")
    return (status if isinstance(status, str) else None, text(light.get("message")))


def _site_link(value: object) -> str | None:
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        return value
    return None


def parse_status(document: object, *, now_ms: int) -> tuple[ProbeResult, str | None]:
    """Normalize one ``status.json``; also return the stats-link fallback.

    The fallback is returned *beside* the result rather than in it, so there
    is no path by which it could be serialized with the result.
    """
    if not isinstance(document, dict):
        return (
            ProbeResult(
                state=FeederState.DOWN,
                observability=Observability.HTTP,
                message="FlightAware status is not a JSON object",
                failed=True,
            ),
            None,
        )

    detail: dict[str, DetailValue] = {
        "version": text(document.get("piaware_version"), limit=40),
        "cpu_temp_c": number(document.get("cpu_temp_celcius")),
        "system_uptime_s": count(document.get("system_uptime")),
    }
    lights = {label: _light(document, key) for key, label in _LIGHTS}
    mlat_status, mlat_message = _light(document, _MLAT_LIGHT)
    for label, (status, _) in lights.items():
        detail[label] = status
    detail["mlat"] = mlat_status

    fallback = _site_link(document.get("site_url"))
    metrics = {"cpu_temp_c": number(document.get("cpu_temp_celcius"))}
    expiry_ms = count(document.get("expiry"))
    written_ms = count(document.get("time"))

    if expiry_ms is not None and now_ms > expiry_ms:
        return (
            ProbeResult(
                state=FeederState.DOWN,
                observability=Observability.HTTP,
                message="piaware stopped refreshing its status",
                detail=detail,
                metrics=metrics,
            ),
            fallback,
        )

    state = FeederState.UP
    message: str | None = None
    for status, light_message in lights.values():
        if status == _RED:
            state, message = FeederState.DOWN, light_message or "FlightAware reports a red light"
            break
        if status != _GREEN and state is FeederState.UP:
            state = FeederState.DEGRADED
            message = light_message or "FlightAware reports a warning"
    if state is FeederState.UP and mlat_status is not None and mlat_status != _GREEN:
        state, message = FeederState.DEGRADED, mlat_message or "MLAT not synchronized"

    connected = lights["connection"][0] == _GREEN
    return (
        ProbeResult(
            state=state,
            observability=Observability.HTTP,
            message=message,
            last_data_sent_ms=(written_ms or now_ms) if connected else None,
            detail=detail,
            metrics=metrics,
        ),
        fallback,
    )


class PiawareProbe:
    """Polls piaware's ``status.json`` (``entry.url`` is the document itself)."""

    __slots__ = ("_client", "_name", "_stats_fallback", "_url")

    kind = "piaware"

    def __init__(self, name: str, *, url: str | None, client: httpx.AsyncClient) -> None:
        self._name = name
        self._url = url
        self._client = client
        self._stats_fallback: str | None = None

    @property
    def name(self) -> str:
        return self._name

    @property
    def stats_fallback(self) -> str | None:
        """The owner's FlightAware stats page, if piaware has told us it."""
        return self._stats_fallback

    async def probe(self, now_ms: int) -> ProbeResult:
        """One poll. Never raises."""
        if self._url is None:
            return ProbeResult(
                state=FeederState.UNKNOWN,
                observability=Observability.NONE,
                message="No status URL configured",
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
        result, fallback = parse_status(document, now_ms=now_ms)
        if fallback is not None:
            self._stats_fallback = fallback
        return result


__all__ = ["PiawareProbe", "parse_status"]
