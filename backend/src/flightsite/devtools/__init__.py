"""Capture & replay tooling: turn a live decoder session into a fixture.

Demo mode (slice 011) covers deterministic, seed-reproducible traffic for
day-to-day development. This package covers the other half: recording an
actual decoder's normalized output for a bounded duration, and replaying it
deterministically — the way to reproduce a real-world bug or pin a regression
test to real-world data (roadmap slice 012).

Module map:

============================ ==============================================
Module                       Responsibility
============================ ==============================================
:mod:`~flightsite.devtools.fixture`  the ``.fsrec.gz`` format: write/read
:mod:`~flightsite.devtools.capture`  ``flightsite-capture`` CLI + core loop
:mod:`~flightsite.devtools.replay`   ``ReplayAdapter`` (a ``DecoderAdapter``)
============================ ==============================================

A fixture stores only :mod:`flightsite.ingest.types` normalized values, never
a decoder's raw JSON (ADR-0003) — see :mod:`~flightsite.devtools.fixture` for
the full format documentation. Because :class:`~flightsite.devtools.replay.ReplayAdapter`
implements :class:`~flightsite.ingest.protocol.DecoderAdapter`, anything wired
to a live decoder can be pointed at a fixture instead, including the
ingestion service itself.
"""

from __future__ import annotations

from flightsite.devtools.capture import (
    GENERATOR,
    CaptureSummary,
    build_arg_parser,
    format_summary,
    main,
    run_capture,
)
from flightsite.devtools.fixture import (
    DEFAULT_GENERATOR,
    FIXTURE_SUFFIX,
    FORMAT_VERSION,
    Fixture,
    FixtureError,
    FixtureHeader,
    FixtureRecord,
    read_fixture,
    write_fixture,
)
from flightsite.devtools.replay import ReplayAdapter

__all__ = [
    "DEFAULT_GENERATOR",
    "FIXTURE_SUFFIX",
    "FORMAT_VERSION",
    "GENERATOR",
    "CaptureSummary",
    "Fixture",
    "FixtureError",
    "FixtureHeader",
    "FixtureRecord",
    "ReplayAdapter",
    "build_arg_parser",
    "format_summary",
    "main",
    "read_fixture",
    "run_capture",
    "write_fixture",
]
