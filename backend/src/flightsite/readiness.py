"""Readiness registry.

Distinguishes "started" (the ASGI app object exists and is answering requests)
from "ready" (the app has finished startup and every registered subsystem has
reported healthy). Subsystems that matter for readiness — the database, the
decoder connection, etc. — register themselves and flip their own status as
later slices land. With no subsystems registered, the app becomes ready as
soon as startup completes.
"""

from __future__ import annotations

import threading


class ReadinessRegistry:
    """Thread-safe registry tracking startup completion and subsystem health."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subsystems: dict[str, bool] = {}
        self._startup_complete = False

    def register(self, name: str) -> None:
        """Register a subsystem as not-ready, if not already registered."""
        with self._lock:
            self._subsystems.setdefault(name, False)

    def mark_ready(self, name: str) -> None:
        """Mark a registered subsystem ready. Raises ``KeyError`` if unregistered."""
        with self._lock:
            if name not in self._subsystems:
                raise KeyError(f"Unregistered subsystem: {name!r}")
            self._subsystems[name] = True

    def mark_not_ready(self, name: str) -> None:
        """Mark a registered subsystem not-ready. Raises ``KeyError`` if unregistered."""
        with self._lock:
            if name not in self._subsystems:
                raise KeyError(f"Unregistered subsystem: {name!r}")
            self._subsystems[name] = False

    def mark_startup_complete(self) -> None:
        """Record that application startup has finished."""
        with self._lock:
            self._startup_complete = True

    @property
    def is_ready(self) -> bool:
        """True once startup has completed and every subsystem reports ready."""
        with self._lock:
            if not self._startup_complete:
                return False
            return all(self._subsystems.values())

    def snapshot(self) -> dict[str, bool]:
        """Return an independent copy of current per-subsystem readiness."""
        with self._lock:
            return dict(self._subsystems)
