"""Domain errors the alerts package raises.

One flat hierarchy, mirroring :mod:`flightsite.watchlists.errors`: the internal
API's job is to turn each into the right HTTP status (``docs/API.md`` §5), and
a single ``isinstance`` chain does that more simply than a caller re-deriving
"was this a 404 or a 422" from a message string.
"""

from __future__ import annotations


class AlertError(Exception):
    """Base class for every alert domain error."""


class AlertRuleNotFoundError(AlertError):
    """Raised for an operation naming a rule id that does not exist."""


class AlertRuleValueError(AlertError):
    """Raised when a rule's name, severity or condition set fails validation."""


class AlertTemplateNotFoundError(AlertError):
    """Raised for an operation naming a template key this build does not ship."""


class AlertTemplateConflictError(AlertError):
    """Raised when a shipped template has no rule left to create.

    Two states reach it, and they are one error rather than two because the
    answer a caller can act on is identical: *there is nothing here to
    instantiate.* A built-in template (SPEC §47's emergency squawks) never had
    a rule to create, and an already-instantiated one no longer does. The
    template gallery renders both as "already on", which is what a user needs
    to read either way.
    """


__all__ = [
    "AlertError",
    "AlertRuleNotFoundError",
    "AlertRuleValueError",
    "AlertTemplateConflictError",
    "AlertTemplateNotFoundError",
]
