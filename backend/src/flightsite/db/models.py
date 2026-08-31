"""SQLAlchemy 2.0 typed ORM models.

:class:`Base` is the single declarative base every FlightSite table hangs off,
and therefore the metadata Alembic autogenerate compares against. Adding a
model here without a matching migration (or vice versa) fails the drift test in
``backend/tests/db/test_migrations.py``.

This slice defines only :class:`Meta`; the domain tables arrive with their own
slices per ``docs/DATA_MODEL.md`` §12.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import Integer, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: ``meta`` key holding T0 — the moment the first observation was persisted
#: (SPEC §16). Written exactly once, by the persistence worker (slice 009).
META_KEY_T0: Final[str] = "t0_ms"


class Base(DeclarativeBase):
    """Declarative base for all FlightSite ORM models."""


class Meta(Base):
    """Application-level key/value state (``docs/DATA_MODEL.md`` §2.1).

    ``WITHOUT ROWID`` because the table is a handful of rows always addressed
    by their text primary key: the clustered b-tree is both smaller and one
    lookup cheaper than the rowid indirection.
    """

    __tablename__ = "meta"
    # Tuple form (dialect kwargs last) rather than a bare dict: SQLAlchemy
    # declares __table_args__ as an instance variable, so a ClassVar annotation
    # is rejected, and an unannotated mutable class attribute is a lint error.
    __table_args__ = ({"sqlite_with_rowid": False},)

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Meta(key={self.key!r}, value={self.value!r}, updated_ms={self.updated_ms!r})"
