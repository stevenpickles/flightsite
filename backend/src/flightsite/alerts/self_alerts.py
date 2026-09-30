"""Receiver self-alerts: telling the owner the *station* is unhealthy (slice 088).

Everything else in this package watches the sky. This module watches the
receiver itself, because the question an owner most needs answered while not
looking is not "did something interesting fly over?" but "is FlightSite still
hearing anything at all?" (issue #231). Three built-in, toggleable conditions
(``self_alerts`` in the configuration, :class:`~flightsite.config.SelfAlertSettings`):

========================  ==========================================  ===========
Condition                 Raised when                                 Detected by
========================  ==========================================  ===========
``message_rate``          the message rate has stayed below the       this module
                          configured share of this hour-of-week's
                          baseline for N minutes
``decoder_down``          the decoder connection has been ``down``    this module, from the
                          for longer than N minutes                   ingest health tracker
``feeder_offline``        a monitored feeder went ``down``            slice 077's feeder
                                                                      service
========================  ==========================================  ===========

What each condition reuses rather than re-detects
-------------------------------------------------

* **The decoder** is judged on the same
  :class:`~flightsite.ingest.health.AdapterHealth` the activity feed's
  ``receiver_offline`` reads (:data:`~flightsite.activity.HealthProbe`) — the
  connection state machine of ADR-0003 is the one source of truth for "is the
  decoder there". What this module adds is the *owner's* threshold: the feed
  narrates any outage longer than a minute, the self-alert fires only once the
  outage has outlived ``decoder_down_minutes``.
* **The message rate** is judged on the receiver-metrics sampler's own samples
  (:data:`~flightsite.receiver_metrics.service.SampleListener`), every fifteen
  seconds — never per ingest tick — against the hour-of-week baseline of
  :mod:`flightsite.receiver_metrics.baseline`. It is held (neither advanced nor
  raised) while the decoder is not ``connected``: a dead decoder collapses the
  rate too, and one cause must produce one alert, not two.
* **Feeders** are not detected here at all. Slice 077 already debounces an
  outage and announces ``feeder_offline`` / ``feeder_restored``; those events
  *are* this condition's activity events, and the toggle decides whether the
  browser turns them into notifications. This module only lists the feeders
  currently ``down`` among the active self-alerts.

One event per episode, and no flapping
--------------------------------------

Each condition is a small state machine with a **minimum duration** to raise
and a separate, **hysteretic** rule to restore:

* ``decoder_down`` raises once the decoder has read ``down`` continuously for
  ``decoder_down_minutes``; it restores once the decoder has read ``connected``
  continuously for :data:`DECODER_RESTORE_HOLD_MS`. A decoder that reconnects
  for a few seconds in the middle of an outage therefore neither restores the
  alert nor, when it drops again, raises a second one.
* ``message_rate`` raises once every usable sample for ``message_rate_minutes``
  has been below ``share * baseline``; it restores only once the rate has been
  back above :data:`RATE_RECOVERY_FACTOR` times that threshold (capped at the
  baseline itself) for :data:`RATE_RESTORE_HOLD_MS`. A rate hovering at the
  threshold sits in the band between the two and changes nothing.

Each raise and each restore becomes one
:class:`~flightsite.activity.SelfAlertEpisode`, handed to
:meth:`~flightsite.activity.ActivityService.record_self_alert`; the activity
service writes ``self_alert_raised`` / ``self_alert_restored`` with a dedupe
key naming the condition and the episode's start, and publishes them on the
WebSocket, where ``frontend/src/features/notifications`` composes the browser
notification — the same path an alert match takes (SPEC §48: the browser is the
only delivery channel).

Where the state lives
---------------------

In memory, plus one ``meta`` row (:data:`ACTIVE_META_KEY`) holding the
*active* episodes as JSON — no table and no migration. The row is what makes an
episode survive a restart: a monitor that starts with an episode active resumes
it, so the recovery that ends it is announced once with the original start
(and the original dedupe key), and a condition that is still bad after the
restart is not announced a second time. Pending (not yet raised) runs are not
persisted; a restart simply starts their clock again, which errs towards
silence.

Switching a condition off ends its episode silently: nothing recovered, so no
``self_alert_restored`` is written, and the Health page stops listing it.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, Protocol
from zoneinfo import ZoneInfo

import structlog

from flightsite.activity.facts import SelfAlertEpisode
from flightsite.config.models import SelfAlertSettings
from flightsite.db.clock import MS_PER_SECOND, TimezoneSource, resolve_zone
from flightsite.db.engine import Database
from flightsite.db.meta import MetaRepository
from flightsite.ingest.health import AdapterHealth, HealthState
from flightsite.receiver_metrics.aggregate import hour_start_ms
from flightsite.receiver_metrics.baseline import (
    BaselineState,
    RateBaseline,
    load_rate_baseline,
)
from flightsite.receiver_metrics.model import MetricSample
from flightsite.receiver_metrics.repository import MetricsRepository

logger = structlog.get_logger(__name__)

CONDITION_MESSAGE_RATE: Final = "message_rate"
CONDITION_DECODER_DOWN: Final = "decoder_down"
CONDITION_FEEDER_OFFLINE: Final = "feeder_offline"

#: Every self-alert condition, in the order the Health page lists them.
SELF_ALERT_CONDITIONS: Final[tuple[str, ...]] = (
    CONDITION_DECODER_DOWN,
    CONDITION_MESSAGE_RATE,
    CONDITION_FEEDER_OFFLINE,
)

#: Severity of every raise: each condition is something the owner can act on
#: (``docs/API.md`` §2.8). Feeder outages carry slice 077's own, also ``high``.
SELF_ALERT_SEVERITY: Final = "high"

MS_PER_MINUTE: Final = 60 * MS_PER_SECOND

#: How long the decoder must read ``connected`` before an active
#: ``decoder_down`` restores — the activity feed's own offline debounce
#: (:data:`~flightsite.activity.DEFAULT_OFFLINE_DEBOUNCE_S`), for the reason it
#: gives: longer than any reconnect blip, shorter than anyone waits to hear.
DECODER_RESTORE_HOLD_MS: Final = MS_PER_MINUTE

#: The recovery threshold, as a multiple of the raise threshold. With the
#: default 40 % share, a collapsed rate must climb back past 50 % of baseline
#: to count as recovering — the band in between is the hysteresis.
RATE_RECOVERY_FACTOR: Final = 1.25

#: How long the rate must stay recovered before ``message_rate`` restores.
RATE_RESTORE_HOLD_MS: Final = 5 * MS_PER_MINUTE

#: ``meta`` key holding the active episodes, as JSON (see "Where the state lives").
ACTIVE_META_KEY: Final = "self_alerts.active"

#: Reads the live ``self_alerts`` section on every evaluation — the read-late
#: pattern that makes a Settings save the whole of applying it.
SettingsProbe = Callable[[], SelfAlertSettings]
#: Reads the decoder's connection health; ``None`` when there is no decoder.
DecoderHealthProbe = Callable[[], AdapterHealth | None]
#: Receives each raise and restore; the activity service's seam in production.
EpisodeSink = Callable[[SelfAlertEpisode], None]
#: Loads the baseline for an instant; injectable so tests need no database.
BaselineLoader = Callable[[int, ZoneInfo], Awaitable[RateBaseline]]


class FeederStatusLike(Protocol):
    """The four fields of :class:`~flightsite.feeders.model.FeederStatus` read here."""

    @property
    def name(self) -> str: ...
    @property
    def label(self) -> str: ...
    @property
    def state(self) -> Any: ...
    @property
    def since_ms(self) -> int | None: ...


#: The feeders the feeder service is watching; ``None`` when there is none.
FeederProbe = Callable[[], Sequence[FeederStatusLike] | None]


@dataclass(frozen=True, slots=True)
class ActiveSelfAlert:
    """One condition that is currently raised — a row of the Health page card."""

    condition: str
    #: When the condition began (the episode's start), not when it was raised.
    since_ms: int
    severity: str = SELF_ALERT_SEVERITY
    #: The feeder's entry name for ``feeder_offline``; ``None`` otherwise.
    subject: str | None = None
    #: The feeder's display label for ``feeder_offline``; ``None`` otherwise.
    label: str | None = None
    detail: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class _Episode:
    """A raised, not yet restored, episode of one condition."""

    since_ms: int
    raised_ms: int
    detail: dict[str, Any] = field(default_factory=dict)


class _Condition:
    """Shared bookkeeping: the active episode and the pending runs either side."""

    __slots__ = ("_active", "_bad_since_ms", "_good_since_ms", "condition")

    def __init__(self, condition: str) -> None:
        self.condition = condition
        self._active: _Episode | None = None
        #: Start of the current run of "bad" readings (raise pending).
        self._bad_since_ms: int | None = None
        #: Start of the current run of "recovered" readings (restore pending).
        self._good_since_ms: int | None = None

    @property
    def active(self) -> _Episode | None:
        """The raised episode, or ``None``."""
        return self._active

    @property
    def pending_since_ms(self) -> int | None:
        """Start of a bad run that has not yet lasted long enough to raise."""
        return None if self._active is not None else self._bad_since_ms

    def resume(self, episode: _Episode) -> None:
        """Adopt an episode persisted by an earlier process, silently."""
        self._active = episode
        self._bad_since_ms = None
        self._good_since_ms = None

    def reset(self) -> None:
        """Forget everything — the condition was switched off."""
        self._active = None
        self._bad_since_ms = None
        self._good_since_ms = None

    def _hold(self) -> None:
        """No usable evidence: neither run may continue across the gap."""
        self._bad_since_ms = None
        self._good_since_ms = None

    def _bad(
        self, now_ms: int, threshold_ms: int, detail: dict[str, Any]
    ) -> SelfAlertEpisode | None:
        self._good_since_ms = None
        if self._bad_since_ms is None:
            self._bad_since_ms = now_ms
        if self._active is not None or now_ms - self._bad_since_ms < threshold_ms:
            return None
        self._active = _Episode(since_ms=self._bad_since_ms, raised_ms=now_ms, detail=detail)
        return SelfAlertEpisode(
            condition=self.condition,
            raised=True,
            since_ms=self._bad_since_ms,
            at_ms=now_ms,
            severity=SELF_ALERT_SEVERITY,
            detail=detail,
        )

    def _good(self, now_ms: int, hold_ms: int, detail: dict[str, Any]) -> SelfAlertEpisode | None:
        self._bad_since_ms = None
        active = self._active
        if active is None:
            self._good_since_ms = None
            return None
        if self._good_since_ms is None:
            self._good_since_ms = now_ms
        if now_ms - self._good_since_ms < hold_ms:
            return None
        self._active = None
        self._good_since_ms = None
        return SelfAlertEpisode(
            condition=self.condition,
            raised=False,
            since_ms=active.since_ms,
            at_ms=now_ms,
            severity=SELF_ALERT_SEVERITY,
            detail=detail,
        )


class DecoderDownCondition(_Condition):
    """``decoder_down``: the decoder read ``down`` for longer than N minutes.

    ``degraded`` — polls failing, but not yet four in a row
    (:mod:`flightsite.ingest.health`) — ends a pending run without starting a
    recovery: it is neither the outage continuing nor the decoder healthy.
    """

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(CONDITION_DECODER_DOWN)

    def observe(
        self, now_ms: int, health: AdapterHealth | None, *, minutes: int
    ) -> SelfAlertEpisode | None:
        """Fold one reading in; returns the raise or restore it justified, if any."""
        if health is None:
            # No decoder configured (a first run): nothing to judge. An active
            # episode is held rather than restored — nothing came back.
            self._hold()
            return None
        if health.state is HealthState.DOWN:
            return self._bad(
                now_ms,
                minutes * MS_PER_MINUTE,
                {"minutes": minutes, "error": health.last_error},
            )
        if health.state is HealthState.CONNECTED:
            return self._good(now_ms, DECODER_RESTORE_HOLD_MS, {"minutes": minutes})
        self._hold()
        return None


class MessageRateCondition(_Condition):
    """``message_rate``: below ``share`` of this hour's baseline for N minutes."""

    __slots__ = ()

    def __init__(self) -> None:
        super().__init__(CONDITION_MESSAGE_RATE)

    def observe(
        self,
        now_ms: int,
        rate: float | None,
        baseline: RateBaseline | None,
        *,
        share_pct: int,
        minutes: int,
        decoder_connected: bool,
    ) -> SelfAlertEpisode | None:
        """Fold one sample in; returns the raise or restore it justified, if any.

        A sample is *usable* only with a rate (the first after a restart has
        none, SPEC §39), a :attr:`~BaselineState.READY` baseline and a
        connected decoder. An unusable sample holds: it cannot continue a run,
        so a gap means the N minutes start again.
        """
        if (
            rate is None
            or baseline is None
            or not baseline.ready
            or baseline.msgs_per_sec is None
            or not decoder_connected
        ):
            self._hold()
            return None
        normal = baseline.msgs_per_sec
        threshold = normal * share_pct / 100.0
        detail: dict[str, Any] = {
            "rate_msgs_s": round(rate, 2),
            "baseline_msgs_s": round(normal, 2),
            "share_pct": share_pct,
            "minutes": minutes,
            "baseline_weeks": baseline.weeks,
        }
        if rate < threshold:
            return self._bad(now_ms, minutes * MS_PER_MINUTE, detail)
        if rate >= min(normal, threshold * RATE_RECOVERY_FACTOR):
            return self._good(now_ms, RATE_RESTORE_HOLD_MS, detail)
        # The hysteresis band: not low enough to continue an outage run, not
        # high enough to count towards recovery.
        self._hold()
        return None


def _iso(epoch_ms: int | None) -> str | None:
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(epoch_ms / MS_PER_SECOND, UTC).isoformat().replace("+00:00", "Z")


def _state_value(state: Any) -> str:
    return str(getattr(state, "value", state))


class SelfAlertMonitor:
    """Evaluates the receiver self-alert conditions on every metrics sample.

    Args:
        database: the application database; only the ``meta`` row and the
            hourly metrics are touched.
        settings: reads the live ``self_alerts`` section.
        health: reads the decoder's connection health (``None``: no decoder).
        sink: receives each raise and restore.
        feeders: reads the feeder service's statuses, for the active list.
        timezone: where to get the receiver's zone (the baseline's weekday).
        baseline_loader: overrides the database-backed baseline, for tests.
    """

    __slots__ = (
        "_baseline",
        "_baseline_key",
        "_decoder",
        "_feeders",
        "_health",
        "_loader",
        "_meta",
        "_persisted",
        "_rate",
        "_settings",
        "_sink",
        "_timezone",
    )

    def __init__(
        self,
        *,
        database: Database,
        settings: SettingsProbe,
        health: DecoderHealthProbe,
        sink: EpisodeSink,
        feeders: FeederProbe | None = None,
        timezone: TimezoneSource = "UTC",
        baseline_loader: BaselineLoader | None = None,
    ) -> None:
        self._meta = MetaRepository(database)
        self._settings = settings
        self._health = health
        self._sink = sink
        self._feeders = feeders
        self._timezone = timezone
        if baseline_loader is None:
            repository = MetricsRepository(database)

            async def load(at_ms: int, zone: ZoneInfo) -> RateBaseline:
                return await load_rate_baseline(repository, at_ms=at_ms, zone=zone)

            baseline_loader = load
        self._loader = baseline_loader
        self._decoder = DecoderDownCondition()
        self._rate = MessageRateCondition()
        self._baseline: RateBaseline | None = None
        self._baseline_key: tuple[int, str] | None = None
        self._persisted: str | None = None

    # ------------------------------------------------------------ inspection

    @property
    def baseline(self) -> RateBaseline | None:
        """The baseline the last sample was judged against, if one was loaded."""
        return self._baseline

    def active(self) -> tuple[ActiveSelfAlert, ...]:
        """Every condition currently raised, in :data:`SELF_ALERT_CONDITIONS` order.

        Feeder outages are read from the feeder service at call time, and only
        while their toggle is on — the same gate the browser applies to their
        notifications, so the Health page and the notifications agree.
        """
        settings = self._settings()
        found: list[ActiveSelfAlert] = []
        for condition in (self._decoder, self._rate):
            episode = condition.active
            if episode is not None:
                found.append(
                    ActiveSelfAlert(
                        condition=condition.condition,
                        since_ms=episode.since_ms,
                        detail=dict(episode.detail),
                    )
                )
        if settings.feeder_offline_enabled and self._feeders is not None:
            for status in self._feeders() or ():
                if _state_value(status.state) == "down" and status.since_ms is not None:
                    found.append(
                        ActiveSelfAlert(
                            condition=CONDITION_FEEDER_OFFLINE,
                            since_ms=status.since_ms,
                            subject=status.name,
                            label=status.label,
                        )
                    )
        return tuple(found)

    def snapshot(self) -> dict[str, Any]:
        """The diagnostics block (``docs/API.md`` §3.10): states and the active list.

        Thresholds, states and timestamps only — nothing here is a secret, and
        the decoder's short error reason is the same one diagnostics already
        publishes under ``decoder``.
        """
        settings = self._settings()
        baseline = self._baseline
        active = self.active()
        feeder_count = sum(1 for alert in active if alert.condition == CONDITION_FEEDER_OFFLINE)

        def state(condition: _Condition, enabled: bool) -> str:
            if not enabled:
                return "disabled"
            if condition.active is not None:
                return "active"
            return "pending" if condition.pending_since_ms is not None else "ok"

        rate_state = state(self._rate, settings.message_rate_enabled)
        if rate_state == "ok" and (baseline is None or not baseline.ready):
            rate_state = (
                BaselineState.QUIET.value
                if baseline is not None and baseline.state is BaselineState.QUIET
                else BaselineState.LEARNING.value
            )
        return {
            "conditions": {
                CONDITION_DECODER_DOWN: {
                    "enabled": settings.decoder_down_enabled,
                    "state": state(self._decoder, settings.decoder_down_enabled),
                    "minutes": settings.decoder_down_minutes,
                },
                CONDITION_MESSAGE_RATE: {
                    "enabled": settings.message_rate_enabled,
                    "state": rate_state,
                    "minutes": settings.message_rate_minutes,
                    "share_pct": settings.message_rate_share_pct,
                    "baseline_msgs_s": (
                        None
                        if baseline is None or baseline.msgs_per_sec is None
                        else round(baseline.msgs_per_sec, 2)
                    ),
                    "baseline_weeks": 0 if baseline is None else baseline.weeks,
                },
                CONDITION_FEEDER_OFFLINE: {
                    "enabled": settings.feeder_offline_enabled,
                    "state": (
                        "disabled"
                        if not settings.feeder_offline_enabled
                        else ("active" if feeder_count else "ok")
                    ),
                    "count": feeder_count,
                },
            },
            "active": [
                {
                    "condition": alert.condition,
                    "since": _iso(alert.since_ms),
                    "severity": alert.severity,
                    "subject": alert.subject,
                    "label": alert.label,
                }
                for alert in active
            ],
        }

    # ------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Resume the episodes an earlier process left active (``meta``)."""
        try:
            raw = await self._meta.get(ACTIVE_META_KEY)
        except Exception as exc:
            logger.warning("self_alerts_resume_failed", error=str(exc))
            return
        self._persisted = raw
        if not raw:
            return
        try:
            stored = json.loads(raw)
        except ValueError:
            logger.warning("self_alerts_state_unreadable")
            return
        if not isinstance(stored, dict):
            return
        for condition in (self._decoder, self._rate):
            entry = stored.get(condition.condition)
            if not isinstance(entry, dict):
                continue
            since_ms, raised_ms = entry.get("since_ms"), entry.get("raised_ms")
            detail = entry.get("detail")
            if isinstance(since_ms, int) and isinstance(raised_ms, int):
                condition.resume(
                    _Episode(
                        since_ms=since_ms,
                        raised_ms=raised_ms,
                        detail=dict(detail) if isinstance(detail, dict) else {},
                    )
                )
        logger.info(
            "self_alerts_resumed",
            conditions=[c.condition for c in (self._decoder, self._rate) if c.active is not None],
        )

    # ------------------------------------------------------------ evaluation

    async def observe(self, sample: MetricSample) -> tuple[SelfAlertEpisode, ...]:
        """Evaluate every condition against one sample. The sampler's listener.

        Never raises for a condition's sake: a baseline that cannot be read
        holds the rate condition for this sample, and a ``meta`` write that
        fails is retried on the next change. What it returns is what it handed
        to the sink, for tests.
        """
        settings = self._settings()
        now_ms = sample.ts_ms
        health = self._health()
        episodes: list[SelfAlertEpisode] = []

        if settings.decoder_down_enabled:
            episode = self._decoder.observe(now_ms, health, minutes=settings.decoder_down_minutes)
            if episode is not None:
                episodes.append(episode)
        else:
            self._decoder.reset()

        if settings.message_rate_enabled:
            baseline = await self._baseline_for(now_ms)
            episode = self._rate.observe(
                now_ms,
                sample.messages_per_sec,
                baseline,
                share_pct=settings.message_rate_share_pct,
                minutes=settings.message_rate_minutes,
                decoder_connected=health is not None and health.state is HealthState.CONNECTED,
            )
            if episode is not None:
                episodes.append(episode)
        else:
            self._rate.reset()

        for episode in episodes:
            logger.info(
                "self_alert_raised" if episode.raised else "self_alert_restored",
                condition=episode.condition,
                since_ms=episode.since_ms,
            )
            self._sink(episode)
        await self._persist()
        return tuple(episodes)

    async def _baseline_for(self, now_ms: int) -> RateBaseline | None:
        """This hour's baseline, loaded once per hour (and per zone)."""
        zone = resolve_zone(self._timezone)
        key = (hour_start_ms(now_ms), str(zone))
        if key != self._baseline_key:
            try:
                self._baseline = await self._loader(now_ms, zone)
            except Exception as exc:
                logger.warning("self_alerts_baseline_failed", error=str(exc))
                self._baseline = None
                return None
            self._baseline_key = key
        return self._baseline

    async def _persist(self) -> None:
        """Write the active episodes to ``meta`` when they changed."""
        state = {
            condition.condition: {
                "since_ms": episode.since_ms,
                "raised_ms": episode.raised_ms,
                "detail": episode.detail,
            }
            for condition in (self._decoder, self._rate)
            if (episode := condition.active) is not None
        }
        encoded = json.dumps(state, sort_keys=True)
        if encoded == (self._persisted or "{}"):
            return
        try:
            await self._meta.set(ACTIVE_META_KEY, encoded)
        except Exception as exc:
            logger.warning("self_alerts_persist_failed", error=str(exc))
            return
        self._persisted = encoded


__all__ = [
    "ACTIVE_META_KEY",
    "CONDITION_DECODER_DOWN",
    "CONDITION_FEEDER_OFFLINE",
    "CONDITION_MESSAGE_RATE",
    "DECODER_RESTORE_HOLD_MS",
    "RATE_RECOVERY_FACTOR",
    "RATE_RESTORE_HOLD_MS",
    "SELF_ALERT_CONDITIONS",
    "SELF_ALERT_SEVERITY",
    "ActiveSelfAlert",
    "DecoderDownCondition",
    "MessageRateCondition",
    "SelfAlertMonitor",
]
