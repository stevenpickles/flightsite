"""The FlightSite settings model.

One Pydantic model is the single description of FlightSite's configuration
(SPEC §30): the ``config.yaml`` file, the ``FLIGHTSITE_*`` environment
overrides, the internal config API, and the Settings UI all validate against
it.

Layering is performed by :mod:`flightsite.config.loader`; this module owns the
*shape*, the defaults, the validation rules, and the secret-safe
serialization.

Secrets (SPEC §29) are typed :class:`pydantic.SecretStr`. That gives leak
resistance by construction — ``repr``/``str`` of the model renders them as
``**********`` and ``model_dump(mode="json")`` renders a fixed-width mask —
and it lets :func:`secret_field_paths` discover the secret fields by type
instead of by a hand-maintained list.
"""

from __future__ import annotations

import types
import typing
import zoneinfo
from pathlib import Path
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

from flightsite.config.paths import DEFAULT_DATA_DIR

#: Placeholder returned instead of a stored secret value. The internal config
#: API accepts this value back on ``PUT`` and treats it as "leave unchanged",
#: so a client can round-trip the document it was given.
SECRET_MASK = "•••"

UnitSystem = Literal["aviation", "metric"]

Latitude = Annotated[float, Field(ge=-90.0, le=90.0)]
Longitude = Annotated[float, Field(ge=-180.0, le=180.0)]


class _ConfigModel(BaseModel):
    """Base for the nested configuration sections."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ReceiverSettings(_ConfigModel):
    """Decoder (readsb / dump1090-fa) HTTP JSON endpoint — SPEC §11."""

    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8080, ge=1, le=65535)
    path: str = Field(default="/data/aircraft.json", min_length=1)
    poll_interval_s: float = Field(default=1.0, gt=0.0, le=60.0)

    @field_validator("host")
    @classmethod
    def _strip_host(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("receiver host must not be blank")
        return stripped

    @field_validator("path")
    @classmethod
    def _leading_slash(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped.startswith("/"):
            raise ValueError("receiver path must start with '/' (e.g. '/data/aircraft.json')")
        return stripped


class LocationSettings(_ConfigModel):
    """Receiver location — SPEC §13.

    Latitude and longitude are required before FlightSite can compute
    bearings, distances or range rings, but they are unset until the setup
    wizard (slice 018) collects them, so both default to ``None``.
    """

    latitude: Latitude | None = None
    longitude: Longitude | None = None
    site_name: str | None = Field(default=None, max_length=120)
    antenna_height_ft: float | None = Field(default=None, ge=-1400.0, le=30000.0)

    @model_validator(mode="after")
    def _both_or_neither(self) -> Self:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError(
                "receiver location requires both latitude and longitude, or neither "
                "(set both to configure the receiver position)"
            )
        return self

    @property
    def is_configured(self) -> bool:
        """True once a usable receiver position is present."""
        return self.latitude is not None and self.longitude is not None


class SightingTimingSettings(_ConfigModel):
    """Sighting lifecycle timing — Phase 0 defaults 15 s / 60 s / 600 s."""

    stale_s: float = Field(default=15.0, gt=0.0, le=3600.0)
    remove_s: float = Field(default=60.0, gt=0.0, le=7200.0)
    close_s: float = Field(default=600.0, gt=0.0, le=86400.0)

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.stale_s < self.remove_s < self.close_s:
            raise ValueError(
                "sighting timings must increase: stale_s < remove_s < close_s "
                f"(got stale_s={self.stale_s}, remove_s={self.remove_s}, close_s={self.close_s})"
            )
        return self


class RetentionSettings(_ConfigModel):
    """Retention policy — SPEC §64 / ADR-0009.

    Only the high-resolution receiver-metric window is user-tunable; sighting
    history is retained indefinitely (SPEC §65).
    """

    high_res_metric_days: int = Field(default=14, ge=7, le=30)


class MapSettings(_ConfigModel):
    """Map configuration — SPEC §32 / §33.

    ``basemap`` is an opaque id resolved against the basemap registry that
    arrives with the map foundation (slice 013); the config layer only stores
    and validates the shape.
    """

    basemap: str = Field(default="dark-aviation", min_length=1, max_length=64)
    range_rings_enabled: bool = True
    range_ring_radii_nm: list[float] = Field(default_factory=lambda: [50.0, 100.0, 150.0, 200.0])

    @field_validator("range_ring_radii_nm")
    @classmethod
    def _sorted_positive(cls, value: list[float]) -> list[float]:
        if len(value) > 10:
            raise ValueError("at most 10 range rings may be configured")
        if any(radius <= 0 for radius in value):
            raise ValueError("range ring radii must be greater than 0 nm")
        if len(set(value)) != len(value):
            raise ValueError("range ring radii must be unique")
        return sorted(value)


class EnrichmentSettings(_ConfigModel):
    """Online route enrichment — SPEC §28.

    ``aerodatabox_api_key`` is the only v1 secret (SPEC §29). It is never
    written to ``config.yaml`` and never serialized by
    :meth:`Settings.dump_public`.

    Every field applies on save. ``PUT /api/internal/config`` rebuilds the
    provider *and* the spending plan from them and hands both to
    :meth:`~flightsite.enrichment.EnrichmentService.apply_provider`, so
    enabling, disabling, re-keying and re-budgeting all take effect in the
    running process (issues #161 and #167).

    The two numbers are the credit economy of slice 070, and they bound
    spending from opposite ends. ``route_ttl_days`` decides how *often* a
    callsign may be asked about; ``daily_lookup_budget`` decides how many
    callsigns may be asked about at all, whatever their TTLs say. Neither is a
    rate limit — the 10/minute burst limiter is separate and unchanged.
    """

    aerodatabox_enabled: bool = False
    aerodatabox_api_key: SecretStr | None = None
    #: Days a found route stays cached. The measured saving: a scheduled
    #: callsign heard on most days costs one lookup a week instead of one or
    #: two a day. The default and the bounds are spelled here as literals
    #: rather than imported from :mod:`flightsite.enrichment.cache`, which
    #: imports this module — the same constraint ``db.models`` works under for
    #: its ``CHECK`` vocabularies, and as there a test asserts the two agree.
    route_ttl_days: int = Field(default=7, ge=1, le=30)
    #: Provider lookups allowed per UTC day. ``0`` — the default — is uncapped,
    #: which is the behaviour every install had before this setting existed;
    #: setting it is how an owner whose feeder earns a fixed number of credits
    #: a day stops enrichment outspending them.
    daily_lookup_budget: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _key_required_when_enabled(self) -> Self:
        if self.aerodatabox_enabled and self.aerodatabox_api_key is None:
            raise ValueError(
                "enrichment.aerodatabox_enabled requires an AeroDataBox API key "
                "(set it in secrets.yaml or FLIGHTSITE_ENRICHMENT__AERODATABOX_API_KEY)"
            )
        return self


class MetadataSettings(_ConfigModel):
    """Aircraft metadata sources — SPEC §25 / §27, ADR-0013.

    The two default sources (``mictronics``, ``faa``) are always registered and
    need no configuration. This section exists for sources that are opt-in.

    ``opensky_enabled`` gates the OpenSky aircraft database. It defaults to
    ``False`` because that source's licensing is ambiguous — OpenSky's general
    Terms of Use restrict their data to non-profit research and education, while
    the aircraft database's own page states it is "unlicensed and does not fall
    under our terms of use" — so whether to fetch it is the operator's call,
    not a default FlightSite makes on their behalf. ADR-0013 records the full
    reasoning; the Settings UI states the caveat beside the control.

    Read at startup by :func:`flightsite.app._build_metadata_registry`, which
    constructs the provider only when this is set, so a change takes effect on
    the next backend restart. ``enrichment.aerodatabox_enabled`` gates its
    provider the same way but no longer shares that half of the contract: it is
    re-read and applied on every configuration save (issue #161), because
    enrichment holds nothing a swap would cost, while the metadata registry is
    wired into a service at construction.
    """

    opensky_enabled: bool = False


class NotificationSettings(_ConfigModel):
    """Browser notification enables per alert severity — SPEC §46 / §48.

    Defaults follow "do not silently enable every possible notification"
    (SPEC §45): the low-signal ``info`` severity is off by default.
    """

    enabled: bool = True
    info: bool = False
    interesting: bool = True
    high: bool = True
    critical: bool = True


class AlertSettings(_ConfigModel):
    """Alert configuration — SPEC §45.

    ``enabled_templates`` is written by the setup wizard (slice 018) and read
    by slice 038 when instantiating the shipped alert templates. The config
    layer does not know the template catalogue, so ids are validated for shape
    only.
    """

    enabled_templates: list[str] = Field(default_factory=list)

    @field_validator("enabled_templates")
    @classmethod
    def _clean_ids(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for template_id in value:
            stripped = template_id.strip()
            if not stripped:
                raise ValueError("alert template ids must not be blank")
            if stripped not in cleaned:
                cleaned.append(stripped)
        return cleaned


class Settings(BaseSettings):
    """Root FlightSite configuration.

    Source precedence is defined by :meth:`settings_customise_sources`:
    environment variables outrank everything, then the values supplied at
    construction (which :mod:`flightsite.config.loader` fills from
    ``config.yaml`` then ``secrets.yaml``), then these defaults.

    ``extra="ignore"`` is deliberate: the ``FLIGHTSITE_`` environment
    namespace is shared with non-settings variables (``FLIGHTSITE_HOST`` and
    ``FLIGHTSITE_PORT`` bind uvicorn, ``FLIGHTSITE_LOG_DIR`` steers the log
    handler), so an unknown ``FLIGHTSITE_*`` variable must not be fatal.
    Unknown keys in ``config.yaml`` — the file a human edits — are rejected
    separately by :func:`flightsite.config.loader.check_unknown_keys`.
    """

    model_config = SettingsConfigDict(
        env_prefix="FLIGHTSITE_",
        env_nested_delimiter="__",
        extra="ignore",
        validate_assignment=True,
        nested_model_default_partial_update=True,
    )

    #: Resolved data directory. Deployment-level and environment-driven, so it
    #: is excluded from serialization and never written to ``config.yaml``.
    data_dir: Annotated[Path, Field(exclude=True)] = DEFAULT_DATA_DIR

    log_level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"
    #: SPEC §68's rotating local logs, written to ``<data_dir>/logs``. On by
    #: default: an appliance the user is not expected to SSH into needs a log
    #: history that outlives the container's stdout buffer.
    log_file_enabled: bool = True

    units: UnitSystem = "aviation"
    timezone: str = "UTC"
    display_radius_nm: float = Field(default=250.0, gt=0.0, le=10000.0)
    #: ``None`` means unlimited: alerts fire regardless of distance (SPEC §66).
    alert_radius_nm: float | None = Field(default=None, gt=0.0, le=10000.0)

    receiver: ReceiverSettings = Field(default_factory=ReceiverSettings)
    location: LocationSettings = Field(default_factory=LocationSettings)
    sighting: SightingTimingSettings = Field(default_factory=SightingTimingSettings)
    retention: RetentionSettings = Field(default_factory=RetentionSettings)
    map: MapSettings = Field(default_factory=MapSettings)
    enrichment: EnrichmentSettings = Field(default_factory=EnrichmentSettings)
    metadata: MetadataSettings = Field(default_factory=MetadataSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    alerts: AlertSettings = Field(default_factory=AlertSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Put environment variables above the file layers.

        Highest priority first. ``init_settings`` carries the merged
        ``config.yaml`` + ``secrets.yaml`` data assembled by the loader, so
        returning ``(env, init)`` yields the documented order:
        defaults < config.yaml < secrets.yaml < ``FLIGHTSITE_*``.
        """
        return (env_settings, init_settings)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            zoneinfo.ZoneInfo(value)
        except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"unknown IANA timezone {value!r} "
                "(expected a tz database name such as 'Europe/London' or 'UTC')"
            ) from exc
        return value

    def dump_public(self) -> dict[str, Any]:
        """Serialize every non-secret field, with secrets masked.

        Secret fields are replaced with :data:`SECRET_MASK` when set and
        ``None`` when unset, so the result is safe for the internal config
        API, for diagnostics, and for logging. Use :meth:`dump_for_file` for
        ``config.yaml`` write-back, which omits secret keys entirely.
        """
        data = self.model_dump(mode="json")
        for path in secret_field_paths(type(self)):
            _set_masked(data, path, mask=SECRET_MASK)
        return data

    def dump_for_file(self) -> dict[str, Any]:
        """Serialize the non-secret configuration for ``config.yaml``.

        Secret keys are removed rather than masked: a mask written to disk
        would be indistinguishable from a real value on the next load.
        """
        data = self.model_dump(mode="json")
        for path in secret_field_paths(type(self)):
            _set_masked(data, path, mask=None)
        return data

    def secrets_state(self) -> dict[str, bool]:
        """Map each secret's dotted path to whether a value is stored."""
        state: dict[str, bool] = {}
        for path in secret_field_paths(type(self)):
            value: Any = self
            for part in path:
                value = getattr(value, part)
            state[".".join(path)] = value is not None
        return state


def _set_masked(data: dict[str, Any], path: tuple[str, ...], *, mask: str | None) -> None:
    """Replace ``path`` in ``data`` with ``mask`` (or drop it when masking to None)."""
    node: Any = data
    for part in path[:-1]:
        node = node.get(part)
        if not isinstance(node, dict):
            return
    leaf = path[-1]
    if leaf not in node:
        return
    if mask is None:
        del node[leaf]
    else:
        node[leaf] = mask if node[leaf] is not None else None


def _contains_secret_str(annotation: Any) -> bool:
    if annotation is SecretStr:
        return True
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return any(_contains_secret_str(arg) for arg in typing.get_args(annotation))
    return False


def secret_field_paths(model: type[BaseModel]) -> tuple[tuple[str, ...], ...]:
    """Discover every ``SecretStr`` field, as dotted paths from the root model.

    Walking the model by type means a secret added in a later slice is
    automatically masked everywhere secrets are masked — nothing has to be
    added to a parallel list.
    """
    paths: list[tuple[str, ...]] = []

    def walk(current: type[BaseModel], prefix: tuple[str, ...]) -> None:
        for name, field in current.model_fields.items():
            annotation = field.annotation
            if _contains_secret_str(annotation):
                paths.append((*prefix, name))
            elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
                walk(annotation, (*prefix, name))

    walk(model, ())
    return tuple(paths)
