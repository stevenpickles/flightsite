"""Alerts as one object the application wires up.

Mirrors :class:`flightsite.watchlists.service.WatchlistService`'s shape: the app
holds one :class:`AlertService`, the internal CRUD API (``docs/API.md`` §5)
calls its methods rather than touching :mod:`flightsite.alerts.repository`
directly, and every method that changes what a rule *means* recompiles the
engine's rule set before returning. That ordering is what makes a rule created
in the UI evaluate on the very next live update rather than after some later
reconciliation — the property roadmap slice 041 will round-trip against.

What "compiling" a rule does
----------------------------

Exactly one thing: it resolves a ``watchlist_id`` condition to the watchlist's
*name*, because :meth:`flightsite.watchlists.matcher.WatchlistMatcher.matches`
answers in names. Doing it here, once per reload, is what keeps evaluation free
of any lookup at all — and doing it from the same read that lists the rules is
what keeps a renamed or deleted watchlist from leaving a rule pointing at
nothing.

A rename happens through the watchlist CRUD API, not this one, so the two must
be connected: :meth:`AlertService.reload_rules` is registered as a
:data:`~flightsite.watchlists.service.IndexListener` on the watchlist service,
which fires after every watchlist mutation rebuilds its match index. One seam,
in the direction the dependency already runs (alerts consume watchlists), and
no polling.

Template instantiation
----------------------

:meth:`AlertService.start` instantiates the templates named by
``alerts.enabled_templates`` — but only when ``alert_rules`` holds no
template-provenance row at all. :mod:`flightsite.alerts.templates` documents why
that guard rather than a per-key one: a user who deletes a shipped rule must not
have it silently return on the next restart, and a user editing the wizard's
answer later is not asking for their tuned rule set to be rewritten.

The whole of it is idempotent, so a boot that instantiates nothing is the
ordinary case from the second boot onwards, and a boot against a database whose
migration failed does nothing at all — the app starts this service only on a
healthy schema, exactly like every other database-dependent subsystem.

Startup alone is not enough (issue #110)
-----------------------------------------

On a *fresh* install the ordering defeats it. The app starts, this service reads
an ``alerts.enabled_templates`` that is still empty because nothing has been
configured yet, and only then does the user run the setup wizard and choose
their templates. ``PUT /api/internal/config`` wrote the answer and swapped
``app.state.settings``, but nothing re-read it here — so the install had no
alert rules at all until someone restarted the backend, which is precisely the
one thing a setup wizard is supposed to save you from.

:meth:`AlertService.apply_enabled_templates` is the second edge, called from the
config apply path with the list as it now stands. It is deliberately *not* a
second copy of startup's logic, because startup's guard cannot serve a running
app: "no template row at all" would refuse the wizard's very first save on an
install that already has one gallery-created rule.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import structlog

from flightsite.alerts.engine import AlertEngine
from flightsite.alerts.errors import (
    AlertRuleNotFoundError,
    AlertRuleValueError,
    AlertTemplateConflictError,
    AlertTemplateNotFoundError,
)
from flightsite.alerts.model import AlertRuleRecord, CompiledRule, RuleConditions
from flightsite.alerts.repository import AlertRepository
from flightsite.alerts.templates import (
    TEMPLATE_KEY_ALIASES,
    TEMPLATES_BY_KEY,
    AlertTemplate,
    aliased_template_keys,
    enabled_templates,
    normalize_template_keys,
    unknown_template_keys,
)
from flightsite.alerts.vocabulary import AlertSeverity
from flightsite.db import Database, utc_now_ms
from flightsite.live import LiveStore
from flightsite.metadata.cache import MetadataCache
from flightsite.sightings.worker import PersistenceWorker
from flightsite.watchlists.repository import WatchlistRepository
from flightsite.watchlists.service import WatchlistService

logger = structlog.get_logger(__name__)

#: UTC epoch-millisecond source, injected for tests.
ClockFn = Callable[[], int]

#: Reads the configured alert radius (SPEC §66) at the moment a cycle needs it.
#: A callable rather than a value because ``PUT /api/internal/config`` replaces
#: ``app.state.settings`` on a running app, and a captured radius would bound
#: alerts by a setting the user has since changed.
AlertRadiusProbe = Callable[[], float | None]


def _normalize_name(name: str) -> str:
    """Trim a rule name, refusing a blank one."""
    stripped = name.strip()
    if not stripped:
        raise AlertRuleValueError("rule name must not be blank")
    return stripped


def _normalize_description(description: str | None) -> str | None:
    """Trim a description, mapping a blank one to ``None``."""
    if description is None:
        return None
    stripped = description.strip()
    return stripped or None


class AlertService:
    """Rule CRUD, template instantiation, and the engine they configure.

    Args:
        database: the application database.
        live: the live store the engine subscribes to.
        metadata: the metadata & rarity cache the engine reads.
        watchlists: the watchlist service, for the match index the engine reads
            and for the reload seam a rename fires.
        persistence: the sighting worker, for the open sighting's ids and for
            the ``max_alert_severity`` apply seam.
        template_keys: ``alerts.enabled_templates`` from the configuration.
        alert_radius: reads the configured alert radius, or ``None`` for an
            installation with no bound.
        clock: UTC epoch-millisecond source, injected for tests.
    """

    __slots__ = (
        "_alert_radius",
        "_clock",
        "_engine",
        "_repository",
        "_started",
        "_template_keys",
        "_watchlist_repository",
        "_watchlists",
    )

    def __init__(
        self,
        *,
        database: Database,
        live: LiveStore,
        metadata: MetadataCache,
        watchlists: WatchlistService,
        persistence: PersistenceWorker,
        template_keys: Sequence[str] = (),
        alert_radius: AlertRadiusProbe | None = None,
        clock: ClockFn = utc_now_ms,
    ) -> None:
        self._repository = AlertRepository(database)
        self._watchlist_repository = WatchlistRepository(database)
        self._watchlists = watchlists
        self._template_keys = tuple(template_keys)
        self._alert_radius = alert_radius
        self._clock = clock
        self._started = False
        self._engine = AlertEngine(
            database=database,
            live=live,
            metadata=metadata,
            watchlists=watchlists.matcher,
            persistence=persistence,
            clock=clock,
        )

    @property
    def engine(self) -> AlertEngine:
        """The evaluation engine — read on the aircraft path for the §3.3 block."""
        return self._engine

    # -------------------------------------------------------------- lifecycle

    async def start(self) -> None:
        """Instantiate templates, load the rules, and start the engine.

        In that order, and the order matters: a first boot must evaluate its
        shipped rules on the very first decoder poll, not on the one after the
        next reload. The engine subscribes *after* the rules are in place, so
        no event is evaluated against an empty rule set that a moment later
        would have matched.
        """
        created = await self._instantiate_templates()
        await self.reload_rules()
        self._engine.adopt_open_matches(await self._repository.open_sighting_match_keys())
        # A watchlist rename or deletion changes what a `watchlist_id`
        # condition resolves to without any rule changing, so the rule set has
        # to be recompiled for it. Subscribing here rather than in the
        # application factory keeps the dependency where it belongs: alerts
        # consume watchlists, and watchlists know nothing about alerts.
        self._watchlists.subscribe_index(self.reload_rules)
        await self._engine.start()
        self._started = True
        logger.info(
            "alert_service_started",
            rules=len(self._engine.rules),
            templates_created=created,
        )

    async def stop(self) -> None:
        """Unsubscribe and stop the engine. Idempotent."""
        self._started = False
        self._watchlists.unsubscribe_index(self.reload_rules)
        await self._engine.stop()

    async def apply_enabled_templates(self, keys: Sequence[str]) -> int:
        """Instantiate the templates a configuration save just enabled.

        Called from the ``PUT /api/internal/config`` apply path with
        ``alerts.enabled_templates`` as it now stands. Returns how many rules
        were created.

        The exact semantics, because they are the whole point
        --------------------------------------------------------

        A template here is instantiated when **both** of these hold:

        1. **This save added it.** The key is in the new list and was not in the
           list this service was last configured with. A save that leaves the
           list alone — which is every save about the receiver, the map, or the
           units — instantiates nothing at all.
        2. **No rule already carries its provenance.** Whether that rule was
           created at startup, from the template gallery, or by an earlier
           save, the template already has its row and a second one would be a
           duplicate rather than a fix.

        Condition 1 is what preserves the startup guard's *purpose*. That guard
        exists so a shipped rule the user deleted stays deleted, and it cannot
        be reused verbatim here — "no template row at all" would refuse the
        wizard's first save on an install that already has one gallery-created
        rule, which is the fresh-install case this method exists for. Nor can
        condition 2 carry the property on its own: rule deletion is a hard
        delete (``docs/DATA_MODEL.md`` §4.2 has no ``deleted_at`` and
        :meth:`flightsite.alerts.repository.AlertRepository.delete_rule`
        removes the row), so after a deletion "no rule carries this provenance"
        is indistinguishable from "never instantiated". The *delta* is what
        distinguishes them: the deleted template is still enabled in the
        configuration, so it is not something this save added, so it is not
        recreated — on this save or on any later one.

        What that deliberately still does
        ---------------------------------

        A user who deletes a shipped rule, then unticks that template, then
        ticks it again gets the rule back. That is not the guard failing; it is
        the user asking twice, in the one vocabulary the settings page has for
        asking. The property being protected is "a deletion is not *silently*
        undone by an unrelated save", and it holds.

        Not instantiating is never an error. A key from another build is
        warned about and skipped for the reason
        :func:`flightsite.alerts.templates.enabled_templates` gives, and a
        service that has not started — the app builds this object even when a
        failed migration stopped it from starting it — records the new list and
        touches no database.
        """
        previous = normalize_template_keys(self._template_keys)
        current = normalize_template_keys(keys)
        # Recorded whatever happens next, so this service's idea of the
        # configured list never lags the file: the *next* save's delta has to
        # be measured against what the user has actually saved, not against
        # whatever was on disk when the process booted.
        self._template_keys = tuple(keys)
        self._warn_about_key_spellings(keys)
        if not self._started:
            logger.debug("alert_templates_not_applied", reason="service not started")
            return 0
        added = [key for key in current if key not in previous]
        if not added:
            return 0
        existing = await self._repository.template_keys_present()
        wanted = [
            template
            for template in enabled_templates(added)
            if template.instantiable and template.key not in existing
        ]
        if not wanted:
            return 0
        created = await self._repository.create_rules(
            [self._template_row(template) for template in wanted], now_ms=self._clock()
        )
        await self.reload_rules()
        logger.info(
            "alert_templates_instantiated_on_save",
            keys=[template.key for template in wanted],
            rules=created,
        )
        return created

    @staticmethod
    def _warn_about_key_spellings(keys: Sequence[str]) -> None:
        """Say what in ``alerts.enabled_templates`` did not name a template.

        Silence here is what let issue #111 ship: the setup wizard sent
        ``law_enforcement``, no such template existed, the key was skipped, and
        the only evidence was the rule the user never got. A skipped key is
        still not fatal — see
        :func:`flightsite.alerts.templates.enabled_templates` — but it is now
        loud enough to find in the logs.
        """
        aliased = aliased_template_keys(keys)
        if aliased:
            logger.warning(
                "alert_template_key_deprecated",
                keys=list(aliased),
                resolved_to=[TEMPLATE_KEY_ALIASES[key] for key in aliased],
            )
        unknown = unknown_template_keys(keys)
        if unknown:
            # Not fatal: `alerts.enabled_templates` is validated for shape by
            # the config model, which deliberately does not know the catalogue,
            # so a key from another build is an ordinary upgrade artefact.
            logger.warning("alert_template_unknown", keys=list(unknown))

    async def _instantiate_templates(self) -> int:
        """Create the enabled shipped rules, once per install. Returns the count."""
        self._warn_about_key_spellings(self._template_keys)
        if not self._template_keys:
            return 0
        if await self._repository.has_template_rules():
            return 0
        wanted = [
            template for template in enabled_templates(self._template_keys) if template.instantiable
        ]
        created = await self._repository.create_rules(
            [self._template_row(template) for template in wanted], now_ms=self._clock()
        )
        if created:
            logger.info(
                "alert_templates_instantiated",
                keys=[template.key for template in wanted],
                rules=created,
            )
        return created

    @staticmethod
    def _template_row(
        template: AlertTemplate,
    ) -> tuple[str, str | None, AlertSeverity, RuleConditions, str]:
        conditions = template.conditions
        if conditions is None:  # pragma: no cover - guarded by `instantiable`
            raise ValueError(f"template {template.key} has no conditions to instantiate")
        return (template.name, template.description, template.severity, conditions, template.key)

    # ---------------------------------------------------------- the rule set

    async def reload_rules(self) -> None:
        """Recompile the engine's rule set from the database's current contents.

        Two reads, not one join, and that is fine for the reason
        :meth:`flightsite.watchlists.service.WatchlistService.reload_index`
        gives: rules and watchlists are both configured at human scale, so this
        runs at startup, after a rule mutation and after a watchlist mutation —
        never on the live path — and its cost is irrelevant next to any of
        them.

        Also registered as the watchlist service's index listener, which is why
        it takes no arguments: a watchlist rename changes what a
        ``watchlist_id`` condition resolves to, and the rule set has to be
        recompiled for it even though no rule changed.
        """
        rules = await self._repository.list_rules()
        names = {
            watchlist.id: watchlist.name
            for watchlist in await self._watchlist_repository.list_watchlists()
        }
        compiled = tuple(
            CompiledRule(
                rule=rule,
                watchlist_name=(
                    None
                    if rule.conditions.watchlist_id is None
                    else names.get(rule.conditions.watchlist_id)
                ),
            )
            for rule in rules
        )
        self._engine.set_rules(compiled)
        self._engine.set_alert_radius(None if self._alert_radius is None else self._alert_radius())
        unresolved = [rule.rule.id for rule in compiled if rule.unresolved_watchlist]
        if unresolved:
            logger.warning("alert_rule_watchlist_missing", rule_ids=unresolved)
        logger.info("alert_rules_reloaded", rules=len(compiled))

    # ------------------------------------------------------------------ CRUD

    async def list_rules(self) -> tuple[AlertRuleRecord, ...]:
        """Every rule, by id."""
        return await self._repository.list_rules()

    async def create_rule(
        self,
        *,
        name: str,
        description: str | None,
        severity: AlertSeverity,
        conditions: RuleConditions,
        enabled: bool = True,
    ) -> AlertRuleRecord:
        """Create a rule and recompile the engine's rule set.

        Raises:
            AlertRuleValueError: the name is blank.
        """
        record = await self._repository.create_rule(
            name=_normalize_name(name),
            description=_normalize_description(description),
            severity=severity,
            conditions=conditions,
            enabled=enabled,
            template_key=None,
            now_ms=self._clock(),
        )
        await self.reload_rules()
        return record

    async def instantiate_template(self, key: str) -> AlertRuleRecord:
        """Create the rule a shipped template describes, keeping its provenance.

        The gallery's counterpart to start-up instantiation, and the reason it
        is a separate method rather than a ``template_key`` argument on
        :meth:`create_rule`: provenance is a statement about where a rule came
        from, so it is set by the operation that *is* "instantiate this
        template" and can never be asserted by a client posting an arbitrary
        body. :func:`update_alert_rule` already refuses to replace it for the
        same reason.

        The conditions and severity come from the catalogue rather than from
        the caller. A user who wants different thresholds edits the rule
        afterwards — which is SPEC §45's "enable, then customize", and it keeps
        the rule honest about having started as the shipped template.

        Refusing a second instantiation is what lets the gallery show one
        truthful state per template. Start-up instantiation's "no template row
        at all" guard cannot serve here: it exists so a *deleted* shipped rule
        stays deleted across restarts, and applying it to an explicit per-key
        request would refuse every template the moment any one of them existed.

        Raises:
            AlertTemplateNotFoundError: this build ships no such template.
            AlertTemplateConflictError: the template is built in, or a rule
                already carries its provenance.
        """
        template = TEMPLATES_BY_KEY.get(key)
        if template is None:
            raise AlertTemplateNotFoundError(f"no alert template with key {key!r}")
        conditions = template.conditions
        if not template.instantiable or conditions is None:
            raise AlertTemplateConflictError(
                f"template {key!r} is built in and always on: it has no rule to create"
            )
        if any(rule.template_key == key for rule in await self._repository.list_rules()):
            raise AlertTemplateConflictError(f"template {key!r} already has a rule")
        record = await self._repository.create_rule(
            name=template.name,
            description=template.description,
            severity=template.severity,
            conditions=conditions,
            enabled=True,
            template_key=key,
            now_ms=self._clock(),
        )
        await self.reload_rules()
        logger.info("alert_template_instantiated", key=key, rule_id=record.id)
        return record

    async def update_rule(
        self,
        rule_id: int,
        *,
        name: str,
        description: str | None,
        severity: AlertSeverity,
        conditions: RuleConditions,
        enabled: bool = True,
    ) -> AlertRuleRecord:
        """Replace a rule's definition and recompile. A full replace, not a patch.

        Raises:
            AlertRuleValueError: the name is blank.
            AlertRuleNotFoundError: no rule has ``rule_id``.
        """
        record = await self._repository.update_rule(
            rule_id,
            name=_normalize_name(name),
            description=_normalize_description(description),
            severity=severity,
            conditions=conditions,
            enabled=enabled,
            now_ms=self._clock(),
        )
        if record is None:
            raise AlertRuleNotFoundError(f"no alert rule with id {rule_id}")
        await self.reload_rules()
        return record

    async def delete_rule(self, rule_id: int) -> bool:
        """Delete a rule (and the matches it produced) and recompile.

        Returns ``False`` for an unknown ``rule_id`` without recompiling
        anything — nothing changed, so there is nothing to recompute.
        """
        deleted = await self._repository.delete_rule(rule_id)
        if deleted:
            await self.reload_rules()
        return deleted


__all__ = ["AlertRadiusProbe", "AlertService", "ClockFn"]
