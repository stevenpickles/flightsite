"""Emergency squawks: the one alert no configuration can switch off (SPEC §47).

SPEC §47 says an emergency squawk must *"not require an unrelated
interesting-aircraft rule to be matched"*, and SPEC §46 puts it at
``critical``. This module is that guarantee, and it is deliberately a separate
evaluation from :func:`flightsite.alerts.evaluator.evaluate` rather than a
shipped rule with a squawk condition, for three reasons that all point the same
way:

* **It cannot be a rule.** ``docs/DATA_MODEL.md`` §4.2's condition set — the
  closed v1 list — has no squawk kind, and §4.2 says so explicitly:
  *"Emergency-squawk detection is built in and rule-independent (SPEC §47)."*
  There is no document a user could write that would express it.
* **A rule can be disabled, edited or deleted.** Anything expressible as a row
  in ``alert_rules`` is by construction something a user can turn off, and §47
  does not permit that.
* **It has no rule row to attribute a match to.** §4.3 gives these matches
  ``builtin_key`` instead, with ``emergency_7700`` as its own example.

What the built-in deliberately ignores
--------------------------------------

Everything that bounds an ordinary rule:

* **The configured alert radius.** SPEC §66 gives the alert radius so that
  ordinary interesting-aircraft traffic at the edge of coverage does not become
  noise. An aircraft squawking 7700 is not noise at any distance.
* **Ground state.** SPEC §40 excludes ground traffic from *relevant* alerts,
  and an emergency on the ground is the case where that exclusion would be
  most wrong — 7500 is unlawful interference, which is a thing that happens at
  a gate.
* **Whether any rule exists at all.** A first-run install with an empty
  ``alert_rules`` table still alerts on 7700, which is the roadmap's
  *"emergency squawks alert with zero user configuration"*.

One key per code
----------------

An aircraft that squawks 7600 and later 7700 produces two matches, because the
two codes get different ``builtin_key``\\ s. §4.3 names that as exactly the
allowed "a newly matched higher-priority condition may notify again" path. A
code that appears, clears and appears again within one sighting produces one
match: the key is the same, so the sighting's dedupe already covers it — which
is the same shape :meth:`flightsite.sightings.state.ActiveSighting.
_observe_emergency` gives the ``emergency_start`` sighting event.
"""

from __future__ import annotations

from flightsite.alerts.model import AlertSubject, MatchProposal
from flightsite.alerts.vocabulary import (
    EMERGENCY_MEANINGS,
    EMERGENCY_SEVERITY,
    emergency_builtin_key,
)


def emergency_reason(squawk: str) -> str:
    """The human-readable reason a built-in emergency match carries.

    Names the code *and* what it means, because the code alone is jargon: a
    user reading "Emergency squawk 7600" in a notification should not have to
    know that 7600 is radio failure.
    """
    return f"Emergency squawk {squawk} ({EMERGENCY_MEANINGS[squawk]})"


def emergency_match(subject: AlertSubject) -> MatchProposal | None:
    """The built-in match this aircraft's current squawk justifies, if any.

    Pure, total and independent of every rule: given a subject it looks at one
    field. ``None`` covers "no squawk reported this poll" and "an ordinary
    squawk" alike — the decoder omitting a squawk is not a statement that an
    emergency ended (:mod:`flightsite.live.aircraft`'s merge semantics), and
    the live record keeps the last one it heard, so a code that is still
    standing keeps producing this match until the sighting's dedupe stops it.
    """
    squawk = subject.squawk
    if squawk is None or squawk not in EMERGENCY_MEANINGS:
        return None
    key = emergency_builtin_key(squawk)
    return MatchProposal(
        key=f"builtin:{key}",
        severity=EMERGENCY_SEVERITY,
        reason=emergency_reason(squawk),
        builtin_key=key,
    )


__all__ = ["emergency_match", "emergency_reason"]
