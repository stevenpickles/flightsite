"""The in-memory watchlist match index and the live-aircraft match cache.

Design: piggy-backing on the metadata cache's own pipeline
--------------------------------------------------------------

``docs/ARCHITECTURE.md`` §3.1 forbids a live request or decoder poll from ever
waiting on SQLite, and matching by registration, type or operator needs the
*resolved* metadata a live aircraft only gets a moment after it appears
(:mod:`flightsite.metadata.cache`). Two seams could supply that:

1. Subscribe to the live event stream directly, the same way
   :class:`~flightsite.metadata.cache.MetadataCache` does.
2. Observe the metadata cache's own population pipeline, which already visits
   every live aircraft at exactly the moment its resolved view becomes known.

This module takes the second seam. A direct live-event subscription would
learn of an aircraft's *appearance* immediately, but metadata resolution
happens asynchronously on the cache's own task with no live event to mark it
— so a matcher driven only by appear/update/remove events would have no
signal for "this aircraft's registration/type/operator is now known" and
entries of those three kinds would silently stay unmatched until an unrelated
callsign change happened to fire an update. :data:`~flightsite.metadata.cache.OnResolvedFn`
(``MetadataCache(..., on_resolved=...)``) closes exactly that gap: it fires
with the fresh :class:`~flightsite.metadata.cache.AircraftMetadataView`
whenever one is installed, reclassified, or evicted (``None``) — which is
precisely "the live set, keyed by its currently-resolved fields" this module
needs, delivered with no second event subscription and, since the callback
runs on the cache's own already off-hot-path population task, no additional
database read of its own.

The trade this makes explicit: an aircraft's icao24-kind match is available
only once the cache's population round visits it (a moment behind appearing
live), not the instant it appears. That is the same trade
``docs/API.md`` §2.7 already documents for every metadata field — "the field
is null until it is not" — extended to watchlist membership, and it is
consistent with treating ``watchlists`` as an additive, best-effort field
rather than a load-bearing alert channel (SPEC §42's alert-matching use lands
in slice 038, over this same index).

What is held, and why nothing here reads a database
-----------------------------------------------------

:class:`WatchlistMatcher` holds three small maps, all bounded by the live set
(≤ ~1,000 aircraft, ``docs/ARCHITECTURE.md`` §3.3) or by the configured
watchlists (expected to be dozens of entries, not thousands):

* ``_views`` — the last :class:`AircraftMetadataView` seen per live icao24,
  kept so a CRUD-triggered index rebuild can recompute every live aircraft's
  matches from memory, with no database read of its own.
* ``_index`` — kind → normalized value → watchlist names, rebuilt from the
  database only when :meth:`reload` is called (at startup, and after any
  watchlist/entry CRUD change — never on the live path).
* ``_matches`` — the published answer: icao24 → the sorted, deduplicated
  watchlist names it currently matches. :meth:`matches` reads this with a
  plain dict lookup, the same "pure memory, no ``await``" shape as
  :meth:`~flightsite.metadata.cache.MetadataCache.get`, which is what lets
  :func:`flightsite.api.serializers.aircraft_payload` carry a ``watchlists``
  field with zero hot-path database reads.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import structlog

from flightsite.classification.vocabulary import MissionCategory
from flightsite.metadata.cache import AircraftMetadataView
from flightsite.watchlists.model import WatchlistEntryRecord
from flightsite.watchlists.vocabulary import WatchlistEntryKind

logger = structlog.get_logger(__name__)


def _upper(value: str | None) -> str | None:
    """Case-fold a live-aircraft field the same way entry values are stored.

    ``registration``, ``type_code`` and ``operator`` entries are normalized to
    upper-case at write time (:mod:`flightsite.watchlists.vocabulary`), but
    the metadata a source actually supplies keeps whatever case it arrived in
    (:func:`flightsite.metadata.records.normalize_text` does not case-fold).
    Folding here, at match time, is what makes the comparison
    case-insensitive without touching the metadata pipeline at all.
    """
    return None if value is None else value.upper()


def _mission_value(view: AircraftMetadataView) -> str | None:
    """The classification's mission category, or ``None`` when unknown.

    ``unknown`` is deliberately not a matchable value — see
    :mod:`flightsite.watchlists.vocabulary`'s module docstring for why a
    ``category`` entry can never take it.
    """
    mission = view.classification.mission
    return None if mission is MissionCategory.UNKNOWN else mission.value


@dataclass(frozen=True, slots=True)
class WatchlistIndex:
    """Kind → normalized value → the watchlist names claiming it.

    Built once per :meth:`WatchlistMatcher.reload` from every entry across
    every watchlist, and then read many times — once per live aircraft, on
    every metadata resolution — so the shape is optimized entirely for the
    read: a dict-of-dicts keyed exactly the way :meth:`match` looks values up,
    with the per-value list already deduplicated and sorted so two matchers
    built from the same entries answer identically.
    """

    _by_kind: Mapping[WatchlistEntryKind, Mapping[str, tuple[str, ...]]] = field(
        default_factory=dict
    )

    @classmethod
    def build(
        cls, entries: Sequence[WatchlistEntryRecord], names: Mapping[int, str]
    ) -> WatchlistIndex:
        """Build an index from every entry and each entry's watchlist name.

        An entry naming a watchlist id absent from ``names`` (deleted between
        the two reads a caller made, or a stale test fixture) is skipped
        rather than raising — see
        :meth:`flightsite.watchlists.service.WatchlistService.reload_index`
        for why the two reads cannot race in practice, and why skipping is
        still the right defensive behaviour if they ever did.
        """
        building: dict[WatchlistEntryKind, dict[str, list[str]]] = {
            kind: {} for kind in WatchlistEntryKind
        }
        for entry in entries:
            name = names.get(entry.watchlist_id)
            if name is None:
                continue
            building[entry.kind].setdefault(entry.value, []).append(name)
        by_kind: dict[WatchlistEntryKind, dict[str, tuple[str, ...]]] = {
            kind: {value: tuple(sorted(set(matched))) for value, matched in values.items()}
            for kind, values in building.items()
        }
        return cls(_by_kind=by_kind)

    def match(
        self,
        *,
        icao24: str,
        registration: str | None,
        type_code: str | None,
        operator: str | None,
        category: str | None,
    ) -> tuple[str, ...]:
        """Every watchlist name whose entries match this aircraft's fields.

        Every argument must already be normalized the way
        :mod:`flightsite.watchlists.vocabulary` normalizes an entry's stored
        ``value`` for the same kind — ``icao24`` lower-case,
        ``registration``/``type_code``/``operator`` upper-case, ``category``
        the :class:`~flightsite.classification.vocabulary.MissionCategory`
        spelling — so this method can compare with plain equality.
        """
        matched: set[str] = set()
        for kind, value in (
            (WatchlistEntryKind.ICAO24, icao24),
            (WatchlistEntryKind.REGISTRATION, registration),
            (WatchlistEntryKind.TYPE_CODE, type_code),
            (WatchlistEntryKind.OPERATOR, operator),
            (WatchlistEntryKind.CATEGORY, category),
        ):
            if value is None:
                continue
            matched.update(self._by_kind.get(kind, {}).get(value, ()))
        return tuple(sorted(matched))

    @property
    def entry_value_count(self) -> int:
        """Distinct (kind, value) pairs held — instrumentation for tests."""
        return sum(len(values) for values in self._by_kind.values())


#: The index an empty watchlist configuration produces — matches nothing.
_EMPTY_INDEX: WatchlistIndex = WatchlistIndex.build((), {})


class WatchlistMatcher:
    """Flags live aircraft with the watchlists they currently match.

    See the module docstring for the design: this object never touches
    SQLite. It is driven entirely by :meth:`on_resolved` — registered as
    :data:`~flightsite.metadata.cache.OnResolvedFn` on the application's
    :class:`~flightsite.metadata.service.MetadataService` — and by
    :meth:`reload`, called by :class:`flightsite.watchlists.service.WatchlistService`
    at startup and after any watchlist/entry CRUD change.
    """

    __slots__ = ("_index", "_matches", "_views")

    def __init__(self) -> None:
        self._index: WatchlistIndex = _EMPTY_INDEX
        self._views: dict[str, AircraftMetadataView] = {}
        self._matches: dict[str, tuple[str, ...]] = {}

    # ---------------------------------------------------------------- reads

    def matches(self, icao: str) -> tuple[str, ...]:
        """Watchlist names ``icao`` currently matches, or ``()`` when none.

        Pure memory: no ``await``, no session, no I/O — the lookup
        :func:`flightsite.api.serializers.aircraft_payload` makes once per
        aircraft per frame.
        """
        return self._matches.get(icao, ())

    @property
    def live_count(self) -> int:
        """Live aircraft currently tracked. Bounded by the live set."""
        return len(self._views)

    @property
    def index(self) -> WatchlistIndex:
        """The currently loaded match index. Read-only; tests inspect this."""
        return self._index

    # ------------------------------------------------------- cache observer

    def on_resolved(self, icao: str, view: AircraftMetadataView | None) -> None:
        """The :data:`~flightsite.metadata.cache.OnResolvedFn` callback.

        ``view is None`` means the aircraft left the live set (see the
        metadata cache's own docstring): its tracked view and its published
        matches are both dropped, which is what keeps :attr:`live_count`
        (and therefore the memory this matcher holds) bounded by the live
        set rather than growing over a process's lifetime.

        Left as it is by issue #138's churn review. This callback fires exactly
        as often as the metadata cache evicts and repopulates, so its rate is
        already bounded by that; what it does per call is two dictionary pops
        on the way out and one :meth:`_compute` on the way back in, entirely in
        memory and against an index sized by the user's watchlists. There is no
        I/O here to make cheaper, and holding a match set for an aircraft that
        is not live would be caching an answer nothing can ask for.
        """
        if view is None:
            self._views.pop(icao, None)
            self._matches.pop(icao, None)
            return
        self._views[icao] = view
        self._matches[icao] = self._compute(view)

    # --------------------------------------------------------- index reload

    def reload(self, entries: Sequence[WatchlistEntryRecord], names: Mapping[int, str]) -> None:
        """Rebuild the match index and recompute every currently-tracked aircraft.

        Called by :class:`~flightsite.watchlists.service.WatchlistService`
        with the full current set of entries and watchlist names — never
        incrementally, because a rename or a deleted entry can change which
        name an existing value maps to, and a full rebuild is cheap at the
        scale watchlists are configured at (dozens of entries, not
        thousands).

        Recomputing every tracked aircraft afterwards needs no database
        read: :attr:`_views` already holds each one's last resolved view, so
        this is a pure in-memory pass over at most the live set.
        """
        self._index = WatchlistIndex.build(entries, names)
        for icao, view in self._views.items():
            self._matches[icao] = self._compute(view)
        logger.info(
            "watchlist_index_reloaded",
            entries=self._index.entry_value_count,
            live_aircraft=len(self._views),
        )

    def _compute(self, view: AircraftMetadataView) -> tuple[str, ...]:
        resolved = view.metadata
        return self._index.match(
            icao24=view.icao24,
            registration=None if resolved is None else _upper(resolved.registration),
            type_code=None if resolved is None else _upper(resolved.type_code),
            operator=None if resolved is None else _upper(resolved.operator_name),
            category=_mission_value(view),
        )


__all__ = ["WatchlistIndex", "WatchlistMatcher"]
