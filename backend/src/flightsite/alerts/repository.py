"""SQLite for the alert tables: rule CRUD, match writes, match history.

The split this module keeps is the one :mod:`flightsite.activity.repository`
and :mod:`flightsite.analytics.repository` keep, for the same reason: above it
everything is :mod:`flightsite.alerts.model` values, so the evaluator and the
engine's dedupe logic are checkable without a database; below it everything is
SQL.

Which writer this is
--------------------

:meth:`AlertRepository.record_matches` takes
:meth:`~flightsite.db.engine.Database.writer_session` — the process's single
serialized writer (ADR-0001, ADR-0008) — rather than joining the sighting
worker's transaction. That is slice 031's and slice 035's decision repeated,
and the reason is unchanged: an alert row is not a sighting row, and folding
its write into the cycle that persists sightings would give an alert bug the
ability to fail a sighting. The writer lock still guarantees the two are never
interleaved.

The *other* half of an alert's persistence does ride the worker's transaction,
and deliberately: ``sightings.max_alert_severity`` is a column of the sighting
row, so it is applied to the worker's accumulator
(:meth:`flightsite.sightings.worker.PersistenceWorker.apply_alert_severity`)
and written by the flush that writes the rest of that row — exactly as an
enriched route is. One fact, one owner, one transaction each.

Idempotency, in SQL
-------------------

:meth:`record_matches` inserts with ``ON CONFLICT DO NOTHING ... RETURNING
id``, so the rows that come back are exactly the ones this call created. That
is what makes SPEC §48's once-per-sighting-per-rule guarantee independent of
the engine's memory: a restart that lost its in-memory record of what had
fired, an event replayed after a queue overflow, and two calls racing the same
proposal all leave one row and announce it once. The engine's own bookkeeping
is an optimisation that saves the round trip, never the guarantee.

Deleting a rule
---------------

``alert_matches.rule_id`` has no ``ON DELETE`` action (``docs/DATA_MODEL.md``
§4.3) and ADR-0001 runs with ``PRAGMA foreign_keys = ON``, so
:meth:`delete_rule` removes the rule's matches in the same transaction. That
discards less than it looks like: each sighting keeps its
``max_alert_severity`` and its ``alert_matched`` event, and the activity feed
keeps the ``alert_triggered`` row carrying the rule's name, severity and reason
— none of which references ``alert_rules``. What goes is the rule-linked
operational log, which has no meaning once the rule it is about is gone.

Query costs
-----------

* :meth:`list_rules` is the whole table, and the table is human-scale (a
  handful to a few dozen rows, edited through a settings-style UI). It is read
  at startup and after a CRUD change, never on the live path.
* :meth:`open_sighting_match_keys` is keyed on the ids of the *open* sightings,
  which the partial index ``ix_sightings_open`` already bounds to the live set;
  it is called once per boot to rehydrate the engine's dedupe state.
* :meth:`list_matches` is newest-first over ``ix_amatch_matched``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from flightsite.alerts.model import AlertRuleRecord, RuleConditions, StoredAlertMatch
from flightsite.alerts.vocabulary import AlertSeverity
from flightsite.db import Aircraft, AlertMatch, AlertRule, Database, Sighting

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class NewAlertMatch:
    """One match the engine wants written, before it has an id."""

    sighting_id: int
    aircraft_id: int
    matched_ms: int
    severity: AlertSeverity
    reason: str
    rule_id: int | None = None
    builtin_key: str | None = None


@dataclass(frozen=True, slots=True)
class AlertRepository:
    """Reads and writes ``alert_rules`` and ``alert_matches``."""

    database: Database

    # -------------------------------------------------------------- the rules

    async def list_rules(self) -> tuple[AlertRuleRecord, ...]:
        """Every rule, by id, with its conditions parsed.

        A row whose ``conditions_json`` does not parse is logged and skipped
        rather than raised. One corrupt or future-versioned document must not
        stop the engine from evaluating the other rules — a rule that cannot be
        read is a rule that matches nothing, which is the same outcome as
        disabling it and is strictly better than alerting on nothing at all.
        """
        async with self.database.read_session() as session:
            rows = (await session.scalars(select(AlertRule).order_by(AlertRule.id))).all()
        records: list[AlertRuleRecord] = []
        for row in rows:
            record = self._record(row)
            if record is not None:
                records.append(record)
        return tuple(records)

    async def get_rule(self, rule_id: int) -> AlertRuleRecord | None:
        """One rule, or ``None`` if it does not exist (or does not parse)."""
        async with self.database.read_session() as session:
            row = await session.get(AlertRule, rule_id)
            return None if row is None else self._record(row)

    async def has_template_rules(self) -> bool:
        """Whether **any** rule carries template provenance.

        The whole of the template-instantiation guard: see
        :mod:`flightsite.alerts.templates` for why it is "any template row at
        all" rather than a per-key check.
        """
        statement = select(AlertRule.id).where(AlertRule.template_key.is_not(None)).limit(1)
        async with self.database.read_session() as session:
            return await session.scalar(statement) is not None

    async def create_rule(
        self,
        *,
        name: str,
        description: str | None,
        severity: AlertSeverity,
        conditions: RuleConditions,
        enabled: bool,
        template_key: str | None,
        now_ms: int,
    ) -> AlertRuleRecord:
        """Insert one rule and return it as it was stored."""
        async with self.database.writer_session() as session:
            row = AlertRule(
                name=name,
                description=description,
                severity=severity.value,
                enabled=int(enabled),
                template_key=template_key,
                conditions_json=conditions.to_json(),
                created_ms=now_ms,
                updated_ms=now_ms,
            )
            session.add(row)
            await session.flush()
            rule_id = row.id
        return AlertRuleRecord(
            id=rule_id,
            name=name,
            severity=severity,
            conditions=conditions,
            description=description,
            enabled=enabled,
            template_key=template_key,
            created_ms=now_ms,
            updated_ms=now_ms,
        )

    async def create_rules(
        self,
        rules: Sequence[tuple[str, str | None, AlertSeverity, RuleConditions, str]],
        *,
        now_ms: int,
    ) -> int:
        """Insert several template rules in one transaction; return the count.

        One transaction rather than one per rule, because template
        instantiation is all-or-nothing: a crash halfway through would leave
        ``alert_rules`` holding *some* template rows, and the
        "any template row at all" guard would then never create the rest.
        """
        if not rules:
            return 0
        async with self.database.writer_session() as session:
            session.add_all(
                [
                    AlertRule(
                        name=name,
                        description=description,
                        severity=severity.value,
                        enabled=1,
                        template_key=template_key,
                        conditions_json=conditions.to_json(),
                        created_ms=now_ms,
                        updated_ms=now_ms,
                    )
                    for name, description, severity, conditions, template_key in rules
                ]
            )
        return len(rules)

    async def update_rule(
        self,
        rule_id: int,
        *,
        name: str,
        description: str | None,
        severity: AlertSeverity,
        conditions: RuleConditions,
        enabled: bool,
        now_ms: int,
    ) -> AlertRuleRecord | None:
        """Replace a rule's definition. ``None`` when it does not exist.

        A full replace rather than a patch, matching
        ``PUT /api/internal/watchlists/{id}``: a rule is a small document a
        client holds whole, and a partial update of an ``AND`` condition set is
        ambiguous about whether an omitted condition was meant to be removed.

        ``template_key`` is deliberately **not** replaceable. Provenance is a
        statement about where a rule came from, and editing a shipped rule does
        not make it stop having been shipped — which is what lets the Alerts
        page (slice 041) keep showing "from the Military template" beside a
        rule whose threshold the user has since tuned.
        """
        async with self.database.writer_session() as session:
            row = await session.get(AlertRule, rule_id)
            if row is None:
                return None
            row.name = name
            row.description = description
            row.severity = severity.value
            row.enabled = int(enabled)
            row.conditions_json = conditions.to_json()
            row.updated_ms = now_ms
            template_key = row.template_key
            created_ms = row.created_ms
        return AlertRuleRecord(
            id=rule_id,
            name=name,
            severity=severity,
            conditions=conditions,
            description=description,
            enabled=enabled,
            template_key=template_key,
            created_ms=created_ms,
            updated_ms=now_ms,
        )

    async def delete_rule(self, rule_id: int) -> bool:
        """Delete one rule and the matches it produced. ``False`` if unknown.

        Both in one transaction — see the module docstring for why the matches
        go with it and what that does *not* discard.
        """
        async with self.database.writer_session() as session:
            row = await session.get(AlertRule, rule_id)
            if row is None:
                return False
            await session.execute(delete(AlertMatch).where(AlertMatch.rule_id == rule_id))
            await session.delete(row)
        return True

    # ------------------------------------------------------------ the matches

    async def record_matches(self, matches: Sequence[NewAlertMatch]) -> tuple[int | None, ...]:
        """Write matches; return each one's new id, or ``None`` if it existed.

        One entry per input, in the input's order — deliberately *positional*
        rather than a set of created ids, because the caller has downstream
        work to do per match (raise the sighting's severity, announce it) and
        needs to know which of its own proposals that work belongs to. A tuple
        of ids alone would make it guess.

        Conflict-tolerant by construction: a proposal whose ``(rule,
        sighting)`` or ``(builtin_key, sighting)`` pair already exists inserts
        nothing and returns ``None`` for that position. That is what makes the
        dedupe survive a restart, an event replay and a race, with no
        read-then-write window to lose.
        """
        if not matches:
            return ()
        created: list[int | None] = []
        async with self.database.writer_session() as session:
            for match in matches:
                created.append(
                    await session.scalar(
                        sqlite_insert(AlertMatch)
                        .values(
                            rule_id=match.rule_id,
                            builtin_key=match.builtin_key,
                            sighting_id=match.sighting_id,
                            aircraft_id=match.aircraft_id,
                            matched_ms=match.matched_ms,
                            severity=match.severity.value,
                            reason=match.reason,
                        )
                        .on_conflict_do_nothing()
                        .returning(AlertMatch.id)
                    )
                )
        return tuple(created)

    async def open_sighting_match_keys(self) -> dict[int, dict[str, AlertSeverity]]:
        """What each currently-open sighting has already matched.

        Read once at start, to rehydrate the engine's per-sighting dedupe state
        for the sightings a previous process left open and this one adopted
        (:class:`flightsite.sightings.recovery.ShutdownRecovery`). Without it a
        restart mid-sighting would re-propose every match, and while the unique
        indexes would refuse the rows, the engine would pay a write attempt per
        rule per cycle for the rest of that sighting.

        Bounded by the open set, which ``ix_sightings_open`` makes a lookup
        rather than a scan of history.
        """
        statement = (
            select(
                AlertMatch.sighting_id,
                AlertMatch.rule_id,
                AlertMatch.builtin_key,
                AlertMatch.severity,
            )
            .join(Sighting, Sighting.id == AlertMatch.sighting_id)
            .where(Sighting.ended_ms.is_(None))
        )
        async with self.database.read_session() as session:
            rows = (await session.execute(statement)).all()
        keys: dict[int, dict[str, AlertSeverity]] = {}
        for sighting_id, rule_id, builtin_key, severity in rows:
            key = f"rule:{rule_id}" if rule_id is not None else f"builtin:{builtin_key}"
            keys.setdefault(int(sighting_id), {})[key] = AlertSeverity(severity)
        return keys

    async def list_matches(
        self,
        *,
        limit: int,
        offset: int,
        severity: str | None = None,
        icao: str | None = None,
        from_ms: int | None = None,
        to_ms: int | None = None,
    ) -> tuple[StoredAlertMatch, ...]:
        """The alert-match history — ``docs/API.md`` §3.9, newest first.

        The id is the tie-break under ``matched_ms`` for the reason the
        activity feed uses it: several matches written in one instant must page
        without repeating or skipping a row.
        """
        statement = (
            select(
                AlertMatch.id,
                AlertMatch.matched_ms,
                AlertMatch.severity,
                AlertMatch.reason,
                AlertMatch.sighting_id,
                AlertMatch.aircraft_id,
                AlertMatch.rule_id,
                AlertMatch.builtin_key,
                AlertMatch.notified,
                Aircraft.icao24,
                AlertRule.name,
            )
            .select_from(AlertMatch)
            .join(Aircraft, Aircraft.id == AlertMatch.aircraft_id)
            .outerjoin(AlertRule, AlertRule.id == AlertMatch.rule_id)
            .order_by(AlertMatch.matched_ms.desc(), AlertMatch.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if severity is not None:
            statement = statement.where(AlertMatch.severity == severity)
        if icao is not None:
            statement = statement.where(Aircraft.icao24 == icao)
        if from_ms is not None:
            statement = statement.where(AlertMatch.matched_ms >= from_ms)
        if to_ms is not None:
            statement = statement.where(AlertMatch.matched_ms <= to_ms)
        async with self.database.read_session() as session:
            rows = (await session.execute(statement)).all()
        return tuple(
            StoredAlertMatch(
                id=int(row[0]),
                matched_ms=int(row[1]),
                severity=str(row[2]),
                reason=str(row[3]),
                sighting_id=int(row[4]),
                aircraft_id=int(row[5]),
                rule_id=None if row[6] is None else int(row[6]),
                builtin_key=row[7],
                notified=bool(row[8]),
                icao24=str(row[9]),
                rule_name=row[10],
            )
            for row in rows
        )

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _record(row: AlertRule) -> AlertRuleRecord | None:
        """One ORM row as a domain record, or ``None`` if its document is bad."""
        try:
            conditions = RuleConditions.from_json(row.conditions_json)
            severity = AlertSeverity(row.severity)
        except ValueError as exc:
            logger.warning(
                "alert_rule_unreadable",
                rule_id=row.id,
                name=row.name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return None
        return AlertRuleRecord(
            id=row.id,
            name=row.name,
            severity=severity,
            conditions=conditions,
            description=row.description,
            enabled=bool(row.enabled),
            template_key=row.template_key,
            created_ms=row.created_ms,
            updated_ms=row.updated_ms,
        )


__all__ = ["AlertRepository", "NewAlertMatch"]
