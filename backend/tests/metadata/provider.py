"""A complete in-memory ``MetadataProvider`` and the fault injection it takes.

The framework ships no concrete provider — slices 022 and 023 do — so the
pipeline needs one real implementation to be exercised against. This is it: a
provider that writes an actual file during ``download``, validates it, and
streams records back out, with a switch to make any single stage fail exactly
the way a real one would.

It lives in the tests rather than in ``src`` deliberately. ADR-0006 warns
against protocol implementations with no consumer sitting in the shipped
package; a provider whose only caller is the test suite belongs beside the test
suite.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path

from flightsite.metadata.records import (
    NormalizedAircraftRecord,
    SourceArtifact,
    ValidationReport,
)
from flightsite.metadata.registry import ImportPhase


class ProviderFailure(RuntimeError):
    """The failure an injected fault raises. Distinct so tests can match it."""


class InMemoryMetadataProvider:
    """A provider over a fixed list of records, with optional injected faults.

    Args:
        records: what ``transform`` yields, in order.
        version: the artifact version, as an upstream release tag would be.
        fail_at: the stage to fail at. ``DOWNLOAD`` raises from the download,
            ``VALIDATE`` returns a rejected report, ``STAGING`` raises partway
            through the transform — the three ways a real source breaks.
        fail_after: records yielded before a ``STAGING`` fault fires.
        report: an explicit validation report, overriding the default.
        bad_rows: raw addresses yielded as unnormalizable records, to exercise
            the rejection tolerance.
    """

    def __init__(
        self,
        records: Sequence[NormalizedAircraftRecord] = (),
        *,
        version: str = "2026-08-31",
        fail_at: ImportPhase | None = None,
        fail_after: int = 0,
        report: ValidationReport | None = None,
        bad_rows: int = 0,
    ) -> None:
        self.records = list(records)
        self.version = version
        self.fail_at = fail_at
        self.fail_after = fail_after
        self.report = report
        self.bad_rows = bad_rows
        self.downloads = 0
        self.validations = 0
        self.transforms = 0

    async def download(self, workdir: Path) -> SourceArtifact:
        self.downloads += 1
        if self.fail_at is ImportPhase.DOWNLOAD:
            raise ProviderFailure("upstream unreachable")
        path = workdir / "snapshot.json"
        payload = [record.icao24 for record in self.records]
        path.write_text(json.dumps(payload), encoding="utf-8")
        return SourceArtifact(
            path=path,
            version=self.version,
            content_hash=f"sha256:{len(payload):08x}",
            size_bytes=path.stat().st_size,
        )

    def validate(self, artifact: SourceArtifact) -> ValidationReport:
        self.validations += 1
        if self.fail_at is ImportPhase.VALIDATE:
            return ValidationReport.rejected("downloaded file is not a snapshot")
        if self.report is not None:
            return self.report
        return ValidationReport.accepted()

    def transform(self, artifact: SourceArtifact) -> Iterator[NormalizedAircraftRecord]:
        self.transforms += 1
        for index, record in enumerate(self.records):
            if self.fail_at is ImportPhase.STAGING and index >= self.fail_after:
                raise ProviderFailure("snapshot truncated mid-record")
            yield record
        for index in range(self.bad_rows):
            # A row a real parser would emit from a corrupt line: the framework
            # re-normalizes at the boundary and drops it.
            yield NormalizedAircraftRecord(icao24=f"not-hex-{index}")


__all__ = ["InMemoryMetadataProvider", "ProviderFailure"]
