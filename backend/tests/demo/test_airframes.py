"""Demo aircraft classify, so the classification alerts can fire (issue #112).

Three levels, because the claim has three parts and they fail differently:

* the airframe table is deterministic and covers exactly the three
  special-interest categories;
* a demo stack's metadata cache reports ``military`` for a scenario military
  aircraft — i.e. the seeded rows really do run through precedence, the
  operator directory and :func:`~flightsite.classification.engine.classify`;
* and with the shipped ``military`` template enabled, a demo stack records an
  alert match, which is the roadmap's acceptance criterion in its literal form.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from flightsite.app import create_app
from flightsite.demo import DEFAULT_CENTER, Category, build_roster
from flightsite.demo.adapter import DEFAULT_POPULATION, DEFAULT_SEED, DemoAdapter
from flightsite.demo.airframes import (
    AIRFRAMES_BY_CATEGORY,
    DEMO_SOURCE,
    GOVERNMENT_AIRFRAMES,
    MILITARY_AIRFRAMES,
    POLICE_AIRFRAMES,
    demo_metadata_records,
)
from flightsite.demo.roster import AircraftProfile
from flightsite.metadata.cache import AircraftMetadataView, MetadataCache

CLASSIFIED = (Category.MILITARY, Category.GOVERNMENT, Category.POLICE)


def _roster() -> tuple[AircraftProfile, ...]:
    return build_roster(seed=DEFAULT_SEED, population=DEFAULT_POPULATION, center=DEFAULT_CENTER)


#: Ceiling on the wait for the metadata cache to resolve one aircraft. It
#: bounds a hang, not the work: the cache's population is a real query through
#: aiosqlite's thread pool, so what is waited on is the loop draining an
#: executor callback, and how long that takes is the machine's business.
RESOLVE_TIMEOUT_S = 10.0


async def resolved(app: FastAPI, icao: str) -> AircraftMetadataView | None:
    """The cache's view of ``icao``, once its own task has produced one."""
    cache: MetadataCache = app.state.metadata.cache
    deadline = time.monotonic() + RESOLVE_TIMEOUT_S
    while time.monotonic() < deadline:
        view = cache.get(icao)
        if view is not None:
            return view
        await asyncio.sleep(0.01)
    return None


# ------------------------------------------------------------------ the table


def test_records_are_written_for_exactly_the_three_special_categories() -> None:
    roster = _roster()
    records = demo_metadata_records(roster)

    classified = {profile.icao for profile in roster if profile.category in CLASSIFIED}
    assert {record.icao24 for record in records} == classified
    assert records, "the scenario always carries at least one of each category"


def test_the_ordinary_categories_are_left_unknown() -> None:
    """A demo in which everything classifies would be a worse demo: "unknown"
    is the common and honest answer for an airframe no registry describes."""
    roster = _roster()
    seeded = {record.icao24 for record in demo_metadata_records(roster)}

    for profile in roster:
        if profile.category not in CLASSIFIED:
            assert profile.icao not in seeded


def test_the_records_are_deterministic_for_a_given_roster() -> None:
    """Same seed, same demo — down to which aircraft is the C-17."""
    first = demo_metadata_records(_roster())
    second = demo_metadata_records(_roster())

    assert first == second


def test_every_airframe_carries_an_operator_and_a_type() -> None:
    """Both are load-bearing: the operator makes the claim, the type draws the
    icon. A blank either side would classify as unknown and look like a bug in
    the classifier rather than a gap in the table."""
    for airframes in AIRFRAMES_BY_CATEGORY.values():
        for airframe in airframes:
            assert airframe.operator_name.strip()
            assert airframe.type_code.strip()
            assert airframe.registration.strip()


def test_the_records_leave_the_military_flag_unset() -> None:
    """The claim comes from the curated operator directory, not from a flag
    whose provenance would be published as `heuristic`."""
    assert all(record.military_flag is None for record in demo_metadata_records(_roster()))


@pytest.mark.parametrize(
    ("airframes", "attribute"),
    [
        (MILITARY_AIRFRAMES, "military"),
        (GOVERNMENT_AIRFRAMES, "government"),
        (POLICE_AIRFRAMES, "law_enforcement"),
    ],
)
def test_every_operator_in_the_table_is_one_the_directory_recognizes(
    airframes: tuple[object, ...], attribute: str
) -> None:
    """The table is only useful if the shipped directory agrees with it, and a
    name that stopped matching would otherwise fail silently as "unknown"."""
    from flightsite.classification.engine import classify
    from flightsite.classification.model import Evidence

    for airframe in airframes:
        classification = classify(
            Evidence(
                icao24="ae1463",
                operator_name=airframe.operator_name,  # type: ignore[attr-defined]
                type_code=airframe.type_code,  # type: ignore[attr-defined]
            )
        )
        assert getattr(classification, attribute), airframe


# ------------------------------------------------------------- the demo stack


@pytest.fixture
def demo_app(isolated_data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("FLIGHTSITE_DEMO", "1")
    return isolated_data_dir


def _first_military(adapter: DemoAdapter) -> AircraftProfile:
    return next(p for p in adapter.roster if p.category is Category.MILITARY)


async def test_a_demo_military_aircraft_resolves_as_military(demo_app: Path) -> None:
    """Seeded metadata, resolved and classified by the ordinary pipeline."""
    app = create_app(demo_app)

    async with app.router.lifespan_context(app):
        adapter: DemoAdapter = app.state.demo_adapter
        profile = _first_military(adapter)
        app.state.live.apply(adapter.batch_for_tick(profile.spawn_tick + 1))

        view = await resolved(app, profile.icao)

    assert view is not None, "the seeded aircraft resolved no metadata at all"
    assert view.classification.military is True
    assert view.metadata is not None
    assert view.metadata.operator_src == DEMO_SOURCE


async def test_a_demo_stack_with_the_military_template_records_a_match(
    demo_app: Path,
) -> None:
    """The acceptance criterion: the template fires in demo mode."""
    (demo_app / "config.yaml").write_text(
        "alerts:\n  enabled_templates:\n    - military\n", encoding="utf-8"
    )
    app = create_app(demo_app)
    transport = ASGITransport(app=app)

    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://testserver") as client,
    ):
        adapter: DemoAdapter = app.state.demo_adapter
        profile = _first_military(adapter)
        app.state.live.apply(adapter.batch_for_tick(profile.spawn_tick + 1))
        assert await resolved(app, profile.icao) is not None
        await app.state.persistence.process_pending()
        await app.state.alerts.engine.process_pending()
        await app.state.persistence.process_pending()

        body = (await client.get("/api/v1/alerts/matches")).json()

    assert body["items"], "no alert match was recorded on a demo stack"
    assert any(match["severity"] == "high" for match in body["items"])
    assert any(
        match["rule"] is not None and match["rule"]["name"] == "Military aircraft"
        for match in body["items"]
    )
