"""Failure modes of the backup/restore commands.

Every refusal the CLI reports is one of these, so a caller embedding the
package (and the tests) can distinguish "this archive is damaged" from "this
archive is from a newer FlightSite" from "you did not pass ``--confirm``"
without matching on message text.
"""

from __future__ import annotations


class BackupError(Exception):
    """Base class for every backup/restore failure."""


class SnapshotError(BackupError):
    """The SQLite snapshot could not be taken."""


class ManifestError(BackupError):
    """``manifest.json`` is missing, unreadable, or structurally wrong."""


class ArchiveValidationError(BackupError):
    """The archive failed integrity validation (container, members, checksums)."""


class SchemaCompatibilityError(BackupError):
    """The backup's schema revision is not restorable by this build.

    Raised for the SPEC §72 case "refuse a newer-schema backup on an
    incompatible older FlightSite version".
    """


class ConfirmationRequiredError(BackupError):
    """A destructive restore was requested without explicit confirmation (SPEC §72)."""


class RestoreError(BackupError):
    """The data directory could not be swapped over to the restored files."""


__all__ = [
    "ArchiveValidationError",
    "BackupError",
    "ConfirmationRequiredError",
    "ManifestError",
    "RestoreError",
    "SchemaCompatibilityError",
    "SnapshotError",
]
