"""FlightSite configuration: settings model, file layering, and write-back.

Public entry points:

* :class:`Settings` — the validated configuration model.
* :class:`ConfigStore` — reads/writes ``config.yaml`` and ``secrets.yaml`` in
  the resolved data directory, and reports first-run state.
* :func:`load_settings` — one-shot load used by the app factory.
"""

from __future__ import annotations

from flightsite.config.loader import (
    ConfigError,
    ConfigStore,
    atomic_write_text,
    check_unknown_keys,
    deep_merge,
    load_settings,
    strip_masked_secrets,
)
from flightsite.config.models import (
    SECRET_MASK,
    AlertSettings,
    EnrichmentSettings,
    LocationSettings,
    MapSettings,
    MetadataSettings,
    NotificationSettings,
    ReceiverSettings,
    RetentionSettings,
    Settings,
    SightingTimingSettings,
    secret_field_paths,
)
from flightsite.config.paths import (
    CONFIG_FILENAME,
    DATA_DIR_ENV_VAR,
    DEFAULT_DATA_DIR,
    SECRETS_FILENAME,
    config_path,
    resolve_data_dir,
    secrets_path,
)

__all__ = [
    "CONFIG_FILENAME",
    "DATA_DIR_ENV_VAR",
    "DEFAULT_DATA_DIR",
    "SECRETS_FILENAME",
    "SECRET_MASK",
    "AlertSettings",
    "ConfigError",
    "ConfigStore",
    "EnrichmentSettings",
    "LocationSettings",
    "MapSettings",
    "MetadataSettings",
    "NotificationSettings",
    "ReceiverSettings",
    "RetentionSettings",
    "Settings",
    "SightingTimingSettings",
    "atomic_write_text",
    "check_unknown_keys",
    "config_path",
    "deep_merge",
    "load_settings",
    "resolve_data_dir",
    "secret_field_paths",
    "secrets_path",
    "strip_masked_secrets",
]
