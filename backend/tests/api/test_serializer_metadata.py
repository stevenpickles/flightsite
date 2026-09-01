"""The metadata half of the §3.3 aircraft object, now that it is populated.

Slice 010 built these keys and left them ``null``; slice 024 fills them in.
What is asserted here is that the *shape* did not have to change to accommodate
that — the object a client coded against in slice 010 is the object it gets now
— and that the two things FlightSite adds of its own (the operator group and
the classification) are labelled as its own in the ``provenance`` map.
"""

from __future__ import annotations

from typing import Any

from flightsite.api.schemas import AircraftView
from flightsite.api.serializers import METADATA_PROVENANCE_KEYS, aircraft_payload
from flightsite.classification.engine import classify
from flightsite.classification.model import Evidence
from flightsite.classification.operators import default_directory
from flightsite.ingest import Position
from flightsite.live import LiveAircraft, appear
from flightsite.metadata.cache import AircraftMetadataView
from flightsite.metadata.precedence import ResolvedMetadata

from ..live.conftest import SEATTLE, make_update

NEARBY = Position(latitude=47.6205, longitude=-122.3493)


def record(**fields: Any) -> LiveAircraft:
    return appear(make_update(position=NEARBY, **fields), now=1_000.0, receiver=SEATTLE)


def view(
    icao24: str = "ae1463",
    *,
    callsign: str | None = None,
    operator_group: str | None = None,
    military_flag_source: str | None = None,
    **resolved: Any,
) -> AircraftMetadataView:
    """A cache entry as the cache would have built it, classification included."""
    metadata = ResolvedMetadata(icao24=icao24, updated_ms=1, **resolved)
    evidence = Evidence(
        icao24=icao24,
        military_flag=military_flag_source is not None,
        military_flag_source=military_flag_source,
        operator_name=metadata.operator_name,
        type_code=metadata.type_code,
        registration=metadata.registration,
        callsign=callsign,
    )
    return AircraftMetadataView(
        icao24=icao24,
        metadata=metadata,
        operator_group=operator_group,
        evidence=evidence,
        classification=classify(evidence),
    )


MILITARY = view(
    "ae1463",
    callsign="RCH492",
    operator_group="US Military",
    military_flag_source="mictronics",
    registration="05-8153",
    registration_src="mictronics",
    type_code="C17",
    type_code_src="mictronics",
    model="Boeing C-17A Globemaster III",
    model_src="mictronics",
    operator_name="United States Air Force",
    operator_src="mictronics",
    operator_group_id=1,
)


def test_the_documented_example_serializes_as_documented() -> None:
    """``docs/API.md`` §3.3's own worked example, field for field."""
    payload = aircraft_payload(record(callsign="RCH492", squawk="4521"), metadata=MILITARY)

    assert payload["registration"] == "05-8153"
    assert payload["aircraft_type"] == "C17"
    assert payload["model"] == "Boeing C-17A Globemaster III"
    assert payload["operator"] == "United States Air Force"
    assert payload["operator_group"] == "US Military"
    assert payload["classification"] == {
        "military": True,
        "government": False,
        "law_enforcement": False,
        "mission": "military",
        "icon_category": "military_transport",
        "confidence": "high",
    }


def test_a_populated_payload_still_validates_against_the_published_model() -> None:
    """``extra="forbid"``: the values arrived without the shape moving."""
    payload = aircraft_payload(record(callsign="RCH492"), metadata=MILITARY)

    assert AircraftView.model_validate(payload).operator_group == "US Military"


def test_every_documented_key_is_still_present() -> None:
    payload = aircraft_payload(record(), metadata=MILITARY)

    assert set(payload) == set(AircraftView.model_fields)


def test_the_classification_object_is_null_when_nothing_is_known() -> None:
    """§2.7: the UI renders ``Unknown``; an object of negatives says less."""
    entry = view("a88888", registration="N99999", type_code="B738")
    payload = aircraft_payload(record(), metadata=entry)

    assert payload["registration"] == "N99999"
    assert payload["aircraft_type"] == "B738"
    assert payload["classification"] is None


def test_an_ungrouped_operator_is_published_without_a_group() -> None:
    """SPEC §38: the exact operator is never withheld for want of a group."""
    entry = view("a00001", operator_name="Nobody In Particular", operator_src="mictronics")
    payload = aircraft_payload(record(), metadata=entry)

    assert payload["operator"] == "Nobody In Particular"
    assert payload["operator_group"] is None


def test_an_aircraft_the_cache_resolved_to_nothing_serializes_as_unknown() -> None:
    """ "Nobody knows" and "we have not looked" are the same to a client."""
    payload = aircraft_payload(record(), metadata=AircraftMetadataView(icao24="beef01"))

    for field in ("registration", "aircraft_type", "model", "operator", "operator_group"):
        assert payload[field] is None, field
    assert payload["classification"] is None


def test_the_icon_category_a_helicopter_emits_is_the_one_the_frontend_draws() -> None:
    """The activation this slice promises: rotorcraft silhouettes start firing.

    ``frontend/src/features/map/aircraft/icons/resolveIcon.ts`` maps the
    category ``helicopter`` onto its rotorcraft shape and falls everything else
    through to the generic one.
    """
    entry = view("a44444", operator_name="Travis County Sheriff", type_code="EC45")
    payload = aircraft_payload(record(), metadata=entry)
    classification = payload["classification"]

    assert isinstance(classification, dict)
    assert classification["icon_category"] == "helicopter"
    assert classification["law_enforcement"] is True


# --------------------------------------------------------------- provenance


def test_metadata_provenance_names_the_payload_field_not_the_column() -> None:
    """§2.6: entries name fields. The §3.3 field is ``aircraft_type``."""
    payload = aircraft_payload(record(), metadata=MILITARY)
    provenance = payload["provenance"]

    assert isinstance(provenance, dict)
    assert provenance["aircraft_type"] == "mictronics"
    assert "type_code" not in provenance


def test_provenance_carries_live_and_metadata_entries_together() -> None:
    payload = aircraft_payload(record(), metadata=MILITARY)

    assert payload["provenance"] == {
        "distance_nm": "derived",
        "bearing_deg": "derived",
        "registration": "mictronics",
        "aircraft_type": "mictronics",
        "model": "mictronics",
        "operator": "mictronics",
        "operator_group": "derived",
        "classification": "mictronics",
    }


def test_a_field_the_payload_does_not_publish_gets_no_provenance_entry() -> None:
    """The resolved row also carries a year and an owner; §3.3 shows neither."""
    entry = view(
        "a00001",
        registration="N12345",
        registration_src="faa",
        manufacture_year=1978,
        year_src="faa",
        owner="Somebody",
        owner_src="faa",
    )
    payload = aircraft_payload(record(), metadata=entry)
    provenance = payload["provenance"]

    assert isinstance(provenance, dict)
    assert provenance["registration"] == "faa"
    assert "manufacture_year" not in provenance
    assert "owner" not in provenance


def test_the_provenance_key_map_covers_everything_the_cache_can_report() -> None:
    """A resolved field gaining a payload slot must gain a key here too."""
    entry = view(
        "a00001",
        registration="N1",
        registration_src="faa",
        type_code="B738",
        type_code_src="mictronics",
        model="737",
        model_src="mictronics",
        operator_name="Delta Air Lines",
        operator_src="mictronics",
        manufacture_year=2001,
        year_src="faa",
        owner="Somebody",
        owner_src="faa",
        operator_group="Delta Air Lines",
    )
    reported = set(entry.provenance())

    assert reported - set(METADATA_PROVENANCE_KEYS) == {"manufacture_year", "owner"}


def test_a_curated_group_attributes_the_classification_to_flightsite() -> None:
    """§2.8's vocabulary: ``heuristic`` is FlightSite's own claim."""
    entry = view(
        "a1b2c3",
        operator_name="Delta Air Lines",
        operator_src="mictronics",
        operator_group=default_directory().groups[0].name,
    )
    payload = aircraft_payload(record(), metadata=entry)
    provenance = payload["provenance"]

    assert isinstance(provenance, dict)
    assert provenance["operator"] == "mictronics"
    assert provenance["classification"] == "heuristic"
