"""The service: template instantiation, rule CRUD, and what recompiles the engine.

Two properties carry most of this module's weight and both are about *not*
doing something. Template instantiation must happen exactly once per install —
a user who deletes a shipped rule must not have it return on the next boot —
and a rule mutation must recompile the engine before the request answers, or
"rules created in the UI evaluate identically to API-created rules" (slice
041's round-trip criterion) is only eventually true.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from flightsite.alerts import AlertRuleNotFoundError, AlertRuleValueError, AlertSeverity
from flightsite.alerts.model import ClassificationCondition, RarityCondition, RuleConditions
from flightsite.alerts.templates import TEMPLATES_BY_KEY
from flightsite.db import Database
from flightsite.ingest import AircraftStateUpdate, Position
from flightsite.live import LiveStore
from flightsite.metadata import MetadataService
from flightsite.sightings import PersistenceWorker
from flightsite.watchlists import WatchlistEntryKind, WatchlistService

from .conftest import NOW_MS, ServiceFactory, settle

BASE_TIME = datetime.fromtimestamp(NOW_MS / 1000, tz=UTC)


def far_away(live: LiveStore, icao: str) -> None:
    """One observation of an aircraft well outside a 25 nm alert radius."""
    live.apply_updates(
        [
            AircraftStateUpdate(
                icao=icao,
                timestamp=BASE_TIME,
                position=Position(latitude=51.0, longitude=-40.0),
                position_source="adsb",
                altitude_ft=25_000.0,
                on_ground=False,
            )
        ]
    )


MILITARY = RuleConditions(classification=ClassificationCondition(military=True))
RARE = RuleConditions(rare_aircraft=RarityCondition(max_sightings=1))


# ------------------------------------------------------ template instantiation


async def test_starting_with_no_enabled_templates_creates_nothing(
    make_service: ServiceFactory,
) -> None:
    """SPEC §45: "do not silently enable every possible notification." The
    default configuration enables none, so a first boot alerts on nothing but
    emergency squawks."""
    service = make_service()
    await service.start()
    try:
        assert await service.list_rules() == ()
    finally:
        await service.stop()


async def test_starting_instantiates_exactly_the_enabled_templates(
    make_service: ServiceFactory,
) -> None:
    service = make_service(template_keys=["military", "watchlist"])
    await service.start()
    try:
        rules = await service.list_rules()
    finally:
        await service.stop()

    assert [rule.template_key for rule in rules] == ["military", "watchlist"]
    assert [rule.name for rule in rules] == [
        TEMPLATES_BY_KEY["military"].name,
        TEMPLATES_BY_KEY["watchlist"].name,
    ]
    assert [rule.severity for rule in rules] == [AlertSeverity.HIGH, AlertSeverity.INTERESTING]
    assert all(rule.enabled for rule in rules)


async def test_the_emergency_template_instantiates_no_rule(
    make_service: ServiceFactory,
) -> None:
    """SPEC §47: emergency detection is built in, so enabling its template
    creates nothing to disable — and the squawks fire either way."""
    service = make_service(template_keys=["emergency_squawk"])
    await service.start()
    try:
        assert await service.list_rules() == ()
    finally:
        await service.stop()


async def test_instantiation_is_idempotent_across_restarts(
    make_service: ServiceFactory,
) -> None:
    """The guard that makes a second boot silent."""
    first = make_service(template_keys=["military"])
    await first.start()
    await first.stop()

    second = make_service(template_keys=["military"])
    await second.start()
    try:
        rules = await second.list_rules()
    finally:
        await second.stop()

    assert len(rules) == 1


async def test_a_deleted_shipped_rule_does_not_return_on_the_next_boot(
    make_service: ServiceFactory,
) -> None:
    """The reason the guard is "any template row at all" rather than a per-key
    check: a user who deleted a shipped rule meant it."""
    first = make_service(template_keys=["military", "watchlist"])
    await first.start()
    rules = await first.list_rules()
    await first.delete_rule(rules[0].id)
    await first.stop()

    second = make_service(template_keys=["military", "watchlist"])
    await second.start()
    try:
        remaining = await second.list_rules()
    finally:
        await second.stop()

    assert [rule.template_key for rule in remaining] == ["watchlist"]


async def test_enabling_more_templates_later_does_not_rewrite_the_rule_set(
    make_service: ServiceFactory,
) -> None:
    """Changing ``alerts.enabled_templates`` after first run is editing a wizard
    answer; from then on the Alerts page owns the rules."""
    first = make_service(template_keys=["military"])
    await first.start()
    await first.stop()

    second = make_service(template_keys=["military", "police", "government"])
    await second.start()
    try:
        rules = await second.list_rules()
    finally:
        await second.stop()

    assert [rule.template_key for rule in rules] == ["military"]


async def test_an_unknown_template_key_is_skipped_rather_than_fatal(
    make_service: ServiceFactory,
) -> None:
    """A key from another build is a normal upgrade artefact; refusing to start
    over one would be a config typo taking the install down."""
    service = make_service(template_keys=["military", "no_such_template"])
    await service.start()
    try:
        rules = await service.list_rules()
    finally:
        await service.stop()

    assert [rule.template_key for rule in rules] == ["military"]


async def test_the_shipped_rules_are_in_force_the_moment_the_service_starts(
    make_service: ServiceFactory,
) -> None:
    """A first boot must evaluate its shipped rules on the very first decoder
    poll, not on the one after the next reload."""
    service = make_service(template_keys=["military", "first_ever"])
    await service.start()
    try:
        assert len(service.engine.rules) == 2
    finally:
        await service.stop()


# ------------------------------------------------------------------- rule CRUD


async def test_a_created_rule_is_in_force_before_the_call_returns(
    make_service: ServiceFactory,
) -> None:
    service = make_service()
    await service.start()
    try:
        record = await service.create_rule(
            name="Military aircraft",
            description=None,
            severity=AlertSeverity.HIGH,
            conditions=MILITARY,
        )

        assert [compiled.rule.id for compiled in service.engine.rules] == [record.id]
    finally:
        await service.stop()


async def test_a_created_rule_has_no_template_provenance(
    make_service: ServiceFactory,
) -> None:
    service = make_service()
    await service.start()
    try:
        record = await service.create_rule(
            name="Mine", description=None, severity=AlertSeverity.INFO, conditions=MILITARY
        )
    finally:
        await service.stop()

    assert record.template_key is None


async def test_a_blank_rule_name_is_refused(make_service: ServiceFactory) -> None:
    service = make_service()
    await service.start()
    try:
        with pytest.raises(AlertRuleValueError, match="must not be blank"):
            await service.create_rule(
                name="   ", description=None, severity=AlertSeverity.INFO, conditions=MILITARY
            )
    finally:
        await service.stop()


async def test_a_rule_name_is_trimmed_and_a_blank_description_becomes_null(
    make_service: ServiceFactory,
) -> None:
    service = make_service()
    await service.start()
    try:
        record = await service.create_rule(
            name="  Military  ",
            description="   ",
            severity=AlertSeverity.INFO,
            conditions=MILITARY,
        )
    finally:
        await service.stop()

    assert record.name == "Military"
    assert record.description is None


async def test_updating_a_rule_puts_the_new_definition_in_force(
    make_service: ServiceFactory,
) -> None:
    service = make_service()
    await service.start()
    try:
        record = await service.create_rule(
            name="Military", description=None, severity=AlertSeverity.INFO, conditions=MILITARY
        )

        await service.update_rule(
            record.id,
            name="Rare",
            description=None,
            severity=AlertSeverity.CRITICAL,
            conditions=RARE,
        )

        (compiled,) = service.engine.rules
        assert compiled.rule.conditions == RARE
        assert compiled.rule.severity is AlertSeverity.CRITICAL
    finally:
        await service.stop()


async def test_disabling_a_rule_leaves_it_in_the_set_but_matching_nothing(
    make_service: ServiceFactory,
) -> None:
    """A disabled rule keeps its id — and therefore its dedupe identity — which
    is why disabling and re-enabling one mid-sighting does not re-alert."""
    service = make_service()
    await service.start()
    try:
        record = await service.create_rule(
            name="Military", description=None, severity=AlertSeverity.INFO, conditions=MILITARY
        )
        await service.update_rule(
            record.id,
            name="Military",
            description=None,
            severity=AlertSeverity.INFO,
            conditions=MILITARY,
            enabled=False,
        )

        (compiled,) = service.engine.rules
        assert compiled.rule.id == record.id
        assert not compiled.rule.enabled
    finally:
        await service.stop()


async def test_updating_a_rule_that_does_not_exist_raises(
    make_service: ServiceFactory,
) -> None:
    service = make_service()
    await service.start()
    try:
        with pytest.raises(AlertRuleNotFoundError):
            await service.update_rule(
                404,
                name="Nope",
                description=None,
                severity=AlertSeverity.INFO,
                conditions=MILITARY,
            )
    finally:
        await service.stop()


async def test_deleting_a_rule_removes_it_from_the_set(
    make_service: ServiceFactory,
) -> None:
    service = make_service()
    await service.start()
    try:
        record = await service.create_rule(
            name="Military", description=None, severity=AlertSeverity.INFO, conditions=MILITARY
        )

        assert await service.delete_rule(record.id) is True
        assert service.engine.rules == ()
    finally:
        await service.stop()


async def test_deleting_a_rule_that_does_not_exist_answers_false(
    make_service: ServiceFactory,
) -> None:
    service = make_service()
    await service.start()
    try:
        assert await service.delete_rule(404) is False
    finally:
        await service.stop()


# ------------------------------------------------- watchlist name resolution


async def test_a_watchlist_id_condition_compiles_to_the_watchlists_name(
    make_service: ServiceFactory, watchlists: WatchlistService
) -> None:
    created = await watchlists.create_watchlist(name="Locals", description=None)
    service = make_service()
    await service.start()
    try:
        await service.create_rule(
            name="Watched",
            description=None,
            severity=AlertSeverity.INTERESTING,
            conditions=RuleConditions(watchlist_id=created.id),
        )

        (compiled,) = service.engine.rules
        assert compiled.watchlist_name == "Locals"
        assert not compiled.unresolved_watchlist
    finally:
        await service.stop()


async def test_renaming_a_watchlist_recompiles_the_rule_that_names_it(
    make_service: ServiceFactory, watchlists: WatchlistService
) -> None:
    """A rename happens through the watchlist API, not this one, so the two are
    connected by the index seam — without it the rule would keep matching the
    old name for the rest of the process's life."""
    created = await watchlists.create_watchlist(name="Locals", description=None)
    service = make_service()
    await service.start()
    try:
        await service.create_rule(
            name="Watched",
            description=None,
            severity=AlertSeverity.INTERESTING,
            conditions=RuleConditions(watchlist_id=created.id),
        )

        await watchlists.rename_watchlist(created.id, name="Neighbours", description=None)

        (compiled,) = service.engine.rules
        assert compiled.watchlist_name == "Neighbours"
    finally:
        await service.stop()


async def test_deleting_a_watchlist_leaves_its_rule_matching_nothing(
    make_service: ServiceFactory, watchlists: WatchlistService
) -> None:
    """The honest outcome: a rule about a watchlist that no longer exists has
    no aircraft it can be true of."""
    created = await watchlists.create_watchlist(name="Locals", description=None)
    await watchlists.add_entry(
        created.id, kind=WatchlistEntryKind.ICAO24, value="ae1463", note=None
    )
    service = make_service()
    await service.start()
    try:
        await service.create_rule(
            name="Watched",
            description=None,
            severity=AlertSeverity.INTERESTING,
            conditions=RuleConditions(watchlist_id=created.id),
        )

        await watchlists.delete_watchlist(created.id)

        (compiled,) = service.engine.rules
        assert compiled.unresolved_watchlist
    finally:
        await service.stop()


async def test_stopping_the_service_detaches_the_watchlist_seam(
    make_service: ServiceFactory, watchlists: WatchlistService, database: Database
) -> None:
    """A stopped service must not keep recompiling: its engine is gone."""
    service = make_service()
    await service.start()
    await service.stop()

    # No exception, and no work: the listener is no longer registered.
    await watchlists.create_watchlist(name="After", description=None)

    assert not service.engine.running


# ------------------------------------------------------------- alert radius


async def test_the_configured_alert_radius_bounds_a_rule_end_to_end(
    make_service: ServiceFactory,
    live: LiveStore,
    metadata: MetadataService,
    persistence: PersistenceWorker,
    database: Database,
) -> None:
    """SPEC §66's radius is a property of the installation, so it reaches the
    engine through the service rather than through any rule — and it is read
    through a callable, because ``PUT /api/internal/config`` can change it on a
    running app."""
    service = make_service(alert_radius_nm=25.0)
    await service.start()
    try:
        await service.create_rule(
            name="First ever",
            description=None,
            severity=AlertSeverity.INFO,
            conditions=RARE,
        )
        far_away(live, "ae1463")
        await settle(metadata)
        await persistence.process_pending()

        assert (await service.engine.process_pending()).recorded == 0
    finally:
        await service.stop()
