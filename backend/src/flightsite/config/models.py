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

import re
import types
import typing
import zoneinfo
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Annotated, Any, Final, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    SecretStr,
    ValidationInfo,
    field_validator,
    model_validator,
)
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

    ``source_url_overrides`` redirects one named source's dataset download to
    another URL — a local mirror, an internal cache, or a fixture served by a
    test's own HTTP server (issue #112). Every source already accepted such an
    override at construction; what was missing was a way for an *operator* to
    set one, which is also what let an integration test exercise the real fetch
    path instead of stubbing the layer underneath it.

    Three properties are deliberate:

    * It is keyed by source name and applies **only** to the dataset sources
      (``mictronics``, ``faa``, ``opensky``, ``airports``, ``routes``). No
      authenticated endpoint is reachable through it, so it can never redirect
      a request that carries a secret to a host of the operator's choosing.
    * ``HttpUrl`` rejects anything that is not an ``http``/``https`` URL, so a
      typo cannot turn into a file read or a scheme the client cannot fetch.
    * The keys are validated for *shape* only — this layer does not know the
      source catalogue, exactly as ``alerts.enabled_templates`` does not know
      the template catalogue. A key naming no registered source is reported by
      :func:`flightsite.app._build_metadata_registry` as a warning at startup
      rather than rejected here, so adding a source is not a config-schema
      change.
    """

    opensky_enabled: bool = False
    source_url_overrides: dict[str, HttpUrl] = Field(default_factory=dict)

    @field_validator("source_url_overrides")
    @classmethod
    def _clean_source_names(cls, value: dict[str, HttpUrl]) -> dict[str, HttpUrl]:
        cleaned: dict[str, HttpUrl] = {}
        for source, url in value.items():
            name = source.strip().lower()
            if not name:
                raise ValueError("metadata.source_url_overrides keys must name a source")
            if name in cleaned:
                raise ValueError(f"metadata.source_url_overrides names {name!r} twice")
            cleaned[name] = url
        return cleaned


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


#: The ``feeders`` entry-name shape: a lowercase slug, so a name is safe in a
#: URL path segment (``/api/v1/feeders/{name}/history``), a dedupe key and a
#: ``secrets.yaml`` key without any escaping.
FEEDER_NAME_PATTERN: Final = r"^[a-z0-9][a-z0-9-]{0,31}$"
_FEEDER_NAME_RE: Final = re.compile(FEEDER_NAME_PATTERN)

FeederKind = Literal[
    "readsb",
    "piaware",
    "fr24",
    "ultrafeeder",
    "opensky_logs",
    "docker_health",
    "link_only",
]

#: Which fields each kind cannot work without (slice 077). A kind absent here
#: needs nothing beyond ``name``/``label``/``kind``. The Settings UI mirrors
#: this table so an entry is rejected per field before it is ever sent.
FEEDER_KIND_REQUIRED_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "readsb": ("url",),
    "piaware": ("url",),
    "fr24": ("url",),
    "ultrafeeder": ("url", "host"),
    "opensky_logs": ("container",),
    "docker_health": ("container",),
}


def _check_feeder_name(value: str, *, what: str) -> str:
    stripped = value.strip()
    if not _FEEDER_NAME_RE.match(stripped):
        raise ValueError(
            f"{what} {value!r} must be a lowercase slug: a letter or digit, then up to 31 "
            "letters, digits or hyphens (e.g. 'flightaware')"
        )
    return stripped


def _is_cleared(value: Any) -> bool:
    """True for a ``stats_urls`` value that means "remove this key"."""
    if value is None:
        return True
    raw = value.get_secret_value() if isinstance(value, SecretStr) else value
    return isinstance(raw, str) and not raw.strip()


class FeederEntry(_ConfigModel):
    """One network the receiver feeds, or one sibling service — slice 077.

    Validated for *shape* only: nothing here opens a connection. What each
    kind needs is in :data:`FEEDER_KIND_REQUIRED_FIELDS`, and a missing field
    is reported against that field (``feeders.entries.2.url``) rather than
    against the entry, so the Settings UI can mark the one input that is wrong.
    ``url``, ``container`` and ``host`` are declared after ``kind`` and
    validated even when left at their default, which is what gives their
    validators the entry's kind to check against.

    The per-network *stats* link is deliberately not here: it usually embeds a
    feeder identity, so it lives in ``secrets.yaml`` as
    ``feeders.stats_urls.<name>`` (:class:`FeederSettings`).
    """

    name: str
    label: str = Field(min_length=1, max_length=80)
    kind: FeederKind
    url: HttpUrl | None = Field(default=None, validate_default=True)
    container: str | None = Field(default=None, max_length=128, validate_default=True)
    host: str | None = Field(default=None, max_length=253, validate_default=True)
    mlat_port: int | None = Field(default=None, ge=1, le=65535)
    beast_port: int | None = Field(default=None, ge=1, le=65535)
    web_url: HttpUrl | None = None

    @field_validator("name")
    @classmethod
    def _slug(cls, value: str) -> str:
        return _check_feeder_name(value, what="feeder name")

    @field_validator("label")
    @classmethod
    def _strip_label(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("feeder label must not be blank")
        return stripped

    @field_validator("container", "host", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip() or None
        return value

    @field_validator("url", "container", "host")
    @classmethod
    def _required_by_kind(cls, value: Any, info: ValidationInfo) -> Any:
        kind = info.data.get("kind")
        field_name = info.field_name
        if (
            value is None
            and kind is not None
            and field_name in FEEDER_KIND_REQUIRED_FIELDS.get(kind, ())
        ):
            raise ValueError(f"{field_name} is required for a feeder of kind {kind!r}")
        return value


class LocalPage(_ConfigModel):
    """A sibling page hosted beside FlightSite (tar1090, graphs1090, ...)."""

    label: str = Field(min_length=1, max_length=80)
    url: HttpUrl

    @field_validator("label")
    @classmethod
    def _strip_label(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("local page label must not be blank")
        return stripped


class FeederSettings(_ConfigModel):
    """Feeder monitoring — slice 077, ADR-0017. Hot-applied on save.

    ``docker_socket`` is off by default and is the one setting here with a
    trust consequence: mounting the Docker Engine socket into the container is
    root-equivalent on most hosts (``docs/SECURITY.md`` §10). Without it the
    log- and health-only signals read ``unknown``, never ``down``.

    ``stats_urls`` is the second kind of secret FlightSite stores and the
    first that is a mapping: one per-network stats URL per entry name, pasted
    by the owner into ``secrets.yaml``. They usually embed a feeder identity (a
    site id, a username, a UUID), so they are typed :class:`SecretStr`, masked
    everywhere secrets are masked (:func:`secret_field_paths` walks mapping
    values), and reached only through the internal ``stats-link`` redirect —
    never through ``/api/v1``. Keys are validated for entry-name *shape* only,
    so pasting a URL before adding its entry is harmless. A ``null`` or blank
    value in an update removes that key; the mask leaves it unchanged.
    """

    poll_interval_s: int = Field(default=15, ge=5, le=120)
    docker_socket: str | None = None
    entries: list[FeederEntry] = Field(default_factory=list)
    local_pages: list[LocalPage] = Field(default_factory=list)
    stats_urls: dict[str, SecretStr] = Field(default_factory=dict)

    @field_validator("docker_socket", mode="before")
    @classmethod
    def _blank_socket_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("docker_socket")
    @classmethod
    def _absolute_socket(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped.startswith("/"):
            raise ValueError(
                "feeders.docker_socket must be an absolute path (e.g. /var/run/docker.sock)"
            )
        return stripped

    @field_validator("entries")
    @classmethod
    def _unique_names(cls, value: list[FeederEntry]) -> list[FeederEntry]:
        seen: set[str] = set()
        for entry in value:
            if entry.name in seen:
                raise ValueError(f"feeder name {entry.name!r} is used by more than one entry")
            seen.add(entry.name)
        return value

    @field_validator("stats_urls", mode="before")
    @classmethod
    def _drop_cleared(cls, value: Any) -> Any:
        # ``null`` or a blank string is how an update clears one stored URL:
        # the file layers are deep-merged, so omitting a key can never remove it.
        if isinstance(value, Mapping):
            return {key: url for key, url in value.items() if not _is_cleared(url)}
        return value

    @field_validator("stats_urls")
    @classmethod
    def _stats_url_shape(cls, value: dict[str, SecretStr]) -> dict[str, SecretStr]:
        cleaned: dict[str, SecretStr] = {}
        for key, secret in value.items():
            name = _check_feeder_name(key, what="feeders.stats_urls key")
            raw = secret.get_secret_value().strip()
            parsed = urlsplit(raw)
            # The message names the key, never the value: it is a secret.
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError(f"feeders.stats_urls.{name} must be an http(s) URL")
            cleaned[name] = SecretStr(raw)
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
    feeders: FeederSettings = Field(default_factory=FeederSettings)

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
        """Map each secret's dotted path to whether a value is stored.

        A scalar secret always appears, ``True`` or ``False``. A mapping of
        secrets (``feeders.stats_urls``) contributes one ``True`` entry per
        stored key — ``feeders.stats_urls.flightaware`` — and nothing for a
        key it does not hold, because the set of possible keys is open.
        """
        state: dict[str, bool] = {}
        for path in secret_field_paths(type(self)):
            value = _resolve(self, path)
            if isinstance(value, Mapping):
                for key, secret in value.items():
                    state[".".join((*path, str(key)))] = secret is not None
            else:
                state[".".join(path)] = value is not None
        return state


def _resolve(root: Any, path: tuple[str, ...]) -> Any:
    """Follow ``path`` through attributes, returning ``None`` if it breaks."""
    value: Any = root
    for part in path:
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def iter_secret_values(settings: BaseModel) -> Iterator[tuple[tuple[str, ...], SecretStr]]:
    """Yield every *stored* secret with its concrete path.

    A scalar secret's path is its field path; a mapping value's path ends in
    its key (``("feeders", "stats_urls", "fr24")``). Every consumer that needs
    secret *values* — ``secrets.yaml`` write-back, diagnostics redaction —
    goes through here, so a secret added as a mapping value cannot be skipped
    by a consumer that only knew how to read a scalar.
    """
    for path in secret_field_paths(type(settings)):
        value = _resolve(settings, path)
        if isinstance(value, SecretStr):
            yield path, value
        elif isinstance(value, Mapping):
            for key, secret in value.items():
                if isinstance(secret, SecretStr):
                    yield (*path, str(key)), secret


def _set_masked(data: dict[str, Any], path: tuple[str, ...], *, mask: str | None) -> None:
    """Replace ``path`` in ``data`` with ``mask`` (or drop it when masking to None).

    When ``path`` holds a mapping of secrets, every value in it is masked
    (keys stay visible — they are entry names, not secrets), or the whole
    mapping is dropped when masking to ``None``.
    """
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
    elif isinstance(node[leaf], dict):
        node[leaf] = {
            key: (mask if value is not None else None) for key, value in node[leaf].items()
        }
    else:
        node[leaf] = mask if node[leaf] is not None else None


def _contains_secret_str(annotation: Any) -> bool:
    if annotation is SecretStr:
        return True
    origin = typing.get_origin(annotation)
    if origin in (typing.Union, types.UnionType):
        return any(_contains_secret_str(arg) for arg in typing.get_args(annotation))
    if origin is dict:
        # ``dict[str, SecretStr]``: a mapping whose *values* are secrets.
        args = typing.get_args(annotation)
        return len(args) == 2 and _contains_secret_str(args[1])
    return False


def secret_field_paths(model: type[BaseModel]) -> tuple[tuple[str, ...], ...]:
    """Discover every ``SecretStr`` field, as dotted paths from the root model.

    Walking the model by type means a secret added in a later slice is
    automatically masked everywhere secrets are masked — nothing has to be
    added to a parallel list.

    A field typed ``dict[str, SecretStr]`` (``feeders.stats_urls``, slice 077)
    is reported by its field path; the value there is a mapping, and every
    consumer handles that case — :func:`iter_secret_values` yields its entries
    one by one with the key appended to the path.
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
