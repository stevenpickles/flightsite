"""Matching an operator string against the curated groups (SPEC §38).

The problem this module exists to solve is that "the operator" is a free-text
field written by whoever maintained the upstream database. ``Delta Air Lines``,
``DELTA AIR LINES INC``, ``Delta Air Lines, Inc.`` and ``Deutsche Lufthansa AG``
are four spellings of two airlines, and SQL equality sees four operators.

So matching happens on a **normalized key** — accents folded, punctuation
dropped, case collapsed, trailing legal suffixes removed — while the *exact*
string is what stays on the metadata row and what goes into ``operators.name``.
That is SPEC §38's rule made mechanical: normalize to compare, never to store.

Three ways to match, in descending order of what they are worth:

1. **Exact name**, once normalized. ``HIGH``: the curated entry names this
   operator and nothing else.
2. **Phrase**, as a run of whole words. ``MEDIUM``: the name says "Sheriff",
   which almost always means what it looks like.
3. **Callsign designator**, and only in the standard ``AAA123`` form.
   ``LOW``: a callsign is transmitted by the aircraft, is not verified against
   the airframe, and is the one input that changes mid-flight.

Word runs rather than substrings, throughout. ``"police"`` as a substring
matches ``"Metropolitan"``; as a word it does not. The distinction is not
hypothetical — substring matching on short law-enforcement words is exactly how
a classifier acquires confident nonsense.

The directory is built once (:func:`default_directory`) and is immutable, so
the import pipeline and the live cache share one instance and one set of
deterministic group ids.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from flightsite.classification.data.operators import OPERATOR_GROUPS, OPERATOR_PATTERNS
from flightsite.classification.specs import OperatorGroupSpec, OperatorPattern
from flightsite.classification.vocabulary import Confidence, EvidenceBasis

#: A callsign in the ICAO flight-identification form: a three-letter airline
#: designator followed by a flight number. Anything else — a registration used
#: as a callsign (``N738AB``), a tactical callsign, a padded fragment — is not
#: matched at all, because only this form carries an airline designator.
CALLSIGN_PATTERN: Final = re.compile(r"^([A-Z]{3})[0-9][A-Z0-9]*$")

#: Words that identify a legal wrapper rather than an operator. Stripped from
#: the *end* of a name only: "Corporate Air" is an operator, "… Corp" is not a
#: different one from "…".
LEGAL_SUFFIXES: Final[frozenset[str]] = frozenset(
    {
        "inc",
        "incorporated",
        "llc",
        "lc",
        "ltd",
        "limited",
        "corp",
        "corporation",
        "co",
        "company",
        "plc",
        "gmbh",
        "ag",
        "sa",
        "sas",
        "srl",
        "spa",
        "bv",
        "nv",
        "ab",
        "as",
        "oy",
        "aps",
        "pty",
        "dba",
    }
)

_WORD = re.compile(r"[a-z0-9]+")

#: Latin letters that carry no combining accent to strip, so Unicode
#: decomposition leaves them intact and the word pattern would then *drop*
#: them - turning the Turkish dotless i in "Yollari" into nothing at all and
#: making the name stop matching its ASCII spelling. Losing a letter is worse
#: than keeping the accent, so these are transliterated by hand.
_TRANSLITERATIONS: Final[dict[str, str]] = {
    "ı": "i",  # noqa: RUF001 - Turkish dotless i
    "ø": "o",
    "đ": "d",
    "ð": "d",
    "ł": "l",
    "ß": "ss",
    "æ": "ae",
    "œ": "oe",
    "þ": "th",
}


def match_key(name: str) -> str:
    """The comparison form of an operator name.

    Accents folded to ASCII (``Aeroméxico`` and ``Aeromexico`` are one
    airline), punctuation and case discarded, and trailing legal suffixes
    removed. Returns ``""`` for a name with nothing comparable in it, which
    never matches anything.

    Stripping stops before it empties the key: an operator whose whole name is
    a word this function would otherwise remove keeps that word rather than
    becoming a key that matches every other such operator.
    """
    lowered = "".join(_TRANSLITERATIONS.get(char, char) for char in name.lower())
    decomposed = unicodedata.normalize("NFKD", lowered)
    ascii_only = "".join(char for char in decomposed if not unicodedata.combining(char))
    words = _WORD.findall(ascii_only)
    while len(words) > 1 and words[-1] in LEGAL_SUFFIXES:
        words.pop()
    return " ".join(words)


@dataclass(frozen=True, slots=True)
class OperatorMatch:
    """A curated group an operator string or callsign was recognized as.

    ``matched`` is the curated text that fired — the exact name, the phrase, or
    the callsign designator — so a claim can say *why* rather than only *what*.
    """

    group_id: int
    group: OperatorGroupSpec
    basis: EvidenceBasis
    confidence: Confidence
    matched: str


class OperatorDirectory:
    """The curated operator data, indexed for lookup.

    Args:
        groups: the curated groups. Ids are assigned by slug order, so the same
            data always yields the same ids and a re-import writes byte-identical
            ``operator_groups`` rows.
        patterns: phrase rules, tried in order, first match winning.

    Raises:
        ValueError: if the curated data is inconsistent — a duplicate slug, a
            name or designator claimed by two groups, or a pattern naming a
            group that does not exist. These are data bugs, and failing at
            construction turns them into an import-time error rather than a
            silently wrong classification.
    """

    __slots__ = ("_by_callsign", "_by_name", "_by_slug", "_groups", "_ids", "_patterns")

    def __init__(
        self,
        groups: Sequence[OperatorGroupSpec],
        patterns: Sequence[OperatorPattern] = (),
    ) -> None:
        self._groups = tuple(groups)
        self._by_slug = {group.slug: group for group in self._groups}
        if len(self._by_slug) != len(self._groups):
            raise ValueError("duplicate operator group slug in curated data")
        # Ids from sorted slugs: insertion order in the data file is editorial
        # (groups are listed by kind, for reading), and ids must not move when
        # somebody reorders it.
        self._ids = {slug: index for index, slug in enumerate(sorted(self._by_slug), start=1)}

        self._by_name: dict[str, str] = {}
        self._by_callsign: dict[str, str] = {}
        for group in self._groups:
            for name in group.operators:
                _claim(self._by_name, match_key(name), group.slug, "operator name")
            for designator in group.callsigns:
                _claim(self._by_callsign, designator.upper(), group.slug, "callsign designator")

        compiled: list[tuple[tuple[str, ...], str]] = []
        for pattern in patterns:
            if pattern.group_slug not in self._by_slug:
                raise ValueError(f"pattern {pattern.phrase!r} names unknown group")
            compiled.append((tuple(match_key(pattern.phrase).split()), pattern.group_slug))
        self._patterns = tuple(compiled)

    # ------------------------------------------------------------- inspection

    @property
    def groups(self) -> tuple[OperatorGroupSpec, ...]:
        """Every curated group, in data-file order."""
        return self._groups

    def group_id(self, slug: str) -> int:
        """The deterministic id assigned to ``slug``."""
        return self._ids[slug]

    def group_rows(self) -> list[dict[str, str | int]]:
        """``operator_groups`` rows (``docs/DATA_MODEL.md`` §3.5), id order."""
        return [
            {"id": self._ids[group.slug], "slug": group.slug, "name": group.name}
            for group in sorted(self._groups, key=lambda group: self._ids[group.slug])
        ]

    def curated_operator_rows(self) -> list[dict[str, str | int]]:
        """``operators`` rows for every curated exact name.

        The table is the curated data made queryable in SQL (§3.5), so every
        name the file lists appears whether or not the receiver has ever heard
        that operator. Names discovered by *pattern* during an import are added
        beside these — see
        :meth:`~flightsite.metadata.repository.MetadataRepository.rebuild_resolved`.
        """
        return [
            {"name": name, "group_id": self._ids[group.slug]}
            for group in self._groups
            for name in group.operators
        ]

    # ---------------------------------------------------------------- lookups

    def match(self, operator_name: str | None) -> OperatorMatch | None:
        """The group ``operator_name`` belongs to, or ``None``.

        Exact first, then phrases in data-file order. A name matching neither
        is simply ungrouped: SPEC §38 makes the group additive, so the absence
        of one costs nothing that was ever promised.
        """
        if operator_name is None:
            return None
        key = match_key(operator_name)
        if not key:
            return None

        slug = self._by_name.get(key)
        if slug is not None:
            return self._match(slug, EvidenceBasis.OPERATOR_NAME, Confidence.HIGH, key)

        words = tuple(key.split())
        for phrase, phrase_slug in self._patterns:
            if _contains(words, phrase):
                return self._match(
                    phrase_slug,
                    EvidenceBasis.OPERATOR_PATTERN,
                    Confidence.MEDIUM,
                    " ".join(phrase),
                )
        return None

    def match_callsign(self, callsign: str | None) -> OperatorMatch | None:
        """The group a callsign's airline designator belongs to, or ``None``.

        Only the ``AAA123`` form is considered (:data:`CALLSIGN_PATTERN`), and
        the result is always ``LOW`` confidence. Callsigns are transmitted by
        the aircraft and are not tied to the airframe: a leased aircraft flies
        under the operating carrier's designator, and a mistyped one is simply
        wrong. It is enough to say "this is probably an airline flight"; it is
        not enough to say what an aircraft *is*.
        """
        if callsign is None:
            return None
        found = CALLSIGN_PATTERN.match(callsign.strip().upper())
        if found is None:
            return None
        slug = self._by_callsign.get(found.group(1))
        if slug is None:
            return None
        return self._match(slug, EvidenceBasis.CALLSIGN, Confidence.LOW, found.group(1))

    def _match(
        self, slug: str, basis: EvidenceBasis, confidence: Confidence, matched: str
    ) -> OperatorMatch:
        return OperatorMatch(
            group_id=self._ids[slug],
            group=self._by_slug[slug],
            basis=basis,
            confidence=confidence,
            matched=matched,
        )


def _claim(index: dict[str, str], key: str, slug: str, what: str) -> None:
    """Record ``key`` for ``slug``, refusing a key two groups both want."""
    existing = index.get(key)
    if existing is not None and existing != slug:
        raise ValueError(f"{what} {key!r} claimed by both {existing!r} and {slug!r}")
    index[key] = slug


def _contains(words: tuple[str, ...], phrase: tuple[str, ...]) -> bool:
    """True when ``phrase`` appears as a consecutive run of whole words."""
    span = len(phrase)
    return any(words[start : start + span] == phrase for start in range(len(words) - span + 1))


@lru_cache(maxsize=1)
def default_directory() -> OperatorDirectory:
    """The shipped curated directory, built once per process.

    Cached because it is immutable and its group ids must be identical
    everywhere: the import pipeline writes them into
    ``aircraft_metadata_resolved.operator_group_id`` and the live cache reads
    them back, and two directories with two id assignments would silently
    disagree.
    """
    return OperatorDirectory(OPERATOR_GROUPS, OPERATOR_PATTERNS)


def group_names(directory: OperatorDirectory) -> Mapping[int, str]:
    """Group id to display name — the API's ``operator_group`` values."""
    return {directory.group_id(group.slug): group.name for group in directory.groups}


def slugs(groups: Iterable[OperatorGroupSpec]) -> tuple[str, ...]:
    """The slugs of ``groups``, in order. A convenience for tests and logs."""
    return tuple(group.slug for group in groups)


__all__ = [
    "CALLSIGN_PATTERN",
    "LEGAL_SUFFIXES",
    "OperatorDirectory",
    "OperatorMatch",
    "default_directory",
    "group_names",
    "match_key",
    "slugs",
]
