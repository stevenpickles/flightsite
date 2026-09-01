"""Archive validation, shared by ``verify`` and ``restore``.

``flightsite-backup verify`` and the validation phase of
``flightsite-backup restore`` run the *same* checks in the same order — the
only difference is what they do with the answer and whether member payloads are
written to disk on the way past. That is why this module exposes one
:func:`inspect_archive` used by both: a restore can never be laxer than the
verification a user ran beforehand.

Checks, in order (cheapest and most diagnostic first):

1. The container opens as a gzip tar.
2. ``manifest.json`` exists and parses at a supported ``format_version``.
3. Members are exactly the manifest's payload set plus the manifest itself —
   no extras, no missing entries, no non-regular entries.
4. Schema compatibility against this build's Alembic head (:mod:`.compat`).
5. Every payload member's SHA-256 and byte length match the manifest.

Verification collects *every* problem rather than stopping at the first, so a
user diagnosing a bad archive sees the whole picture in one run.
"""

from __future__ import annotations

import tarfile
from dataclasses import dataclass
from pathlib import Path

from flightsite.backup import archive as archive_io
from flightsite.backup.compat import SchemaCompatibility, check_schema
from flightsite.backup.errors import ArchiveValidationError, BackupError
from flightsite.backup.manifest import (
    ALLOWED_MEMBERS,
    MANIFEST_MEMBER,
    Manifest,
    parse_manifest,
)


@dataclass(frozen=True, slots=True)
class FileCheck:
    """The checksum verdict for one payload member."""

    name: str
    expected_sha256: str
    actual_sha256: str
    expected_size: int
    actual_size: int

    @property
    def ok(self) -> bool:
        """True when the member matched the manifest byte for byte."""
        return self.expected_sha256 == self.actual_sha256 and self.expected_size == self.actual_size

    def problem(self) -> str | None:
        """A human-readable description of the mismatch, or ``None``."""
        if self.ok:
            return None
        if self.expected_size != self.actual_size:
            return (
                f"{self.name}: size mismatch — manifest says {self.expected_size} bytes, "
                f"archive holds {self.actual_size}"
            )
        return (
            f"{self.name}: checksum mismatch — manifest says sha256 "
            f"{self.expected_sha256}, archive holds {self.actual_sha256}. "
            "The archive is corrupted or was modified after it was written."
        )


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Everything ``verify`` learned about one archive."""

    archive: Path
    manifest: Manifest | None = None
    compatibility: SchemaCompatibility | None = None
    checks: tuple[FileCheck, ...] = ()
    problems: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """True when the archive is intact and restorable by this build."""
        return not self.problems

    def render(self) -> str:
        """The multi-line report ``flightsite-backup verify`` prints."""
        lines = [f"archive: {self.archive}"]
        manifest = self.manifest
        if manifest is not None:
            lines += [
                f"  format version:     {manifest.format_version}",
                f"  flightsite version: {manifest.flightsite_version}",
                f"  created (UTC):      {manifest.created_utc}",
                f"  schema revision:    {manifest.schema_revision or '(unstamped)'}",
                f"  includes secrets:   {'yes' if manifest.includes_secrets else 'no'}",
            ]
            if manifest.metadata_sources:
                lines.append("  metadata sources:")
                lines += [
                    f"    - {entry.source}: version={entry.dataset_version or '-'} "
                    f"last_success={entry.last_success or 'never'}"
                    for entry in manifest.metadata_sources
                ]
            else:
                lines.append("  metadata sources:   (none recorded)")
        if self.checks:
            lines.append("  checksums:")
            lines += [
                f"    - {check.name}: {'OK' if check.ok else 'FAILED'} ({check.actual_size} bytes)"
                for check in self.checks
            ]
        if self.compatibility is not None:
            lines.append(f"  compatibility:      {self.compatibility.summary()}")
        if self.problems:
            lines.append("  RESULT: NOT RESTORABLE")
            lines += [f"    - {problem}" for problem in self.problems]
        else:
            lines.append("  RESULT: restorable")
        return "\n".join(lines)


def _member_problems(
    names: tuple[str, ...], irregular: tuple[str, ...], manifest: Manifest
) -> list[str]:
    problems: list[str] = []
    present = set(names)
    expected = manifest.file_names | {MANIFEST_MEMBER}

    for name in sorted(present - expected):
        problems.append(f"archive holds {name!r}, which the manifest does not list")
    for name in sorted(expected - present):
        problems.append(f"manifest lists {name!r}, which the archive does not contain")
    for name in sorted(present - ALLOWED_MEMBERS):
        problems.append(f"member {name!r} is not a member name FlightSite backups may contain")
    for name in sorted(set(irregular)):
        problems.append(f"member {name!r} is not a regular file")
    return problems


def inspect_archive(path: Path, *, extract_to: Path | None = None) -> VerificationReport:
    """Validate ``path``, optionally extracting payload members to ``extract_to``.

    Never raises for a *content* problem: everything wrong with the archive
    lands in :attr:`VerificationReport.problems`. Extraction to ``extract_to``
    happens as part of the checksum pass, so a caller that wants the files
    reads them exactly once.
    """
    problems: list[str] = []
    manifest: Manifest | None = None
    compatibility: SchemaCompatibility | None = None
    checks: tuple[FileCheck, ...] = ()

    try:
        with archive_io.open_archive(path) as handle:
            names = archive_io.member_names(handle)
            manifest = parse_manifest(archive_io.read_member(handle, MANIFEST_MEMBER))
            problems += _member_problems(names, archive_io.irregular_members(handle), manifest)

            compatibility = check_schema(manifest.schema_revision)
            if not compatibility.restorable:
                problems.append(compatibility.summary())

            checks, checksum_problems = _check_payloads(handle, manifest, names, extract_to)
            problems += checksum_problems
    except BackupError as exc:
        problems.append(str(exc))

    return VerificationReport(
        archive=path,
        manifest=manifest,
        compatibility=compatibility,
        checks=checks,
        problems=tuple(problems),
    )


def _check_payloads(
    handle: tarfile.TarFile,
    manifest: Manifest,
    names: tuple[str, ...],
    extract_to: Path | None,
) -> tuple[tuple[FileCheck, ...], list[str]]:
    checks: list[FileCheck] = []
    problems: list[str] = []
    present = set(names)

    for entry in manifest.files:
        if entry.name not in present:
            # Already reported as a missing member; do not also fail on it here.
            continue
        destination = None if extract_to is None else extract_to / entry.name
        try:
            digest = archive_io.copy_member(handle, entry.name, destination)
        except ArchiveValidationError as exc:
            problems.append(str(exc))
            continue
        check = FileCheck(
            name=entry.name,
            expected_sha256=entry.sha256,
            actual_sha256=digest.sha256,
            expected_size=entry.size_bytes,
            actual_size=digest.size_bytes,
        )
        checks.append(check)
        problem = check.problem()
        if problem is not None:
            problems.append(problem)

    return tuple(checks), problems


def verify_archive(path: Path) -> VerificationReport:
    """Validate an archive without touching anything on disk."""
    return inspect_archive(path, extract_to=None)


__all__ = ["FileCheck", "VerificationReport", "inspect_archive", "verify_archive"]
