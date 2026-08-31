"""Data-directory resolution.

All persistent FlightSite state lives under a single directory
(``docs/ARCHITECTURE.md`` §2.1). In containers this is the bind mount
``/opt/flightsite/data``; tests and non-container runs override it with the
``FLIGHTSITE_DATA_DIR`` environment variable.

The data directory has to be resolved *before* the settings model is loaded —
``config.yaml`` and ``secrets.yaml`` live inside it — so this resolution is
deliberately a plain function over the environment rather than a settings
field lookup.
"""

from __future__ import annotations

import os
from pathlib import Path

DATA_DIR_ENV_VAR = "FLIGHTSITE_DATA_DIR"
DEFAULT_DATA_DIR = Path("/opt/flightsite/data")

CONFIG_FILENAME = "config.yaml"
SECRETS_FILENAME = "secrets.yaml"


def resolve_data_dir(data_dir: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the FlightSite data directory.

    Precedence: explicit argument, then ``FLIGHTSITE_DATA_DIR``, then
    ``/opt/flightsite/data``. The path is not created or required to exist.
    """
    if data_dir is not None:
        return Path(data_dir)
    from_env = os.environ.get(DATA_DIR_ENV_VAR)
    if from_env:
        return Path(from_env)
    return DEFAULT_DATA_DIR


def config_path(data_dir: Path) -> Path:
    """Path of the canonical non-secret configuration file."""
    return data_dir / CONFIG_FILENAME


def secrets_path(data_dir: Path) -> Path:
    """Path of the optional secrets file."""
    return data_dir / SECRETS_FILENAME
