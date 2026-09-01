"""Measurement primitives: samples, summaries, and process memory.

Everything the harness reports is a :class:`Measurement` — a named series of
samples in a stated unit, summarized the same way every time. Reporting the
whole distribution rather than a single number is deliberate: a budget that is
crossed by a p99 while the median sits at a tenth of it is a scheduling
artefact, and a budget crossed by the median is a regression. The harness
prints both, and :meth:`Measurement.verdict` gates on whichever statistic the
budget names.

Memory is measured without adding a dependency. ``docs/ARCHITECTURE.md`` §6
bounds the *process* at 1 GB, so resident set size is the honest quantity, and
it is read straight from the platform: ``/proc/self/statm`` on Linux (the
reference target and CI), ``GetProcessMemoryInfo`` through ``ctypes`` on
Windows, ``getrusage`` elsewhere. :func:`rss_bytes` returns ``None`` when no
source is available rather than guessing, and the harness degrades to the
Python-heap figure from :mod:`tracemalloc`, which is portable but measures only
what Python allocated.
"""

from __future__ import annotations

import ctypes
import os
import sys
import tracemalloc
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from statistics import mean, median
from typing import Final

#: Bytes in a mebibyte, spelled once.
MIB: Final = 1024.0 * 1024.0


class Statistic(StrEnum):
    """Which number in a distribution a budget is stated against.

    A budget names one of these so the gate is unambiguous. Throughput budgets
    are floors stated against :attr:`MEDIAN`; latency budgets are ceilings, and
    which of :attr:`MEDIAN` / :attr:`P95` / :attr:`MAX` applies depends on
    whether the budget protects an average cost or a worst case.
    """

    MEDIAN = "median"
    MEAN = "mean"
    P95 = "p95"
    P99 = "p99"
    MAX = "max"
    MIN = "min"


def percentile(samples: Sequence[float], fraction: float) -> float:
    """The ``fraction`` percentile of ``samples``, nearest-rank.

    The same definition ``tests/metadata/test_cache_latency.py`` uses, so a
    p99 quoted by the harness and a p99 quoted by that test mean the same
    thing.
    """
    if not samples:
        raise ValueError("percentile of an empty sample set")
    ordered = sorted(samples)
    index = min(len(ordered) - 1, int(len(ordered) * fraction))
    return ordered[index]


@dataclass(frozen=True, slots=True)
class Measurement:
    """A named series of samples in one unit.

    Args:
        metric: the stable metric id, matching a :class:`~.budgets.Budget`.
        unit: what a sample counts (``ms``, ``MiB``, ``batches/s``).
        samples: the raw observations, in collection order.
        note: free text carried into the report — a population size, a client
            count, whatever makes the figure interpretable later.
    """

    metric: str
    unit: str
    samples: tuple[float, ...]
    note: str = ""

    def __post_init__(self) -> None:
        if not self.samples:
            raise ValueError(f"measurement {self.metric!r} has no samples")

    @property
    def count(self) -> int:
        """How many samples were taken."""
        return len(self.samples)

    def statistic(self, which: Statistic) -> float:
        """One summary statistic of the sample set."""
        match which:
            case Statistic.MEDIAN:
                return median(self.samples)
            case Statistic.MEAN:
                return mean(self.samples)
            case Statistic.P95:
                return percentile(self.samples, 0.95)
            case Statistic.P99:
                return percentile(self.samples, 0.99)
            case Statistic.MAX:
                return max(self.samples)
            case Statistic.MIN:
                return min(self.samples)

    @property
    def summary(self) -> str:
        """A one-line distribution summary for logs and the CLI table."""
        return (
            f"median {self.statistic(Statistic.MEDIAN):.3g} "
            f"p95 {self.statistic(Statistic.P95):.3g} "
            f"max {self.statistic(Statistic.MAX):.3g} {self.unit} "
            f"(n={self.count})"
        )


def python_heap_bytes() -> int:
    """Currently traced Python allocations, in bytes.

    Requires :func:`tracemalloc.start` to have been called; returns ``0``
    otherwise, which the caller distinguishes from a real reading by having
    started tracing itself.
    """
    if not tracemalloc.is_tracing():
        return 0
    current, _peak = tracemalloc.get_traced_memory()
    return current


def rss_bytes() -> int | None:
    """Resident set size of this process, or ``None`` if unobtainable.

    Deliberately dependency-free (the stack in ``CLAUDE.md`` is pinned, and a
    memory reading does not justify an ADR to widen it). ``None`` is a real
    answer — the harness reports "not available on this platform" rather than
    substituting a different quantity and calling it RSS.
    """
    if sys.platform == "linux":
        return _rss_from_proc()
    if sys.platform == "win32":
        return _rss_from_psapi()
    return _rss_from_rusage()


def _rss_from_proc() -> int | None:
    """Linux: field 2 of ``/proc/self/statm`` is resident pages.

    The ``sys.platform`` guard is load-bearing for mypy as well as at runtime:
    it makes the body unreachable when the checker is targeting another
    platform, so ``os.sysconf`` needs no ``type: ignore`` that would then be
    flagged as unused on Linux. Every platform branch below is guarded the same
    way, and for the same reason.
    """
    if sys.platform != "linux":  # pragma: no cover - platform guard
        return None
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            fields = handle.read().split()
        return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, IndexError, ValueError):  # pragma: no cover - defensive
        return None


class _ProcessMemoryCounters(ctypes.Structure):
    """The ``PROCESS_MEMORY_COUNTERS`` layout ``GetProcessMemoryInfo`` fills."""

    _fields_ = (
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    )


def _rss_from_psapi() -> int | None:
    """Windows: ``WorkingSetSize`` is the platform's RSS equivalent.

    ``GetCurrentProcess`` returns a pseudo-handle of ``(HANDLE)-1``. Its
    ``restype`` must be declared: ctypes defaults to ``c_int``, which truncates
    the 64-bit value and makes the subsequent call fail with
    ``ERROR_INVALID_HANDLE`` rather than filling the struct.
    """
    if sys.platform != "win32":  # pragma: no cover - platform guard
        return None
    try:
        counters = _ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(_ProcessMemoryCounters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        handle = ctypes.c_void_p(kernel32.GetCurrentProcess())
        ok = psapi.GetProcessMemoryInfo(
            handle, ctypes.byref(counters), ctypes.sizeof(_ProcessMemoryCounters)
        )
        if not ok:
            return None
        return int(counters.WorkingSetSize)
    except (OSError, AttributeError, ValueError):  # pragma: no cover - platform guard
        return None


def _rss_from_rusage() -> int | None:
    """macOS/BSD fallback: ``ru_maxrss`` is a peak, not a current reading.

    Returned anyway because a peak below the budget still proves the budget
    held; the harness labels it so nobody reads it as a live figure.
    """
    if sys.platform == "win32":  # pragma: no cover - platform guard
        return None
    try:  # pragma: no cover - exercised only off Linux/Windows
        import resource

        maximum = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # Darwin reports bytes; the BSDs and Linux report kibibytes.
        return int(maximum) if sys.platform == "darwin" else int(maximum) * 1024
    except (ImportError, OSError, ValueError):
        return None


__all__ = [
    "MIB",
    "Measurement",
    "Statistic",
    "percentile",
    "python_heap_bytes",
    "rss_bytes",
]
