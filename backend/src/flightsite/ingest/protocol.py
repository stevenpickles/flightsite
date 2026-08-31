"""The ``DecoderAdapter`` seam.

Every aircraft observation FlightSite has ever seen entered through this
protocol. It is the boundary
[ADR-0003](../../../../docs/adr/0003-decoder-adapter-abstraction.md) draws:
decoder-specific transports, cadences and field names live *below* it, and
everything above it — live store, sightings, alerts, analytics, the API —
speaks only :mod:`flightsite.ingest.types`.

Implementations planned by the roadmap:

===================== ======= ==================================================
Adapter               Slice   Transport
===================== ======= ==================================================
``ReadsbJsonAdapter``  007    HTTP polling of readsb / dump1090-fa aircraft.json
``DemoAdapter``        011    deterministic in-process simulation
``ReplayAdapter``      012    captured fixtures replayed against a clock
``BeastAdapter``       —      backlog: Beast binary stream
``SbsAdapter``         —      backlog: SBS/BaseStation text stream
===================== ======= ==================================================

Contract an implementation must honour:

* :meth:`~DecoderAdapter.updates` yields one batch per decoder observation. It
  is an infinite stream: a decoder outage is *not* the end of iteration, it is
  a health transition plus a retry. The stream ends only when the adapter is
  stopped (or the consuming task is cancelled).
* Nothing an ill-behaved decoder can do may escape as an exception from the
  stream. Malformed documents, connection failures and absurd values are
  absorbed, counted and reflected in health.
* :meth:`~DecoderAdapter.health` is cheap, synchronous and safe to call at any
  time, including while the stream is running.
* :meth:`~DecoderAdapter.stop` is idempotent and releases every resource the
  adapter opened.

Push-based sources fit this shape too: a stream adapter simply awaits its
socket instead of a timer. The protocol is intentionally pull-shaped at the
consumer end so a slow consumer cannot be handed an unbounded backlog.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from flightsite.ingest.health import AdapterHealth
from flightsite.ingest.types import AircraftStateBatch


class DecoderError(Exception):
    """Base class for decoder-boundary failures."""


class DecoderUnavailableError(DecoderError):
    """The decoder could not be reached, or answered with an error status."""


class DecoderParseError(DecoderError):
    """The decoder answered, but the document was not a usable aircraft feed.

    Raised for whole-document problems (invalid JSON, a top-level value that is
    not an object, a missing or non-list aircraft collection). Problems with a
    *single* aircraft entry never raise: they are skipped and counted, because
    one bad entry must not cost us the other 400 aircraft in the document.
    """


@runtime_checkable
class DecoderAdapter(Protocol):
    """A source of normalized aircraft observations.

    Matches the seam sketched in ``docs/ARCHITECTURE.md`` §3.5;
    :class:`~flightsite.ingest.types.AircraftStateBatch` is a
    ``Sequence[AircraftStateUpdate]`` that also carries the decoder's own
    timestamp and per-poll counters.
    """

    async def start(self) -> None:
        """Acquire whatever the adapter needs to produce updates."""
        ...

    async def stop(self) -> None:
        """Release everything :meth:`start` acquired. Idempotent."""
        ...

    def updates(self) -> AsyncIterator[AircraftStateBatch]:
        """Yield normalized batches until the adapter is stopped."""
        ...

    def health(self) -> AdapterHealth:
        """Return the current connection health snapshot."""
        ...


__all__ = [
    "DecoderAdapter",
    "DecoderError",
    "DecoderParseError",
    "DecoderUnavailableError",
]
