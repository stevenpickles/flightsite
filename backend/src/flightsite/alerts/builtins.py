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
  There is no document a user could write that would express it. (Version 2
  of the document — slice 089 — added ``squawk_in``, so a user *can* now write
  a rule about a squawk; it is an ordinary, disable-able rule beside this
  guarantee, never a substitute for it.)
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

Two sources, one emergency (slice 086)
--------------------------------------

The decoder's emergency state — the ADS-B emergency/priority status, which an
aircraft broadcasts independently of its squawk — is a second source. An
aircraft reporting ``nordo`` with no 7600 on the transponder raises an
emergency exactly as 7600 would, at the same severity and with the same
once-per-sighting dedupe, and its reason names the decoder as the source.

What must not happen is one emergency notifying twice because both sources
report it, and two rules together guarantee it cannot:

* **One proposal per evaluation.** The squawk is consulted first and the
  decoder only when the squawk declares nothing
  (:func:`~flightsite.sightings.vocabulary.declared_emergency`), so a single
  instant never yields two emergency matches.
* **One key per kind.** A kind a squawk can declare is keyed by that squawk
  whichever source raised it (:func:`~flightsite.alerts.vocabulary.
  emergency_kind_builtin_key`): ``nordo`` from the decoder is
  ``emergency_7600``. So the order the two sources arrive in does not matter
  either — ``nordo`` first and 7600 a poll later is the same key, which the
  sighting has already fired.

A decoder kind no squawk can express (``minfuel``, ``lifeguard``, ``downed``)
has a key of its own, and a different kind arriving later in the sighting is a
new match — the same "a newly matched condition may notify again" path as 7600
followed by 7700.
"""

from __future__ import annotations

from flightsite.alerts.model import AlertSubject, MatchProposal
from flightsite.alerts.vocabulary import (
    DECODER_EMERGENCY_MEANINGS,
    EMERGENCY_MEANINGS,
    EMERGENCY_SEVERITY,
    emergency_kind_builtin_key,
)
from flightsite.sightings.vocabulary import EMERGENCY_SOURCE_SQUAWK, declared_emergency


def emergency_reason(squawk: str) -> str:
    """The human-readable reason a built-in emergency match carries.

    Names the code *and* what it means, because the code alone is jargon: a
    user reading "Emergency squawk 7600" in a notification should not have to
    know that 7600 is radio failure.
    """
    return f"Emergency squawk {squawk} ({EMERGENCY_MEANINGS[squawk]})"


def decoder_emergency_reason(kind: str) -> str:
    """The reason for an emergency the decoder's emergency state declared.

    Names the source as well as the kind, because the one thing a reader of
    "minimum fuel" cannot otherwise tell is that no emergency squawk was set.
    """
    return f"Decoder emergency state: {DECODER_EMERGENCY_MEANINGS[kind]}"


def emergency_match(subject: AlertSubject) -> MatchProposal | None:
    """The built-in match this aircraft's current emergency justifies, if any.

    Pure, total and independent of every rule: given a subject it looks at two
    fields, the squawk first. ``None`` covers "nothing declared" in all its
    forms. For the squawk that includes "no squawk reported this poll" — the
    decoder omitting a squawk is not a statement that an emergency ended
    (:mod:`flightsite.live.aircraft`'s merge semantics), and the live record
    keeps the last one it heard, so a code that is still standing keeps
    producing this match until the sighting's dedupe stops it. The decoder's
    emergency state is its current statement, so it produces the match exactly
    while the decoder reports it.
    """
    declared = declared_emergency(subject.squawk, subject.decoder_emergency)
    if declared is None:
        return None
    source, kind = declared
    if kind not in DECODER_EMERGENCY_MEANINGS:  # pragma: no cover - vocabularies pinned by test
        return None
    key = emergency_kind_builtin_key(kind)
    squawk = subject.squawk
    reason = (
        emergency_reason(squawk)
        if source == EMERGENCY_SOURCE_SQUAWK and squawk is not None
        else decoder_emergency_reason(kind)
    )
    return MatchProposal(
        key=f"builtin:{key}",
        severity=EMERGENCY_SEVERITY,
        reason=reason,
        builtin_key=key,
        emergency_source=source,
        emergency_kind=kind,
    )


__all__ = ["decoder_emergency_reason", "emergency_match", "emergency_reason"]
