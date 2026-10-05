/**
 * Shared decisions for the time-series cards (slice 097).
 *
 * Two things went wrong together on a one-day window. The day-granular
 * series had exactly one point, and every line was drawn with its point
 * markers hidden — so a one-point line drew nothing at all until a hover
 * revealed the value. The fix has two halves, both here:
 *
 * - a single-day window is drawn **hour by hour** instead
 *   ({@link singleDayOf} says when, the hourly helpers label it), and
 * - a line shows its markers whenever it has few enough points for them to
 *   be legible ({@link lineSymbols}), so a sparse series — the first hour of
 *   a day, a week with one computed day — is never an empty plot.
 */
import type { AnalyticsHourlyRow, AnalyticsWindow } from "@/lib/api/analytics";

/** At or below this many points a line draws its markers: a month of days
 * or a day of hours reads fine with dots; a year of days would be a smear. */
export const LINE_SYMBOL_POINT_LIMIT = 31;

/** The marker options for a line of `pointCount` points. */
export function lineSymbols(pointCount: number): {
  showSymbol: boolean;
  symbolSize: number;
} {
  return {
    showSymbol: pointCount <= LINE_SYMBOL_POINT_LIMIT,
    symbolSize: 6,
  };
}

/** The receiver-local day a window covers when it covers exactly one, else
 * `undefined` — the cue to draw hours rather than days. */
export function singleDayOf(
  window: AnalyticsWindow | undefined,
): string | undefined {
  return window !== undefined && window.first_day === window.last_day
    ? window.last_day
    : undefined;
}

/** `"09"` — the category-axis label of one hourly bucket. */
export function hourAxisLabel(row: AnalyticsHourlyRow): string {
  return String(row.hour).padStart(2, "0");
}

/** `"09:00"` — one hourly bucket in a tooltip or a summary sentence. */
export function hourClockLabel(row: AnalyticsHourlyRow): string {
  return `${hourAxisLabel(row)}:00`;
}
