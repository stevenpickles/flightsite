"""Schema-compatibility rules for restoring a backup (SPEC §72).

The rule, stated once:

    A backup is restorable by this build **iff** its ``schema_revision`` is an
    ancestor of, or equal to, this build's Alembic head.

Both halves matter.

* **Ancestor (older backup).** The restored database is behind the code, which
  is the ordinary upgrade path: FlightSite migrates it to head at the next
  startup exactly as it migrates an in-place data directory
  (:func:`flightsite.db.startup.initialize_database`). Restore does *not*
  migrate; it puts the files in place and lets the normal startup sequence do
  the one thing that already has migration tests behind it.
* **Equal.** Nothing to do.
* **Anything else (newer, or unknown lineage).** Refused. A revision this
  build's migration graph has never heard of means the archive was written by a
  newer FlightSite whose migrations this code does not contain — it could not
  migrate the database *down*, and running an older code base against a newer
  schema is how data gets silently mangled. ``docs/RELEASE.md`` §Rollback
  depends on this refusal being reliable.

An unstamped snapshot (no ``alembic_version`` row) is treated as "older than
everything": migrating it from base is well defined, and refusing it would make
a backup of a freshly created data directory unrestorable.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from flightsite.db import migrate


class SchemaRelation(StrEnum):
    """How a backup's schema revision relates to this build's head."""

    #: Same revision — restore and start, no migration needed.
    SAME = "same"
    #: An ancestor of head — restore, then startup migrates forward.
    OLDER = "older"
    #: Not in this build's migration graph at all — refuse.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SchemaCompatibility:
    """The verdict for one backup, with the text the CLI prints."""

    backup_revision: str | None
    head_revision: str
    relation: SchemaRelation

    @property
    def restorable(self) -> bool:
        """True when this build may restore the backup."""
        return self.relation is not SchemaRelation.UNKNOWN

    @property
    def migration_required(self) -> bool:
        """True when the restored database still has to be migrated forward."""
        return self.relation is SchemaRelation.OLDER

    def summary(self) -> str:
        """One line explaining the verdict, suitable for a CLI or an exception."""
        shown = self.backup_revision if self.backup_revision is not None else "(unstamped)"
        if self.relation is SchemaRelation.SAME:
            return f"schema revision {shown} matches this build's head; no migration needed"
        if self.relation is SchemaRelation.OLDER:
            return (
                f"schema revision {shown} is older than this build's head "
                f"{self.head_revision}; FlightSite will migrate it forward on the next start"
            )
        return (
            f"schema revision {shown} is not part of this build's migration history "
            f"(head {self.head_revision}). This backup was almost certainly written by a "
            "newer FlightSite; restoring it into this older build would corrupt it. "
            "Upgrade FlightSite to at least the version that wrote the backup, then retry."
        )


def check_schema(backup_revision: str | None) -> SchemaCompatibility:
    """Classify ``backup_revision`` against this build's migration graph."""
    head = migrate.head_revision()
    if backup_revision is None:
        return SchemaCompatibility(None, head, SchemaRelation.OLDER)
    if backup_revision == head:
        return SchemaCompatibility(backup_revision, head, SchemaRelation.SAME)

    script = migrate.script_directory()
    try:
        ancestors = {revision.revision for revision in script.iterate_revisions(head, "base")}
    except Exception:  # pragma: no cover - a broken graph fails the single-head test first
        ancestors = set()

    relation = SchemaRelation.OLDER if backup_revision in ancestors else SchemaRelation.UNKNOWN
    return SchemaCompatibility(backup_revision, head, relation)


__all__ = ["SchemaCompatibility", "SchemaRelation", "check_schema"]
