import { describe, expect, it } from "vitest";

import {
  hourAxisLabel,
  hourClockLabel,
  LINE_SYMBOL_POINT_LIMIT,
  lineSymbols,
  singleDayOf,
} from "@/features/analytics/lib/series";
import type { AnalyticsHourlyRow, AnalyticsWindow } from "@/lib/api/analytics";

function analyticsWindow(first: string, last: string): AnalyticsWindow {
  return {
    preset: "today",
    from: `${first}T04:00:00.000Z`,
    to: `${last}T23:00:00.000Z`,
    first_day: first,
    last_day: last,
    timezone: "America/New_York",
  };
}

function hour(value: number): AnalyticsHourlyRow {
  return {
    t: "2026-10-05T04:00:00.000Z",
    hour: value,
    sightings: 0,
    unique_aircraft: 0,
    messages: null,
    positions: null,
    max_range_nm: null,
  };
}

describe("lineSymbols", () => {
  it("shows markers on a sparse line, so one point is never an empty plot", () => {
    expect(lineSymbols(1).showSymbol).toBe(true);
    expect(lineSymbols(24).showSymbol).toBe(true);
    expect(lineSymbols(LINE_SYMBOL_POINT_LIMIT).showSymbol).toBe(true);
  });

  it("hides them on a dense line", () => {
    expect(lineSymbols(LINE_SYMBOL_POINT_LIMIT + 1).showSymbol).toBe(false);
    expect(lineSymbols(365).showSymbol).toBe(false);
  });
});

describe("singleDayOf", () => {
  it("names the day of a one-day window", () => {
    expect(singleDayOf(analyticsWindow("2026-10-05", "2026-10-05"))).toBe(
      "2026-10-05",
    );
  });

  it("is undefined for a multi-day window, and before any window is known", () => {
    expect(
      singleDayOf(analyticsWindow("2026-09-29", "2026-10-05")),
    ).toBeUndefined();
    expect(singleDayOf(undefined)).toBeUndefined();
  });
});

describe("hour labels", () => {
  it("pads the axis label and writes the clock label", () => {
    expect(hourAxisLabel(hour(0))).toBe("00");
    expect(hourAxisLabel(hour(9))).toBe("09");
    expect(hourAxisLabel(hour(23))).toBe("23");
    expect(hourClockLabel(hour(9))).toBe("09:00");
  });
});
