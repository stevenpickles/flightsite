"""The normalized records that cross the provider boundary.

ADR-0006 draws one line through the metadata subsystem: *upstream format
changes are contained to one module per source; the domain sees only
normalized records with provenance*. These types are that line. Everything on
the upstream side of it — CSV quirks, JSON layouts, bit-packed flag fields,
whatever slice 022 and 023 find — is a provider's private problem. Everything
on this side deals only in :class:`NormalizedAircraftRecord`.

Normalization is enforced here rather than trusted to each provider, because a
provider that quietly emitted ``"N302DN "`` or ``"A0B1C2"`` would corrupt the
resolved table in a way no schema constraint would catch: SQLite compares text
byte for byte, so one stray space or capital makes an airframe two airframes.
:func:`normalize_record` is therefore the only supported way to build a record
from raw values, and it *rejects* rather than repairs anything it cannot
interpret — a rejected row is counted and reported, never guessed at.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

#: A valid ICAO 24-bit address in FlightSite's canonical spelling: six
#: lowercase hex digits. The live pipeline already speaks this spelling, which
#: is what lets the cache join live aircraft to metadata by plain dict lookup.
ICAO24_PATTERN: Final = re.compile(r"^[0-9a-f]{6}$")

#: Bounds on a plausible manufacture year. The lower bound predates powered
#: flight; the upper bound is deliberately absent (a record may legitimately
#: describe an airframe delivered next year), so only nonsense is refused.
MIN_MANUFACTURE_YEAR: Final = 1900


class MetadataError(RuntimeError):
    """Base class for metadata subsystem failures."""


class RecordError(ValueError):
    """A source row could not be normalized into a usable record.

    Raised by :func:`normalize_record` and caught by the import pipeline, which
    counts the row as rejected and carries on. One bad row in a
    half-million-row snapshot must not fail an import; a *lot* of bad rows is
    what validation thresholds are for.
    """


@dataclass(frozen=True, slots=True)
class SourceArtifact:
    """A downloaded snapshot on local disk, ready to be validated and read.

    ``version`` is whatever identifies the snapshot upstream — a release tag, a
    date stamp, or a content hash where upstream offers nothing better. It is
    recorded in ``metadata_sources.dataset_version`` so a user can tell whether
    an "update" actually changed anything, and it is the only thing tying a set
    of resolved rows back to the bytes that produced them.
    """

    #: Where the downloaded bytes live. Inside the run's working directory, so
    #: the pipeline can delete the whole tree when the run ends.
    path: Path
    version: str
    #: Hex digest of the downloaded bytes, or ``""`` when the provider has no
    #: cheap way to compute one over a large artifact.
    content_hash: str = ""
    size_bytes: int = 0

    def describe(self) -> str:
        """A short, log-safe identification of this artifact."""
        return f"{self.version} ({self.size_bytes} bytes)"


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """A provider's verdict on a downloaded artifact.

    ``ok`` is the whole decision: the pipeline does not second-guess a provider
    that says its download is sound, and does not proceed past one that says it
    is not. ``errors`` explain a rejection to the user (they reach
    ``metadata_sources.last_error``); ``warnings`` are recorded in the run log
    and do not block.

    ``expected_rows`` is a **lower bound**: the fewest airframes the provider
    believes this artifact should yield. It lets the pipeline catch a
    *transform* that silently produced far fewer rows than the *download*
    contained — a truncation the provider's own file-level checks cannot see.
    """

    ok: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    expected_rows: int | None = None

    @classmethod
    def accepted(
        cls, *, expected_rows: int | None = None, warnings: Sequence[str] = ()
    ) -> ValidationReport:
        """A passing report, optionally carrying warnings."""
        return cls(ok=True, warnings=tuple(warnings), expected_rows=expected_rows)

    @classmethod
    def rejected(cls, *errors: str) -> ValidationReport:
        """A failing report. At least one reason is required."""
        if not errors:
            raise ValueError("a rejected validation report must give a reason")
        return cls(ok=False, errors=tuple(errors))

    def reason(self) -> str:
        """The rejection reasons as one line, for status and logs."""
        return "; ".join(self.errors)


@dataclass(frozen=True, slots=True)
class NormalizedAircraftRecord:
    """One airframe's metadata as a single source claims it.

    Every field is optional except the address: a source that knows only a
    registration still contributes, and precedence lets a better source fill
    the rest. ``None`` means *this source does not know*, never *nobody
    knows* — the distinction is what stops a sparse source from blanking a
    richer one.
    """

    icao24: str
    registration: str | None = None
    type_code: str | None = None
    model: str | None = None
    manufacture_year: int | None = None
    operator_name: str | None = None
    owner: str | None = None
    #: ``None`` when the source says nothing about military status, so slice
    #: 024 can tell silence from an explicit "no".
    military_flag: bool | None = None
    #: Source-specific extras, stored as JSON for slice 024 to mine. Kept out
    #: of the resolved table on purpose: nothing sorts or filters on it.
    flags: Mapping[str, str | int | float | bool | None] = field(default_factory=dict)

    def flags_json(self) -> str | None:
        """``flags`` as a compact JSON object, or ``None`` when empty.

        Sorted keys so an unchanged snapshot produces byte-identical rows and
        a re-import is genuinely a no-op at the storage layer.
        """
        if not self.flags:
            return None
        return json.dumps(dict(self.flags), sort_keys=True, separators=(",", ":"))


def normalize_icao24(raw: str) -> str:
    """Canonicalize an ICAO 24-bit address, or raise :class:`RecordError`.

    Accepts the spellings real datasets use — mixed case, surrounding
    whitespace, a ``0x`` or ``~`` prefix (tar1090 marks non-ICAO addresses with
    a tilde) — and refuses anything that is not then six hex digits.
    """
    text = raw.strip().lower().removeprefix("0x").removeprefix("~")
    if not ICAO24_PATTERN.match(text):
        raise RecordError(f"not an ICAO 24-bit address: {raw!r}")
    return text


def normalize_text(raw: object) -> str | None:
    """Collapse a raw field to a clean string, or ``None`` if it says nothing.

    Whitespace is stripped and internal runs collapsed to single spaces, and an
    empty result becomes ``None``: a source that supplies ``"   "`` knows
    nothing, and storing that as a value would make it outrank a source that
    actually does.
    """
    if raw is None:
        return None
    text = " ".join(str(raw).split())
    return text or None


def normalize_year(raw: object) -> int | None:
    """Interpret a manufacture year, or ``None`` when it is absent or nonsense.

    Unlike :func:`normalize_icao24` this never raises: a registry with a
    garbled year is still worth importing for its registration and owner, so a
    bad year is dropped rather than taken as a reason to reject the airframe.
    """
    text = normalize_text(raw)
    if text is None:
        return None
    try:
        year = int(text)
    except ValueError:
        return None
    return year if year >= MIN_MANUFACTURE_YEAR else None


def normalize_record(
    *,
    icao24: str,
    registration: object = None,
    type_code: object = None,
    model: object = None,
    manufacture_year: object = None,
    operator_name: object = None,
    owner: object = None,
    military_flag: bool | None = None,
    flags: Mapping[str, str | int | float | bool | None] | None = None,
) -> NormalizedAircraftRecord:
    """Build a :class:`NormalizedAircraftRecord` from raw provider values.

    The one constructor providers should use. Raises :class:`RecordError` if
    the address is unusable — the only field whose absence makes a row
    meaningless, since it is the key everything else hangs off.
    """
    return NormalizedAircraftRecord(
        icao24=normalize_icao24(icao24),
        registration=normalize_text(registration),
        type_code=_normalize_type_code(type_code),
        model=normalize_text(model),
        manufacture_year=normalize_year(manufacture_year),
        operator_name=normalize_text(operator_name),
        owner=normalize_text(owner),
        military_flag=military_flag,
        flags=dict(flags) if flags else {},
    )


def _normalize_type_code(raw: object) -> str | None:
    """Upper-case an ICAO type designator (``b738`` and ``B738`` are one type).

    Type is the one metadata field FlightSite *groups* by — rarity, type
    statistics, the icon hierarchy — so a case split here would silently
    fragment those counts.
    """
    text = normalize_text(raw)
    return text.upper() if text is not None else None


__all__ = [
    "ICAO24_PATTERN",
    "MIN_MANUFACTURE_YEAR",
    "MetadataError",
    "NormalizedAircraftRecord",
    "RecordError",
    "SourceArtifact",
    "ValidationReport",
    "normalize_icao24",
    "normalize_record",
    "normalize_text",
    "normalize_year",
]
