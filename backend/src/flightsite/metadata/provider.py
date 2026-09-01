"""The ``MetadataProvider`` seam (ADR-0006, ``docs/ARCHITECTURE.md`` §3.5).

Three methods, in the order the import pipeline calls them:

``download(workdir)``
    Fetch the upstream snapshot into ``workdir`` and describe it as a
    :class:`~flightsite.metadata.records.SourceArtifact`. This is the only
    method that touches the network, and the only one that is ``async``.

``validate(artifact)``
    Decide whether the bytes on disk are a usable snapshot — the check that
    stops a captive-portal HTML page or a truncated download from replacing a
    year of good data. Synchronous and cheap by contract; a provider needing an
    expensive check does it during ``download``.

``transform(artifact)``
    Yield :class:`~flightsite.metadata.records.NormalizedAircraftRecord` values.
    An *iterator*, not a list: snapshots run to hundreds of thousands of rows,
    and the pipeline streams them into staging in batches so peak memory is one
    batch rather than one dataset (``docs/ARCHITECTURE.md`` §6, "streamed
    imports").

The protocol deliberately carries no ``name``: a provider does not get to
decide which source row it writes to. The name comes from registration
(:mod:`flightsite.metadata.registry`), which is also where per-field precedence
is declared — so the two things that determine what a provider's data *means*
to FlightSite sit together, outside the provider itself.

Both ``validate`` and ``transform`` are synchronous and may block; the pipeline
runs a provider's transform on the event loop only for small artifacts and
otherwise hands it to a worker thread, per §3.3.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol, runtime_checkable

from flightsite.metadata.records import (
    NormalizedAircraftRecord,
    SourceArtifact,
    ValidationReport,
)


@runtime_checkable
class MetadataProvider(Protocol):
    """One upstream aircraft-metadata source, isolated behind three calls.

    ``runtime_checkable`` so the registry can reject an object that is missing
    a method at registration time — a clearer failure than an
    :class:`AttributeError` in the middle of an import run.
    """

    async def download(self, workdir: Path) -> SourceArtifact:
        """Fetch the upstream snapshot into ``workdir``.

        Raises whatever the transport raises; the pipeline records the failure
        against this source alone and leaves the previous dataset in place.
        """
        ...

    def validate(self, artifact: SourceArtifact) -> ValidationReport:
        """Judge whether ``artifact`` is a snapshot worth importing."""
        ...

    def transform(self, artifact: SourceArtifact) -> Iterator[NormalizedAircraftRecord]:
        """Stream ``artifact`` as normalized records."""
        ...


__all__ = ["MetadataProvider"]
