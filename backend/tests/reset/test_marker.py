"""``flightsite.reset.marker``: mark-and-restart semantics for "Reset FlightSite
Data" (SPEC §73, slice 045).

Pure filesystem logic, tested against a bare directory rather than a real
:class:`~flightsite.db.engine.Database` — the module never opens one. What is
under test: the marker round-trips, applying it deletes exactly the database
file and its WAL sidecars, ``config.yaml``/``secrets.yaml`` are left alone,
and a marker that failed to parse still gets applied rather than silently
ignored.
"""

from __future__ import annotations

import json
from pathlib import Path

from flightsite.db.engine import DB_FILENAME
from flightsite.reset.marker import (
    RESET_MARKER_FILENAME,
    apply_pending_reset,
    marker_path,
    reset_pending,
    write_reset_marker,
)

REQUESTED_MS = 1_756_600_000_000


def _touch(path: Path, content: str = "x") -> None:
    path.write_text(content, encoding="utf-8")


def test_reset_pending_is_false_with_no_marker(tmp_path: Path) -> None:
    assert reset_pending(tmp_path) is False


def test_write_reset_marker_creates_a_readable_marker(tmp_path: Path) -> None:
    path = write_reset_marker(tmp_path, requested_ms=REQUESTED_MS)

    assert path == marker_path(tmp_path)
    assert path.name == RESET_MARKER_FILENAME
    assert reset_pending(tmp_path) is True
    assert json.loads(path.read_text(encoding="utf-8"))["requested_ms"] == REQUESTED_MS


def test_write_reset_marker_is_idempotent(tmp_path: Path) -> None:
    write_reset_marker(tmp_path, requested_ms=REQUESTED_MS)
    write_reset_marker(tmp_path, requested_ms=REQUESTED_MS + 1)

    path = marker_path(tmp_path)
    assert json.loads(path.read_text(encoding="utf-8"))["requested_ms"] == REQUESTED_MS + 1


def test_apply_pending_reset_does_nothing_when_no_marker_is_present(tmp_path: Path) -> None:
    _touch(tmp_path / DB_FILENAME, "not actually sqlite, but present")

    applied = apply_pending_reset(tmp_path)

    assert applied is False
    assert (tmp_path / DB_FILENAME).exists()


def test_apply_pending_reset_deletes_the_database_and_its_sidecars(tmp_path: Path) -> None:
    _touch(tmp_path / DB_FILENAME)
    _touch(tmp_path / f"{DB_FILENAME}-wal")
    _touch(tmp_path / f"{DB_FILENAME}-shm")
    write_reset_marker(tmp_path, requested_ms=REQUESTED_MS)

    applied = apply_pending_reset(tmp_path)

    assert applied is True
    assert not (tmp_path / DB_FILENAME).exists()
    assert not (tmp_path / f"{DB_FILENAME}-wal").exists()
    assert not (tmp_path / f"{DB_FILENAME}-shm").exists()
    assert reset_pending(tmp_path) is False


def test_apply_pending_reset_preserves_config_and_secrets(tmp_path: Path) -> None:
    _touch(tmp_path / DB_FILENAME)
    _touch(tmp_path / "config.yaml", "receiver:\n  host: 192.168.1.50\n")
    _touch(tmp_path / "secrets.yaml", "enrichment:\n  aerodatabox_api_key: shh\n")
    write_reset_marker(tmp_path, requested_ms=REQUESTED_MS)

    apply_pending_reset(tmp_path)

    config_text = (tmp_path / "config.yaml").read_text(encoding="utf-8")
    assert config_text == "receiver:\n  host: 192.168.1.50\n"
    assert (tmp_path / "secrets.yaml").exists()


def test_apply_pending_reset_tolerates_a_missing_database_file(tmp_path: Path) -> None:
    """A reset requested before anything was ever persisted must not raise."""
    write_reset_marker(tmp_path, requested_ms=REQUESTED_MS)

    assert apply_pending_reset(tmp_path) is True
    assert reset_pending(tmp_path) is False


def test_apply_pending_reset_is_a_no_op_the_second_time(tmp_path: Path) -> None:
    _touch(tmp_path / DB_FILENAME)
    write_reset_marker(tmp_path, requested_ms=REQUESTED_MS)
    apply_pending_reset(tmp_path)

    assert apply_pending_reset(tmp_path) is False


def test_a_corrupt_marker_is_still_applied(tmp_path: Path) -> None:
    """Unreadable bookkeeping must not be a reason to refuse a requested reset."""
    _touch(tmp_path / DB_FILENAME)
    _touch(marker_path(tmp_path), "{not json")

    assert apply_pending_reset(tmp_path) is True
    assert not (tmp_path / DB_FILENAME).exists()
