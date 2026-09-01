/**
 * Formatting for the Today panel's stat tiles (roadmap slice 036).
 *
 * Distance/count formatting is deliberately duplicated from
 * `features/receiver/lib/format.ts` rather than imported — the same
 * self-contained-feature call that file's own doc comment makes relative to
 * `features/aircraft-detail/lib/format.ts`. Storage and the wire format are
 * always nm (`CLAUDE.md`); `formatDistance` converts to km only for display
 * when the receiver's `units` preference (`docs/API.md` §3.2) is `"metric"`.
 */
import type { UnitSystem } from "@/lib/api/config";

const NM_PER_KM = 1 / 1.852;

function round(value: number, decimals = 0): number {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

function localeNumber(value: number, decimals = 0): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatCount(count: number): string {
  return localeNumber(count);
}

export function formatDistance(
  distanceNm: number | null,
  units: UnitSystem,
): string | null {
  if (distanceNm === null) {
    return null;
  }
  return units === "metric"
    ? `${localeNumber(round(distanceNm / NM_PER_KM, 1), 1)} km`
    : `${localeNumber(round(distanceNm, 1), 1)} nm`;
}

/** `"14:00–15:00"` for `hour === 14` — the receiver-local clock hour
 * `busiest_hour` names, spelled as the hour-long window it actually covers
 * rather than a bare number a viewer would have to interpret. `null` (no
 * traffic yet today, or the day has not accumulated an hourly sample) reads
 * as `"No data yet"` rather than a blank tile. */
export function formatHourRange(hour: number | null): string {
  if (hour === null) {
    return "No data yet";
  }
  const pad = (value: number) => String(value).padStart(2, "0");
  const next = (hour + 1) % 24;
  return `${pad(hour)}:00–${pad(next)}:00`;
}
