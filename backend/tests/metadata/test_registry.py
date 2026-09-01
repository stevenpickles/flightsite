"""The source registry: registration, declared precedence, and run state."""

from __future__ import annotations

import pytest

from flightsite.db.models import METADATA_SOURCE_STATUS_CHECK
from flightsite.metadata.precedence import UNRANKED, FieldPriority
from flightsite.metadata.registry import (
    ImportPhase,
    RegistrationError,
    SourceRegistry,
    SourceStatus,
    SourceStatusRecord,
)
from tests.metadata.provider import InMemoryMetadataProvider


@pytest.fixture
def registry() -> SourceRegistry:
    return SourceRegistry()


def test_a_registered_source_is_retrievable_by_name(registry: SourceRegistry) -> None:
    provider = InMemoryMetadataProvider()

    registered = registry.register("mictronics", provider)

    assert registered.provider is provider
    assert registry.get("mictronics") is registered
    assert "mictronics" in registry
    assert len(registry) == 1


def test_names_are_sorted_so_runs_are_deterministic(registry: SourceRegistry) -> None:
    registry.register("mictronics", InMemoryMetadataProvider())
    registry.register("faa", InMemoryMetadataProvider())

    assert registry.names == ("faa", "mictronics")
    assert [source.name for source in registry] == ["faa", "mictronics"]


def test_a_known_source_gets_its_declared_precedence(registry: SourceRegistry) -> None:
    registry.register("mictronics", InMemoryMetadataProvider())

    assert registry.get("mictronics").priority.rank("type_code") == 0


def test_an_unknown_source_gets_an_unranked_precedence(registry: SourceRegistry) -> None:
    """Registered without a ranking means last, not excluded."""
    registry.register("stranger", InMemoryMetadataProvider())

    assert registry.get("stranger").priority.rank("type_code") == UNRANKED


def test_an_explicit_priority_overrides_the_declared_one(registry: SourceRegistry) -> None:
    registry.register(
        "mictronics", InMemoryMetadataProvider(), priority=FieldPriority(ranks={"type_code": 9})
    )

    assert registry.get("mictronics").priority.rank("type_code") == 9


def test_the_precedence_model_covers_exactly_the_registered_sources(
    registry: SourceRegistry,
) -> None:
    """Rows from a source this build no longer ships must not win a field."""
    registry.register("faa", InMemoryMetadataProvider())

    model = registry.precedence()

    assert model.rank_of("faa", "owner") == 0
    assert model.rank_of("mictronics", "owner") == UNRANKED


@pytest.mark.parametrize("name", ["", "Mictronics", "MICTRONICS", "x" * 33])
def test_an_unusable_source_name_is_refused(registry: SourceRegistry, name: str) -> None:
    with pytest.raises(RegistrationError):
        registry.register(name, InMemoryMetadataProvider())


def test_registering_the_same_name_twice_is_refused(registry: SourceRegistry) -> None:
    registry.register("faa", InMemoryMetadataProvider())

    with pytest.raises(RegistrationError, match="already registered"):
        registry.register("faa", InMemoryMetadataProvider())


def test_an_object_that_is_not_a_provider_is_refused(registry: SourceRegistry) -> None:
    """Caught at registration, not halfway through a run."""
    with pytest.raises(RegistrationError, match="DatasetProvider"):
        registry.register("faa", object())  # type: ignore[arg-type]


def test_an_unknown_source_lookup_names_the_source(registry: SourceRegistry) -> None:
    with pytest.raises(KeyError, match="nope"):
        registry.get("nope")


# --------------------------------------------------------------- run state


def test_run_state_starts_idle(registry: SourceRegistry) -> None:
    registry.register("faa", InMemoryMetadataProvider())

    state = registry.run_state("faa")

    assert not state.running
    assert state.phase is None


def test_marking_a_phase_makes_the_source_running(registry: SourceRegistry) -> None:
    registry.register("faa", InMemoryMetadataProvider())

    registry.mark_phase("faa", ImportPhase.STAGING, staged_rows=17)

    state = registry.run_state("faa")
    assert state.running
    assert state.phase is ImportPhase.STAGING
    assert state.staged_rows == 17


def test_finishing_keeps_the_last_phase_but_clears_running(
    registry: SourceRegistry,
) -> None:
    """ "How far did it get" survives the run; "is it going" does not."""
    registry.register("faa", InMemoryMetadataProvider())
    registry.mark_phase("faa", ImportPhase.SWAP)

    registry.mark_finished("faa")

    state = registry.run_state("faa")
    assert not state.running
    assert state.phase is ImportPhase.SWAP


def test_run_states_snapshot_every_registered_source(registry: SourceRegistry) -> None:
    registry.register("faa", InMemoryMetadataProvider())
    registry.register("mictronics", InMemoryMetadataProvider())

    assert set(registry.run_states()) == {"faa", "mictronics"}


def test_run_state_of_an_unknown_source_is_idle(registry: SourceRegistry) -> None:
    assert not registry.run_state("nope").running


# --------------------------------------------------------------- vocabulary


def test_the_status_enum_matches_the_sql_check_constraint() -> None:
    """The enum cannot be imported into ``db.models``, so it is asserted here.

    Same discipline as ``closure_reason`` and ``sighting_events.type``: the
    storage vocabulary and the runtime one must not drift apart silently.
    """
    spelled = {f"'{status.value}'" for status in SourceStatus}
    inside = METADATA_SOURCE_STATUS_CHECK.removeprefix("status IN (").removesuffix(")")

    assert {value.strip() for value in inside.split(",")} == spelled


def test_running_is_deliberately_not_a_stored_status() -> None:
    """A crash mid-import must not leave a row claiming to be running."""
    assert "running" not in {status.value for status in SourceStatus}
    assert "running" not in METADATA_SOURCE_STATUS_CHECK


def test_a_status_record_knows_whether_a_dataset_exists() -> None:
    assert not SourceStatusRecord(source="faa").has_data
    assert SourceStatusRecord(source="faa", last_success_ms=1).has_data
