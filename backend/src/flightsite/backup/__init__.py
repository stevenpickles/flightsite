"""Version-aware, checksum-validated backup and restore (SPEC §72, slice 043).

A FlightSite backup is one ``tar.gz`` under ``<data_dir>/backups/`` holding:

======================= ========================================================
``flightsite.sqlite3``  a ``VACUUM INTO`` snapshot of the database, safe to take
                        while the persistence worker is writing (:mod:`.snapshot`)
``config.yaml``         the non-secret configuration
``secrets.yaml``        **only** with ``--include-secrets`` (``docs/SECURITY.md`` §3)
``manifest.json``       FlightSite version, schema revision, creation time,
                        per-file SHA-256, and metadata dataset versions
======================= ========================================================

Public entry points:

* :func:`create_backup` — take one.
* :func:`verify_archive` — validate one without touching anything.
* :func:`restore_backup` — replace a data directory with one, deliberately.

The command-line face of all three is :mod:`flightsite.backup.cli`
(``flightsite-backup``); the operator-facing procedure is ``docs/BACKUP.md``.
"""

from __future__ import annotations

from flightsite.backup.compat import SchemaCompatibility, SchemaRelation, check_schema
from flightsite.backup.create import (
    BACKUPS_DIRNAME,
    BackupResult,
    archive_name,
    create_backup,
    default_backup_dir,
)
from flightsite.backup.errors import (
    ArchiveValidationError,
    BackupError,
    ConfirmationRequiredError,
    ManifestError,
    RestoreError,
    SchemaCompatibilityError,
    SnapshotError,
)
from flightsite.backup.manifest import (
    ALLOWED_MEMBERS,
    CONFIG_MEMBER,
    DATABASE_MEMBER,
    FORMAT_VERSION,
    MANIFEST_MEMBER,
    SECRETS_MEMBER,
    FileEntry,
    Manifest,
    MetadataSourceEntry,
    parse_manifest,
)
from flightsite.backup.restore import RestoreResult, restore_backup
from flightsite.backup.verify import (
    FileCheck,
    VerificationReport,
    inspect_archive,
    verify_archive,
)

__all__ = [
    "ALLOWED_MEMBERS",
    "BACKUPS_DIRNAME",
    "CONFIG_MEMBER",
    "DATABASE_MEMBER",
    "FORMAT_VERSION",
    "MANIFEST_MEMBER",
    "SECRETS_MEMBER",
    "ArchiveValidationError",
    "BackupError",
    "BackupResult",
    "ConfirmationRequiredError",
    "FileCheck",
    "FileEntry",
    "Manifest",
    "ManifestError",
    "MetadataSourceEntry",
    "RestoreError",
    "RestoreResult",
    "SchemaCompatibility",
    "SchemaCompatibilityError",
    "SchemaRelation",
    "SnapshotError",
    "VerificationReport",
    "archive_name",
    "check_schema",
    "create_backup",
    "default_backup_dir",
    "inspect_archive",
    "parse_manifest",
    "restore_backup",
    "verify_archive",
]
