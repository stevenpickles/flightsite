"""Receiver-local day arithmetic and the ``docs/API.md`` §3.7 presets.

Pure functions over a :class:`~zoneinfo.ZoneInfo` and epoch milliseconds: no
database, no configuration, no clock of its own. Everything in this package
that has to answer *"which day is this?"* or *"what does `preset=7d` mean right
now?"* asks here, so the answer is one implementation that the DST fixtures can
be pointed at directly.

Why nothing here does offset arithmetic
---------------------------------------

``docs/DATA_MODEL.md`` §10 requires day boundaries to be **receiver-local and
DST-correct**: a 23-hour or a 25-hour local day must roll up as the day it
actually was. That rules out the tempting shortcut of dividing epoch
milliseconds by 86,400,000 and adding a fixed offset — it is wrong twice a year
in every DST zone, and wrong all year in a zone whose offset is not a whole
number of hours (``Asia/Kolkata`` at +05:30, ``Pacific/Chatham`` at +12:45).

So every boundary is computed by :mod:`zoneinfo` from a *calendar date*:
:func:`day_start_ms` builds local midnight for the named date and asks the zone
what instant that was. Day length then falls out of the two boundaries rather
than being assumed, which is exactly what :func:`day_bounds_ms` returns.

Midnight that does not exist, and midnight that happens twice
-------------------------------------------------------------

A handful of zones move their clocks *at* midnight. Spring-forward there means
the local time 00:00 never occurs; fall-back means it occurs twice. Python's
:pep:`495` fold rules resolve both to a real instant on the correct calendar
date — the first of the two for a repeated midnight, and the instant the clock
jumped to for a skipped one — so a day still has a single unambiguous start and
a single unambiguous end, and consecutive days still tile the timeline without
a gap or an overlap. :func:`day_bounds_ms` derives a day's end as the *next*
day's start rather than by adding 24 hours, which is what makes that tiling
hold whatever the zone does in between.

Presets
-------

``docs/API.md`` §3.7's five presets all resolve to a half-open UTC window
``[start_ms, end_ms)`` whose lower bound is a local midnight and whose upper
bound is "now". They are calendar statements, not durations: ``7d`` is *the
last seven local days including today*, so it starts at the local midnight
opening the day six days back — which is 167, 168 or 169 hours ago depending on
what the zone did in between, and is the same seven rows of ``daily_stats``
either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo

from flightsite.db.clock import MS_PER_SECOND

#: Hours in a nominal day. Used only to size loop bounds, never as a day length.
HOURS_PER_DAY: Final = 24

#: Days in the ``7d`` and ``30d`` presets, counting today (``docs/API.md`` §3.7).
PRESET_7D_DAYS: Final = 7
PRESET_30D_DAYS: Final = 30

#: Upper bound on how many day rows one window may span. Ten years of daily
#: rows: comfortably beyond any real install's history, and low enough that a
#: hand-written ``from``/``to`` pair cannot ask the API to materialize an
#: unbounded list. Windows longer than this still answer — the rollup reads are
#: range scans — but :func:`days_in_range` refuses to enumerate them.
MAX_WINDOW_DAYS: Final = 3_660


class Preset(StrEnum):
    """``docs/API.md`` §3.7's time presets, spelled as the query values."""

    TODAY = "today"
    LAST_7D = "7d"
    LAST_30D = "30d"
    YTD = "ytd"
    SINCE_T0 = "t0"


@dataclass(frozen=True, slots=True)
class Window:
    """A resolved half-open UTC window, plus the local days it covers.

    Args:
        start_ms: inclusive lower bound, UTC epoch milliseconds.
        end_ms: exclusive upper bound, UTC epoch milliseconds.
        first_day: receiver-local date of ``start_ms``.
        last_day: receiver-local date of the last instant before ``end_ms``.
        whole_history: True when the window provably covers every observation
            this receiver has ever made — the ``t0`` preset, or an explicit
            ``from`` at or before T0. Queries that have a cheap whole-history
            form (counting ``aircraft`` rows rather than distinct sighting
            aircraft) switch on this and on nothing else.
    """

    start_ms: int
    end_ms: int
    first_day: str
    last_day: str
    whole_history: bool = False

    @property
    def empty(self) -> bool:
        """True when the window contains no instant at all."""
        return self.end_ms <= self.start_ms

    @property
    def days(self) -> list[str]:
        """Every receiver-local day the window touches, in order."""
        return days_in_range(self.first_day, self.last_day)


def local_day(ts_ms: int, zone: ZoneInfo) -> str:
    """The receiver-local calendar date of ``ts_ms`` as ``YYYY-MM-DD`` (§10)."""
    return datetime.fromtimestamp(ts_ms / MS_PER_SECOND, tz=zone).date().isoformat()


def local_hour(ts_ms: int, zone: ZoneInfo) -> int:
    """The receiver-local hour of ``ts_ms``, ``0``-``23``.

    Read straight off the local wall clock rather than derived from an offset
    into the day, so the repeated hour of a fall-back day and the skipped hour
    of a spring-forward day both name the hour the clock actually showed.
    """
    return datetime.fromtimestamp(ts_ms / MS_PER_SECOND, tz=zone).hour


def day_start_ms(day: str, zone: ZoneInfo) -> int:
    """Epoch ms of local midnight opening ``day`` in ``zone`` (see module docs)."""
    midnight = datetime.combine(date.fromisoformat(day), time.min, tzinfo=zone)
    return int(midnight.timestamp() * MS_PER_SECOND)


def next_day(day: str) -> str:
    """The calendar date after ``day``."""
    return (date.fromisoformat(day) + timedelta(days=1)).isoformat()


def previous_day(day: str) -> str:
    """The calendar date before ``day``."""
    return (date.fromisoformat(day) - timedelta(days=1)).isoformat()


def shift_days(day: str, delta: int) -> str:
    """``day`` moved by ``delta`` calendar days."""
    return (date.fromisoformat(day) + timedelta(days=delta)).isoformat()


def day_bounds_ms(day: str, zone: ZoneInfo) -> tuple[int, int]:
    """The half-open ``[start, end)`` UTC bounds of one receiver-local day.

    The end is the *next* day's start, never ``start + 24h``: that is what
    makes the 23-hour and 25-hour local days of a DST transition roll up as
    themselves, and what makes consecutive days tile the timeline exactly.
    """
    return day_start_ms(day, zone), day_start_ms(next_day(day), zone)


def days_in_range(first_day: str, last_day: str) -> list[str]:
    """Every calendar date from ``first_day`` to ``last_day`` inclusive.

    Raises:
        ValueError: if the range spans more than :data:`MAX_WINDOW_DAYS` days.
            An explicit ``from``/``to`` pair is client input, and enumerating an
            unbounded span of it would be an unbounded allocation.
    """
    start, end = date.fromisoformat(first_day), date.fromisoformat(last_day)
    span = (end - start).days
    if span < 0:
        return []
    if span >= MAX_WINDOW_DAYS:
        raise ValueError(f"window spans {span + 1} days, more than the {MAX_WINDOW_DAYS} allowed")
    return [(start + timedelta(days=offset)).isoformat() for offset in range(span + 1)]


def resolve_window(
    preset: Preset,
    *,
    now_ms: int,
    zone: ZoneInfo,
    t0_ms: int | None = None,
) -> Window:
    """Turn one of §3.7's presets into a UTC window over receiver-local days.

    Every preset's lower bound is a local midnight and its upper bound is
    ``now_ms`` — exclusive, so "today" ends at this instant rather than at a
    future midnight and the window never claims data that does not exist yet.

    ``t0`` on an install that has never persisted an observation has no lower
    bound to anchor to. Rather than inventing one (the epoch, or today), the
    window is returned empty: ``docs/API.md`` §2.7's rule is that unknown is
    unknown, and every endpoint renders an empty window as empty results.
    """
    today = local_day(now_ms, zone)
    end_ms = now_ms

    if preset is Preset.SINCE_T0:
        if t0_ms is None:
            return Window(start_ms=end_ms, end_ms=end_ms, first_day=today, last_day=today)
        first = local_day(t0_ms, zone)
        return Window(
            start_ms=day_start_ms(first, zone),
            end_ms=end_ms,
            first_day=first,
            last_day=today,
            whole_history=True,
        )

    first = {
        Preset.TODAY: today,
        Preset.LAST_7D: shift_days(today, -(PRESET_7D_DAYS - 1)),
        Preset.LAST_30D: shift_days(today, -(PRESET_30D_DAYS - 1)),
        Preset.YTD: date.fromisoformat(today).replace(month=1, day=1).isoformat(),
    }[preset]
    start_ms = day_start_ms(first, zone)
    return Window(
        start_ms=start_ms,
        end_ms=end_ms,
        first_day=first,
        last_day=today,
        # A preset that reaches back past T0 covers the whole history just as
        # surely as `t0` does, and the cheap whole-history query forms are
        # correct for it too.
        whole_history=t0_ms is not None and start_ms <= t0_ms,
    )


def explicit_window(
    start_ms: int,
    end_ms: int,
    *,
    zone: ZoneInfo,
    t0_ms: int | None = None,
) -> Window:
    """A window from explicit UTC bounds, snapped to the days it touches.

    The bounds are used verbatim for instant-level queries; ``first_day`` and
    ``last_day`` name the receiver-local days they fall in, which is the range
    of rollup rows that can contribute. A partially covered day therefore
    appears in :attr:`Window.days` — the honest answer, since some of its
    sightings are inside the window — and callers reading whole-day rollups say
    so in their own documentation.

    A range longer than :data:`MAX_WINDOW_DAYS` is **clamped to its most recent
    ``MAX_WINDOW_DAYS`` days** rather than refused. Client input is the only
    place a window can be arbitrarily long, and clamping is both bounded and
    visible: every response carries the window it actually used, so a clamped
    request answers with the range it covered rather than with an error the
    client cannot act on or, worse, with a silent partial answer.
    """
    upper = max(start_ms, end_ms)
    last_day = local_day(max(start_ms, upper - 1), zone)
    first_day = local_day(start_ms, zone)
    floor_day = shift_days(last_day, -(MAX_WINDOW_DAYS - 1))
    if first_day < floor_day:
        first_day = floor_day
        start_ms = max(start_ms, day_start_ms(floor_day, zone))
    return Window(
        start_ms=start_ms,
        end_ms=max(start_ms, upper),
        first_day=first_day,
        last_day=last_day,
        whole_history=t0_ms is not None and start_ms <= t0_ms,
    )


__all__ = [
    "HOURS_PER_DAY",
    "MAX_WINDOW_DAYS",
    "PRESET_7D_DAYS",
    "PRESET_30D_DAYS",
    "Preset",
    "Window",
    "day_bounds_ms",
    "day_start_ms",
    "days_in_range",
    "explicit_window",
    "local_day",
    "local_hour",
    "next_day",
    "previous_day",
    "resolve_window",
    "shift_days",
]
