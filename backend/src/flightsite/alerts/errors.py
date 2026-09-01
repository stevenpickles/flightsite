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


__all__ = ["AlertError", "AlertRuleNotFoundError", "AlertRuleValueError"]
