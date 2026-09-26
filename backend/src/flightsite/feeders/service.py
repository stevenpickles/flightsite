"""The feeder service: a poller, a state machine per feeder, and a maintenance loop.

Modelled on :mod:`flightsite.receiver_metrics.service` and for the same
reasons: its own low-frequency asyncio tasks, nothing on the ingestion path,
and every write a short transaction through the process's one serialized
writer (ADR-0001, ADR-0008).

The cadences
------------

* **Polling** every ``feeders.poll_interval_s`` (default 15 s): every probe
  runs concurrently, each bounded by its own 3-second request timeouts, so one
  unreachable network never delays another. The first poll runs immediately
  on start, so a fresh page has real states within one interval.
* **Sampling** — one stored reading per feeder per
  :data:`DEFAULT_SAMPLE_INTERVAL_S`, buffered and written every
  :data:`DEFAULT_FLUSH_INTERVAL_S` in one transaction.
* **Maintenance** every :data:`DEFAULT_MAINTENANCE_INTERVAL_S`: prune samples
  older than :data:`DEFAULT_SAMPLE_RETENTION_DAYS` and closed episodes older
  than :data:`DEFAULT_EPISODE_RETENTION_DAYS` (``docs/DATA_MODEL.md`` §9).

The state machine
-----------------

A probe reports what it sees *now*; the service decides what to *commit*.
Everything but ``down`` commits at once. ``down`` commits only after
:data:`DOWN_DEBOUNCE_POLLS` consecutive ``down`` readings, so a single
dropped request never costs the owner an offline notification and a gap on
the timeline. While a ``down`` reading is held back, the card keeps showing
the committed state.

Each committed change closes the feeder's current
:class:`~flightsite.feeders.model.FeederEpisode` and opens the next. A ``down``
episode starts at the **first** failing poll, not at the poll that got past
the debounce, so the timeline and the outage's duration are honest about when
the feed actually stopped.

The injected ``on_transition`` listener hears about outages only, as
:class:`flightsite.activity.FeederEpisode` facts — ``offline=True`` on the
transition into ``down`` (``since_ms`` = ``at_ms`` = the outage row's
``started_ms``), ``offline=False`` when the feeder is next seen ``up`` or
``degraded`` (``since_ms`` the same outage start, ``at_ms`` the restore). A
spell of ``unknown`` in between neither ends the outage nor starts a second
one: FlightSite losing sight of a feed is not the feed recovering. The
listener is synchronous and must not raise; if it does, the error is logged
and polling carries on.

Stopping cleanly closes every open episode at the stop instant, silently —
the process stopping is not a feeder transition. An unclean stop leaves them
open, and the next start closes each at the last sample the old process wrote
(:meth:`~flightsite.feeders.repository.FeederRepository.close_dangling`).

Hot apply
---------

:meth:`FeederService.apply_settings` takes a saved ``feeders`` section and
rebuilds what changed. A feeder whose name survives keeps its committed state,
its episode and its debounce count; its probe is rebuilt only if its entry
changed (or the Docker socket did). Removed feeders have their open episode
closed. With no entries left, the poll and maintenance tasks stop; adding the
first entry to a started service starts them.

Secrets
-------

Stats URLs live in ``feeders.stats_urls`` (``SecretStr``) and, for
FlightAware, in the probe's :attr:`~flightsite.feeders.piaware.PiawareProbe.stats_fallback`.
Only :meth:`FeederService.stats_url` ever reads them, for the internal
redirect. :meth:`FeederService.report` says only whether one exists.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Literal, get_args

import httpx
import structlog
from pydantic import SecretStr

from flightsite.activity.facts import FeederEpisode as OutageFact
from flightsite.counters import CounterRegistry
from flightsite.counters import counters as default_counters
from flightsite.db.clock import MS_PER_SECOND, utc_now_ms
from flightsite.db.engine import Database
from flightsite.db.startup import DB_ERRORS_COUNTER
from flightsite.feeders.docker import DockerClient, DockerFactory, DockerHealthProbe
from flightsite.feeders.fetch import REQUEST_TIMEOUT_S
from flightsite.feeders.fr24 import Fr24Probe
from flightsite.feeders.model import (
    AdsbOutStatus,
    DetailValue,
    FeederEpisode,
    FeederKind,
    FeederSample,
    FeederState,
    FeederStatus,
    MlatStatus,
    Observability,
    ProbeResult,
    ReceiverUplink,
)
from flightsite.feeders.opensky import OpenSkyLogsProbe
from flightsite.feeders.piaware import PiawareProbe
from flightsite.feeders.protocol import (
    FeederEntryLike,
    FeederProbe,
    FeederSettingsLike,
    LocalPageLike,
    ProbeContext,
    ProbeFactory,
    StatsFallbackSource,
    text_or_none,
)
from flightsite.feeders.readsb import ReadsbProbe
from flightsite.feeders.repository import FeederRepository
from flightsite.feeders.ultrafeeder import UltrafeederProbe

logger = structlog.get_logger(__name__)

#: Counter a genuinely failed probe increments (``flightsite.counters``).
POLL_FAILURES_COUNTER: Final = "feeder_poll_failures"

#: Consecutive ``down`` readings before ``down`` is committed.
DOWN_DEBOUNCE_POLLS: Final = 2

DEFAULT_POLL_INTERVAL_S: Final = 15.0
DEFAULT_SAMPLE_INTERVAL_S: Final = 60.0
DEFAULT_FLUSH_INTERVAL_S: Final = 60.0
DEFAULT_MAINTENANCE_INTERVAL_S: Final = 300.0
DEFAULT_SAMPLE_RETENTION_DAYS: Final = 14
DEFAULT_EPISODE_RETENTION_DAYS: Final = 90

#: Buffered samples before the oldest are shed (a few hours of six feeders).
MAX_PENDING_SAMPLES: Final = 2_000

MS_PER_MINUTE: Final = 60 * MS_PER_SECOND
MS_PER_DAY: Final = 24 * 60 * MS_PER_MINUTE

#: ``GET /api/v1/feeders/{name}/history?window=`` values.
HistoryWindow = Literal["24h", "7d", "30d"]
HISTORY_WINDOWS: Final = frozenset(get_args(HistoryWindow))
WINDOW_MS: Final[Mapping[str, int]] = {
    "24h": MS_PER_DAY,
    "7d": 7 * MS_PER_DAY,
    "30d": 30 * MS_PER_DAY,
}
#: Sample bucket per window: one point per bucket (the latest), so every window
#: answers with at most ~1 500 points per feeder.
BUCKET_MS: Final[Mapping[str, int]] = {
    "24h": MS_PER_MINUTE,
    "7d": 10 * MS_PER_MINUTE,
    "30d": 30 * MS_PER_MINUTE,
}

#: ``docker_socket`` as the API and diagnostics report it.
DockerSocketStatus = Literal["available", "unset", "unreachable"]

#: Hears every outage start and end (see "The state machine"). Synchronous;
#: must not raise.
TransitionListener = Callable[[OutageFact], None]
EpochClock = Callable[[], int]
Sleeper = Callable[[float], Awaitable[None]]
ClientFactory = Callable[[], httpx.AsyncClient]

#: States that count as "feeding" for ``availability_pct``.
_AVAILABLE: Final = frozenset({FeederState.UP, FeederState.DEGRADED})
#: States that count at all — ``unknown`` time is time nobody could see.
_KNOWN: Final = frozenset({FeederState.UP, FeederState.DEGRADED, FeederState.DOWN})


def iso_ms(epoch_ms: int | None) -> str | None:
    """``docs/API.md`` §2.2 UTC ISO-8601 with milliseconds, or ``None``."""
    if epoch_ms is None:
        return None
    moment = datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)
    return f"{moment.strftime('%Y-%m-%dT%H:%M:%S')}.{moment.microsecond // 1000:03d}Z"


def _default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, follow_redirects=False)


@dataclass(frozen=True, slots=True)
class FeederEntry:
    """A configured entry, normalized. Also what the demo configures itself with."""

    name: str
    label: str
    kind: str
    url: str | None = None
    web_url: str | None = None
    host: str | None = None
    mlat_port: int | None = None
    beast_port: int | None = None
    container: str | None = None

    @classmethod
    def of(cls, entry: FeederEntryLike) -> FeederEntry:
        return cls(
            name=entry.name,
            label=entry.label,
            kind=str(entry.kind),
            url=text_or_none(entry.url),
            web_url=text_or_none(entry.web_url),
            host=entry.host,
            mlat_port=entry.mlat_port,
            beast_port=entry.beast_port,
            container=entry.container,
        )


@dataclass(frozen=True, slots=True)
class LocalPage:
    """A ``feeders.local_pages[]`` link, normalized."""

    label: str
    url: str

    @classmethod
    def of(cls, page: LocalPageLike) -> LocalPage | None:
        url = text_or_none(page.url)
        return None if url is None else cls(label=page.label, url=url)


@dataclass(frozen=True, slots=True)
class _SettingsView:
    """A ``feeders`` section assembled from constructor keywords."""

    poll_interval_s: float = DEFAULT_POLL_INTERVAL_S
    docker_socket: str | None = None
    entries: Sequence[FeederEntryLike] = ()
    local_pages: Sequence[LocalPageLike] = ()
    stats_urls: Mapping[str, SecretStr] = field(default_factory=dict)


def build_probe(entry: FeederEntryLike, context: ProbeContext) -> FeederProbe:
    """The production :data:`~flightsite.feeders.protocol.ProbeFactory`."""
    normalized = FeederEntry.of(entry)
    kind = normalized.kind
    if kind == FeederKind.READSB:
        return ReadsbProbe(normalized.name, url=normalized.url, client=context.http)
    if kind == FeederKind.PIAWARE:
        return PiawareProbe(normalized.name, url=normalized.url, client=context.http)
    if kind == FeederKind.FR24:
        return Fr24Probe(normalized.name, url=normalized.url, client=context.http)
    if kind == FeederKind.ULTRAFEEDER:
        return UltrafeederProbe(
            normalized.name,
            url=normalized.url,
            host=normalized.host,
            mlat_port=normalized.mlat_port,
            beast_port=normalized.beast_port,
            container=normalized.container,
            client=context.http,
            docker=context.docker,
        )
    if kind == FeederKind.OPENSKY_LOGS:
        return OpenSkyLogsProbe(
            normalized.name, container=normalized.container, docker=context.docker
        )
    if kind == FeederKind.DOCKER_HEALTH:
        return DockerHealthProbe(
            normalized.name, container=normalized.container, docker=context.docker
        )
    return LinkOnlyProbe(normalized.name)


class LinkOnlyProbe:
    """The ``link_only`` kind (and any kind this build does not know): links, no state."""

    __slots__ = ("_name",)

    kind = "link_only"

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    async def probe(self, now_ms: int) -> ProbeResult:
        return ProbeResult(state=FeederState.UNKNOWN, observability=Observability.NONE)


@dataclass(slots=True)
class _Tracker:
    """One feeder's mutable state across polls."""

    entry: FeederEntry
    probe: FeederProbe
    state: FeederState = FeederState.UNKNOWN
    observability: Observability = Observability.NONE
    episode_started_ms: int | None = None
    held_downs: int = 0
    #: When the current run of ``down`` readings began (debounce pending).
    first_down_ms: int | None = None
    #: When the announced, not-yet-restored outage began.
    outage_since_ms: int | None = None
    last_polled_ms: int | None = None
    last_success_ms: int | None = None
    last_data_sent_ms: int | None = None
    last_sample_ms: int | None = None
    message: str | None = None
    mlat: MlatStatus | None = None
    adsb_out: AdsbOutStatus | None = None
    detail: Mapping[str, DetailValue] = field(default_factory=dict)


class FeederService:
    """Polls every configured feeder and keeps its status and history.

    Args:
        database: the application database; writes take its single writer lock.
        settings: the whole ``feeders`` section (with ``stats_urls`` merged in
            from ``secrets.yaml``). Alternatively pass its parts as ``entries``
            / ``docker_socket`` / ``poll_interval_s`` / ``local_pages`` /
            ``stats_urls``; ``settings`` wins when both are given. No entries
            is a fully supported state in which nothing is polled.
        probes: ready-made probes that replace construction for their names —
            the demo's stand-ins. A probe carrying an ``entry`` attribute
            brings that entry with it when it is not configured, and a
            collection carrying ``local_pages`` brings those, so demo mode
            shows a full page on an install with no feeders configured.
        on_transition: hears every outage start and end.
        probe_factory: builds a probe per entry.
        client_factory: builds the shared HTTP client.
        docker_factory: builds the Docker client for a configured socket.
            Never called when ``feeders.docker_socket`` is unset.
        sample_interval_s / flush_interval_s / maintenance_interval_s: cadences.
        sample_retention_days / episode_retention_days: pruning horizons.
        clock: UTC epoch-millisecond source.
        sleep: awaited between ticks; injected so tests drive the cadence.
        counters: receives poll and write failures.
    """

    def __init__(
        self,
        *,
        database: Database,
        settings: FeederSettingsLike | None = None,
        entries: Sequence[FeederEntryLike] | None = None,
        docker_socket: str | None = None,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        local_pages: Sequence[LocalPageLike] | None = None,
        stats_urls: Mapping[str, SecretStr] | None = None,
        probes: Iterable[FeederProbe] | Mapping[str, FeederProbe] | None = None,
        on_transition: TransitionListener | None = None,
        probe_factory: ProbeFactory = build_probe,
        client_factory: ClientFactory = _default_client,
        docker_factory: DockerFactory = DockerClient,
        sample_interval_s: float = DEFAULT_SAMPLE_INTERVAL_S,
        flush_interval_s: float = DEFAULT_FLUSH_INTERVAL_S,
        maintenance_interval_s: float = DEFAULT_MAINTENANCE_INTERVAL_S,
        sample_retention_days: int = DEFAULT_SAMPLE_RETENTION_DAYS,
        episode_retention_days: int = DEFAULT_EPISODE_RETENTION_DAYS,
        clock: EpochClock = utc_now_ms,
        sleep: Sleeper = asyncio.sleep,
        counters: CounterRegistry = default_counters,
    ) -> None:
        if min(sample_interval_s, flush_interval_s, maintenance_interval_s) <= 0:
            raise ValueError("feeder service intervals must be greater than zero")
        self._repository = FeederRepository(database)
        self._on_transition = on_transition
        self._probe_factory = probe_factory
        self._client_factory = client_factory
        self._docker_factory = docker_factory
        self._sample_interval_ms = int(sample_interval_s * MS_PER_SECOND)
        self._flush_interval_ms = int(flush_interval_s * MS_PER_SECOND)
        self._maintenance_interval_s = maintenance_interval_s
        self._sample_retention_ms = sample_retention_days * MS_PER_DAY
        self._episode_retention_ms = episode_retention_days * MS_PER_DAY
        self._clock = clock
        self._sleep = sleep
        self._counters = counters

        self._http: httpx.AsyncClient | None = None
        self._docker: DockerClient | None = None
        self._docker_socket: str | None = None
        self._poll_interval_s = DEFAULT_POLL_INTERVAL_S
        self._local_pages: tuple[LocalPage, ...] = ()
        self._stats_urls: Mapping[str, SecretStr] = {}
        self._trackers: dict[str, _Tracker] = {}
        self._receiver: ReceiverUplink | None = None

        self._pending_samples: list[FeederSample] = []
        self._pending_episodes: dict[tuple[str, int], FeederEpisode] = {}
        self._last_flush_ms: int | None = None
        self._shed = 0
        self._started = False
        self._poll_task: asyncio.Task[None] | None = None
        self._maintenance_task: asyncio.Task[None] | None = None

        self._fixed: dict[str, FeederProbe] = {}
        self._fixed_pages: tuple[LocalPage, ...] = ()
        if probes is not None:
            listed = probes.values() if isinstance(probes, Mapping) else probes
            self._fixed = {probe.name: probe for probe in listed}
            pages: Iterable[LocalPageLike] = getattr(probes, "local_pages", ()) or ()
            self._fixed_pages = tuple(p for p in (LocalPage.of(raw) for raw in pages) if p)
        if settings is None:
            settings = _SettingsView(
                poll_interval_s=poll_interval_s,
                docker_socket=docker_socket,
                entries=tuple(entries or ()),
                local_pages=tuple(local_pages or ()),
                stats_urls=dict(stats_urls or {}),
            )
        self._configure(settings, now_ms=None)

    # ------------------------------------------------------------ inspection

    @property
    def running(self) -> bool:
        """True while the poll task is alive."""
        return self._poll_task is not None and not self._poll_task.done()

    @property
    def configured(self) -> int:
        """How many feeders are configured."""
        return len(self._trackers)

    @property
    def names(self) -> tuple[str, ...]:
        """Configured feeder names, in configuration order."""
        return tuple(self._trackers)

    @property
    def poll_interval_s(self) -> float:
        return self._poll_interval_s

    @property
    def docker_client(self) -> DockerClient | None:
        """The Docker client — ``None`` whenever ``docker_socket`` is unset."""
        return self._docker

    @property
    def docker_socket_status(self) -> DockerSocketStatus:
        if self._docker is None:
            return "unset"
        return "unreachable" if self._docker.reachable is False else "available"

    @property
    def pending_samples(self) -> int:
        return len(self._pending_samples)

    @property
    def shed_samples(self) -> int:
        return self._shed

    def statuses(
        self, stats_urls: Mapping[str, SecretStr] | None = None
    ) -> tuple[FeederStatus, ...]:
        """Every feeder's committed status, in configuration order."""
        return tuple(self._status(tracker, stats_urls) for tracker in self._trackers.values())

    def status(self, name: str) -> FeederStatus | None:
        tracker = self._trackers.get(name)
        return None if tracker is None else self._status(tracker)

    def _status(
        self, tracker: _Tracker, stats_urls: Mapping[str, SecretStr] | None = None
    ) -> FeederStatus:
        entry = tracker.entry
        return FeederStatus(
            name=entry.name,
            label=entry.label,
            kind=entry.kind,
            state=tracker.state,
            observability=tracker.observability,
            since_ms=tracker.episode_started_ms,
            last_polled_ms=tracker.last_polled_ms,
            last_success_ms=tracker.last_success_ms,
            last_data_sent_ms=tracker.last_data_sent_ms,
            message=tracker.message,
            mlat=tracker.mlat,
            adsb_out=tracker.adsb_out,
            detail=dict(tracker.detail),
            web_url=entry.web_url,
            stats_link=self.stats_url(entry.name, stats_urls) is not None,
        )

    def stats_url(self, name: str, configured: Mapping[str, SecretStr] | None = None) -> str | None:
        """The per-feeder stats page for the internal redirect. A secret: never log it.

        ``configured`` is the live ``feeders.stats_urls`` when the caller has
        it; then the service's own copy; then what the feeder's probe found
        for itself (FlightAware's site page, a demo landing page).
        """
        tracker = self._trackers.get(name)
        if tracker is None:
            return None
        for source in (configured or {}, self._stats_urls):
            secret = source.get(name)
            value = secret.get_secret_value().strip() if secret is not None else ""
            if value:
                return value
        return self.stats_fallback(name)

    def stats_fallback(self, name: str) -> str | None:
        """The link a feeder's probe discovered for itself, if any. Also a secret."""
        tracker = self._trackers.get(name)
        if tracker is None or not isinstance(tracker.probe, StatsFallbackSource):
            return None
        return tracker.probe.stats_fallback

    def summary(self) -> dict[str, Any]:
        """Counts by state plus the socket status — diagnostics' ``feeders`` section."""
        counts = dict.fromkeys((state.value for state in FeederState), 0)
        for tracker in self._trackers.values():
            counts[tracker.state.value] += 1
        return {
            "configured": len(self._trackers),
            **counts,
            "docker_socket": self.docker_socket_status,
        }

    # ----------------------------------------------------------- report / API

    def report(
        self,
        *,
        stats_urls: Mapping[str, SecretStr] | None = None,
        local_pages: Sequence[LocalPageLike] | None = None,
    ) -> dict[str, Any]:
        """The ``GET /api/v1/feeders`` payload (``docs/API.md`` §3.12).

        The API passes the live ``feeders.stats_urls`` and ``local_pages`` so
        a save is reflected on the next read whatever the service was built
        with; either left out (or empty) falls back to the service's own.
        """
        pages = tuple(p for p in (LocalPage.of(raw) for raw in local_pages or ()) if p)
        return {
            "generated_at": iso_ms(self._clock()),
            "poll_interval_s": self._poll_interval_s,
            "docker_socket": self.docker_socket_status,
            "receiver": _receiver_payload(self._receiver),
            "feeders": [_status_payload(status) for status in self.statuses(stats_urls)],
            "local_pages": [
                {"label": page.label, "url": page.url} for page in pages or self._local_pages
            ],
        }

    async def history(self, name: str, window: str) -> dict[str, Any] | None:
        """The ``GET /api/v1/feeders/{name}/history`` payload; ``None`` for an unknown name.

        Stored rows and not-yet-flushed ones together, so the current episode
        and the last minute's samples are never missing from the answer.
        """
        if name not in self._trackers:
            return None
        if window not in HISTORY_WINDOWS:
            raise ValueError(f"unknown history window {window!r}")
        now_ms = self._clock()
        from_ms = now_ms - WINDOW_MS[window]

        episodes: dict[int, FeederEpisode] = {
            episode.started_ms: episode
            for episode in await self._repository.episodes_between(name, from_ms, now_ms + 1)
        }
        for (feeder, started), episode in self._pending_episodes.items():
            if (
                feeder == name
                and started <= now_ms
                and (episode.ended_ms is None or episode.ended_ms > from_ms)
            ):
                episodes[started] = episode
        ordered = [episodes[key] for key in sorted(episodes)]

        samples = await self._repository.samples_between(name, from_ms, now_ms + 1)
        stored = {sample.ts_ms for sample in samples}
        samples.extend(
            sample
            for sample in self._pending_samples
            if sample.feeder == name
            and from_ms <= sample.ts_ms <= now_ms
            and sample.ts_ms not in stored
        )
        samples.sort(key=lambda sample: sample.ts_ms)

        return {
            "episodes": [
                {
                    "state": episode.state.value,
                    "started_at": iso_ms(episode.started_ms),
                    "ended_at": iso_ms(episode.ended_ms),
                }
                for episode in ordered
            ],
            "samples": [
                {
                    "t": iso_ms(sample.ts_ms),
                    "state": sample.state.value,
                    "metrics": dict(sample.metrics),
                }
                for sample in _bucketed(samples, BUCKET_MS[window])
            ],
            "availability_pct": availability_pct(ordered, from_ms=from_ms, to_ms=now_ms),
        }

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Close what an unclean stop left open, then start polling. Idempotent.

        With no feeders configured nothing is started; a later
        :meth:`apply_settings` that adds one starts the tasks then.
        """
        if self._started:
            return
        self._started = True
        if self._http is None:
            self._rebuild_all()
        try:
            closed = await self._repository.close_dangling(self._clock())
        except Exception as exc:
            self._counters.increment(DB_ERRORS_COUNTER)
            logger.warning("feeders_close_dangling_failed", error_type=type(exc).__name__)
        else:
            if closed:
                logger.info("feeders_closed_dangling_episodes", episodes=closed)
        self._ensure_tasks()
        logger.info(
            "feeders_started",
            feeders=len(self._trackers),
            poll_interval_s=self._poll_interval_s,
            docker_socket=self.docker_socket_status,
        )

    async def stop(self) -> None:
        """Stop the tasks, close open episodes silently, flush, close clients. Idempotent."""
        was_started, self._started = self._started, False
        await self._cancel_tasks()
        now_ms = self._clock()
        for tracker in self._trackers.values():
            self._close_episode(tracker, now_ms)
        await self.flush()
        await self._close_clients()
        if was_started:
            logger.info("feeders_stopped", pending=len(self._pending_samples), shed=self._shed)

    def _ensure_tasks(self) -> None:
        if not self._started or not self._trackers or self.running:
            return
        self._poll_task = asyncio.create_task(self._poll_loop(), name="flightsite-feeders-poller")
        self._maintenance_task = asyncio.create_task(
            self._maintenance_loop(), name="flightsite-feeders-maintenance"
        )

    async def _cancel_tasks(self) -> None:
        for attribute in ("_poll_task", "_maintenance_task"):
            task: asyncio.Task[None] | None = getattr(self, attribute)
            setattr(self, attribute, None)
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def _close_clients(self) -> None:
        http, self._http = self._http, None
        docker, self._docker = self._docker, None
        if http is not None:
            await http.aclose()
        if docker is not None:
            await docker.aclose()

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.poll_once()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("feeders_poll_error", error=str(exc), error_type=type(exc).__name__)
            await self._sleep(self._poll_interval_s)

    async def _maintenance_loop(self) -> None:
        while True:
            await self._sleep(self._maintenance_interval_s)
            try:
                await self.run_maintenance()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "feeders_maintenance_error", error=str(exc), error_type=type(exc).__name__
                )

    # --------------------------------------------------------------- hot apply

    async def apply_settings(self, settings: FeederSettingsLike | None) -> None:
        """Adopt a saved ``feeders`` section without a restart. See "Hot apply" above."""
        stale = self._configure(settings, now_ms=self._clock())
        for client in stale:
            await client.aclose()
        if not self._trackers:
            await self._cancel_tasks()
        self._ensure_tasks()
        if self._pending_episodes:
            await self.flush()

    def _configure(
        self, settings: FeederSettingsLike | None, *, now_ms: int | None
    ) -> list[DockerClient]:
        """Swap in ``settings``; return Docker clients the caller must close."""
        entries = [FeederEntry.of(entry) for entry in settings.entries] if settings else []
        named = {entry.name for entry in entries}
        for probe in self._fixed.values():
            carried = getattr(probe, "entry", None)
            if carried is not None and probe.name not in named:
                entries.append(FeederEntry.of(carried))
                named.add(probe.name)
        self._poll_interval_s = (
            float(settings.poll_interval_s) if settings else DEFAULT_POLL_INTERVAL_S
        )
        self._local_pages = (
            tuple(
                page
                for page in (
                    LocalPage.of(raw) for raw in (settings.local_pages if settings else ())
                )
                if page is not None
            )
            or self._fixed_pages
        )
        self._stats_urls = dict(settings.stats_urls) if settings else {}

        built = [entry for entry in entries if entry.name not in self._fixed]
        stale: list[DockerClient] = []
        socket = text_or_none(settings.docker_socket) if settings else None
        socket_changed = socket != self._docker_socket
        if socket_changed:
            if self._docker is not None:
                stale.append(self._docker)
            self._docker_socket = socket
            self._docker = self._docker_factory(socket) if socket and built else None
        elif socket and built and self._docker is None:
            self._docker = self._docker_factory(socket)
            socket_changed = True
        elif not built and self._docker is not None:
            stale.append(self._docker)
            self._docker = None

        rebuild = socket_changed
        if self._http is None and built:
            self._http = self._client_factory()
            rebuild = True

        previous = self._trackers
        trackers: dict[str, _Tracker] = {}
        for entry in entries:
            if entry.name in trackers:
                continue
            tracker = previous.get(entry.name)
            if tracker is None:
                trackers[entry.name] = _Tracker(entry=entry, probe=self._probe_for(entry))
                continue
            if entry.name not in self._fixed and (rebuild or tracker.entry != entry):
                tracker.probe = self._probe_for(entry)
            tracker.entry = entry
            trackers[entry.name] = tracker
        for name, tracker in previous.items():
            if name not in trackers and now_ms is not None:
                self._close_episode(tracker, now_ms)
        self._trackers = trackers
        if not any(t.entry.kind == FeederKind.READSB for t in trackers.values()):
            self._receiver = None
        return stale

    def _probe_for(self, entry: FeederEntry) -> FeederProbe:
        """A fixed probe when one was supplied; otherwise one built from the entry."""
        fixed = self._fixed.get(entry.name)
        if fixed is not None:
            return fixed
        if self._http is None:
            self._http = self._client_factory()
        return self._probe_factory(entry, ProbeContext(http=self._http, docker=self._docker))

    def _rebuild_all(self) -> None:
        """Recreate the HTTP client and every built probe, keeping each feeder's state."""
        built = [t for t in self._trackers.values() if t.entry.name not in self._fixed]
        if not built:
            return
        self._http = self._client_factory()
        if self._docker is None and self._docker_socket:
            self._docker = self._docker_factory(self._docker_socket)
        for tracker in built:
            tracker.probe = self._probe_for(tracker.entry)

    # ---------------------------------------------------------------- polling

    async def poll_once(self) -> tuple[FeederStatus, ...]:
        """Probe every feeder once, commit, sample, and flush if due."""
        if self._http is None:
            self._rebuild_all()
        trackers = list(self._trackers.values())
        now_ms = self._clock()
        probes: list[Awaitable[ProbeResult]] = [self._safe_probe(t.probe, now_ms) for t in trackers]
        if self._docker is not None:
            await self._docker.ping()
        results = await asyncio.gather(*probes)
        for tracker, result in zip(trackers, results, strict=True):
            self._apply(tracker, result, now_ms)
        if self._flush_due(now_ms):
            await self.flush()
        return self.statuses()

    async def _safe_probe(self, probe: FeederProbe, now_ms: int) -> ProbeResult:
        try:
            return await probe.probe(now_ms)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("feeders_probe_error", feeder=probe.name, error_type=type(exc).__name__)
            return ProbeResult(
                state=FeederState.UNKNOWN,
                observability=Observability.NONE,
                message="Probe error",
                failed=True,
            )

    def _apply(self, tracker: _Tracker, result: ProbeResult, now_ms: int) -> None:
        tracker.last_polled_ms = now_ms
        if result.failed:
            self._count_failure()
        else:
            tracker.last_success_ms = now_ms
        if result.last_data_sent_ms is not None:
            tracker.last_data_sent_ms = max(
                tracker.last_data_sent_ms or 0, result.last_data_sent_ms
            )
        if result.receiver is not None:
            self._receiver = result.receiver

        committed = result.state
        if result.state is FeederState.DOWN and tracker.state is not FeederState.DOWN:
            if tracker.held_downs == 0:
                tracker.first_down_ms = now_ms
            tracker.held_downs += 1
            if tracker.held_downs < DOWN_DEBOUNCE_POLLS:
                committed = tracker.state
        else:
            tracker.held_downs = 0
            tracker.first_down_ms = None

        held = committed is not result.state
        if not held:
            tracker.observability = result.observability
            tracker.message = result.message
            tracker.mlat = result.mlat
            tracker.adsb_out = result.adsb_out
            tracker.detail = dict(result.detail)
        if tracker.episode_started_ms is None or committed is not tracker.state:
            # A committed outage is dated from its first failing poll.
            began = tracker.first_down_ms if committed is FeederState.DOWN else None
            self._transition(tracker, committed, began if began is not None else now_ms, now_ms)

        if (
            tracker.last_sample_ms is None
            or now_ms - tracker.last_sample_ms >= self._sample_interval_ms
        ):
            tracker.last_sample_ms = now_ms
            self._buffer(
                FeederSample(
                    feeder=tracker.entry.name,
                    ts_ms=now_ms,
                    state=tracker.state,
                    metrics=dict(result.metrics),
                )
            )

    def _transition(self, tracker: _Tracker, state: FeederState, at_ms: int, now_ms: int) -> None:
        """Close the current episode and open ``state``'s at ``at_ms``; announce outages."""
        previous = tracker.state
        self._close_episode(tracker, at_ms)
        tracker.state = state
        tracker.episode_started_ms = at_ms
        opened = FeederEpisode(feeder=tracker.entry.name, started_ms=at_ms, state=state)
        self._pending_episodes[(opened.feeder, opened.started_ms)] = opened
        logger.info(
            "feeder_state_changed",
            feeder=tracker.entry.name,
            previous=previous.value,
            state=state.value,
        )

        if state is FeederState.DOWN and tracker.outage_since_ms is None:
            tracker.outage_since_ms = at_ms
            self._announce(tracker, offline=True, since_ms=at_ms, at_ms=at_ms)
        elif state in _AVAILABLE and tracker.outage_since_ms is not None:
            since_ms, tracker.outage_since_ms = tracker.outage_since_ms, None
            self._announce(tracker, offline=False, since_ms=since_ms, at_ms=now_ms)

    def _close_episode(self, tracker: _Tracker, ended_ms: int) -> None:
        started = tracker.episode_started_ms
        if started is None:
            return
        closed = FeederEpisode(
            feeder=tracker.entry.name,
            started_ms=started,
            state=tracker.state,
            ended_ms=max(started, ended_ms),
        )
        self._pending_episodes[(closed.feeder, closed.started_ms)] = closed
        tracker.episode_started_ms = None

    def _announce(self, tracker: _Tracker, *, offline: bool, since_ms: int, at_ms: int) -> None:
        if self._on_transition is None:
            return
        fact = OutageFact(
            feeder=tracker.entry.name,
            label=tracker.entry.label,
            kind=tracker.entry.kind,
            offline=offline,
            since_ms=since_ms,
            at_ms=at_ms,
        )
        try:
            self._on_transition(fact)
        except Exception as exc:
            logger.warning(
                "feeders_transition_listener_error",
                feeder=tracker.entry.name,
                error_type=type(exc).__name__,
            )

    def _count_failure(self) -> None:
        # A counter this build has not declared must never stop the poller.
        with contextlib.suppress(KeyError):
            self._counters.increment(POLL_FAILURES_COUNTER)

    def _buffer(self, sample: FeederSample) -> None:
        self._pending_samples.append(sample)
        overflow = len(self._pending_samples) - MAX_PENDING_SAMPLES
        if overflow > 0:
            del self._pending_samples[:overflow]
            self._shed += overflow

    def _flush_due(self, now_ms: int) -> bool:
        """Due on the flush interval — or at once when an episode changed.

        Transitions are rare and are the part of the history worth having
        durable immediately: an unclean stop should cost a minute of samples,
        never the record that a feeder went down.
        """
        if self._pending_episodes:
            return True
        if self._last_flush_ms is None:
            self._last_flush_ms = now_ms
            return False
        return now_ms - self._last_flush_ms >= self._flush_interval_ms

    # ---------------------------------------------------------------- writing

    async def flush(self) -> bool:
        """Write buffered samples and episode changes in one transaction. Never raises."""
        samples = tuple(self._pending_samples)
        episodes = dict(self._pending_episodes)
        if not samples and not episodes:
            return False
        try:
            await self._repository.record(samples, episodes.values())
        except Exception as exc:
            self._counters.increment(DB_ERRORS_COUNTER)
            logger.warning(
                "feeders_flush_failed", error_type=type(exc).__name__, samples=len(samples)
            )
            return False
        del self._pending_samples[: len(samples)]
        for key, episode in episodes.items():
            if self._pending_episodes.get(key) is episode:
                del self._pending_episodes[key]
        self._last_flush_ms = self._clock()
        return True

    async def run_maintenance(self) -> tuple[int, int]:
        """Prune expired samples and closed episodes. Returns (samples, episodes)."""
        now_ms = self._clock()
        try:
            pruned = await self._repository.prune(
                samples_before_ms=now_ms - self._sample_retention_ms,
                episodes_before_ms=now_ms - self._episode_retention_ms,
            )
        except Exception as exc:
            self._counters.increment(DB_ERRORS_COUNTER)
            logger.warning("feeders_prune_failed", error_type=type(exc).__name__)
            return 0, 0
        if any(pruned):
            logger.info("feeders_pruned", samples=pruned[0], episodes=pruned[1])
        return pruned


def availability_pct(
    episodes: Sequence[FeederEpisode], *, from_ms: int, to_ms: int
) -> float | None:
    """Percent of the *observed* part of ``[from_ms, to_ms]`` spent feeding.

    ``up`` and ``degraded`` count as feeding; ``unknown`` time, and time no
    episode covers, is left out rather than counted against the feeder —
    FlightSite not watching is not the feed failing. ``None`` when nothing in
    the window was observed at all.
    """
    known = 0
    available = 0
    for episode in episodes:
        start = max(from_ms, episode.started_ms)
        end = min(to_ms, episode.ended_ms if episode.ended_ms is not None else to_ms)
        span = end - start
        if span <= 0 or episode.state not in _KNOWN:
            continue
        known += span
        if episode.state in _AVAILABLE:
            available += span
    if known == 0:
        return None
    return round(100.0 * available / known, 2)


def _bucketed(samples: Sequence[FeederSample], bucket_ms: int) -> list[FeederSample]:
    """The latest sample in each ``bucket_ms`` bucket, oldest bucket first."""
    latest: dict[int, FeederSample] = {}
    for sample in samples:
        latest[sample.ts_ms // bucket_ms] = sample
    return [latest[key] for key in sorted(latest)]


def _mlat_payload(mlat: MlatStatus | None) -> dict[str, Any] | None:
    if mlat is None:
        return None
    return {
        "peers": mlat.peers,
        "good_sync_pct": mlat.good_sync_pct,
        "bad_sync_timeout_s": mlat.bad_sync_timeout_s,
        "last_bad_sync_at": iso_ms(mlat.last_bad_sync_ms),
    }


def _adsb_out_payload(adsb_out: AdsbOutStatus | None) -> dict[str, Any] | None:
    if adsb_out is None:
        return None
    return {"connected": adsb_out.connected, "since": iso_ms(adsb_out.since_ms)}


def _receiver_payload(uplink: ReceiverUplink | None) -> dict[str, Any] | None:
    if uplink is None:
        return None
    return {
        "bytes_out_rate_per_s": uplink.bytes_out_rate_per_s,
        "messages_per_min": uplink.messages_per_min,
        "positions_per_min": uplink.positions_per_min,
        "aircraft": uplink.aircraft,
        "aircraft_with_pos": uplink.aircraft_with_pos,
        "mlat_inbound": uplink.mlat_inbound,
        # The published name (docs/API.md §3.12) happens to be readsb's own.
        "samples_dropped": uplink.dropped_samples,
        "max_range_nm": uplink.max_range_nm,
        "gain_db": uplink.gain_db,
        "signal_db": uplink.signal_db,
        "noise_db": uplink.noise_db,
        "uptime_s": uplink.uptime_s,
        "updated_at": iso_ms(uplink.updated_ms),
    }


def _status_payload(status: FeederStatus) -> dict[str, Any]:
    return {
        "name": status.name,
        "label": status.label,
        "kind": status.kind,
        "state": status.state.value,
        "observability": status.observability.value,
        "since": iso_ms(status.since_ms),
        "last_polled_at": iso_ms(status.last_polled_ms),
        "last_success_at": iso_ms(status.last_success_ms),
        "last_data_sent_at": iso_ms(status.last_data_sent_ms),
        "message": status.message,
        "mlat": _mlat_payload(status.mlat),
        "adsb_out": _adsb_out_payload(status.adsb_out),
        "detail": dict(status.detail),
        "web_url": status.web_url,
        "stats_link": status.stats_link,
    }


def empty_report(now_ms: int) -> dict[str, Any]:
    """The ``/api/v1/feeders`` payload of an install with no feeder service at all."""
    return {
        "generated_at": iso_ms(now_ms),
        "poll_interval_s": DEFAULT_POLL_INTERVAL_S,
        "docker_socket": "unset",
        "receiver": None,
        "feeders": [],
        "local_pages": [],
    }


__all__ = [
    "BUCKET_MS",
    "DEFAULT_EPISODE_RETENTION_DAYS",
    "DEFAULT_FLUSH_INTERVAL_S",
    "DEFAULT_MAINTENANCE_INTERVAL_S",
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_SAMPLE_INTERVAL_S",
    "DEFAULT_SAMPLE_RETENTION_DAYS",
    "DOWN_DEBOUNCE_POLLS",
    "HISTORY_WINDOWS",
    "MAX_PENDING_SAMPLES",
    "POLL_FAILURES_COUNTER",
    "WINDOW_MS",
    "ClientFactory",
    "DockerSocketStatus",
    "FeederEntry",
    "FeederService",
    "HistoryWindow",
    "LinkOnlyProbe",
    "LocalPage",
    "TransitionListener",
    "availability_pct",
    "build_probe",
    "empty_report",
    "iso_ms",
]
