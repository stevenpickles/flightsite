"""The alert vocabulary: the severity ladder and the built-in detector keys.

Severity, in one place with an order
------------------------------------

``docs/API.md`` §2.8 fixes four values and SPEC §46 fixes their meaning:
``info`` < ``interesting`` < ``high`` < ``critical``. The *ladder* is what this
slice needs that nothing before it did — "does this match outrank the one
already standing on this sighting?" is the question behind
``sightings.max_alert_severity``, behind the interesting panel's ordering, and
behind the one documented exception to once-per-sighting-per-rule notification
(SPEC §48) — so :class:`AlertSeverity` carries :attr:`AlertSeverity.rank`
rather than leaving every caller to re-derive an order from a list.

The same four strings are spelled in three other places for reasons each of
those places documents: :class:`flightsite.activity.model.Severity` (the feed's
column), :data:`flightsite.db.models.ALERT_ROW_SEVERITY_CHECK` and
:data:`~flightsite.db.models.ALERT_SEVERITY_CHECK` (the SQL constraints), and
:data:`flightsite.sightings.vocabulary.ALERT_SEVERITIES` (the accumulator's
ordering, which cannot import this module without inverting the dependency
between ``sightings`` and ``alerts``). ``tests/alerts/test_vocabulary.py``
asserts all of them are one ladder, which is this codebase's established answer
to a vocabulary that several layers must know and none may own alone.

Built-in detector keys
----------------------

SPEC §47 makes emergency squawks alert *without* a rule, so their matches have
no ``alert_rules`` row to point at; ``docs/DATA_MODEL.md`` §4.3 gives them
``builtin_key`` instead, with ``emergency_7700`` as its own example. One key per
code rather than one shared ``emergency`` key is what makes an aircraft that
squawks 7600 and later 7700 produce two matches — §4.3 names that as exactly
the allowed "a newly matched higher-priority condition may notify again" path,
and a shared key would collapse it into one.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final


class AlertSeverity(StrEnum):
    """``docs/API.md`` §2.8's four-value ladder, ordered (SPEC §46).

    Ordered by :attr:`rank` rather than by declaration order alone, so a
    comparison reads as a comparison and cannot be accidentally satisfied by a
    string comparison — ``"critical" < "info"`` is true alphabetically and is
    the exact bug this property exists to make impossible.
    """

    INFO = "info"
    INTERESTING = "interesting"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        """Position on the ladder, ``0`` for ``info`` through ``3`` for ``critical``."""
        return _RANKS[self]

    def outranks(self, other: AlertSeverity | None) -> bool:
        """Whether this severity is *strictly* higher than ``other``.

        ``None`` means nothing is standing yet, which everything outranks. A
        tie does not: SPEC §48 allows another notification for a *higher*
        priority condition, and treating equal as higher would turn every
        additional match of the same severity into a second notification.
        """
        return other is None or self.rank > other.rank


_RANKS: Final[MappingProxyType[AlertSeverity, int]] = MappingProxyType(
    {
        AlertSeverity.INFO: 0,
        AlertSeverity.INTERESTING: 1,
        AlertSeverity.HIGH: 2,
        AlertSeverity.CRITICAL: 3,
    }
)


#: Emergency transponder codes and what each one means, in the wording the
#: reason string shows a user. The set matches
#: :data:`flightsite.sightings.vocabulary.EMERGENCY_SQUAWKS`, which slice 009
#: already records on the sighting; this module adds SPEC §47's *alerting*.
EMERGENCY_MEANINGS: Final[MappingProxyType[str, str]] = MappingProxyType(
    {
        "7500": "unlawful interference",
        "7600": "radio failure",
        "7700": "general emergency",
    }
)

#: Prefix of a built-in emergency detector's ``alert_matches.builtin_key``.
#: ``docs/DATA_MODEL.md`` §4.3 gives ``emergency_7700`` as its example.
EMERGENCY_BUILTIN_PREFIX: Final = "emergency_"

#: Every ``builtin_key`` this build can write, for the API's filter vocabulary
#: and for the test that pins it.
EMERGENCY_BUILTIN_KEYS: Final[tuple[str, ...]] = tuple(
    f"{EMERGENCY_BUILTIN_PREFIX}{code}" for code in sorted(EMERGENCY_MEANINGS)
)

#: The severity every emergency squawk fires at (SPEC §46: "emergency squawk to
#: Critical"). Not configurable and not lowerable by rule configuration — see
#: :mod:`flightsite.alerts.builtins`.
EMERGENCY_SEVERITY: Final = AlertSeverity.CRITICAL


def emergency_builtin_key(squawk: str) -> str:
    """The ``builtin_key`` for an emergency ``squawk``, e.g. ``emergency_7700``."""
    return f"{EMERGENCY_BUILTIN_PREFIX}{squawk}"


__all__ = [
    "EMERGENCY_BUILTIN_KEYS",
    "EMERGENCY_BUILTIN_PREFIX",
    "EMERGENCY_MEANINGS",
    "EMERGENCY_SEVERITY",
    "AlertSeverity",
    "emergency_builtin_key",
]
