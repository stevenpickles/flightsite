"""Demo aircraft classify, so the classification alerts can fire (issue #112),
and carry the type designators the map's silhouettes key on (slice 094).

Three levels, because the claim has three parts and they fail differently:

* the airframe table is deterministic, gives the three special-interest
  categories an operator and the ordinary ones a type alone, and classifies
  each exactly as a real registry row would;
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
from flightsite.classification.engine import classify
from flightsite.classification.model import Classification, Evidence
from flightsite.demo import DEFAULT_CENTER, Category, build_roster
from flightsite.demo.adapter import DEFAULT_POPULATION, DEFAULT_SEED, DemoAdapter
from flightsite.demo.airframes import (
    AIRFRAMES_BY_CATEGORY,
    COMMERCIAL_AIRFRAMES,
    DEMO_SOURCE,
    GOVERNMENT_AIRFRAMES,
    MILITARY_AIRFRAMES,
    MLAT_AIRFRAMES,
    OPERATED_CATEGORIES,
    POLICE_AIRFRAMES,
    RARE_AIRFRAMES,
    DemoAirframe,
    demo_metadata_records,
)
from flightsite.demo.roster import AircraftProfile
from flightsite.metadata.cache import AircraftMetadataView, MetadataCache

CLASSIFIED = (Category.MILITARY, Category.GOVERNMENT, Category.POLICE)

#: The categories deliberately left without any identity.
UNDESCRIBED = (Category.GROUND, Category.MODE_S, Category.ROTORCRAFT)


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


def test_records_are_written_for_exactly_the_described_categories() -> None:
    roster = _roster()
    records = demo_metadata_records(roster)

    described = {profile.icao for profile in roster if profile.category in AIRFRAMES_BY_CATEGORY}
    assert {record.icao24 for record in records} == described
    assert records, "the scenario always carries at least one of each category"


def test_ground_mode_s_and_the_emitter_only_helicopter_stay_undescribed() -> None:
    """Ground traffic keeps the generic ground form on the map, Mode-S-only
    aircraft have nothing to draw, and the slice-086 helicopter is the
    emitter-category fallback's acceptance case."""
    roster = _roster()
    seeded = {record.icao24 for record in demo_metadata_records(roster)}

    for profile in roster:
        if profile.category in UNDESCRIBED:
            assert profile.icao not in seeded
    assert not (set(UNDESCRIBED) & set(AIRFRAMES_BY_CATEGORY))


def test_the_records_are_deterministic_for_a_given_roster() -> None:
    """Same seed, same demo — down to which aircraft is the C-17."""
    first = demo_metadata_records(_roster())
    second = demo_metadata_records(_roster())

    assert first == second


def test_every_airframe_carries_a_type() -> None:
    """The type draws the icon; a blank one would be a silent gap."""
    for airframes in AIRFRAMES_BY_CATEGORY.values():
        for airframe in airframes:
            assert airframe.type_code.strip()
            assert airframe.model.strip()


def test_special_interest_airframes_carry_an_operator_and_a_registration() -> None:
    """The operator makes the classification claim. A blank one would classify
    as unknown and look like a bug in the classifier rather than a gap in the
    table."""
    for category in OPERATED_CATEGORIES:
        for airframe in AIRFRAMES_BY_CATEGORY[category]:
            assert airframe.operator_name is not None and airframe.operator_name.strip()
            assert airframe.registration is not None and airframe.registration.strip()


def test_ordinary_airframes_are_type_only() -> None:
    """No operator, so no classification claim; no registration, so the table
    wrapping around a category's profiles never shares a tail number."""
    for category, airframes in AIRFRAMES_BY_CATEGORY.items():
        if category in OPERATED_CATEGORIES:
            continue
        for airframe in airframes:
            assert airframe.operator_name is None
            assert airframe.registration is None


def test_the_records_leave_the_military_flag_unset() -> None:
    """The claim comes from the curated operator directory, not from a flag
    whose provenance would be published as `heuristic`."""
    assert all(record.military_flag is None for record in demo_metadata_records(_roster()))


def _classify(airframe: DemoAirframe) -> Classification:
    return classify(
        Evidence(
            icao24="ae1463",
            operator_name=airframe.operator_name,
            type_code=airframe.type_code,
        )
    )


@pytest.mark.parametrize(
    ("airframes", "attribute"),
    [
        (MILITARY_AIRFRAMES, "military"),
        (GOVERNMENT_AIRFRAMES, "government"),
        (POLICE_AIRFRAMES, "law_enforcement"),
    ],
)
def test_every_operator_in_the_table_is_one_the_directory_recognizes(
    airframes: tuple[DemoAirframe, ...], attribute: str
) -> None:
    """The table is only useful if the shipped directory agrees with it, and a
    name that stopped matching would otherwise fail silently as "unknown"."""
    for airframe in airframes:
        assert getattr(_classify(airframe), attribute), airframe


def test_type_only_identities_classify_honestly() -> None:
    """The real engine on the real inputs: an airliner type with no operator is
    unknown (``classification/data/types.py``), a business jet is business
    aviation, a light single is general aviation, and nothing is military."""
    for airframe in COMMERCIAL_AIRFRAMES:
        classification = _classify(airframe)
        assert classification.icon_category.value == "unknown", airframe
    for airframe in RARE_AIRFRAMES:
        classification = _classify(airframe)
        assert classification.icon_category.value == "business_jet", airframe
    c172 = next(a for a in MLAT_AIRFRAMES if a.type_code == "C172")
    assert _classify(c172).icon_category.value == "light_aircraft"
    for category, airframes in AIRFRAMES_BY_CATEGORY.items():
        if category in OPERATED_CATEGORIES:
            continue
        for airframe in airframes:
            classification = _classify(airframe)
            assert not classification.military, airframe
            assert not classification.government, airframe
            assert not classification.law_enforcement, airframe


def test_the_default_roster_reaches_every_military_silhouette() -> None:
    """A default-population roster has about eight military profiles; the
    first eight table entries must between them exercise every military
    shape the map draws (transport, tanker, fighter, bomber, tiltrotor,
    tandem rotor)."""
    reached = {airframe.type_code for airframe in MILITARY_AIRFRAMES[:8]}
    assert {"C17", "K35R", "V22", "A400", "F16", "B52", "H47"} <= reached
    military = [p for p in _roster() if p.category is Category.MILITARY]
    assert len(military) >= 7


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
