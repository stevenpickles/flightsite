"""The airframe's last emitter category, written by the persistence worker.

Roadmap slice 086. The category describes the airframe, not the flight, so it
lands on ``aircraft`` (rev 0019) rather than on the sighting — and like the
lifetime records beside it, it is written on every flush, so it is there while
the aircraft is still overhead and survives a crash mid-sighting.
"""

from __future__ import annotations

from flightsite.db import Database
from flightsite.live import LiveStore
from flightsite.sightings import PersistenceWorker

from .conftest import (
    CLOSE_S,
    REMOVE_S,
    SimulatedTime,
    existing_aircraft,
    observe,
)


async def _close_current_sighting(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime
) -> None:
    clock.advance(REMOVE_S + 1.0)
    live.sweep()
    await worker.process_pending()
    clock.advance(CLOSE_S)
    await worker.process_pending()


async def test_the_category_is_written_while_the_sighting_is_open(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, emitter_category="A7")

    await worker.process_pending()

    assert (await existing_aircraft(database)).emitter_category == "A7"


async def test_an_airframe_that_never_sent_one_stays_null(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, squawk="1200")

    await worker.process_pending()

    assert (await existing_aircraft(database)).emitter_category is None


async def test_the_category_arriving_mid_sighting_is_written_on_a_later_flush(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock)
    await worker.process_pending()
    clock.advance(5.0)
    observe(live, clock, emitter_category="A3")
    await _close_current_sighting(worker, live, clock)

    assert (await existing_aircraft(database)).emitter_category == "A3"


async def test_a_later_sighting_replaces_it_and_a_silent_one_keeps_it(
    worker: PersistenceWorker, live: LiveStore, clock: SimulatedTime, database: Database
) -> None:
    observe(live, clock, emitter_category="A1")
    await worker.process_pending()
    await _close_current_sighting(worker, live, clock)

    clock.advance(3_600.0)
    observe(live, clock, emitter_category="A2")
    await worker.process_pending()
    await _close_current_sighting(worker, live, clock)
    assert (await existing_aircraft(database)).emitter_category == "A2"

    # Heard again through a feed that never reports a category: nothing to
    # say is not a statement that the category went away.
    clock.advance(3_600.0)
    observe(live, clock)
    await worker.process_pending()
    await _close_current_sighting(worker, live, clock)
    assert (await existing_aircraft(database)).emitter_category == "A2"
