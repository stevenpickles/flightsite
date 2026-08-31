"""Event emission exactness and the bounded-queue backpressure contract.

Two things are pinned here. First, that the store says each thing once: an
aircraft appears once per entry into the live set, and staleness fires once per
episode. Second, that a consumer which stops reading is *shed*, not waited on —
the rule ``docs/ARCHITECTURE.md`` §3.1 states as "a slow consumer can lag or
drop to a resync; it cannot stall the adapter loop".
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from flightsite.counters import LIVE_EVENTS_DROPPED, counters
from flightsite.ingest import Position
from flightsite.live import (
    AircraftAppeared,
    AircraftRemoved,
    AircraftUpdated,
    EventDispatcher,
    LiveAircraft,
    LiveEvent,
    LiveStore,
)
from flightsite.live.aircraft import appear

from .conftest import BASE_TIME, ICAO, ManualClock, make_batch, make_update


def an_event(icao: str = ICAO) -> LiveEvent:
    aircraft: LiveAircraft = appear(make_update(icao), now=0.0)
    return AircraftAppeared(aircraft=aircraft, at=aircraft.last_seen)


# ------------------------------------------------------------ store emission


def test_an_aircraft_appears_exactly_once(live_store: LiveStore) -> None:
    subscription = live_store.subscribe("test")
    for step in range(4):
        live_store.apply(make_batch(make_update(offset_s=float(step)), offset_s=float(step)))

    kinds = [type(event) for event in subscription.drain()]

    assert kinds == [AircraftAppeared, AircraftUpdated, AircraftUpdated, AircraftUpdated]


def test_re_entry_after_removal_appears_again(live_store: LiveStore, clock: ManualClock) -> None:
    subscription = live_store.subscribe("test")
    live_store.apply_updates([make_update()])
    clock.advance(live_store.remove_s)
    live_store.sweep()
    clock.advance(1.0)
    live_store.apply_updates([make_update(offset_s=61.0)])

    kinds = [type(event) for event in subscription.drain()]

    assert kinds == [AircraftAppeared, AircraftRemoved, AircraftAppeared]


def test_events_carry_the_decoder_timestamp_not_the_wall_clock(live_store: LiveStore) -> None:
    subscription = live_store.subscribe("test")
    live_store.apply_updates([make_update()])

    event = subscription.drain()[0]

    assert event.at == BASE_TIME
    assert event.icao == ICAO


def test_a_non_positioned_aircraft_is_eventful(live_store: LiveStore) -> None:
    # Mode S-only traffic is first-class live state (SPEC §20), so it must
    # produce the same event stream as positioned traffic.
    subscription = live_store.subscribe("test")
    live_store.apply_updates([make_update("4ca7b3", callsign="EIN117")])
    live_store.apply_updates([make_update("4ca7b3", offset_s=1.0, squawk="2000")])

    events = subscription.drain()

    assert [type(event) for event in events] == [AircraftAppeared, AircraftUpdated]
    assert events[0].aircraft.position_source == "none"
    assert isinstance(events[1], AircraftUpdated)
    assert events[1].changed == frozenset({"squawk"})


def test_an_unchanged_re_report_yields_an_empty_change_set(live_store: LiveStore) -> None:
    subscription = live_store.subscribe("test")
    position = Position(latitude=47.0, longitude=-122.0)
    live_store.apply_updates([make_update(position=position, callsign="RCH492")])
    live_store.apply_updates([make_update(offset_s=1.0, position=position, callsign="RCH492")])

    updated = subscription.drain()[1]

    assert isinstance(updated, AircraftUpdated)
    assert updated.changed == frozenset()


def test_every_subscriber_sees_every_event(live_store: LiveStore) -> None:
    first = live_store.subscribe("first")
    second = live_store.subscribe("second")

    live_store.apply_updates([make_update()])

    assert live_store.events.subscriber_count == 2
    assert len(first.drain()) == 1
    assert len(second.drain()) == 1


def test_a_closed_subscription_stops_receiving(live_store: LiveStore) -> None:
    subscription = live_store.subscribe("test")
    subscription.close()

    live_store.apply_updates([make_update()])

    assert subscription.drain() == ()
    assert live_store.events.subscriber_count == 0


def test_closing_twice_is_harmless(live_store: LiveStore) -> None:
    subscription = live_store.subscribe("test")
    subscription.close()
    subscription.close()

    assert live_store.events.subscriber_count == 0


def test_detaching_an_already_detached_subscription_is_harmless(
    live_store: LiveStore,
) -> None:
    subscription = live_store.subscribe("test")

    live_store.events.detach(subscription)
    live_store.events.detach(subscription)

    assert live_store.events.subscriber_count == 0


def test_a_subscription_reports_its_consumer_name(live_store: LiveStore) -> None:
    # The name is what a shedding log and, from slice 042, diagnostics use to
    # say *which* consumer fell behind.
    assert live_store.subscribe("sighting-engine").name == "sighting-engine"


# -------------------------------------------------------------- backpressure


def test_a_full_queue_sheds_the_oldest_event_and_flags_the_gap() -> None:
    dispatcher = EventDispatcher()
    subscription = dispatcher.subscribe("slow", maxsize=2)

    for icao in ("ae1463", "4ca7b3", "a12345"):
        dispatcher.publish(an_event(icao))

    assert subscription.dropped == 1
    assert subscription.overflowed is True
    # The tail survives, which is what makes "resync from snapshot then carry
    # on" a valid recovery.
    assert [event.icao for event in subscription.drain()] == ["4ca7b3", "a12345"]


def test_publishing_never_blocks_on_a_stalled_consumer() -> None:
    dispatcher = EventDispatcher()
    subscription = dispatcher.subscribe("stalled", maxsize=4)

    for _ in range(1_000):
        dispatcher.publish(an_event())

    assert subscription.pending == 4
    assert subscription.dropped == 996
    assert dispatcher.published == 1_000


def test_shedding_increments_the_visible_counter() -> None:
    dispatcher = EventDispatcher()
    dispatcher.subscribe("slow", maxsize=1)

    dispatcher.publish(an_event())
    dispatcher.publish(an_event())

    assert counters.snapshot()[LIVE_EVENTS_DROPPED] == 1


def test_acknowledging_an_overflow_clears_the_flag_but_keeps_the_total() -> None:
    dispatcher = EventDispatcher()
    subscription = dispatcher.subscribe("slow", maxsize=1)
    dispatcher.publish(an_event())
    dispatcher.publish(an_event())

    dropped = subscription.acknowledge_overflow()

    assert dropped == 1
    assert subscription.overflowed is False
    assert subscription.dropped == 1


def test_a_healthy_consumer_is_never_flagged() -> None:
    dispatcher = EventDispatcher()
    subscription = dispatcher.subscribe("fast", maxsize=2)

    dispatcher.publish(an_event())
    subscription.drain()
    dispatcher.publish(an_event())

    assert subscription.dropped == 0
    assert subscription.overflowed is False


def test_a_zero_sized_queue_is_rejected() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        EventDispatcher().subscribe("bad", maxsize=0)


def test_closing_the_dispatcher_detaches_everyone() -> None:
    dispatcher = EventDispatcher()
    subscription = dispatcher.subscribe("test")

    dispatcher.close()
    dispatcher.publish(an_event())

    assert dispatcher.subscriber_count == 0
    assert subscription.drain() == ()


# ------------------------------------------------------------ async consumption


async def test_a_consumer_task_can_await_events(live_store: LiveStore) -> None:
    subscription = live_store.subscribe("consumer")
    received: list[LiveEvent] = []

    async def consume() -> None:
        async for event in subscription:
            received.append(event)

    task = asyncio.create_task(consume())
    live_store.apply_updates([make_update()])
    await asyncio.sleep(0)

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert [type(event) for event in received] == [AircraftAppeared]


async def test_get_awaits_the_next_event(live_store: LiveStore) -> None:
    subscription = live_store.subscribe("consumer")
    pending = asyncio.ensure_future(subscription.get())
    await asyncio.sleep(0)

    live_store.apply_updates([make_update()])

    assert isinstance(await pending, AircraftAppeared)
