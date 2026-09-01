"""Recent-error capture for the diagnostics view (SPEC §67, §68).

SPEC §67 asks the health area to show *recent* ingestion errors, database
errors, enrichment failures and WebSocket issues — not merely how many have
happened since boot. The counters registry (:mod:`flightsite.counters`) answers
"how many"; this module answers "what, and when".

Capture is deliberately passive. Every subsystem that fails already emits a
structured log record, so a bounded :class:`logging.Handler` attached to the
root logger collects those records without a single change at any call site and
without adding work to a hot path: the handler does a level check, a dict copy
and a ``deque`` append, all under a short non-blocking lock.

Records are bucketed into the SPEC §67 categories by logger name, and anything
outside a named subsystem lands in ``other`` so a novel failure stays visible
rather than being silently dropped.

**Redaction happens here, on the way in.** ``docs/SECURITY.md`` §3 requires
diagnostics output to provably contain no secrets. Rather than inheriting that
property from the separate guarantee that secrets never reach logs, every
captured field is passed through :func:`redact` against the live secret values,
so a secret cannot survive the trip into the ring buffer even if something
upstream were to log one by mistake. The two guarantees are then independent,
and this boundary is the one slice 042's secret-absence test exercises.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # pragma: no cover - typing only
    from flightsite.config.models import Settings

#: Placeholder substituted for any secret value found in captured text.
REDACTED: Final = "***REDACTED***"

#: SPEC §67 error categories, in the order the diagnostics payload presents
#: them. ``other`` is the catch-all for records outside a named subsystem.
INGESTION: Final = "ingestion"
DATABASE: Final = "database"
ENRICHMENT: Final = "enrichment"
WEBSOCKET: Final = "websocket"
OTHER: Final = "other"

CATEGORIES: Final[tuple[str, ...]] = (INGESTION, DATABASE, ENRICHMENT, WEBSOCKET, OTHER)

#: Logger-name prefixes mapped to categories. The longest matching prefix wins,
#: so a specific module outranks its parent package.
_CATEGORY_PREFIXES: Final[tuple[tuple[str, str], ...]] = (
    ("flightsite.ingest", INGESTION),
    ("flightsite.demo", INGESTION),
    ("flightsite.receiver_metrics", INGESTION),
    ("flightsite.db", DATABASE),
    ("flightsite.maintenance", DATABASE),
    ("flightsite.sightings", DATABASE),
    ("flightsite.analytics", DATABASE),
    ("flightsite.activity", DATABASE),
    ("flightsite.alerts", DATABASE),
    ("flightsite.backup", DATABASE),
    ("flightsite.enrichment", ENRICHMENT),
    ("flightsite.metadata", ENRICHMENT),
    ("flightsite.api.ws", WEBSOCKET),
    ("flightsite.live", WEBSOCKET),
)

#: How many records each category retains. Small enough that the whole buffer
#: stays bounded memory on a Pi, large enough to show a burst rather than only
#: its tail.
DEFAULT_CAPACITY: Final = 50

#: Upper bound on one rendered context value, so a single enormous log field
#: cannot dominate the payload.
MAX_VALUE_LEN: Final = 200

#: Attributes stdlib puts on every record, plus the keys :class:`RecentError`
#: already models. Neither belongs in the free-form detail string.
_UNINTERESTING_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
        # structlog's stdlib bridge adds these; they duplicate dedicated fields.
        "event",
        "level",
        "logger",
        "timestamp",
        "_record",
        "_from_structlog",
    }
)

#: Callable returning the currently configured secret values.
SecretsProvider = Callable[[], Iterable[str]]


def category_for_logger(name: str) -> str:
    """Return the SPEC §67 category a logger name belongs to."""
    best_prefix = ""
    best_category = OTHER
    for prefix, category in _CATEGORY_PREFIXES:
        matches = name == prefix or name.startswith(f"{prefix}.")
        if matches and len(prefix) > len(best_prefix):
            best_prefix, best_category = prefix, category
    return best_category


def redact(text: str, secrets: Iterable[str]) -> str:
    """Replace every occurrence of a secret value in ``text`` with the mask.

    Empty and whitespace-only secrets are ignored: substituting on those would
    shred unrelated text without protecting anything.
    """
    for secret in secrets:
        if secret and secret.strip():
            text = text.replace(secret, REDACTED)
    return text


def redact_value(value: Any, secrets: Iterable[str]) -> Any:
    """Deep-redact every string inside a JSON-shaped value."""
    secret_values = tuple(secrets)

    def walk(item: Any) -> Any:
        if isinstance(item, str):
            return redact(item, secret_values)
        if isinstance(item, Mapping):
            return {key: walk(sub) for key, sub in item.items()}
        if isinstance(item, list | tuple):
            return [walk(sub) for sub in item]
        return item

    return walk(value)


def secrets_from_settings(settings: Settings | None) -> tuple[str, ...]:
    """Collect every configured ``SecretStr`` value from a settings object.

    Discovery is by type (:func:`flightsite.config.secret_field_paths`), so a
    secret introduced by a later slice is redacted from diagnostics the moment
    it exists — nothing has to be added to a parallel list here.
    """
    if settings is None:
        return ()

    from flightsite.config.models import Settings as SettingsModel
    from flightsite.config.models import secret_field_paths

    values: list[str] = []
    for path in secret_field_paths(SettingsModel):
        node: Any = settings
        for part in path:
            node = getattr(node, part, None)
            if node is None:
                break
        reveal = getattr(node, "get_secret_value", None)
        if reveal is not None:
            values.append(str(reveal()))
    return tuple(values)


@dataclass(frozen=True, slots=True)
class RecentError:
    """One captured error, already redacted and safe to serialize."""

    at: datetime
    category: str
    event: str
    level: str
    logger: str
    detail: str | None


def _render_context(record: logging.LogRecord) -> str | None:
    """Summarize a record's structured fields as ``key=value`` pairs.

    ``structlog``'s stdlib bridge leaves the bound key/values on the record, so
    the interesting context (a decoder URL, a failure reason) is reachable
    without re-parsing the rendered line.
    """
    parts: list[str] = []
    for key, value in vars(record).items():
        if key in _UNINTERESTING_FIELDS or key.startswith("_"):
            continue
        rendered = str(value)
        if len(rendered) > MAX_VALUE_LEN:
            rendered = f"{rendered[:MAX_VALUE_LEN]}…"
        parts.append(f"{key}={rendered}")
    return ", ".join(parts) if parts else None


class ErrorRing:
    """Bounded, thread-safe store of recent errors bucketed by category.

    Safe to call from synchronous and asyncio code alike: the lock guards a
    short critical section with no ``await`` inside it, so it can neither
    deadlock nor stall the event loop — the discipline
    :class:`flightsite.counters.CounterRegistry` already follows.
    """

    def __init__(self, capacity: int = DEFAULT_CAPACITY) -> None:
        self._lock = threading.Lock()
        self._capacity = capacity
        self._buckets: dict[str, deque[RecentError]] = {
            category: deque(maxlen=capacity) for category in CATEGORIES
        }

    @property
    def capacity(self) -> int:
        """How many records each category retains."""
        return self._capacity

    def record(
        self,
        *,
        at: datetime,
        category: str,
        event: str,
        level: str,
        logger: str,
        detail: str | None = None,
        secrets: Iterable[str] = (),
    ) -> None:
        """Capture one error, redacting secret values out of every text field."""
        secret_values = tuple(secrets)
        entry = RecentError(
            at=at,
            category=category if category in self._buckets else OTHER,
            event=redact(event, secret_values),
            level=level,
            logger=redact(logger, secret_values),
            detail=redact(detail, secret_values) if detail is not None else None,
        )
        with self._lock:
            self._buckets[entry.category].append(entry)

    def recent(self, category: str, limit: int | None = None) -> tuple[RecentError, ...]:
        """Return one category's errors, newest first."""
        with self._lock:
            bucket = self._buckets.get(category)
            entries = tuple(reversed(bucket)) if bucket is not None else ()
        return entries[:limit] if limit is not None else entries

    def snapshot(self, limit: int | None = None) -> dict[str, tuple[RecentError, ...]]:
        """Return every category's errors, newest first."""
        return {category: self.recent(category, limit) for category in CATEGORIES}

    def total(self) -> int:
        """How many records are currently retained across every category."""
        with self._lock:
            return sum(len(bucket) for bucket in self._buckets.values())

    def clear(self) -> None:
        """Drop every captured error.

        The module-level :data:`error_ring` is process-global, so the test
        suite clears it between tests to keep one test's failures out of
        another's assertions.
        """
        with self._lock:
            for bucket in self._buckets.values():
                bucket.clear()


class ErrorRingHandler(logging.Handler):
    """Logging handler filing WARNING-and-above records into an :class:`ErrorRing`.

    ``secrets_provider`` is consulted per record rather than captured once, so
    a key added or rotated through the Settings UI takes effect immediately
    instead of at the next restart.
    """

    def __init__(
        self,
        ring: ErrorRing,
        secrets_provider: SecretsProvider | None = None,
        level: int = logging.WARNING,
    ) -> None:
        super().__init__(level=level)
        self._ring = ring
        self._secrets_provider = secrets_provider

    def emit(self, record: logging.LogRecord) -> None:
        """File one record. Never raises: diagnostics must not break logging."""
        try:
            provider = self._secrets_provider
            secrets = provider() if provider is not None else ()
            self._ring.record(
                at=datetime.fromtimestamp(record.created, UTC),
                category=category_for_logger(record.name),
                event=record.getMessage(),
                level=record.levelname,
                logger=record.name,
                detail=_render_context(record),
                secrets=secrets,
            )
        except Exception:  # pragma: no cover - defensive
            self.handleError(record)


#: Process-global ring shared by the logging handler and the diagnostics service.
error_ring = ErrorRing()
