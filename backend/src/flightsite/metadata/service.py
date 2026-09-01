"""The metadata subsystem as one object the application wires up.

``app.state`` should not have to know that "update the metadata" means *run the
importer, then, if anything actually changed, invalidate the cache*. That
sequencing is the subsystem's own business, so it lives here: the app holds one
:class:`MetadataService`, starts and stops it in the lifespan hook, and slice
025's ``POST /api/internal/metadata/update`` calls :meth:`MetadataService.update`.

The ordering is load-bearing in one direction only. Invalidation must follow a
completed import, never precede or accompany one: a cache repopulated while a
promotion is still in flight would refill from the *old* resolved rows and then
believe itself current. Because promotion is a single transaction, "after the
importer returns" is exactly "after the new rows are visible".

Slice 027 adds a second thing that has to happen on the same edge: the airport
index rebuilding after the ``airports`` source imports. Rather than teaching
this module about airports — which would invert the dependency, since
:mod:`flightsite.airports` consumes the import pipeline and not the reverse —
the "and then" becomes a list of :data:`ImportListener` callables the app wires
in. They run in registration order once the run has completed.

Listeners run on **every** completed run, not only on one that changed data.
That is slice 035's requirement and it is the right rule: SPEC §55 puts
*"metadata update results"* in the activity feed and SPEC §27 is explicit that
the user must be able to see which sources worked, so a run in which every
source failed is news rather than a non-event. Cache invalidation keeps its
narrower condition — a cache repopulated from rows nothing replaced would be a
repopulation for no new data — which is why the two are no longer one branch.
A listener that only cares about fresh data still guards on ``run.succeeded``,
exactly as the airport index rebuild does.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from pathlib import Path

import structlog

from flightsite.classification.engine import classify
from flightsite.db import Database, utc_now_ms
from flightsite.live.store import LiveStore
from flightsite.metadata.cache import AircraftMetadataView, MetadataCache, OnResolvedFn
from flightsite.metadata.importer import ClockFn, ImportRun, MetadataImporter
from flightsite.metadata.registry import SourceRegistry, SourceStatusRecord
from flightsite.metadata.repository import MetadataRepository

logger = structlog.get_logger(__name__)

#: Something to do once an import run has completed, whatever it achieved.
#: Receives the run, so a listener can decide from ``run.succeeded`` and
#: ``run.failed`` what it cares about. Exceptions are caught and logged: a
#: listener that fails must not turn an import into a failed request.
ImportListener = Callable[[ImportRun], Awaitable[None]]


class MetadataService:
    """Import orchestration plus the live metadata cache.

    Args:
        database: the application database.
        live: the live store the cache subscribes to.
        data_dir: parent of the importer's working directory.
        registry: registered sources; an empty registry is valid — slice 021
            ships no concrete provider, so a stock install has nothing to
            import until slices 022/023 register theirs.
        clock: UTC epoch-millisecond source, injected for tests.
        listeners: called after every completed run, in order. Slice 027 wires
            the airport index rebuild in here and slice 035 the activity
            feed's per-source outcome events.
        on_resolved: forwarded to :class:`MetadataCache` — an optional
            observer notified whenever a cached entry's resolved view changes.
            Slice 037 wires the watchlist matcher's index update in here.
    """

    __slots__ = ("_cache", "_importer", "_listeners", "_registry", "_repository")

    def __init__(
        self,
        *,
        database: Database,
        live: LiveStore,
        data_dir: Path,
        registry: SourceRegistry | None = None,
        clock: ClockFn = utc_now_ms,
        listeners: Sequence[ImportListener] = (),
        on_resolved: OnResolvedFn | None = None,
    ) -> None:
        self._registry = registry if registry is not None else SourceRegistry()
        self._repository = MetadataRepository(database)
        self._importer = MetadataImporter(
            database=database, registry=self._registry, data_dir=data_dir, clock=clock
        )
        self._cache = MetadataCache(database=database, live=live, on_resolved=on_resolved)
        self._listeners = tuple(listeners)

    @property
    def cache(self) -> MetadataCache:
        """The live metadata & rarity cache."""
        return self._cache

    @property
    def registry(self) -> SourceRegistry:
        """The source registry slices 022/023 register their providers with."""
        return self._registry

    async def start(self) -> None:
        """Start the cache. Idempotent."""
        await self._cache.start()

    async def stop(self) -> None:
        """Stop the cache. Idempotent, and safe before start."""
        await self._cache.stop()

    async def lookup(self, icao24: str) -> AircraftMetadataView | None:
        """Resolved metadata and rarity for any airframe, live or historical.

        The lookup that spans both halves of the roadmap's *"joining live and
        persisted aircraft to metadata with provenance"*: a live aircraft is
        answered from the cache with no I/O at all, and one that is not live —
        an aircraft page for something last seen in March — costs one read.

        ``None`` means the address is unknown to FlightSite entirely: no
        metadata source describes it and it has never been observed. An
        airframe that has been seen but that nobody has metadata for comes back
        as a view with ``known`` false, which is the different (and honest)
        answer.

        **Not for the live path.** It is ``async`` and it can touch SQLite;
        anything on the per-update path reads
        :meth:`~flightsite.metadata.cache.MetadataCache.get` instead
        (``docs/ARCHITECTURE.md`` §3.1).
        """
        cached = self._cache.get(icao24)
        if cached is not None:
            return cached

        found = await self._repository.load_live_view([icao24])
        lookup = found.get(icao24)
        if lookup is None or (lookup.metadata is None and lookup.sighting_count is None):
            return None
        metadata = lookup.metadata
        type_code = None if metadata is None else metadata.type_code
        # No callsign: this path answers about an airframe that is not live, so
        # there is no transmission to read one from. The classification is the
        # metadata-only one, which is the same one the import wrote.
        evidence = lookup.evidence(icao24)
        return AircraftMetadataView(
            icao24=icao24,
            metadata=metadata,
            sighting_count=lookup.sighting_count,
            type_count=None if type_code is None else self._cache.type_count(type_code),
            operator_group=lookup.operator_group,
            evidence=evidence,
            classification=classify(evidence),
        )

    async def update(self, sources: Sequence[str] | None = None) -> ImportRun:
        """Run an import over ``sources`` and refresh the cache if it changed.

        The entrypoint behind slice 025's "Update Aircraft Metadata" action.
        Returns per-source results — including failures, which are results
        rather than exceptions because the user needs to see which sources
        worked (SPEC §27).
        """
        run = await self._importer.run(sources)
        if run.changed_data:
            await self._cache.invalidate()
        await self._notify(run)
        return run

    async def _notify(self, run: ImportRun) -> None:
        """Run the post-import listeners, surviving any of them failing.

        A listener rebuilds a derived, in-memory structure; if one throws, the
        import itself still succeeded and its rows are still in the database.
        Turning that into an error the user sees would misreport what happened,
        so the failure is logged and the remaining listeners still run.
        """
        for listener in self._listeners:
            try:
                await listener(run)
            except Exception as exc:
                logger.error(
                    "metadata_import_listener_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

    async def statuses(self) -> tuple[SourceStatusRecord, ...]:
        """Per-source status, durable outcome merged with in-flight state.

        The row says how the last completed attempt went; the registry says
        whether one is happening right now. A caller wants both in one object,
        and neither alone is the whole answer.
        """
        stored = {record.source: record for record in await self._repository.read_statuses()}
        merged: list[SourceStatusRecord] = []
        for name in self._registry.names:
            record = stored.pop(name, SourceStatusRecord(source=name))
            merged.append(_with_run(record, self._registry))
        # Sources with a stored row but no registration: data from a source
        # this build no longer ships. Reported rather than hidden, so the row
        # explains where the rows in aircraft_metadata came from.
        merged.extend(stored[name] for name in sorted(stored))
        return tuple(merged)


def _with_run(record: SourceStatusRecord, registry: SourceRegistry) -> SourceStatusRecord:
    return replace(record, run=registry.run_state(record.source))


__all__ = ["ImportListener", "MetadataService"]
