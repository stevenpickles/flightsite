"""The backup manifest: what an archive contains and what produced it.

SPEC §72 makes backups *version-aware*: the manifest carries the FlightSite
version, the database schema revision, the creation time, checksums, and the
relevant metadata/source versions. Restore reads it before touching anything.

The manifest is deliberately plain JSON parsed by hand rather than a Pydantic
model. It is the one file a restore must be able to read from an archive
written by a *different* build of FlightSite, so its parser has to fail with a
precise, human-readable complaint about an unexpected shape rather than a
validation traceback — and it must never gain a field whose absence breaks an
older reader silently. ``format_version`` is the compatibility gate: a reader
refuses a format it does not know.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

from flightsite.backup.errors import ManifestError

#: Manifest schema version written by this build.
FORMAT_VERSION: Final = 1

#: Manifest schema versions this build can read.
SUPPORTED_FORMAT_VERSIONS: Final = frozenset({1})

#: Archive member holding the manifest.
MANIFEST_MEMBER: Final = "manifest.json"

#: Archive member holding the SQLite snapshot.
DATABASE_MEMBER: Final = "flightsite.sqlite3"

#: Archive member holding the non-secret configuration.
CONFIG_MEMBER: Final = "config.yaml"

#: Archive member holding secrets — present only when explicitly requested.
SECRETS_MEMBER: Final = "secrets.yaml"

#: Every member name an archive is allowed to contain. Restore reads members by
#: name from this set and never calls ``extractall``, so a hostile archive
#: cannot write outside the destination directory.
ALLOWED_MEMBERS: Final = frozenset(
    {MANIFEST_MEMBER, DATABASE_MEMBER, CONFIG_MEMBER, SECRETS_MEMBER}
)

#: Payload members in the order restore swaps them into the data directory.
PAYLOAD_MEMBERS: Final = (DATABASE_MEMBER, CONFIG_MEMBER, SECRETS_MEMBER)


def utc_iso(moment: datetime) -> str:
    """Render ``moment`` as a ``Z``-suffixed UTC ISO-8601 string."""
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_iso_from_ms(epoch_ms: int | None) -> str | None:
    """Render an epoch-millisecond column as UTC ISO-8601, passing ``None`` through."""
    if epoch_ms is None:
        return None
    return utc_iso(datetime.fromtimestamp(epoch_ms / 1000, tz=UTC))


@dataclass(frozen=True, slots=True)
class FileEntry:
    """Checksum and size of one payload member."""

    name: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class MetadataSourceEntry:
    """A ``metadata_sources`` row as the manifest records it (SPEC §72).

    Enough to answer "which metadata datasets does this backup carry?" without
    opening the database — the question a user asks when choosing between two
    archives.
    """

    source: str
    dataset_version: str | None
    last_success: str | None


@dataclass(frozen=True, slots=True)
class Manifest:
    """The contents of ``manifest.json``."""

    format_version: int
    flightsite_version: str
    #: Alembic revision stamped in the snapshot; ``None`` if it was unstamped.
    schema_revision: str | None
    created_utc: str
    includes_secrets: bool
    files: tuple[FileEntry, ...]
    metadata_sources: tuple[MetadataSourceEntry, ...]

    def file(self, name: str) -> FileEntry | None:
        """The entry for ``name``, or ``None`` if the manifest does not list it."""
        for entry in self.files:
            if entry.name == name:
                return entry
        return None

    @property
    def file_names(self) -> frozenset[str]:
        """Names of every payload member the manifest claims."""
        return frozenset(entry.name for entry in self.files)

    def to_dict(self) -> dict[str, Any]:
        """The JSON-serializable form written into the archive."""
        return {
            "format_version": self.format_version,
            "flightsite_version": self.flightsite_version,
            "schema_revision": self.schema_revision,
            "created_utc": self.created_utc,
            "includes_secrets": self.includes_secrets,
            "files": {
                entry.name: {"sha256": entry.sha256, "size_bytes": entry.size_bytes}
                for entry in self.files
            },
            "metadata_sources": [
                {
                    "source": entry.source,
                    "dataset_version": entry.dataset_version,
                    "last_success": entry.last_success,
                }
                for entry in self.metadata_sources
            ],
        }

    def to_json(self) -> str:
        """Pretty-printed JSON, newline-terminated so the file reads cleanly."""
        return json.dumps(self.to_dict(), indent=2, sort_keys=False) + "\n"


def _require(data: Mapping[str, Any], key: str) -> Any:
    if key not in data:
        raise ManifestError(f"manifest is missing required key {key!r}")
    return data[key]


def _require_str(data: Mapping[str, Any], key: str) -> str:
    value = _require(data, key)
    if not isinstance(value, str):
        raise ManifestError(f"manifest key {key!r} must be a string, got {type(value).__name__}")
    return value


def _optional_str(data: Mapping[str, Any], key: str) -> str | None:
    value = _require(data, key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ManifestError(
            f"manifest key {key!r} must be a string or null, got {type(value).__name__}"
        )
    return value


def _parse_files(raw: Any) -> tuple[FileEntry, ...]:
    if not isinstance(raw, dict):
        raise ManifestError("manifest key 'files' must be an object of name -> checksum record")
    entries: list[FileEntry] = []
    for name, record in raw.items():
        if not isinstance(record, dict):
            raise ManifestError(f"manifest file entry {name!r} must be an object")
        sha256 = record.get("sha256")
        size = record.get("size_bytes")
        if not isinstance(sha256, str) or len(sha256) != 64:
            raise ManifestError(f"manifest file entry {name!r} has no valid 'sha256'")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ManifestError(f"manifest file entry {name!r} has no valid 'size_bytes'")
        entries.append(FileEntry(name=str(name), sha256=sha256, size_bytes=size))
    return tuple(sorted(entries, key=lambda entry: entry.name))


def _parse_metadata_sources(raw: Any) -> tuple[MetadataSourceEntry, ...]:
    if not isinstance(raw, list):
        raise ManifestError("manifest key 'metadata_sources' must be a list")
    entries: list[MetadataSourceEntry] = []
    for record in raw:
        if not isinstance(record, dict):
            raise ManifestError("each 'metadata_sources' item must be an object")
        entries.append(
            MetadataSourceEntry(
                source=_require_str(record, "source"),
                dataset_version=_optional_str(record, "dataset_version"),
                last_success=_optional_str(record, "last_success"),
            )
        )
    return tuple(entries)


def parse_manifest(payload: bytes | str) -> Manifest:
    """Parse ``manifest.json`` bytes into a :class:`Manifest`.

    Raises:
        ManifestError: if the JSON is unreadable, the format version is one
            this build does not support, or a required key is missing or
            mistyped.
    """
    try:
        data = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ManifestError(f"manifest is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError("manifest must be a JSON object")

    format_version = _require(data, "format_version")
    if not isinstance(format_version, int) or isinstance(format_version, bool):
        raise ManifestError("manifest key 'format_version' must be an integer")
    if format_version not in SUPPORTED_FORMAT_VERSIONS:
        supported = ", ".join(str(version) for version in sorted(SUPPORTED_FORMAT_VERSIONS))
        raise ManifestError(
            f"manifest format_version {format_version} is not supported by this "
            f"FlightSite build (supported: {supported}). Restore this backup with "
            "the FlightSite version that wrote it, or upgrade."
        )

    includes_secrets = _require(data, "includes_secrets")
    if not isinstance(includes_secrets, bool):
        raise ManifestError("manifest key 'includes_secrets' must be a boolean")

    return Manifest(
        format_version=format_version,
        flightsite_version=_require_str(data, "flightsite_version"),
        schema_revision=_optional_str(data, "schema_revision"),
        created_utc=_require_str(data, "created_utc"),
        includes_secrets=includes_secrets,
        files=_parse_files(_require(data, "files")),
        metadata_sources=_parse_metadata_sources(_require(data, "metadata_sources")),
    )


__all__ = [
    "ALLOWED_MEMBERS",
    "CONFIG_MEMBER",
    "DATABASE_MEMBER",
    "FORMAT_VERSION",
    "MANIFEST_MEMBER",
    "PAYLOAD_MEMBERS",
    "SECRETS_MEMBER",
    "SUPPORTED_FORMAT_VERSIONS",
    "FileEntry",
    "Manifest",
    "MetadataSourceEntry",
    "parse_manifest",
    "utc_iso",
    "utc_iso_from_ms",
]
