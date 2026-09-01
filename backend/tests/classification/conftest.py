"""Shared fixtures for the classification tests.

The important one is :func:`toy_directory`: a hand-written operator directory
small enough to read in full. Most rule tests use it rather than the shipped
curated data, so that "a phrase match is MEDIUM" is asserted against three
groups a reader can hold in their head, and so a future edit to
``data/operators.py`` cannot quietly change what a rule test means. The shipped
data gets its own tests (:mod:`tests.classification.test_curated_data`) that
assert its *invariants* rather than its contents.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from flightsite.classification.operators import OperatorDirectory
from flightsite.classification.specs import OperatorGroupSpec, OperatorPattern
from flightsite.classification.vocabulary import GroupKind, MissionCategory
from flightsite.db import database_path


@pytest.fixture
def db_path(isolated_data_dir: Path) -> Path:
    """Path the application would use for its database in this test's data dir."""
    return database_path(isolated_data_dir)


@pytest.fixture
def toy_directory() -> OperatorDirectory:
    """A four-group directory covering every kind of consequence a group has."""
    return OperatorDirectory(
        (
            OperatorGroupSpec(
                slug="toy-airline",
                name="Toy Airline",
                kind=GroupKind.PASSENGER,
                mission=MissionCategory.COMMERCIAL_PASSENGER,
                operators=("Toy Airline", "Toy Airline Inc"),
                callsigns=("TOY",),
            ),
            OperatorGroupSpec(
                slug="toy-forces",
                name="Toy Armed Forces",
                kind=GroupKind.MILITARY,
                mission=MissionCategory.MILITARY,
                military=True,
                operators=("Toy Armed Forces",),
            ),
            OperatorGroupSpec(
                # Declares a callsign designator on purpose: it is what proves a
                # callsign match cannot raise the law-enforcement flag.
                slug="toy-police",
                name="Toy Police",
                kind=GroupKind.LAW_ENFORCEMENT,
                mission=MissionCategory.LAW_ENFORCEMENT,
                government=True,
                law_enforcement=True,
                operators=("Toy City Police",),
                callsigns=("TPD",),
            ),
            OperatorGroupSpec(
                slug="toy-unaligned",
                name="Toy Holdings",
                kind=GroupKind.OTHER,
                operators=("Toy Holdings",),
            ),
        ),
        (OperatorPattern("sheriff", "toy-police"),),
    )
