"""Emitter category, selected altitude and emergency state on the live record.

Roadmap slice 086. The two self-descriptions (category, selected altitude)
merge like every other decoder field — sticky, because a poll that omits them
is not a statement that they changed. The emergency state does not: the
decoder lists it only while it holds a valid one, so an update without it is
the emergency ending, and the live record follows it (see the module
docstring of :mod:`flightsite.live.aircraft`).
"""

from __future__ import annotations

from flightsite.api.schemas import AircraftView
from flightsite.api.serializers import aircraft_payload
from flightsite.live import CHANGE_TRACKED_FIELDS, DEFAULT_STALE_S, appear, merge

from .conftest import SEATTLE, make_update


def test_appear_takes_all_three_from_the_first_observation() -> None:
    record = appear(
        make_update(emitter_category="A7", selected_altitude_ft=3000.0, decoder_emergency="nordo"),
        now=1_000.0,
    )

    assert record.emitter_category == "A7"
    assert record.selected_altitude_ft == 3000.0
    assert record.decoder_emergency == "nordo"


def test_category_and_selected_altitude_are_sticky() -> None:
    first = appear(make_update(emitter_category="A3", selected_altitude_ft=24000.0), now=1_000.0)

    merged, changed = merge(first, make_update(offset_s=1.0), now=1_001.0, stale_s=DEFAULT_STALE_S)

    assert merged.emitter_category == "A3"
    assert merged.selected_altitude_ft == 24000.0
    assert "emitter_category" not in changed
    assert "selected_altitude_ft" not in changed


def test_a_new_selected_altitude_replaces_the_old_and_is_a_change() -> None:
    first = appear(make_update(selected_altitude_ft=24000.0), now=1_000.0)

    merged, changed = merge(
        first,
        make_update(offset_s=1.0, selected_altitude_ft=11000.0),
        now=1_001.0,
        stale_s=DEFAULT_STALE_S,
    )

    assert merged.selected_altitude_ft == 11000.0
    assert "selected_altitude_ft" in changed


def test_the_emergency_state_follows_the_decoder_and_is_not_sticky() -> None:
    first = appear(make_update(decoder_emergency="minfuel"), now=1_000.0)

    still, unchanged = merge(
        first,
        make_update(offset_s=1.0, decoder_emergency="minfuel"),
        now=1_001.0,
        stale_s=DEFAULT_STALE_S,
    )
    ended, changed = merge(still, make_update(offset_s=2.0), now=1_002.0, stale_s=DEFAULT_STALE_S)

    assert still.decoder_emergency == "minfuel"
    assert "decoder_emergency" not in unchanged
    assert ended.decoder_emergency is None
    assert "decoder_emergency" in changed


def test_the_three_fields_are_change_tracked() -> None:
    assert {"emitter_category", "selected_altitude_ft", "decoder_emergency"} <= set(
        CHANGE_TRACKED_FIELDS
    )


# -------------------------------------------------------------- serialization


def test_the_payload_carries_all_three() -> None:
    record = appear(
        make_update(emitter_category="A7", selected_altitude_ft=3000.0, decoder_emergency="nordo"),
        now=1_000.0,
        receiver=SEATTLE,
    )

    payload = aircraft_payload(record)

    assert payload["emitter_category"] == "A7"
    assert payload["selected_altitude_ft"] == 3000.0
    assert payload["decoder_emergency"] == "nordo"
    AircraftView.model_validate(payload)


def test_the_decoder_emergency_does_not_masquerade_as_a_squawk_emergency() -> None:
    """``emergency`` keeps meaning "the squawk says so" (``docs/API.md`` §3.3)."""
    payload = aircraft_payload(
        appear(make_update(squawk="2341", decoder_emergency="nordo"), now=1_000.0)
    )

    assert payload["emergency"] is None
    assert payload["decoder_emergency"] == "nordo"


def test_absent_fields_are_present_and_null() -> None:
    payload = aircraft_payload(appear(make_update(), now=1_000.0))

    for key in ("emitter_category", "selected_altitude_ft", "decoder_emergency"):
        assert key in payload
        assert payload[key] is None, key
