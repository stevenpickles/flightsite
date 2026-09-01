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

Datasets that are not aircraft metadata
---------------------------------------

Slice 027 imports an *airport* dataset (``docs/DATA_MODEL.md`` §3.6) and needs
everything this seam already provides — download, validation, transactional
promotion, independent per-source status in ``metadata_sources`` so slice 025's
update action reports it beside the others — but its rows are not
:class:`~flightsite.metadata.records.NormalizedAircraftRecord` and they do not
land in ``aircraft_metadata``.

The extension is deliberately two things and no more:

* :class:`DatasetProvider` — this same three-call shape with the record type
  left open. :class:`MetadataProvider` is the aircraft specialization of it and
  is unchanged, so slices 022 and 023 are untouched.
* :class:`~flightsite.metadata.sink.ImportSink` — *where* a source's rows land
  and how they are promoted, bound to the source at registration exactly as
  precedence is. The pipeline in :mod:`flightsite.metadata.importer` is then
  the same pipeline for both, because the only thing that differed between them
  was the destination.

Nothing else generalizes. Precedence, resolution and the metadata cache remain
aircraft-only concepts: an airport dataset has no competing sources to rank.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from flightsite.metadata.records import (
    NormalizedAircraftRecord,
    SourceArtifact,
    ValidationReport,
)


@runtime_checkable
class DatasetProvider(Protocol):
    """One upstream dataset, isolated behind three calls.

    The record type is open: what a provider yields is understood by the
    :class:`~flightsite.metadata.sink.ImportSink` it is registered with, and by
    nothing else in the pipeline. See the module docstring for why the seam is
    shaped this way.

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

    def transform(self, artifact: SourceArtifact) -> Iterator[Any]:
        """Stream ``artifact`` as records this source's sink understands."""
        ...


@runtime_checkable
class MetadataProvider(DatasetProvider, Protocol):
    """One upstream aircraft-metadata source.

    :class:`DatasetProvider` narrowed to the record type the aircraft sink
    stores. Slices 022 and 023 implement exactly this.
    """

    def transform(self, artifact: SourceArtifact) -> Iterator[NormalizedAircraftRecord]:
        """Stream ``artifact`` as normalized aircraft records."""
        ...


__all__ = ["DatasetProvider", "MetadataProvider"]
