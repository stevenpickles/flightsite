"""The feeder vocabulary boundary — each vendor's field names stay in its module.

The companion to ``tests/receiver_metrics/test_field_isolation.py``, and a
plain source grep for the same reason: the failure it guards against is
someone *typing* ``peer_count`` into the service or the API, and a grep
catches that in review. A vendor that renames a field then costs one module,
and the service, the repository, the API and the frontend never learn a
vendor's spelling.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import flightsite

PACKAGE_ROOT = Path(flightsite.__file__).parent
FEEDERS = PACKAGE_ROOT / "feeders"

#: Field names (and log phrases) distinctive to one vendor, keyed by the only
#: module allowed to spell them.
VENDOR_VOCABULARY: dict[str, tuple[str, ...]] = {
    "piaware.py": ("adept", "piaware_version", "cpu_temp_celcius", "system_uptime", "site_url"),
    "fr24.py": (
        "fr24key",
        "feed_alias",
        "feed_legacy_id",
        "local_ips",
        "feed_status",
        "feed_status_message",
        "rx_connected",
        "feed_last_ac_sent_time",
        "feed_last_ac_sent_num",
        "feed_last_connected_time",
        "feed_current_server",
        "time_update_utc",
        "build_version",
        "num_messages",
    ),
    "ultrafeeder.py": (
        "peer_count",
        "good_sync_percentage_last_hour",
        "bad_sync_timeout",
        "outlier_percent",
        "last_bad_sync",
        "BeastReduce",
        "mlat-client-stats",
    ),
    "readsb.py": ("aircraft_without_pos", "aircraft_count_by_type", "bytes_out", "gain_db"),
    "opensky.py": ("seconds online", "disconnections", "bytes sent"),
}

#: Where a spelling may legitimately recur: its own module, and FlightSite's
#: own schema/serializer names that happen to share a word (``gain_db`` is the
#: normalized receiver field too; ``disconnections`` names the OpenSky metric).
SHARED_OK: dict[str, frozenset[str]] = {
    "gain_db": frozenset({"model.py", "service.py", "schemas.py", "feeders.py"}),
    "disconnections": frozenset({"feeders.py"}),
}


def source_files() -> list[Path]:
    return sorted(p for p in PACKAGE_ROOT.rglob("*.py") if "__pycache__" not in p.parts)


CASES = [(module, word) for module, words in VENDOR_VOCABULARY.items() for word in words]


def test_every_vendor_module_exists_and_uses_its_vocabulary() -> None:
    for module, words in VENDOR_VOCABULARY.items():
        source = (FEEDERS / module).read_text(encoding="utf-8")
        missing = [word for word in words if word not in source]
        assert missing == [], f"{module} no longer mentions {missing}"


@pytest.mark.parametrize(("module", "word"), CASES)
def test_vendor_vocabulary_stays_in_its_module(module: str, word: str) -> None:
    pattern = re.compile(rf"(?<![\w-]){re.escape(word)}(?![\w-])")
    allowed = SHARED_OK.get(word, frozenset())
    offenders = [
        str(path.relative_to(PACKAGE_ROOT))
        for path in source_files()
        if path != FEEDERS / module
        and path.name not in allowed
        and pattern.search(path.read_text(encoding="utf-8"))
    ]

    assert offenders == [], f"{word!r} leaked out of feeders/{module} into {offenders}"


def test_the_domain_model_speaks_flightsite_not_a_vendor() -> None:
    model = (FEEDERS / "model.py").read_text(encoding="utf-8")

    assert "dropped_samples" in model
    assert "peers" in model
    for word in ("peer_count", "samples_dropped", "fr24key", "site_url"):
        assert word not in model


def test_nothing_outside_the_repository_writes_sql() -> None:
    allowed = {"repository.py", "__init__.py"}
    offenders = [
        path.name
        for path in FEEDERS.glob("*.py")
        if path.name not in allowed
        and re.search(r"\b(select|insert|delete|update)\(", path.read_text(encoding="utf-8"))
    ]

    assert offenders == []
