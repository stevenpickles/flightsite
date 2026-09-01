"""Unit tests for the readiness registry (independent of the HTTP layer)."""

from __future__ import annotations

import pytest

from flightsite.readiness import ReadinessRegistry


def test_not_ready_before_startup_complete() -> None:
    registry = ReadinessRegistry()

    assert registry.is_ready is False


def test_ready_after_startup_complete_with_no_subsystems() -> None:
    registry = ReadinessRegistry()
    registry.mark_startup_complete()

    assert registry.is_ready is True


def test_registered_subsystem_blocks_readiness_until_marked_ready() -> None:
    registry = ReadinessRegistry()
    registry.mark_startup_complete()
    registry.register("db")

    assert registry.is_ready is False

    registry.mark_ready("db")

    assert registry.is_ready is True


def test_mark_not_ready_reverts_readiness() -> None:
    registry = ReadinessRegistry()
    registry.mark_startup_complete()
    registry.register("db")
    registry.mark_ready("db")

    assert registry.is_ready is True

    registry.mark_not_ready("db")

    assert registry.is_ready is False


def test_register_is_idempotent_and_does_not_reset_ready_state() -> None:
    registry = ReadinessRegistry()
    registry.register("db")
    registry.mark_ready("db")

    registry.register("db")

    assert registry.snapshot()["db"] is True


def test_mark_ready_unknown_subsystem_raises() -> None:
    registry = ReadinessRegistry()

    with pytest.raises(KeyError):
        registry.mark_ready("nonexistent")


def test_mark_not_ready_unknown_subsystem_raises() -> None:
    registry = ReadinessRegistry()

    with pytest.raises(KeyError):
        registry.mark_not_ready("nonexistent")


def test_snapshot_returns_independent_copy() -> None:
    registry = ReadinessRegistry()
    registry.register("db")

    snapshot = registry.snapshot()
    snapshot["db"] = True

    assert registry.snapshot()["db"] is False
