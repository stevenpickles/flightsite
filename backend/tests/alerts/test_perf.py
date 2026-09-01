"""Perf sanity: a full evaluation cycle over 500 live aircraft inside 50 ms.

Roadmap slice 038's third acceptance criterion, verbatim: *"full evaluation
cycle over 500 live aircraft completes in <=50 ms (perf test)"*. The budget is
not arbitrary — ``docs/ARCHITECTURE.md`` §3.3 bounds the live set at roughly
1 000 aircraft at a 1 Hz poll, so an evaluation pass that approached the poll
interval would turn the live picture into a backlog, exactly as an over-long
``LiveStore.apply`` would.

What is measured, and why that is the right thing
--------------------------------------------------

:meth:`~flightsite.alerts.engine.AlertEngine._evaluate` — the whole in-memory
cycle: building a subject per aircraft from the live record, the metadata view,
the watchlist index and the persistence worker's accumulator, then running
every rule against it. That is what the criterion calls "the evaluation
cycle", and it is deliberately separable from the write leg: matches are
written behind the cycle on the single writer, so SQLite's speed on the day is
not part of this budget and must not be able to mask a regression in the
arithmetic.

The measurement is the median of several steady-state passes rather than one
cold one, and it is taken with a **realistic rule set** — the shipped templates
plus a handful of user-shaped rules — because a pass against zero rules would
measure subject construction only and pass forever.

Marked ``perf`` so it can be selected (``-m perf``) or excluded, but it runs in
the normal suite: a regression that doubles the cost of a cycle should fail a
routine test run, not wait for someone to remember the marker.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

import pytest

from flightsite.alerts.engine import AlertEngine
from flightsite.alerts.model import (
    ClassificationCondition,
    CompiledRule,
    RarityCondition,
    RuleConditions,
)
from flightsite.alerts.templates import SHIPPED_TEMPLATES
from flightsite.alerts.vocabulary import AlertSeverity
from flightsite.classification.vocabulary import MissionCategory
from flightsite.ingest import AircraftStateUpdate, Position
from flightsite.live import LiveStore
from flightsite.metadata import MetadataService

from .conftest import NOW_MS, rule, settle

AIRCRAFT_COUNT = 500

#: The acceptance criterion's own number.
BUDGET_MS = 50.0

#: Passes measured; the median is taken, so a single scheduling hiccup on a
#: busy machine cannot fail the run.
PASSES = 9

BASE_TIME = datetime.fromtimestamp(NOW_MS / 1000, tz=UTC)

#: A rule set the size a real install carries: every shipped template that
#: instantiates, plus five user-shaped rules exercising the condition kinds a
#: template does not (type, model, distance, altitude, and an AND of several).
#: Twelve rules against 500 aircraft is 6 000 evaluations per cycle.
EXTRA_RULES = (
    RuleConditions(type_code="C17"),
    RuleConditions(model="Globemaster"),
    RuleConditions(min_distance_nm=5.0, max_distance_nm=80.0),
    RuleConditions(min_alt_ft=1_000.0, max_alt_ft=10_000.0),
    RuleConditions(
        classification=ClassificationCondition(military=True, mission=MissionCategory.MILITARY),
        rare_aircraft=RarityCondition(max_sightings=2),
        max_distance_nm=100.0,
    ),
)


def realistic_rules() -> tuple[CompiledRule, ...]:
    """Every shipped rule plus the extras above, compiled and ready."""
    shipped = [
        rule(template.conditions, rule_id=index, name=template.name, severity=template.severity)
        for index, template in enumerate(SHIPPED_TEMPLATES, start=1)
        if template.conditions is not None
    ]
    extra = [
        rule(conditions, rule_id=len(shipped) + index, severity=AlertSeverity.INTERESTING)
        for index, conditions in enumerate(EXTRA_RULES, start=1)
    ]
    return tuple(shipped + extra)


def synthetic_poll(sequence: int) -> list[AircraftStateUpdate]:
    """One decoder poll covering 500 aircraft, most positioned and moving.

    Modelled on ``tests/live/test_perf.py``'s batch so the two budgets measure
    comparable traffic: every tenth aircraft is Mode S-only (no position, and
    therefore no distance for a rule to test), and a few carry emergency
    squawks so the built-in path is exercised too.
    """
    timestamp = BASE_TIME + timedelta(seconds=sequence)
    updates: list[AircraftStateUpdate] = []
    for index in range(AIRCRAFT_COUNT):
        icao = f"{index:06x}"
        squawk = "7700" if index % 250 == 0 else "1200"
        if index % 10 == 0:
            updates.append(
                AircraftStateUpdate(
                    icao=icao, timestamp=timestamp, callsign=f"FS{index:04d}", squawk=squawk
                )
            )
            continue
        updates.append(
            AircraftStateUpdate(
                icao=icao,
                timestamp=timestamp,
                position=Position(
                    latitude=50.0 + (index % 200) * 0.01 + sequence * 0.001,
                    longitude=-2.0 + (index % 150) * 0.01,
                ),
                position_source="adsb",
                callsign=f"FS{index:04d}",
                squawk=squawk,
                altitude_ft=1_000.0 + (index % 380) * 100.0,
                on_ground=False,
            )
        )
    return updates


@pytest.mark.perf
async def test_a_full_cycle_over_500_aircraft_is_inside_the_budget(
    engine: AlertEngine, live: LiveStore, metadata: MetadataService
) -> None:
    engine.set_rules(realistic_rules())
    live.apply_updates(synthetic_poll(0))
    await settle(metadata)
    icaos = [record.icao for record in live.snapshot()]
    assert len(icaos) == AIRCRAFT_COUNT

    # Warm up: the first pass allocates every aircraft's alert state, which a
    # running receiver does once rather than every second.
    engine._evaluate(icaos, NOW_MS)

    elapsed_ms: list[float] = []
    for sequence in range(1, PASSES + 1):
        live.apply_updates(synthetic_poll(sequence))
        started = time.perf_counter()
        engine._evaluate(icaos, NOW_MS + sequence)
        elapsed_ms.append((time.perf_counter() - started) * 1_000.0)

    elapsed_ms.sort()
    median_ms = elapsed_ms[len(elapsed_ms) // 2]

    assert median_ms <= BUDGET_MS, (
        f"evaluating {AIRCRAFT_COUNT} aircraft against {len(engine.rules)} rules took "
        f"{median_ms:.1f} ms (budget {BUDGET_MS:.0f} ms); samples: "
        + ", ".join(f"{sample:.1f}" for sample in elapsed_ms)
    )


@pytest.mark.perf
async def test_evaluating_one_aircraft_does_not_cost_a_pass_over_the_others(
    engine: AlertEngine, live: LiveStore, metadata: MetadataService
) -> None:
    """The incremental property, measured rather than asserted structurally:
    one changed aircraft must cost roughly one aircraft's evaluation, not a
    rescan. A generous factor — twenty, against a live set of five hundred —
    because what is being ruled out is a *linear* dependence on the live set,
    not a constant-factor difference."""
    engine.set_rules(realistic_rules())
    live.apply_updates(synthetic_poll(0))
    await settle(metadata)
    icaos = [record.icao for record in live.snapshot()]
    engine._evaluate(icaos, NOW_MS)

    started = time.perf_counter()
    for sequence in range(1, PASSES + 1):
        engine._evaluate(icaos[:1], NOW_MS + sequence)
    one_ms = (time.perf_counter() - started) * 1_000.0 / PASSES

    started = time.perf_counter()
    for sequence in range(1, PASSES + 1):
        engine._evaluate(icaos, NOW_MS + sequence)
    all_ms = (time.perf_counter() - started) * 1_000.0 / PASSES

    assert one_ms * 20 < all_ms, (
        f"one aircraft took {one_ms:.3f} ms and {AIRCRAFT_COUNT} took {all_ms:.3f} ms, "
        "which is not the shape of an incremental evaluation"
    )
