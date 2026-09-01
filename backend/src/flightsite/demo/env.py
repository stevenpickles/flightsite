"""Demo mode activation: the ``FLIGHTSITE_DEMO`` environment flag.

Kept env-only, deliberately not a field on
:class:`flightsite.config.models.Settings`: demo mode is a run-mode switch an
operator flips for a container or a development shell, not a persisted
preference a user sets through the config API, and it must work before any
``config.yaml`` exists (SPEC §76: "demo mode runs the full stack with no
decoder and no internet" — including on a first run). Reading it directly
here, rather than threading it through the settings model, keeps the config
schema untouched by this slice.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

#: Values that turn demo mode on, compared case-insensitively.
_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})

#: The environment variable itself, named once so app wiring and tests never
#: hand-spell it differently.
DEMO_ENV_VAR = "FLIGHTSITE_DEMO"


def demo_enabled(environ: Mapping[str, str] | None = None) -> bool:
    """True when ``FLIGHTSITE_DEMO`` is set to a truthy value.

    Args:
        environ: overrides the source of environment variables; defaults to
            ``os.environ``. Tests pass an explicit mapping rather than
            monkeypatching the process environment when they want isolation
            without touching global state.
    """
    source = environ if environ is not None else os.environ
    return source.get(DEMO_ENV_VAR, "").strip().lower() in _TRUTHY_VALUES


__all__ = ["DEMO_ENV_VAR", "demo_enabled"]
