"""YAML layering, atomic write-back, and first-run detection.

This module owns every filesystem interaction for configuration:

* reading ``config.yaml`` and ``secrets.yaml`` out of the data directory,
* merging them under the environment (see
  :meth:`flightsite.config.models.Settings.settings_customise_sources`),
* writing them back atomically (temp file in the same directory, ``fsync``,
  then :func:`os.replace`), and
* reporting first-run state (no ``config.yaml`` on disk).

``config.yaml`` is written from the model, not patched in place: comment
preservation is explicitly not required (roadmap slice 004), and a full,
field-ordered dump keeps the output clean and stable across writes.
"""

from __future__ import annotations

import os
import stat
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from flightsite.config.models import SECRET_MASK, Settings, secret_field_paths
from flightsite.config.paths import config_path, resolve_data_dir, secrets_path

CONFIG_HEADER = (
    "# FlightSite configuration (non-secret).\n"
    "# Secrets live in secrets.yaml; FLIGHTSITE_* environment variables override\n"
    "# both files. Written by FlightSite — comments are not preserved on save.\n"
)
SECRETS_HEADER = (
    "# FlightSite secrets. Never commit this file; never include it in a backup\n"
    "# unless the backup manifest says so. Written by FlightSite.\n"
)

_SECRET_FILE_MODE = 0o600


class ConfigError(Exception):
    """Raised when configuration on disk cannot be read or is malformed."""


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Read a YAML file into a mapping; missing files yield ``{}``."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ConfigError(f"could not read {path}: {exc}") from exc

    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level")
    return parsed


def deep_merge(base: Mapping[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``overlay`` onto ``base``, returning a new dict."""
    merged: dict[str, Any] = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            merged[key] = deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def check_unknown_keys(data: Mapping[str, Any], model: type[BaseModel], source: str) -> None:
    """Reject keys the settings model does not define.

    The settings model itself ignores extra input so that unrelated
    ``FLIGHTSITE_*`` environment variables stay harmless. Files and API
    payloads are hand-authored, though, so a typo there should be a loud,
    helpful error rather than a silently dropped setting.
    """

    def walk(node: Mapping[str, Any], current: type[BaseModel], prefix: str) -> None:
        fields = current.model_fields
        for key, value in node.items():
            dotted = f"{prefix}{key}"
            field = fields.get(key)
            if field is None:
                known = ", ".join(sorted(f"{prefix}{name}" for name in fields))
                raise ConfigError(
                    f"unknown configuration key {dotted!r} in {source}; known keys: {known}"
                )
            annotation = field.annotation
            if (
                isinstance(value, Mapping)
                and isinstance(annotation, type)
                and issubclass(annotation, BaseModel)
            ):
                walk(value, annotation, f"{dotted}.")

    walk(data, model, "")


def _deep_copy_mapping(source: Mapping[str, Any]) -> dict[str, Any]:
    """Copy nested mappings so the caller's payload is never mutated."""
    return {
        key: _deep_copy_mapping(value) if isinstance(value, Mapping) else value
        for key, value in source.items()
    }


def strip_masked_secrets(patch: Mapping[str, Any]) -> dict[str, Any]:
    """Drop secret entries whose value is the mask placeholder.

    ``GET /api/internal/config`` returns stored secrets as
    :data:`~flightsite.config.models.SECRET_MASK`. A client that edits one
    field and sends the whole document back must not overwrite the real
    secret with the mask, so masked secret values mean "leave unchanged".
    """
    result = _deep_copy_mapping(patch)
    for path in secret_field_paths(Settings):
        node: Any = result
        for part in path[:-1]:
            node = node.get(part) if isinstance(node, dict) else None
            if not isinstance(node, dict):
                break
        if isinstance(node, dict) and node.get(path[-1]) == SECRET_MASK:
            del node[path[-1]]
    return result


def _dump_yaml(data: Mapping[str, Any], header: str) -> str:
    """Render a stable, human-readable YAML document."""
    body = yaml.safe_dump(
        dict(data),
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
        width=100,
    )
    return header + body


def atomic_write_text(path: Path, text: str, *, file_mode: int | None = None) -> None:
    """Write ``text`` to ``path`` atomically.

    The content goes to a temporary file in the destination directory, is
    flushed and ``fsync``-ed, then moved into place with :func:`os.replace`.
    If anything fails before the replace, the temporary file is removed and
    any existing file at ``path`` is left byte-for-byte intact.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if file_mode is not None:
            os.chmod(tmp_path, file_mode)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


class ConfigStore:
    """Reads, validates, and writes FlightSite configuration for one data directory."""

    def __init__(self, data_dir: str | os.PathLike[str] | None = None) -> None:
        self.data_dir = resolve_data_dir(data_dir)

    @property
    def config_path(self) -> Path:
        """Path of ``config.yaml`` inside the data directory."""
        return config_path(self.data_dir)

    @property
    def secrets_path(self) -> Path:
        """Path of ``secrets.yaml`` inside the data directory."""
        return secrets_path(self.data_dir)

    @property
    def first_run(self) -> bool:
        """True while no ``config.yaml`` exists — FlightSite has never been set up."""
        return not self.config_path.exists()

    def load(self, overrides: Mapping[str, Any] | None = None) -> Settings:
        """Build the effective settings.

        Layers, lowest first: model defaults, ``config.yaml``,
        ``secrets.yaml``, ``FLIGHTSITE_*`` environment variables. ``overrides``
        sits with the file layers and exists so a candidate update can be
        validated before it is written.
        """
        file_data = _load_yaml_mapping(self.config_path)
        check_unknown_keys(file_data, Settings, str(self.config_path))
        secret_data = _load_yaml_mapping(self.secrets_path)
        check_unknown_keys(secret_data, Settings, str(self.secrets_path))

        merged = deep_merge(file_data, secret_data)
        if overrides:
            merged = deep_merge(merged, overrides)
        merged.pop("data_dir", None)

        return Settings(data_dir=self.data_dir, **merged)

    def save(self, settings: Settings) -> None:
        """Write the non-secret configuration to ``config.yaml`` atomically."""
        atomic_write_text(self.config_path, _dump_yaml(settings.dump_for_file(), CONFIG_HEADER))

    def save_secrets(self, settings: Settings) -> None:
        """Write stored secrets to ``secrets.yaml`` atomically, or remove the file.

        Only secret fields are written, and only those with a value. When no
        secret is set, an existing ``secrets.yaml`` is deleted rather than
        left holding a stale key.
        """
        document: dict[str, Any] = {}
        for path in secret_field_paths(Settings):
            value: Any = settings
            for part in path:
                value = getattr(value, part)
            if value is None:
                continue
            node = document
            for part in path[:-1]:
                node = node.setdefault(part, {})
            node[path[-1]] = value.get_secret_value()

        if not document:
            self.secrets_path.unlink(missing_ok=True)
            return

        atomic_write_text(
            self.secrets_path,
            _dump_yaml(document, SECRETS_HEADER),
            file_mode=stat.S_IRUSR | stat.S_IWUSR,
        )

    def apply_update(self, patch: Mapping[str, Any]) -> Settings:
        """Validate a partial or full configuration update, then persist it.

        The patch is merged over the current effective configuration, secret
        fields are routed to ``secrets.yaml`` and non-secret fields to
        ``config.yaml``, and both files are written atomically. Raises
        :class:`ConfigError` for unknown keys and
        :class:`pydantic.ValidationError` for invalid values; in both cases
        nothing is written.

        A secret whose patch value is :data:`SECRET_MASK` is left unchanged,
        so a client can send back the masked document it was given. An
        explicit ``None`` clears the stored secret.

        Values pinned by a ``FLIGHTSITE_*`` environment variable keep winning
        after the write: the update reaches ``config.yaml``, but the
        environment still outranks the file (SPEC §30).
        """
        check_unknown_keys(patch, Settings, "configuration update")
        candidate = self.load(overrides=strip_masked_secrets(patch))
        self.save(candidate)
        self.save_secrets(candidate)
        return candidate


def load_settings(data_dir: str | os.PathLike[str] | None = None) -> Settings:
    """Convenience loader used by the app factory and by scripts."""
    return ConfigStore(data_dir).load()


__all__ = [
    "ConfigError",
    "ConfigStore",
    "ValidationError",
    "atomic_write_text",
    "check_unknown_keys",
    "deep_merge",
    "load_settings",
    "strip_masked_secrets",
]
