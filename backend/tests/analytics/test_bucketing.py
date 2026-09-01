"""Day bucketing and the §3.7 presets, across DST and an odd-offset zone.

``docs/DATA_MODEL.md`` §10 requires day boundaries to be receiver-local and
DST-correct, and slice 031's acceptance criterion names a DST fixture. Two
zones are exercised throughout:

* ``America/New_York`` — spring forward (a 23-hour local day) and fall back (a
  25-hour local day). The 2026 transitions are 8 March and 1 November.
* ``Asia/Kolkata`` — a permanent +05:30 offset and no DST at all, which is the
  case that a "divide the epoch by 86,400,000" bucketing gets wrong on *every*
  day rather than twice a year.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from flightsite.analytics.bucketing import (
    MAX_WINDOW_DAYS,
    PRESET_7D_DAYS,
    PRESET_30D_DAYS,
    Preset,
    day_bounds_ms,
    day_start_ms,
    days_in_range,
    explicit_window,
    local_day,
    local_hour,
    resolve_window,
    shift_days,
)
from flightsite.db.clock import from_epoch_ms, to_epoch_ms

from .conftest import KOLKATA, MS_PER_HOUR, NEW_YORK

#: 2026's US transitions: clocks go forward on 8 March, back on 1 November.
SPRING_FORWARD = "2026-03-08"
FALL_BACK = "2026-11-01"

HOURS = MS_PER_HOUR


def _ms(text: str) -> int:
    return to_epoch_ms(datetime.fromisoformat(text).replace(tzinfo=UTC))


# ------------------------------------------------------------- day length


@pytest.mark.parametrize(
    ("zone_name", "day", "expected_hours"),
    [
        (NEW_YORK, SPRING_FORWARD, 23),
        (NEW_YORK, FALL_BACK, 25),
        (NEW_YORK, "2026-06-02", 24),
        (KOLKATA, SPRING_FORWARD, 24),
        (KOLKATA, FALL_BACK, 24),
    ],
)
def test_a_local_day_is_as_long_as_the_zone_actually_made_it(
    zone_name: str, day: str, expected_hours: int
) -> None:
    zone = ZoneInfo(zone_name)

    start_ms, end_ms = day_bounds_ms(day, zone)

    assert (end_ms - start_ms) == expected_hours * HOURS


@pytest.mark.parametrize("zone_name", [NEW_YORK, KOLKATA])
def test_consecutive_days_tile_the_timeline_without_gap_or_overlap(zone_name: str) -> None:
    """Every day's end is the next day's start, across both transitions."""
    zone = ZoneInfo(zone_name)
    runs = [days_in_range("2026-03-06", "2026-03-11"), days_in_range("2026-10-30", "2026-11-03")]

    for days in runs:
        bounds = [day_bounds_ms(day, zone) for day in days]
        for (_, end_ms), day in zip(bounds, days[1:], strict=False):
            assert end_ms == day_start_ms(day, zone)


def test_kolkata_day_boundaries_land_at_the_half_hour_offset() -> None:
    """+05:30 means local midnight is 18:30 UTC the day before, all year."""
    zone = ZoneInfo(KOLKATA)

    for day in ("2026-01-15", SPRING_FORWARD, "2026-06-02", FALL_BACK):
        opened = from_epoch_ms(day_start_ms(day, zone))
        assert (opened.hour, opened.minute) == (18, 30), day


# --------------------------------------------------------- bucketing by day


@pytest.mark.parametrize("zone_name", [NEW_YORK, KOLKATA])
def test_every_instant_of_a_day_buckets_into_that_day(zone_name: str) -> None:
    """Sampled minute by minute across both transition days and a normal one."""
    zone = ZoneInfo(zone_name)

    for day in (SPRING_FORWARD, FALL_BACK, "2026-06-02"):
        start_ms, end_ms = day_bounds_ms(day, zone)
        for offset in range(0, end_ms - start_ms, 60_000):
            assert local_day(start_ms + offset, zone) == day
        assert local_day(start_ms - 1, zone) != day
        assert local_day(end_ms, zone) != day


def test_the_skipped_hour_of_a_spring_forward_day_has_no_instants() -> None:
    """02:00-02:59 local never happens on 8 March in New York."""
    zone = ZoneInfo(NEW_YORK)
    start_ms, end_ms = day_bounds_ms(SPRING_FORWARD, zone)

    hours = {local_hour(ms, zone) for ms in range(start_ms, end_ms, 60_000)}

    assert 2 not in hours
    assert hours == set(range(24)) - {2}


def test_the_repeated_hour_of_a_fall_back_day_appears_twice_in_the_same_bucket() -> None:
    """01:00-01:59 local happens twice on 1 November; both are hour 1 of that day."""
    zone = ZoneInfo(NEW_YORK)
    start_ms, end_ms = day_bounds_ms(FALL_BACK, zone)

    minutes_in_hour_one = [
        ms for ms in range(start_ms, end_ms, 60_000) if local_hour(ms, zone) == 1
    ]

    assert len(minutes_in_hour_one) == 120
    assert all(local_day(ms, zone) == FALL_BACK for ms in minutes_in_hour_one)


# ------------------------------------------------------------------ presets


@pytest.mark.parametrize("zone_name", [NEW_YORK, KOLKATA])
def test_today_starts_at_local_midnight_not_utc_midnight(zone_name: str) -> None:
    zone = ZoneInfo(zone_name)
    now_ms = _ms("2026-06-02T14:00:00")

    window = resolve_window(Preset.TODAY, now_ms=now_ms, zone=zone)

    assert window.start_ms == day_start_ms(local_day(now_ms, zone), zone)
    assert window.end_ms == now_ms
    assert window.days == [local_day(now_ms, zone)]


@pytest.mark.parametrize(
    ("preset", "expected_days"),
    [(Preset.LAST_7D, PRESET_7D_DAYS), (Preset.LAST_30D, PRESET_30D_DAYS)],
)
def test_the_rolling_presets_count_calendar_days_including_today(
    preset: Preset, expected_days: int
) -> None:
    zone = ZoneInfo(NEW_YORK)
    now_ms = _ms("2026-11-03T18:00:00")

    window = resolve_window(preset, now_ms=now_ms, zone=zone)

    assert len(window.days) == expected_days
    assert window.last_day == local_day(now_ms, zone)
    assert window.first_day == shift_days(window.last_day, -(expected_days - 1))


def test_a_rolling_preset_spanning_fall_back_is_an_hour_longer_than_nominal() -> None:
    """The calendar range is fixed at seven days; the elapsed time is not."""
    zone = ZoneInfo(NEW_YORK)
    now_ms = _ms("2026-11-03T04:00:00")

    window = resolve_window(Preset.LAST_7D, now_ms=now_ms, zone=zone)

    nominal = now_ms - 6 * 24 * HOURS - (now_ms - day_start_ms(local_day(now_ms, zone), zone))
    assert window.start_ms == nominal - HOURS
    assert len(window.days) == PRESET_7D_DAYS


def test_ytd_starts_at_local_new_year() -> None:
    zone = ZoneInfo(NEW_YORK)
    now_ms = _ms("2026-06-02T14:00:00")

    window = resolve_window(Preset.YTD, now_ms=now_ms, zone=zone)

    assert window.first_day == "2026-01-01"
    assert window.start_ms == day_start_ms("2026-01-01", zone)


def test_since_t0_starts_at_the_local_day_t0_fell_in() -> None:
    zone = ZoneInfo(NEW_YORK)
    t0_ms = _ms("2026-01-17T03:20:00")
    now_ms = _ms("2026-06-02T14:00:00")

    window = resolve_window(Preset.SINCE_T0, now_ms=now_ms, zone=zone, t0_ms=t0_ms)

    assert window.first_day == local_day(t0_ms, zone)
    assert window.whole_history is True


def test_since_t0_without_a_t0_is_an_empty_window_rather_than_an_invented_one() -> None:
    """A fresh install has no T0; §2.7 says unknown, not a guess at the epoch."""
    zone = ZoneInfo(NEW_YORK)
    now_ms = _ms("2026-06-02T14:00:00")

    window = resolve_window(Preset.SINCE_T0, now_ms=now_ms, zone=zone, t0_ms=None)

    assert window.empty is True
    assert window.whole_history is False


def test_a_preset_reaching_back_past_t0_also_covers_the_whole_history() -> None:
    zone = ZoneInfo(NEW_YORK)
    now_ms = _ms("2026-06-02T14:00:00")
    t0_ms = now_ms - 3 * 24 * HOURS

    assert resolve_window(Preset.LAST_30D, now_ms=now_ms, zone=zone, t0_ms=t0_ms).whole_history
    assert not resolve_window(Preset.TODAY, now_ms=now_ms, zone=zone, t0_ms=t0_ms).whole_history


# --------------------------------------------------------- explicit windows


def test_explicit_bounds_are_used_verbatim_and_snapped_to_their_local_days() -> None:
    zone = ZoneInfo(KOLKATA)
    start_ms = _ms("2026-06-02T20:00:00")
    end_ms = _ms("2026-06-04T02:00:00")

    window = explicit_window(start_ms, end_ms, zone=zone)

    assert (window.start_ms, window.end_ms) == (start_ms, end_ms)
    assert window.first_day == local_day(start_ms, zone)
    assert window.last_day == local_day(end_ms - 1, zone)


def test_an_absurdly_long_explicit_window_is_clamped_rather_than_enumerated() -> None:
    """Client input is the only unbounded source; the response says what it covered."""
    zone = ZoneInfo(NEW_YORK)
    end_ms = _ms("2026-06-02T14:00:00")
    start_ms = end_ms - 40 * 365 * 24 * HOURS

    window = explicit_window(start_ms, end_ms, zone=zone)

    assert len(window.days) == MAX_WINDOW_DAYS
    assert window.start_ms > start_ms
    assert window.last_day == local_day(end_ms - 1, zone)


def test_an_inverted_explicit_window_is_empty_rather_than_negative() -> None:
    zone = ZoneInfo(NEW_YORK)
    later = _ms("2026-06-02T14:00:00")

    window = explicit_window(later, later - 10 * HOURS, zone=zone)

    assert window.empty is True
    assert window.days == [local_day(later, zone)]


def test_days_in_range_refuses_a_span_it_cannot_bound() -> None:
    with pytest.raises(ValueError, match="more than"):
        days_in_range("1990-01-01", "2026-01-01")


def test_days_in_range_of_a_backwards_pair_is_empty() -> None:
    assert days_in_range("2026-06-02", "2026-06-01") == []


def test_day_arithmetic_crosses_a_month_and_a_leap_year_boundary() -> None:
    assert shift_days("2028-02-28", 1) == "2028-02-29"
    assert shift_days("2026-12-31", 1) == "2027-01-01"
    assert shift_days("2027-01-01", -1) == "2026-12-31"


def test_a_local_day_is_the_calendar_date_a_person_would_read_off_the_wall() -> None:
    """The definition, checked directly rather than through the helpers."""
    zone = ZoneInfo(KOLKATA)
    instant = datetime(2026, 6, 2, 19, 0, tzinfo=UTC)

    assert local_day(to_epoch_ms(instant), zone) == instant.astimezone(zone).date().isoformat()
    assert local_day(to_epoch_ms(instant - timedelta(hours=1)), zone) == "2026-06-02"
