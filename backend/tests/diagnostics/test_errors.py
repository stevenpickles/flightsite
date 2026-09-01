"""The recent-error ring buffer and its logging handler (SPEC §67, §68)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest

from flightsite.diagnostics.errors import (
    DATABASE,
    ENRICHMENT,
    INGESTION,
    OTHER,
    REDACTED,
    WEBSOCKET,
    ErrorRing,
    ErrorRingHandler,
    category_for_logger,
    redact,
    redact_value,
)

MOMENT = datetime(2026, 8, 31, 14, 3, 22, tzinfo=UTC)


def _record(ring: ErrorRing, event: str, category: str = INGESTION, **kwargs: object) -> None:
    ring.record(
        at=kwargs.pop("at", MOMENT),  # type: ignore[arg-type]
        category=category,
        event=event,
        level="WARNING",
        logger="flightsite.test",
        **kwargs,  # type: ignore[arg-type]
    )


class TestCategoryMapping:
    @pytest.mark.parametrize(
        ("logger", "expected"),
        [
            ("flightsite.ingest.readsb", INGESTION),
            ("flightsite.ingest", INGESTION),
            ("flightsite.demo.adapter", INGESTION),
            ("flightsite.db.startup", DATABASE),
            ("flightsite.maintenance.service", DATABASE),
            ("flightsite.sightings.worker", DATABASE),
            ("flightsite.enrichment.service", ENRICHMENT),
            ("flightsite.api.ws", WEBSOCKET),
            ("flightsite.live.events", WEBSOCKET),
            ("uvicorn.error", OTHER),
            ("flightsite.api.v1", OTHER),
        ],
    )
    def test_logger_names_map_to_spec_67_categories(self, logger: str, expected: str) -> None:
        assert category_for_logger(logger) == expected

    def test_the_longest_matching_prefix_wins(self) -> None:
        """``flightsite.api.ws`` is a WebSocket concern; ``flightsite.api`` is not."""
        assert category_for_logger("flightsite.api.ws.broadcast") == WEBSOCKET
        assert category_for_logger("flightsite.api.internal") == OTHER

    def test_a_near_miss_prefix_does_not_match(self) -> None:
        """``flightsite.database`` must not be captured by the ``flightsite.db`` prefix."""
        assert category_for_logger("flightsite.dbsomething") == OTHER


class TestRedaction:
    def test_a_secret_is_replaced_everywhere_it_appears(self) -> None:
        assert redact("key=abc and abc again", ["abc"]) == (f"key={REDACTED} and {REDACTED} again")

    def test_empty_and_blank_secrets_are_ignored(self) -> None:
        """Substituting on an empty string would shred the text protecting nothing."""
        assert redact("untouched", ["", "   "]) == "untouched"

    def test_no_configured_secret_leaves_text_alone(self) -> None:
        assert redact("untouched", []) == "untouched"

    def test_nested_structures_are_walked(self) -> None:
        payload = {
            "a": "s3cret",
            "b": {"c": ["s3cret", 1, None]},
            "d": 42,
            "e": True,
        }
        redacted = redact_value(payload, ["s3cret"])
        assert redacted == {
            "a": REDACTED,
            "b": {"c": [REDACTED, 1, None]},
            "d": 42,
            "e": True,
        }

    def test_non_string_leaves_survive_unchanged(self) -> None:
        """Numbers must not be stringified on the way through."""
        redacted = redact_value({"n": 1, "f": 1.5, "b": False, "z": None}, ["x"])
        assert redacted == {"n": 1, "f": 1.5, "b": False, "z": None}


class TestErrorRing:
    def test_records_are_returned_newest_first(self) -> None:
        ring = ErrorRing()
        for index in range(3):
            _record(ring, f"event-{index}", at=MOMENT + timedelta(seconds=index))

        assert [entry.event for entry in ring.recent(INGESTION)] == [
            "event-2",
            "event-1",
            "event-0",
        ]

    def test_the_buffer_is_bounded_and_drops_the_oldest(self) -> None:
        ring = ErrorRing(capacity=3)
        for index in range(10):
            _record(ring, f"event-{index}")

        events = [entry.event for entry in ring.recent(INGESTION)]
        assert events == ["event-9", "event-8", "event-7"]
        assert ring.total() == 3

    def test_categories_are_independent(self) -> None:
        ring = ErrorRing()
        _record(ring, "ingest", INGESTION)
        _record(ring, "db", DATABASE)

        assert [e.event for e in ring.recent(INGESTION)] == ["ingest"]
        assert [e.event for e in ring.recent(DATABASE)] == ["db"]
        assert ring.recent(ENRICHMENT) == ()

    def test_an_unknown_category_is_filed_under_other(self) -> None:
        """A caller must not be able to create unbounded buckets."""
        ring = ErrorRing()
        _record(ring, "mystery", "not-a-category")

        assert [e.event for e in ring.recent(OTHER)] == ["mystery"]

    def test_limit_truncates_newest_first(self) -> None:
        ring = ErrorRing()
        for index in range(5):
            _record(ring, f"event-{index}")

        assert [e.event for e in ring.recent(INGESTION, limit=2)] == ["event-4", "event-3"]

    def test_snapshot_covers_every_category(self) -> None:
        ring = ErrorRing()
        _record(ring, "one", WEBSOCKET)
        snapshot = ring.snapshot()

        assert set(snapshot) == {INGESTION, DATABASE, ENRICHMENT, WEBSOCKET, OTHER}
        assert [e.event for e in snapshot[WEBSOCKET]] == ["one"]

    def test_clear_empties_every_category(self) -> None:
        ring = ErrorRing()
        _record(ring, "one", WEBSOCKET)
        _record(ring, "two", DATABASE)
        ring.clear()

        assert ring.total() == 0

    def test_secrets_are_redacted_on_the_way_in(self) -> None:
        """Storage, not serialization, is the redaction boundary."""
        ring = ErrorRing()
        ring.record(
            at=MOMENT,
            category=ENRICHMENT,
            event="lookup failed with key sup3rs3cret",
            level="WARNING",
            logger="flightsite.enrichment.service",
            detail="api_key=sup3rs3cret",
            secrets=["sup3rs3cret"],
        )

        entry = ring.recent(ENRICHMENT)[0]
        assert "sup3rs3cret" not in entry.event
        assert "sup3rs3cret" not in (entry.detail or "")
        assert REDACTED in entry.event


class TestErrorRingHandler:
    def test_warnings_and_above_are_captured(self) -> None:
        ring = ErrorRing()
        handler = ErrorRingHandler(ring)
        logger = logging.getLogger("flightsite.db.test-capture")
        logger.addHandler(handler)
        try:
            logger.warning("a_warning")
            logger.error("an_error")
        finally:
            logger.removeHandler(handler)

        assert [e.event for e in ring.recent(DATABASE)] == ["an_error", "a_warning"]

    def test_info_is_not_captured(self) -> None:
        """The ring is for problems; INFO would drown them."""
        ring = ErrorRing()
        handler = ErrorRingHandler(ring)
        logger = logging.getLogger("flightsite.db.test-info")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        try:
            logger.info("routine")
        finally:
            logger.removeHandler(handler)

        assert ring.total() == 0

    def test_structured_fields_become_the_detail_string(self) -> None:
        ring = ErrorRing()
        handler = ErrorRingHandler(ring)
        logger = logging.getLogger("flightsite.ingest.test-detail")
        logger.addHandler(handler)
        try:
            logger.warning("decoder_poll_failed", extra={"url": "http://x", "attempt": 3})
        finally:
            logger.removeHandler(handler)

        detail = ring.recent(INGESTION)[0].detail or ""
        assert "url=http://x" in detail
        assert "attempt=3" in detail

    def test_stdlib_noise_is_not_rendered_into_the_detail(self) -> None:
        ring = ErrorRing()
        handler = ErrorRingHandler(ring)
        logger = logging.getLogger("flightsite.ingest.test-noise")
        logger.addHandler(handler)
        try:
            logger.warning("plain")
        finally:
            logger.removeHandler(handler)

        assert ring.recent(INGESTION)[0].detail is None

    def test_an_enormous_field_is_truncated(self) -> None:
        """One runaway log field must not dominate the diagnostics payload."""
        ring = ErrorRing()
        handler = ErrorRingHandler(ring)
        logger = logging.getLogger("flightsite.ingest.test-huge")
        logger.addHandler(handler)
        try:
            logger.warning("big", extra={"blob": "x" * 5000})
        finally:
            logger.removeHandler(handler)

        detail = ring.recent(INGESTION)[0].detail or ""
        assert len(detail) < 400
        assert detail.endswith("…")

    def test_the_handler_uses_the_records_own_timestamp(self) -> None:
        ring = ErrorRing()
        handler = ErrorRingHandler(ring)
        logger = logging.getLogger("flightsite.db.test-time")
        logger.addHandler(handler)
        try:
            logger.warning("timed")
        finally:
            logger.removeHandler(handler)

        entry = ring.recent(DATABASE)[0]
        assert entry.at.tzinfo is not None
        assert abs((datetime.now(UTC) - entry.at).total_seconds()) < 60

    def test_a_failing_secrets_provider_never_breaks_logging(self) -> None:
        """Diagnostics is an observer; it must not be able to kill a log call."""

        def explode() -> list[str]:
            raise RuntimeError("provider is broken")

        ring = ErrorRing()
        handler = ErrorRingHandler(ring, explode)
        handler.handleError = lambda record: None  # type: ignore[method-assign]
        logger = logging.getLogger("flightsite.db.test-boom")
        logger.addHandler(handler)
        try:
            logger.warning("still fine")
        finally:
            logger.removeHandler(handler)

        assert ring.total() == 0
