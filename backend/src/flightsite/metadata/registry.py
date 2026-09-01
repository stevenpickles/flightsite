"""The metadata source registry: who provides what, and how it last went.

A source is three things bound together — a name, a
:class:`~flightsite.metadata.provider.MetadataProvider`, and the per-field
precedence its data carries (:mod:`flightsite.metadata.precedence`). Binding
them at registration rather than inside the provider is deliberate: what a
source's data *means* to FlightSite is FlightSite's decision, not the
provider's, and it keeps ranking changes out of the modules that parse upstream
formats.

Status lives in two places on purpose. The **durable** status is the
``metadata_sources`` row: the outcome of the last completed attempt, which is
what SPEC §27's per-source reporting, the metadata-age health signal (SPEC §67)
and backup manifests (SPEC §72) all read. The **in-flight** status is
:class:`SourceRunState` here in memory: whether a run is happening right now,
and which phase it reached. Those are different questions with different
lifetimes — a crashed process must not leave a row claiming an import is still
running, which is exactly why ``docs/DATA_MODEL.md`` §3.1 gives the column only
three terminal values.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import Final

from flightsite.metadata.precedence import (
    DEFAULT_FIELD_PRIORITIES,
    FieldPriority,
    PrecedenceModel,
)
from flightsite.metadata.provider import MetadataProvider
from flightsite.metadata.records import MetadataError


class SourceStatus(StrEnum):
    """Durable per-source outcome (``metadata_sources.status``).

    Mirrors :data:`flightsite.db.models.METADATA_SOURCE_STATUS_CHECK`; a test
    asserts the two agree, since the enum cannot be imported into the models
    module without inverting the ``metadata`` → ``db`` dependency.
    """

    NEVER_RUN = "never_run"
    OK = "ok"
    FAILED = "failed"


class ImportPhase(StrEnum):
    """Where a run currently is, for progress reporting (slice 025).

    The order is the order the pipeline executes, and each value names the step
    that is *in progress* — so a failure reported at ``STAGING`` means staging
    is where it broke.
    """

    DOWNLOAD = "download"
    VALIDATE = "validate"
    STAGING = "staging"
    SWAP = "swap"
    DONE = "done"


class RegistrationError(MetadataError):
    """A source could not be registered."""


@dataclass(frozen=True, slots=True)
class SourceRunState:
    """In-memory progress of the current or most recent run of one source."""

    running: bool = False
    phase: ImportPhase | None = None
    #: Records staged so far in this run, for a progress readout.
    staged_rows: int = 0

    def at(self, phase: ImportPhase) -> SourceRunState:
        """This state advanced to ``phase`` and marked running."""
        return replace(self, running=True, phase=phase)

    def finished(self) -> SourceRunState:
        """This state with the run marked complete, keeping the last phase."""
        return replace(self, running=False)


@dataclass(frozen=True, slots=True)
class RegisteredSource:
    """One registered metadata source."""

    name: str
    provider: MetadataProvider
    priority: FieldPriority


#: Bound on a source name. Names are primary keys in ``metadata_sources`` and
#: appear verbatim in API ``provenance`` maps (``docs/API.md`` §2.6), so they
#: are short, lowercase, and stable.
MAX_SOURCE_NAME_LENGTH: Final = 32


class SourceRegistry:
    """The set of metadata sources this process knows how to import.

    Empty in slice 021 — the framework ships no concrete provider; slices 022
    and 023 register ``mictronics`` and ``faa``. Registration order does not
    affect resolution, which is governed entirely by declared precedence.
    """

    __slots__ = ("_run_state", "_sources")

    def __init__(self) -> None:
        self._sources: dict[str, RegisteredSource] = {}
        self._run_state: dict[str, SourceRunState] = {}

    def register(
        self,
        name: str,
        provider: MetadataProvider,
        *,
        priority: FieldPriority | None = None,
    ) -> RegisteredSource:
        """Register ``provider`` under ``name``.

        ``priority`` defaults to the declared ranking for a known source name
        (:data:`~flightsite.metadata.precedence.DEFAULT_FIELD_PRIORITIES`) and,
        failing that, to an unranked one — a source nobody ranked still
        contributes fields nobody else supplies, but never outranks one that
        was ranked deliberately.

        Raises:
            RegistrationError: if the name is unusable, already taken, or the
                object does not implement
                :class:`~flightsite.metadata.provider.MetadataProvider`.
        """
        if not name or not name.islower() or len(name) > MAX_SOURCE_NAME_LENGTH:
            raise RegistrationError(
                f"source name must be lowercase and at most "
                f"{MAX_SOURCE_NAME_LENGTH} characters: {name!r}"
            )
        if name in self._sources:
            raise RegistrationError(f"source already registered: {name!r}")
        if not isinstance(provider, MetadataProvider):
            raise RegistrationError(f"{name!r} does not implement MetadataProvider")

        resolved = priority if priority is not None else DEFAULT_FIELD_PRIORITIES.get(name)
        source = RegisteredSource(
            name=name,
            provider=provider,
            priority=resolved if resolved is not None else FieldPriority(),
        )
        self._sources[name] = source
        self._run_state[name] = SourceRunState()
        return source

    # ------------------------------------------------------------- inspection

    @property
    def names(self) -> tuple[str, ...]:
        """Registered source names, sorted so runs are deterministic."""
        return tuple(sorted(self._sources))

    def get(self, name: str) -> RegisteredSource:
        """The registered source ``name``.

        Raises:
            KeyError: if no such source is registered.
        """
        try:
            return self._sources[name]
        except KeyError:
            raise KeyError(f"unknown metadata source: {name!r}") from None

    def __contains__(self, name: object) -> bool:
        return name in self._sources

    def __len__(self) -> int:
        return len(self._sources)

    def __iter__(self) -> Iterator[RegisteredSource]:
        return (self._sources[name] for name in self.names)

    def precedence(self) -> PrecedenceModel:
        """A precedence model over exactly the registered sources.

        Built from the registry rather than from a module constant so an
        unregistered source's rows — left behind by a source that was removed
        — cannot win a field. They rank unranked and lose to anything current.
        """
        return PrecedenceModel({source.name: source.priority for source in self})

    # ------------------------------------------------------------- run state

    def run_state(self, name: str) -> SourceRunState:
        """Current in-flight state of ``name``; a fresh state if unknown."""
        return self._run_state.get(name, SourceRunState())

    def run_states(self) -> Mapping[str, SourceRunState]:
        """A snapshot of every registered source's in-flight state."""
        return {name: self.run_state(name) for name in self.names}

    def mark_phase(self, name: str, phase: ImportPhase, *, staged_rows: int = 0) -> None:
        """Record that ``name``'s run has reached ``phase``."""
        state = self.run_state(name)
        self._run_state[name] = replace(state.at(phase), staged_rows=staged_rows)

    def mark_finished(self, name: str) -> None:
        """Record that ``name``'s run has ended, however it ended."""
        self._run_state[name] = self.run_state(name).finished()


@dataclass(frozen=True, slots=True)
class SourceStatusRecord:
    """A ``metadata_sources`` row as the rest of the app reads it.

    A plain value object rather than an ORM instance so callers (the slice-025
    status endpoint, health, backup manifests) hold something detached from a
    session and safe to serialize.
    """

    source: str
    status: SourceStatus = SourceStatus.NEVER_RUN
    last_attempt_ms: int | None = None
    last_success_ms: int | None = None
    dataset_version: str | None = None
    row_count: int | None = None
    last_error: str | None = None
    #: In-flight state, filled from the registry when one is available.
    run: SourceRunState = field(default_factory=SourceRunState)

    @property
    def has_data(self) -> bool:
        """True when a successful import has ever left rows for this source."""
        return self.last_success_ms is not None


__all__ = [
    "MAX_SOURCE_NAME_LENGTH",
    "ImportPhase",
    "RegisteredSource",
    "RegistrationError",
    "SourceRegistry",
    "SourceRunState",
    "SourceStatus",
    "SourceStatusRecord",
]
