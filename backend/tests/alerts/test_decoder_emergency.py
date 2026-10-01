"""The decoder's emergency state as a second built-in emergency source.

Roadmap slice 086 (issue #229). The acceptance criterion is *"a readsb
`emergency: nordo` without squawk 7600 raises one emergency event naming the
decoder as source"*, and the requirement around it is that the two sources
never notify twice for one emergency. The pure half is checked against
:func:`~flightsite.alerts.builtins.emergency_match`; the "exactly one" half
runs the real engine against the real persistence worker, because the claim is
about what lands in ``alert_matches`` and what the feed announces.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from flightsite.activity.facts import AlertMatchFact
from flightsite.activity.model import ActivityEventType
from flightsite.activity.producers import alert_events
from flightsite.alerts.builtins import decoder_emergency_reason, emergency_match
from flightsite.alerts.engine import AlertEngine
from flightsite.alerts.evaluator import evaluate
from flightsite.alerts.vocabulary import (
    DECODER_EMERGENCY_MEANINGS,
    EMERGENCY_BUILTIN_KEYS,
    AlertSeverity,
    emergency_kind_builtin_key,
)
from flightsite.db import Database
from flightsite.ingest import AircraftStateUpdate, Position
from flightsite.ingest.types import DECODER_EMERGENCIES, DecoderEmergency
from flightsite.live import GroundState, LiveStore
from flightsite.metadata import MetadataService
from flightsite.sightings import PersistenceWorker

from .conftest import NOW_MS, settle, stored_matches, subject

BASE_TIME = datetime.fromtimestamp(NOW_MS / 1000, tz=UTC)


class Collector:
    """An alert listener that keeps what each cycle published."""

    def __init__(self) -> None:
        self.facts: list[AlertMatchFact] = []

    def __call__(self, matches: Sequence[AlertMatchFact]) -> None:
        self.facts.extend(matches)


@pytest.fixture
def collected(engine: AlertEngine) -> Collector:
    collector = Collector()
    engine.subscribe(collector)
    return collector


def observe(
    live: LiveStore,
    *,
    second: int = 0,
    squawk: str | None = "2341",
    decoder_emergency: DecoderEmergency | None = None,
) -> None:
    """One decoder observation, by default an ordinary squawk and no emergency."""
    live.apply_updates(
        [
            AircraftStateUpdate(
                icao="ae1463",
                timestamp=BASE_TIME + timedelta(seconds=second),
                position=Position(latitude=51.0, longitude=-1.0),
                position_source="adsb",
                altitude_ft=25_000.0,
                squawk=squawk,
                decoder_emergency=decoder_emergency,
                on_ground=False,
            )
        ]
    )


# ------------------------------------------------------------- the pure rule


def test_the_vocabularies_agree() -> None:
    assert set(DECODER_EMERGENCY_MEANINGS) == DECODER_EMERGENCIES


@pytest.mark.parametrize("kind", sorted(DECODER_EMERGENCY_MEANINGS))
def test_every_decoder_kind_fires_at_critical_with_no_rules(kind: DecoderEmergency) -> None:
    (proposal,) = evaluate(replace(subject(squawk="2341"), decoder_emergency=kind), [])

    assert proposal.severity is AlertSeverity.CRITICAL
    assert proposal.emergency_source == "decoder"
    assert proposal.emergency_kind == kind
    assert proposal.builtin_key == emergency_kind_builtin_key(kind)
    assert proposal.builtin_key in EMERGENCY_BUILTIN_KEYS
    assert proposal.reason == decoder_emergency_reason(kind)


def test_nordo_without_7600_names_the_decoder_and_shares_7600s_key() -> None:
    proposal = emergency_match(replace(subject(squawk="2341"), decoder_emergency="nordo"))

    assert proposal is not None
    assert proposal.builtin_key == "emergency_7600"
    assert proposal.emergency_source == "decoder"
    assert proposal.emergency_kind == "nordo"
    assert proposal.reason == "Decoder emergency state: no radio"


@pytest.mark.parametrize(
    ("kind", "key"),
    [
        ("general", "emergency_7700"),
        ("nordo", "emergency_7600"),
        ("unlawful", "emergency_7500"),
        ("minfuel", "emergency_minfuel"),
        ("lifeguard", "emergency_lifeguard"),
        ("downed", "emergency_downed"),
    ],
)
def test_a_kind_a_squawk_can_declare_is_keyed_by_that_squawk(kind: str, key: str) -> None:
    assert emergency_kind_builtin_key(kind) == key


def test_a_squawk_emergency_still_names_the_squawk() -> None:
    proposal = emergency_match(subject(squawk="7600"))

    assert proposal is not None
    assert proposal.emergency_source == "squawk"
    assert proposal.emergency_kind == "nordo"
    assert proposal.reason == "Emergency squawk 7600 (radio failure)"


def test_when_both_declare_the_squawk_wins_and_only_one_match_is_proposed() -> None:
    both = replace(subject(squawk="7600"), decoder_emergency="nordo")

    (proposal,) = evaluate(both, [])

    assert proposal.builtin_key == "emergency_7600"
    assert proposal.emergency_source == "squawk"


def test_when_they_disagree_the_squawk_still_wins() -> None:
    """One proposal per instant, never two."""
    disagreeing = replace(subject(squawk="7700"), decoder_emergency="minfuel")

    (proposal,) = evaluate(disagreeing, [])

    assert proposal.builtin_key == "emergency_7700"


def test_no_decoder_emergency_and_an_ordinary_squawk_fires_nothing() -> None:
    assert emergency_match(subject(squawk="2341")) is None


def test_a_decoder_emergency_on_the_ground_still_fires() -> None:
    grounded = replace(
        subject(squawk=None, ground_state=GroundState.ON_GROUND, altitude_ft=None),
        decoder_emergency="downed",
    )

    (proposal,) = evaluate(grounded, [], alert_radius_nm=1.0)

    assert proposal.builtin_key == "emergency_downed"


# --------------------------------------------------------------- the engine


async def test_nordo_without_7600_raises_exactly_one_emergency_naming_the_decoder(
    engine: AlertEngine,
    collected: Collector,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """The roadmap acceptance criterion, end to end through the engine."""
    observe(live, decoder_emergency="nordo")
    await settle(metadata)
    await persistence.process_pending()
    await engine.process_pending()
    for second in range(1, 6):
        observe(live, second=second, decoder_emergency="nordo")
        await engine.process_pending()

    (row,) = await stored_matches(database)
    assert row[1] == "emergency_7600"
    assert row[3] == "critical"
    assert row[4] == "Decoder emergency state: no radio"
    (fact,) = collected.facts
    assert fact.emergency_source == "decoder"
    assert fact.emergency_kind == "nordo"


async def test_squawk_7600_arriving_after_nordo_does_not_notify_again(
    engine: AlertEngine,
    collected: Collector,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    observe(live, decoder_emergency="nordo")
    await settle(metadata)
    await persistence.process_pending()
    await engine.process_pending()

    observe(live, second=1, squawk="7600", decoder_emergency="nordo")
    await engine.process_pending()

    assert [row[1] for row in await stored_matches(database)] == ["emergency_7600"]
    assert len(collected.facts) == 1


async def test_both_sources_at_once_record_one_match_naming_the_squawk(
    engine: AlertEngine,
    collected: Collector,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    observe(live, squawk="7700", decoder_emergency="general")
    await settle(metadata)
    await persistence.process_pending()
    await engine.process_pending()

    (row,) = await stored_matches(database)
    assert row[1] == "emergency_7700"
    (fact,) = collected.facts
    assert fact.emergency_source == "squawk"
    assert fact.emergency_kind == "general"


async def test_a_decoder_emergency_that_clears_and_returns_is_still_one_match(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """Once per sighting, the same as a squawk code that flaps."""
    observe(live, decoder_emergency="minfuel")
    await settle(metadata)
    await persistence.process_pending()
    await engine.process_pending()
    observe(live, second=1)
    await engine.process_pending()
    observe(live, second=2, decoder_emergency="minfuel")
    await engine.process_pending()

    assert [row[1] for row in await stored_matches(database)] == ["emergency_minfuel"]


async def test_the_sighting_records_had_emergency_for_a_decoder_only_emergency(
    engine: AlertEngine,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
) -> None:
    observe(live, decoder_emergency="lifeguard")
    await settle(metadata)
    await persistence.process_pending()

    active = persistence.sighting_for("ae1463")
    assert active is not None
    assert active.had_emergency


# ----------------------------------------------------------- the feed event


def _fact(**fields: object) -> AlertMatchFact:
    base: dict[str, object] = {
        "match_id": 7,
        "matched_ms": NOW_MS,
        "severity": "critical",
        "reason": "Decoder emergency state: minimum fuel",
        "aircraft_id": 1,
        "sighting_id": 2,
        "icao24": "ae1463",
        "builtin_key": "emergency_minfuel",
        "emergency_source": "decoder",
        "emergency_kind": "minfuel",
        "squawk": "2341",
    }
    base.update(fields)
    return AlertMatchFact(**base)  # type: ignore[arg-type]


def test_the_feed_event_names_the_source_and_the_kind() -> None:
    (event,) = alert_events([_fact()]).events

    assert event.type is ActivityEventType.EMERGENCY_SQUAWK
    assert event.payload["emergency_source"] == "decoder"
    assert event.payload["emergency_kind"] == "minfuel"
    assert event.payload["builtin_key"] == "emergency_minfuel"
    # The ordinary code the transponder showed is not an emergency squawk.
    assert event.payload["squawk"] is None


def test_a_squawk_emergency_event_keeps_its_squawk() -> None:
    (event,) = alert_events(
        [
            _fact(
                reason="Emergency squawk 7600 (radio failure)",
                builtin_key="emergency_7600",
                emergency_source="squawk",
                emergency_kind="nordo",
                squawk="7600",
            )
        ]
    ).events

    assert event.payload["squawk"] == "7600"
    assert event.payload["emergency_source"] == "squawk"
    assert event.payload["emergency_kind"] == "nordo"
