"""Airport data and nearest-airport context (SPEC §41, roadmap slice 027).

Five parts, each with one job:

``records`` / ``ourairports``
    The OurAirports dataset behind the ADR-0006 boundary — one module knows the
    upstream's columns, everything else sees
    :class:`~flightsite.airports.records.AirportRecord`.
``repository`` / ``sink``
    The ``airports`` table, and the
    :class:`~flightsite.metadata.sink.ImportSink` that lets the dataset ride the
    existing import pipeline. Registered as the source ``airports``, so slice
    025's "Update Aircraft Metadata" action reports it beside the aircraft
    sources with its own independent status (SPEC §27).
``index``
    The whole dataset in memory, grid-bucketed, so a nearest-airport question
    never becomes a query (``docs/ARCHITECTURE.md`` §3.1).
``inference``
    The confidence gates, as a pure function. This is where "conservative"
    lives, and it is deliberately readable in one place.
``service``
    An independent consumer of the live event stream that holds the current
    answer per aircraft in memory and writes the confident ones onto the
    sighting through the persistence worker.

Everything this package produces is labeled ``heuristic`` in ``provenance``
(``docs/API.md`` §2.6) and is kept in different columns and a different API
block from externally reported routes. SPEC §41 requires the inference to be
*clearly labeled as inferred*; keeping the two apart structurally is how that
stays true no matter what a later slice renders.
"""

from __future__ import annotations

from flightsite.airports.index import AirportIndex, NearestAirport
from flightsite.airports.inference import NEAREST_SEARCH_NM, Kinematics, TrendSample
from flightsite.airports.model import AirportContext, InferredPhase
from flightsite.airports.ourairports import OurAirportsProvider
from flightsite.airports.records import AirportRecord, AirportRecordError
from flightsite.airports.repository import AirportRepository
from flightsite.airports.service import AirportContextService
from flightsite.airports.sink import AirportImportSink

#: The registry name this dataset is registered under, and the value that
#: appears in ``metadata_sources.source``. Named once here because the app
#: wiring, the status endpoint's tests and the licensing register all refer to
#: the same string.
AIRPORTS_SOURCE = "airports"

__all__ = [
    "AIRPORTS_SOURCE",
    "NEAREST_SEARCH_NM",
    "AirportContext",
    "AirportContextService",
    "AirportImportSink",
    "AirportIndex",
    "AirportRecord",
    "AirportRecordError",
    "AirportRepository",
    "InferredPhase",
    "Kinematics",
    "NearestAirport",
    "OurAirportsProvider",
    "TrendSample",
]
