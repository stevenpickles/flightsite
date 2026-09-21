/**
 * Analytics-specific formatting: the echoed window's subtle date range,
 * compact counts for chart tooltips/axis labels, and unit-aware distance
 * conversion for chart values (as opposed to
 * `features/aircraft-detail/lib/format.ts`'s `formatDistance`, which returns
 * a display string — charts need the bare converted number for the axis
 * scale, and only format it to a string in the tooltip).
 */

import type { AnalyticsWindow } from "@/lib/api/analytics";
import type { UnitSystem } from "@/lib/api/config";

const NM_PER_KM = 1 / 1.852;

/** `"nm"` or `"km"` — the axis/tooltip suffix for a unit-aware distance. */
export function distanceUnitLabel(units: UnitSystem): "nm" | "km" {
  return units === "metric" ? "km" : "nm";
}

/** Converts a canonical nautical-mile distance to the display unit's bare
 * number (no suffix), rounded to one decimal — the numeric value a chart
 * plots, not the string a label shows. */
export function convertDistance(distanceNm: number, units: UnitSystem): number {
  const value = units === "metric" ? distanceNm / NM_PER_KM : distanceNm;
  return Math.round(value * 10) / 10;
}

/** `"1.2K"`, `"48"`, `"3.4M"` — a compact count for chart axes and dense
 * tooltips, where `formatMessageCount`'s full `12,345` would crowd the
 * label. */
export function formatCompactNumber(value: number): string {
  return new Intl.NumberFormat(undefined, { notation: "compact" }).format(
    value,
  );
}

/** Parses a `YYYY-MM-DD` receiver-local calendar date (`AnalyticsWindow`'s
 * `first_day`/`last_day`) as that day's UTC midnight, so formatting it never
 * shifts a day backward in a browser west of UTC — the string already *is*
 * the receiver-local date; there is nothing left to convert. */
function parseCalendarDay(day: string): Date {
  return new Date(`${day}T00:00:00Z`);
}

function formatCalendarDay(day: string): string {
  const date = parseCalendarDay(day);
  if (Number.isNaN(date.getTime())) {
    return day;
  }
  return new Intl.DateTimeFormat(undefined, {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

/** `"Aug 25 – Aug 31, 2026 · America/Los_Angeles"` (or a single date when
 * the window is one day) — the subtle window caption every analytics card
 * shows beneath its title, so a chart is never read against the wrong
 * range. */
export function formatWindowLabel(window: AnalyticsWindow): string {
  const range =
    window.first_day === window.last_day
      ? formatCalendarDay(window.first_day)
      : `${formatCalendarDay(window.first_day)} – ${formatCalendarDay(window.last_day)}`;
  return `${range} · ${window.timezone}`;
}

/** `"military_transport"` -> `"Military transport"` — a plain-language
 * fallback for the short mission-category slugs the analytics aircraft rows
 * carry, when no richer classification lookup applies. */
export function humanizeSlug(slug: string): string {
  const spaced = slug.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

/** Cuts a long secondary axis label (a type's "Boeing 737-800 Next Gen…")
 * to `max` characters with an ellipsis, so a horizontal bar chart keeps
 * its bars; the tooltip carries the full text. */
export function truncateLabel(text: string, max: number): string {
  if (text.length <= max) {
    return text;
  }
  return `${text.slice(0, Math.max(0, max - 1)).trimEnd()}…`;
}

const HTML_ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

/** Metadata strings (registrations, operator names, model descriptions)
 * are data from upstream sources, never markup — so anything that lands in
 * an ECharts HTML tooltip goes through here first. */
export function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (char) => HTML_ESCAPES[char] ?? char);
}

/** Builds an ECharts HTML tooltip body from plain-text lines: the first
 * kept line in bold, one line per entry, every line escaped, and `null`/
 * empty entries dropped — so a card lists what it *might* know about a row
 * and only the parts it actually knows are shown. */
export function tooltipLines(lines: ReadonlyArray<string | null>): string {
  const kept = lines.filter(
    (line): line is string => line !== null && line.length > 0,
  );
  if (kept.length === 0) {
    return "";
  }
  const [head, ...rest] = kept.map(escapeHtml);
  return [`<strong>${head}</strong>`, ...rest].join("<br/>");
}

/** `"1 sighting"` / `"12 sightings"` — the count line of a ranking tooltip. */
export function formatSightings(count: number): string {
  return `${formatCompactNumber(count)} ${count === 1 ? "sighting" : "sightings"}`;
}

/** The most recent of several TanStack Query `dataUpdatedAt` epoch-ms
 * values, or `undefined` when none has ever succeeded (every one is `0`) —
 * the "Data as of" freshness caption (R3-06) reads this rather than any
 * single card's timestamp, since the page shares queries across cards and a
 * user reads freshness for the page, not per card. */
export function latestDataUpdatedAt(
  timestamps: readonly number[],
): number | undefined {
  const present = timestamps.filter((value) => value > 0);
  return present.length === 0 ? undefined : Math.max(...present);
}
