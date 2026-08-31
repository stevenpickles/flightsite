"""The decoder-vocabulary boundary.

Roadmap slice 007 acceptance: *"no readsb-specific field names appear outside
the adapter module"*. SPEC §11 requires that readsb-specific assumptions not
leak through the domain, and ADR-0003 makes that the whole point of the
``DecoderAdapter`` seam — a future Beast or SBS adapter has none of these
fields, and neither does the demo adapter.

The check is deliberately a plain source grep rather than an import graph or
an AST walk: the failure it guards against is someone *typing* ``alt_baro``
into a live-store or API module, and a grep catches that in the review where a
cleverer check would only catch it at runtime.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import flightsite

PACKAGE_ROOT = Path(flightsite.__file__).parent

#: The module allowed to speak readsb. Everything else must not.
ADAPTER_MODULE = PACKAGE_ROOT / "ingest" / "readsb.py"

#: Field names and ``type`` values unique to the readsb / dump1090-fa JSON
#: output that the adapter genuinely handles. Each must appear in
#: ``ingest/readsb.py`` and nowhere else in the package.
DECODER_FIELD_NAMES = (
    "alt_baro",
    "alt_geom",
    "baro_rate",
    "geom_rate",
    "vert_rate",
    "seen_pos",
    "nucp",
    "dbFlags",
    "calc_track",
    "rr_lat",
    "rr_lon",
    "adsb_icao",
    "tisb_icao",
    "adsr_icao",
    "tisb_trackfile",
    "mode_s",
)

#: Further decoder spellings the adapter does not consume today. They are
#: banned outside it anyway, so that consuming one later is a change to
#: ``ingest/readsb.py`` rather than a quiet dependency somewhere downstream.
RESERVED_DECODER_FIELD_NAMES = (
    "nic_baro",
    "sil_type",
    "nav_altitude_mcp",
    "nav_qnh",
    "track_rate",
    "mag_heading",
    "gpsOkBefore",
    "receiverCount",
)


def source_files() -> list[Path]:
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if path != ADAPTER_MODULE and "__pycache__" not in path.parts
    )


def test_the_adapter_module_and_some_other_sources_exist() -> None:
    # Guards against the grep below passing because it found nothing to read.
    assert ADAPTER_MODULE.is_file()
    assert len(source_files()) > 5


@pytest.mark.parametrize("field", (*DECODER_FIELD_NAMES, *RESERVED_DECODER_FIELD_NAMES))
def test_decoder_field_names_stay_inside_the_adapter(field: str) -> None:
    pattern = re.compile(rf"\b{re.escape(field)}\b")
    offenders = [
        str(path.relative_to(PACKAGE_ROOT))
        for path in source_files()
        if pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], (
        f"decoder field {field!r} leaked out of ingest/readsb.py into: {', '.join(offenders)}"
    )


def test_the_adapter_module_really_does_use_those_names() -> None:
    # If readsb.py stopped mentioning them the test above would be vacuous.
    source = ADAPTER_MODULE.read_text(encoding="utf-8")

    assert all(field in source for field in DECODER_FIELD_NAMES)


def test_domain_field_names_are_not_mistaken_for_decoder_ones() -> None:
    # The canonical `seen_pos_s` deliberately looks like readsb's `seen_pos`;
    # the word-boundary match must not confuse the two.
    types_source = (PACKAGE_ROOT / "ingest" / "types.py").read_text(encoding="utf-8")

    assert "seen_pos_s" in types_source
    assert not re.search(r"\bseen_pos\b", types_source)
