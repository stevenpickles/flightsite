"""The ``meta`` key/value store and T0's write-once semantics.

T0 is the moment FlightSite first persisted an observation (SPEC §16). Every
"since T0" figure in the product — lifetime records, rarity, receiver
statistics — is measured from it, so silently resetting it would silently
rewrite the meaning of that history. It is therefore **write-once**:
:meth:`MetaRepository.set_t0_once` inserts only if the key is absent and
reports whether it wrote, and nothing in the codebase can overwrite it.

Nothing sets T0 in this slice. The write-behind persistence worker sets it when
it persists the first observation (slice 009); the acceptance criterion for a
fresh install is precisely that T0 stays unset until then.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from flightsite.db.clock import utc_now_ms
from flightsite.db.engine import Database
from flightsite.db.models import META_KEY_T0, Meta


class MetaError(RuntimeError):
    """Raised when a ``meta`` value cannot be interpreted as its declared type."""


@dataclass(frozen=True, slots=True)
class MetaRepository:
    """Reads and writes ``meta`` rows through the database's session discipline.

    Reads use :meth:`~flightsite.db.engine.Database.read_session`; writes use
    the single writer session. Callers never pick a session themselves.
    """

    database: Database

    async def get(self, key: str) -> str | None:
        """Value stored under ``key``, or ``None`` if the key is absent."""
        async with self.database.read_session() as session:
            value: str | None = await session.scalar(select(Meta.value).where(Meta.key == key))
            return value

    async def set(self, key: str, value: str) -> None:
        """Insert or overwrite ``key``. Not for write-once keys such as T0."""
        now_ms = utc_now_ms()
        statement = (
            sqlite_insert(Meta)
            .values(key=key, value=value, updated_ms=now_ms)
            .on_conflict_do_update(
                index_elements=[Meta.key],
                set_={"value": value, "updated_ms": now_ms},
            )
        )
        async with self.database.writer_session() as session:
            await session.execute(statement)

    async def set_if_absent(self, key: str, value: str) -> bool:
        """Insert ``key`` only when it does not exist yet.

        The absence check and the insert are one ``INSERT ... ON CONFLICT DO
        NOTHING`` statement, so two concurrent callers cannot both observe the
        key as absent.

        Returns:
            True if this call wrote the row; False if it already existed.
        """
        # RETURNING yields a row only when the insert actually happened, which
        # is both typed and unambiguous where a driver rowcount is neither.
        statement = (
            sqlite_insert(Meta)
            .values(key=key, value=value, updated_ms=utc_now_ms())
            .on_conflict_do_nothing(index_elements=[Meta.key])
            .returning(Meta.key)
        )
        async with self.database.writer_session() as session:
            inserted: str | None = await session.scalar(statement)
            return inserted is not None

    async def delete(self, key: str) -> bool:
        """Remove ``key``; returns True if a row was deleted."""
        statement = delete(Meta).where(Meta.key == key).returning(Meta.key)
        async with self.database.writer_session() as session:
            deleted: str | None = await session.scalar(statement)
            return deleted is not None

    async def get_t0(self) -> int | None:
        """T0 as epoch milliseconds, or ``None`` if no observation is persisted yet."""
        raw = await self.get(META_KEY_T0)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError as exc:
            raise MetaError(f"meta[{META_KEY_T0!r}] is not an integer: {raw!r}") from exc

    async def set_t0_once(self, t0_ms: int) -> bool:
        """Record T0 if — and only if — it has never been recorded.

        Returns:
            True if this call established T0; False if T0 already existed, in
            which case the stored value is left exactly as it was.

        Raises:
            ValueError: if ``t0_ms`` is not a positive epoch-millisecond value.
        """
        if t0_ms <= 0:
            raise ValueError(f"T0 must be a positive epoch-ms timestamp, got {t0_ms!r}")
        return await self.set_if_absent(META_KEY_T0, str(t0_ms))
