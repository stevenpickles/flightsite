"""The probe seam, and the shape of configuration this package reads.

Two contracts live here.

**:class:`FeederProbe`** is what the service polls: a name, a kind, and one
coroutine that answers "what is this feeder doing right now" with a
:class:`~flightsite.feeders.model.ProbeResult` and never raises. Each vendor
module implements it; so does every demo stand-in
(:mod:`flightsite.demo.feeders`), which is what lets the demo stack drive the
Feeders page with no network at all.

**The ``*Like`` protocols** are the configuration this package consumes,
stated structurally rather than imported from
:mod:`flightsite.config.models`. The service only ever *reads* its settings,
and depending on the read-only shape keeps the feeders package importable —
and testable — without the whole configuration model, and keeps a config
schema change from being a feeders change unless it touches these fields.
URLs are typed ``object`` because a validated URL type and a plain ``str``
both render correctly through ``str()``, which is all a probe does with one.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx
from pydantic import SecretStr

from flightsite.feeders.model import ProbeResult

if TYPE_CHECKING:
    from flightsite.feeders.docker import DockerClient


class FeederEntryLike(Protocol):
    """One configured feeder — ``feeders.entries[]`` in ``config.yaml``."""

    @property
    def name(self) -> str: ...
    @property
    def label(self) -> str: ...
    @property
    def kind(self) -> str: ...
    @property
    def url(self) -> object: ...
    @property
    def web_url(self) -> object: ...
    @property
    def host(self) -> str | None: ...
    @property
    def mlat_port(self) -> int | None: ...
    @property
    def beast_port(self) -> int | None: ...
    @property
    def container(self) -> str | None: ...


class LocalPageLike(Protocol):
    """One ``feeders.local_pages[]`` link."""

    @property
    def label(self) -> str: ...
    @property
    def url(self) -> object: ...


class FeederSettingsLike(Protocol):
    """The ``feeders`` section, with its ``secrets.yaml`` half merged in."""

    @property
    def poll_interval_s(self) -> float: ...
    @property
    def docker_socket(self) -> object: ...
    @property
    def entries(self) -> Sequence[FeederEntryLike]: ...
    @property
    def local_pages(self) -> Sequence[LocalPageLike]: ...
    @property
    def stats_urls(self) -> Mapping[str, SecretStr]: ...


@runtime_checkable
class FeederProbe(Protocol):
    """Reads one feeder's state. Implementations never raise.

    ``now_ms`` is the service's clock, passed in rather than read, so a probe's
    staleness arithmetic runs against the same instant the service stamps the
    result with — and against a hand-driven clock in tests.
    """

    @property
    def name(self) -> str: ...

    @property
    def kind(self) -> str: ...

    async def probe(self, now_ms: int) -> ProbeResult: ...


@runtime_checkable
class StatsFallbackSource(Protocol):
    """A probe that discovered a stats link on its own (FlightAware only).

    The value is a secret in everything but name — it identifies the owner's
    account — so it is read only by
    :meth:`~flightsite.feeders.service.FeederService.stats_url` for the
    internal redirect, and never reaches a :class:`ProbeResult`, a log line or
    ``/api/v1``.
    """

    @property
    def stats_fallback(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class ProbeContext:
    """The shared clients a probe is built with.

    Owned by the service: one HTTP client for every HTTP probe, and one Docker
    client — or ``None`` when ``feeders.docker_socket`` is unset, which is the
    default and a fully supported state.
    """

    http: httpx.AsyncClient
    docker: DockerClient | None


#: Builds the probe for one configured entry.
ProbeFactory = Callable[[FeederEntryLike, ProbeContext], FeederProbe]


def text_or_none(value: object) -> str | None:
    """A configured URL-ish value as a non-empty string, or ``None``."""
    if value is None:
        return None
    rendered = str(value).strip()
    return rendered or None


__all__ = [
    "FeederEntryLike",
    "FeederProbe",
    "FeederSettingsLike",
    "LocalPageLike",
    "ProbeContext",
    "ProbeFactory",
    "StatsFallbackSource",
    "text_or_none",
]
