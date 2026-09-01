"""Aircraft classification and operator normalization (SPEC §38-§39).

What this package is for
------------------------

Two questions the metadata subsystem deliberately does not answer. Slices
021-023 resolve *what an upstream database says* about an airframe — its
registration, type, model, operator string and military bit — with per-field
provenance. This package answers *what that means*: is it military, is it a
state aircraft, is it police, what is it broadly for, and what should it be
drawn as.

The product principle it is built around (SPEC §39, ``docs/PRODUCT.md``) is
that classification **must carry provenance and must not claim certainty when
the evidence is weak**. That is not a style note here, it is the type system:

* :class:`~flightsite.classification.model.Classification` cannot be
  constructed with an assertion that has no
  :class:`~flightsite.classification.model.Claim` behind it.
* Every claim carries a
  :class:`~flightsite.classification.vocabulary.ClaimSource` (whose statement
  this is), an :class:`~flightsite.classification.vocabulary.EvidenceBasis`
  (what was recognized) and a
  :class:`~flightsite.classification.vocabulary.Confidence` band.
* ``unknown`` is a first-class answer, returned for weak evidence *and* for
  conflicting evidence, and it is what an aircraft with an airliner type and no
  operator gets.

Layout
------

``vocabulary``   the closed sets of words classification may use.
``specs``        the shapes the curated data files are written in.
``data/``        the curated data itself — operators, groups, type designators.
``operators``    matching an operator string or callsign to a curated group.
``engine``       :func:`~flightsite.classification.engine.classify`, pure.
``store``        the SQL the import pipeline runs to persist all of it.

Where it runs
-------------

Classification is computed at metadata import time, alongside precedence
resolution and inside the same transaction, and written to
``aircraft_classification`` (``docs/DATA_MODEL.md`` §3.4). The live path never
computes it from the database: the metadata cache classifies each aircraft once
when its entry is built, off the hot path, and the API serializer reads the
result (``docs/ARCHITECTURE.md`` §3.1 — no live request waits on SQLite).
"""

from __future__ import annotations

from flightsite.classification.engine import classify, icon_category_for
from flightsite.classification.model import Claim, Classification, Evidence
from flightsite.classification.operators import (
    OperatorDirectory,
    OperatorMatch,
    default_directory,
    match_key,
)
from flightsite.classification.specs import OperatorGroupSpec, OperatorPattern, TypeRule
from flightsite.classification.vocabulary import (
    ClaimSource,
    Confidence,
    EvidenceBasis,
    GroupKind,
    IconCategory,
    MissionCategory,
)

__all__ = [
    "Claim",
    "ClaimSource",
    "Classification",
    "Confidence",
    "Evidence",
    "EvidenceBasis",
    "GroupKind",
    "IconCategory",
    "MissionCategory",
    "OperatorDirectory",
    "OperatorGroupSpec",
    "OperatorMatch",
    "OperatorPattern",
    "TypeRule",
    "classify",
    "default_directory",
    "icon_category_for",
    "match_key",
]
