"""The decoder-statistics vocabulary boundary.

The companion to ``tests/ingest/test_no_field_leakage.py``, for the second
decoder document. SPEC §11 requires that decoder-specific assumptions not leak
through the domain and ADR-0003 makes that the point of the adapter seam: a
future Beast or SBS source has no ``stats.json`` at all, and the demo adapter
has no decoder.

The check is deliberately a plain source grep rather than an import graph. The
failure it guards against is someone *typing* ``peak_signal`` into the
repository or the service, and a grep catches that in review where a cleverer
check would only catch it at runtime.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import flightsite

PACKAGE_ROOT = Path(flightsite.__file__).parent

#: The module allowed to speak the decoder's statistics vocabulary.
ADAPTER_MODULE = PACKAGE_ROOT / "receiver_metrics" / "statsjson.py"

#: Field names unique to the readsb / dump1090-fa statistics document that the
#: adapter genuinely reads. Each must appear there and nowhere else.
STATS_FIELD_NAMES = (
    "peak_signal",
    "global_ok",
    "local_ok",
    "max_distance_in_nautical_miles",
    "last1min",
    "last15min",
)

#: Further statistics spellings the adapter does not consume today. Banned
#: outside it anyway, so that consuming one later is a change to
#: ``receiver_metrics/statsjson.py`` rather than a quiet dependency downstream.
RESERVED_STATS_FIELD_NAMES = (
    "strong_signals",
    "samples_processed",
    "samples_dropped",
    "unknown_icao",
    "single_message",
    "altitude_suppressed",
    "global_bad",
    "local_skipped",
    "max_distance_in_metres",
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


@pytest.mark.parametrize("field", (*STATS_FIELD_NAMES, *RESERVED_STATS_FIELD_NAMES))
def test_statistics_field_names_stay_inside_the_adapter(field: str) -> None:
    pattern = re.compile(rf"\b{re.escape(field)}\b")
    offenders = [
        str(path.relative_to(PACKAGE_ROOT))
        for path in source_files()
        if pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], (
        f"decoder statistics field {field!r} leaked out of "
        f"receiver_metrics/statsjson.py into: {', '.join(offenders)}"
    )


def test_the_adapter_module_really_does_use_those_names() -> None:
    # If statsjson.py stopped mentioning them the test above would be vacuous.
    source = ADAPTER_MODULE.read_text(encoding="utf-8")

    assert all(field in source for field in STATS_FIELD_NAMES)


def test_the_normalized_names_are_not_the_decoders() -> None:
    """The domain vocabulary must be recognisable as FlightSite's own.

    ``rssi_peak_db`` is not ``peak_signal`` and ``positions_total`` is not
    ``global_ok``: the columns of ``docs/DATA_MODEL.md`` §6 name what the value
    *is*, not which decoder field happened to supply it.
    """
    model = (PACKAGE_ROOT / "receiver_metrics" / "model.py").read_text(encoding="utf-8")

    assert "rssi_peak_db" in model
    assert "positions_total" in model
    for field in STATS_FIELD_NAMES:
        assert not re.search(rf"\b{re.escape(field)}\b", model)


def test_nothing_outside_the_repository_writes_sql() -> None:
    """The other boundary this package draws (see its ``__init__`` module map).

    Storage vocabulary belongs to
    :mod:`flightsite.receiver_metrics.repository`, so the retention arithmetic
    stays testable without a database and the transaction discipline stays in
    one place.
    """
    allowed = {"repository.py", "__init__.py"}
    offenders = [
        path.name
        for path in (PACKAGE_ROOT / "receiver_metrics").glob("*.py")
        if path.name not in allowed
        and re.search(r"\b(select|insert|delete|update)\(", path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
