"""The alert tables' SQL: rule CRUD, conflict-tolerant match writes, history.

The dedupe assertions here are deliberately at the *repository* level rather
than only at the engine's. SPEC §48's once-per-sighting-per-rule guarantee has
to survive an engine that lost its memory — a restart, a replayed event, a
second process — and what makes that true is the two partial unique indexes
plus ``ON CONFLICT DO NOTHING``. Testing it here proves the guarantee holds
even when nothing above the repository is checking.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from flightsite.alerts.model import ClassificationCondition, RarityCondition, RuleConditions
from flightsite.alerts.repository import AlertRepository, NewAlertMatch
from flightsite.alerts.vocabulary import AlertSeverity
from flightsite.db import Database

from .conftest import NOW_MS

MILITARY = RuleConditions(classification=ClassificationCondition(military=True))
RARE = RuleConditions(rare_aircraft=RarityCondition(max_sightings=1))


@pytest.fixture
def repository(database: Database) -> AlertRepository:
    return AlertRepository(database)


@pytest.fixture
async def sighting(database: Database) -> tuple[int, int]:
    """An airframe and one open sighting of it: ``(aircraft_id, sighting_id)``.

    Written with raw SQL rather than through the persistence worker: these
    tests are about what the alert tables do, not about how the sighting got
    there.
    """
    async with database.writer_session() as session:
        await session.execute(
            text(
                "INSERT INTO aircraft (id, icao24, first_seen_ms, last_seen_ms) "
                "VALUES (1, 'ae1463', :now, :now)"
            ),
            {"now": NOW_MS},
        )
        await session.execute(
            text("INSERT INTO sightings (id, aircraft_id, started_ms) VALUES (10, 1, :now)"),
            {"now": NOW_MS},
        )
    return 1, 10


def match(
    ids: tuple[int, int],
    *,
    rule_id: int | None = None,
    builtin_key: str | None = None,
    severity: AlertSeverity = AlertSeverity.HIGH,
    reason: str = "Rule: Military aircraft",
    sighting_id: int | None = None,
) -> NewAlertMatch:
    aircraft_id, default_sighting = ids
    return NewAlertMatch(
        sighting_id=default_sighting if sighting_id is None else sighting_id,
        aircraft_id=aircraft_id,
        matched_ms=NOW_MS,
        severity=severity,
        reason=reason,
        rule_id=rule_id,
        builtin_key=builtin_key,
    )


# ----------------------------------------------------------------- rule CRUD


async def test_a_created_rule_reads_back_with_its_conditions_parsed(
    repository: AlertRepository,
) -> None:
    created = await repository.create_rule(
        name="Military aircraft",
        description="Anything military",
        severity=AlertSeverity.HIGH,
        conditions=MILITARY,
        enabled=True,
        template_key="military",
        now_ms=NOW_MS,
    )

    (stored,) = await repository.list_rules()

    assert stored == created
    assert stored.conditions == MILITARY
    assert stored.template_key == "military"
    assert stored.reason == "Rule: Military aircraft"


async def test_rules_come_back_by_id(repository: AlertRepository) -> None:
    for name in ("B", "A", "C"):
        await repository.create_rule(
            name=name,
            description=None,
            severity=AlertSeverity.INFO,
            conditions=MILITARY,
            enabled=True,
            template_key=None,
            now_ms=NOW_MS,
        )

    assert [rule.name for rule in await repository.list_rules()] == ["B", "A", "C"]


async def test_an_unreadable_conditions_document_is_skipped_rather_than_fatal(
    repository: AlertRepository, database: Database
) -> None:
    """One corrupt or future-versioned row must not stop the engine evaluating
    the others: a rule that cannot be read is a rule that matches nothing."""
    good = await repository.create_rule(
        name="Good",
        description=None,
        severity=AlertSeverity.INFO,
        conditions=MILITARY,
        enabled=True,
        template_key=None,
        now_ms=NOW_MS,
    )
    async with database.writer_session() as session:
        await session.execute(
            text(
                "INSERT INTO alert_rules (id, name, severity, conditions_json, "
                "created_ms, updated_ms) VALUES (99, 'Broken', 'info', '{oops', 0, 0)"
            )
        )

    assert [rule.id for rule in await repository.list_rules()] == [good.id]
    assert await repository.get_rule(99) is None


async def test_updating_a_rule_replaces_its_definition_but_keeps_its_provenance(
    repository: AlertRepository,
) -> None:
    """Tuning a shipped rule does not make it stop having been shipped."""
    created = await repository.create_rule(
        name="Military aircraft",
        description=None,
        severity=AlertSeverity.HIGH,
        conditions=MILITARY,
        enabled=True,
        template_key="military",
        now_ms=NOW_MS,
    )

    updated = await repository.update_rule(
        created.id,
        name="Military, close in",
        description="Within 50 nm",
        severity=AlertSeverity.CRITICAL,
        conditions=RARE,
        enabled=False,
        now_ms=NOW_MS + 1,
    )

    assert updated is not None
    assert updated.template_key == "military"
    assert updated.created_ms == NOW_MS
    assert updated.updated_ms == NOW_MS + 1
    assert updated.conditions == RARE
    assert updated.enabled is False
    assert await repository.get_rule(created.id) == updated


async def test_updating_a_rule_that_does_not_exist_answers_none(
    repository: AlertRepository,
) -> None:
    assert (
        await repository.update_rule(
            404,
            name="Nope",
            description=None,
            severity=AlertSeverity.INFO,
            conditions=MILITARY,
            enabled=True,
            now_ms=NOW_MS,
        )
        is None
    )


async def test_deleting_a_rule_takes_its_matches_with_it(
    repository: AlertRepository, sighting: tuple[int, int]
) -> None:
    """``alert_matches.rule_id`` has no ``ON DELETE`` action and foreign keys
    are enforced, so the matches must go in the same transaction or the delete
    is a referential error."""
    created = await repository.create_rule(
        name="Military aircraft",
        description=None,
        severity=AlertSeverity.HIGH,
        conditions=MILITARY,
        enabled=True,
        template_key=None,
        now_ms=NOW_MS,
    )
    await repository.record_matches([match(sighting, rule_id=created.id)])
    assert await repository.list_matches(limit=10, offset=0)

    assert await repository.delete_rule(created.id) is True

    assert await repository.list_rules() == ()
    assert await repository.list_matches(limit=10, offset=0) == ()


async def test_deleting_a_rule_leaves_another_rules_matches_alone(
    repository: AlertRepository, sighting: tuple[int, int]
) -> None:
    kept = await repository.create_rule(
        name="Kept",
        description=None,
        severity=AlertSeverity.INFO,
        conditions=MILITARY,
        enabled=True,
        template_key=None,
        now_ms=NOW_MS,
    )
    doomed = await repository.create_rule(
        name="Doomed",
        description=None,
        severity=AlertSeverity.INFO,
        conditions=RARE,
        enabled=True,
        template_key=None,
        now_ms=NOW_MS,
    )
    await repository.record_matches(
        [match(sighting, rule_id=kept.id), match(sighting, rule_id=doomed.id)]
    )

    await repository.delete_rule(doomed.id)

    remaining = await repository.list_matches(limit=10, offset=0)
    assert [stored.rule_id for stored in remaining] == [kept.id]


async def test_deleting_a_rule_that_does_not_exist_answers_false(
    repository: AlertRepository,
) -> None:
    assert await repository.delete_rule(404) is False


# ---------------------------------------------------- template provenance guard


async def test_has_template_rules_is_false_on_an_empty_table(
    repository: AlertRepository,
) -> None:
    assert await repository.has_template_rules() is False


async def test_a_user_written_rule_does_not_count_as_template_provenance(
    repository: AlertRepository,
) -> None:
    await repository.create_rule(
        name="Mine",
        description=None,
        severity=AlertSeverity.INFO,
        conditions=MILITARY,
        enabled=True,
        template_key=None,
        now_ms=NOW_MS,
    )

    assert await repository.has_template_rules() is False


async def test_one_template_rule_is_enough_to_count(repository: AlertRepository) -> None:
    await repository.create_rules(
        [("Military aircraft", None, AlertSeverity.HIGH, MILITARY, "military")], now_ms=NOW_MS
    )

    assert await repository.has_template_rules() is True


async def test_creating_no_template_rules_writes_nothing(repository: AlertRepository) -> None:
    assert await repository.create_rules([], now_ms=NOW_MS) == 0
    assert await repository.list_rules() == ()


# -------------------------------------------------------------- match writes


async def test_a_recorded_match_reads_back_with_its_rule_and_airframe(
    repository: AlertRepository, sighting: tuple[int, int]
) -> None:
    rule_record = await repository.create_rule(
        name="Military aircraft",
        description=None,
        severity=AlertSeverity.HIGH,
        conditions=MILITARY,
        enabled=True,
        template_key=None,
        now_ms=NOW_MS,
    )

    (created,) = await repository.record_matches([match(sighting, rule_id=rule_record.id)])

    assert created is not None
    (stored,) = await repository.list_matches(limit=10, offset=0)
    assert stored.id == created
    assert stored.rule_id == rule_record.id
    assert stored.rule_name == "Military aircraft"
    assert stored.icao24 == "ae1463"
    assert stored.severity == "high"
    assert stored.reason == "Rule: Military aircraft"
    assert stored.notified is False


async def test_the_same_rule_cannot_match_one_sighting_twice(
    repository: AlertRepository, sighting: tuple[int, int]
) -> None:
    """SPEC §48's once-per-sighting-per-rule guarantee, at the layer that
    enforces it — no engine memory involved."""
    rule_record = await repository.create_rule(
        name="Military aircraft",
        description=None,
        severity=AlertSeverity.HIGH,
        conditions=MILITARY,
        enabled=True,
        template_key=None,
        now_ms=NOW_MS,
    )

    first = await repository.record_matches([match(sighting, rule_id=rule_record.id)])
    second = await repository.record_matches([match(sighting, rule_id=rule_record.id)])

    assert first[0] is not None
    assert second == (None,)
    assert len(await repository.list_matches(limit=10, offset=0)) == 1


async def test_the_same_builtin_cannot_match_one_sighting_twice(
    repository: AlertRepository, sighting: tuple[int, int]
) -> None:
    first = await repository.record_matches(
        [match(sighting, builtin_key="emergency_7700", severity=AlertSeverity.CRITICAL)]
    )
    second = await repository.record_matches(
        [match(sighting, builtin_key="emergency_7700", severity=AlertSeverity.CRITICAL)]
    )

    assert first[0] is not None
    assert second == (None,)


async def test_two_emergency_codes_in_one_sighting_are_two_matches(
    repository: AlertRepository, sighting: tuple[int, int]
) -> None:
    """``docs/DATA_MODEL.md`` §4.3 names distinct ``builtin_key``\\ s as exactly
    the allowed "higher-priority condition may notify again" path."""
    created = await repository.record_matches(
        [
            match(sighting, builtin_key="emergency_7600", severity=AlertSeverity.CRITICAL),
            match(sighting, builtin_key="emergency_7700", severity=AlertSeverity.CRITICAL),
        ]
    )

    assert all(match_id is not None for match_id in created)


async def test_the_created_ids_line_up_positionally_with_the_input(
    repository: AlertRepository, sighting: tuple[int, int]
) -> None:
    """The caller has per-match downstream work to do, so it must be able to
    tell *which* of its proposals were new — not merely how many."""
    rule_record = await repository.create_rule(
        name="R",
        description=None,
        severity=AlertSeverity.INFO,
        conditions=MILITARY,
        enabled=True,
        template_key=None,
        now_ms=NOW_MS,
    )
    await repository.record_matches([match(sighting, rule_id=rule_record.id)])

    created = await repository.record_matches(
        [
            match(sighting, rule_id=rule_record.id),  # already there
            match(sighting, builtin_key="emergency_7700", severity=AlertSeverity.CRITICAL),
        ]
    )

    assert created[0] is None
    assert created[1] is not None


async def test_recording_nothing_writes_nothing(repository: AlertRepository) -> None:
    assert await repository.record_matches([]) == ()


# ------------------------------------------------------------- open sightings


async def test_open_sighting_match_keys_answers_by_sighting(
    repository: AlertRepository, sighting: tuple[int, int]
) -> None:
    rule_record = await repository.create_rule(
        name="R",
        description=None,
        severity=AlertSeverity.HIGH,
        conditions=MILITARY,
        enabled=True,
        template_key=None,
        now_ms=NOW_MS,
    )
    await repository.record_matches(
        [
            match(sighting, rule_id=rule_record.id),
            match(sighting, builtin_key="emergency_7700", severity=AlertSeverity.CRITICAL),
        ]
    )

    keys = await repository.open_sighting_match_keys()

    assert keys == {
        10: {
            f"rule:{rule_record.id}": AlertSeverity.HIGH,
            "builtin:emergency_7700": AlertSeverity.CRITICAL,
        }
    }


async def test_a_closed_sightings_matches_are_not_adopted(
    repository: AlertRepository, sighting: tuple[int, int], database: Database
) -> None:
    """A closed sighting can never be alerted on again, so carrying its keys
    would be memory the engine can never use."""
    await repository.record_matches(
        [match(sighting, builtin_key="emergency_7700", severity=AlertSeverity.CRITICAL)]
    )
    async with database.writer_session() as session:
        await session.execute(text("UPDATE sightings SET ended_ms = 1 WHERE id = 10"))

    assert await repository.open_sighting_match_keys() == {}


# ----------------------------------------------------------------- history


async def test_history_is_newest_first_with_the_id_as_the_tie_break(
    repository: AlertRepository, sighting: tuple[int, int]
) -> None:
    for index, key in enumerate(("emergency_7500", "emergency_7600", "emergency_7700")):
        await repository.record_matches(
            [
                NewAlertMatch(
                    sighting_id=10,
                    aircraft_id=1,
                    matched_ms=NOW_MS if index < 2 else NOW_MS + 1,
                    severity=AlertSeverity.CRITICAL,
                    reason=key,
                    builtin_key=key,
                )
            ]
        )

    stored = await repository.list_matches(limit=10, offset=0)

    assert [row.builtin_key for row in stored] == [
        "emergency_7700",
        "emergency_7600",
        "emergency_7500",
    ]


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"severity": "critical"}, ["emergency_7700"]),
        ({"severity": "info"}, []),
        ({"icao": "ae1463"}, ["emergency_7700"]),
        ({"icao": "000000"}, []),
        ({"from_ms": NOW_MS + 1}, []),
        ({"to_ms": NOW_MS - 1}, []),
        ({"from_ms": NOW_MS, "to_ms": NOW_MS}, ["emergency_7700"]),
    ],
)
async def test_history_filters(
    repository: AlertRepository,
    sighting: tuple[int, int],
    filters: dict[str, object],
    expected: list[str],
) -> None:
    await repository.record_matches(
        [match(sighting, builtin_key="emergency_7700", severity=AlertSeverity.CRITICAL)]
    )

    stored = await repository.list_matches(limit=10, offset=0, **filters)  # type: ignore[arg-type]

    assert [row.builtin_key for row in stored] == expected


async def test_history_pages(repository: AlertRepository, sighting: tuple[int, int]) -> None:
    for key in ("emergency_7500", "emergency_7600", "emergency_7700"):
        await repository.record_matches(
            [match(sighting, builtin_key=key, severity=AlertSeverity.CRITICAL)]
        )

    first = await repository.list_matches(limit=2, offset=0)
    second = await repository.list_matches(limit=2, offset=2)

    assert len(first) == 2
    assert len(second) == 1
    assert {row.id for row in first}.isdisjoint({row.id for row in second})


async def test_a_builtin_match_has_no_rule_in_the_history(
    repository: AlertRepository, sighting: tuple[int, int]
) -> None:
    await repository.record_matches(
        [match(sighting, builtin_key="emergency_7700", severity=AlertSeverity.CRITICAL)]
    )

    (stored,) = await repository.list_matches(limit=10, offset=0)

    assert stored.rule_id is None
    assert stored.rule_name is None
    assert stored.builtin_key == "emergency_7700"
