/**
 * Unit-aware, receiver-local formatting for the Receiver page (roadmap slice
 * 034). Deliberately self-contained rather than importing
 * `features/aircraft-detail/lib/format.ts` — the same "duplicated rather than
 * imported" call `lib/api/sightings.ts` makes relative to `aircraft.ts`, so
 * this feature stays a self-contained read of a few small files.
 *
 * Storage and the wire format are always nm/ft/kt (`CLAUDE.md`); every
 * distance formatter here starts from nautical miles and converts only for
 * display when the receiver's `units` preference (`docs/API.md` §3.2) is
 * `"metric"`. `null` always means "not available" (§2.7) and is the caller's
 * job to render as a placeholder — these functions only format values that
 * exist.
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

/** Distance-axis value only (no unit suffix) — for chart axis ticks, where
 * the unit is named once in the axis title instead of on every tick. */
export function distanceAxisValue(
  distanceNm: number,
  units: UnitSystem,
): number {
  return units === "metric"
    ? round(distanceNm / NM_PER_KM, 1)
    : round(distanceNm, 1);
}

export function distanceUnitLabel(units: UnitSystem): string {
  return units === "metric" ? "km" : "nm";
}

export function formatCount(count: number | null): string {
  if (count === null) {
    return "—";
  }
  return localeNumber(count);
}

export function formatRatePerSec(value: number | null, unit: string): string {
  if (value === null) {
    return "—";
  }
  return `${localeNumber(round(value, 1), 1)} ${unit}/s`;
}

export function formatDb(value: number | null): string {
  if (value === null) {
    return "—";
  }
  return `${localeNumber(round(value, 1), 1)} dB`;
}

/** `"3d 4h"` / `"2h 15m"` / `"48s"` — coarse enough for a scorecard tile,
 * never more than two units. */
export function formatDurationCompact(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) {
    return "—";
  }
  const totalSeconds = Math.floor(seconds);
  const days = Math.floor(totalSeconds / 86400);
  const hours = Math.floor((totalSeconds % 86400) / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const secs = totalSeconds % 60;

  if (days > 0) {
    return hours > 0 ? `${days}d ${hours}h` : `${days}d`;
  }
  if (hours > 0) {
    return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  }
  if (minutes > 0) {
    return `${minutes}m`;
  }
  return `${secs}s`;
}

/** The receiver-local wall-clock time for an ISO instant — e.g. `"14:03"`.
 * Falls back to the bare ISO string if the timezone or instant is
 * unparseable rather than throwing mid-render. */
export function formatReceiverLocalTime(iso: string, timezone: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) {
    return iso;
  }
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: timezone,
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(when);
  } catch {
    return when.toISOString();
  }
}

/** The receiver-local calendar date and wall-clock time for an ISO instant —
 * e.g. `"2026-04-02 18:11"` — for chart tooltips and axis labels spanning
 * more than a day. Falls back to the bare ISO string on any error. */
export function formatReceiverLocalDateTime(
  iso: string,
  timezone: string,
): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) {
    return iso;
  }
  try {
    const parts = new Intl.DateTimeFormat(undefined, {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).formatToParts(when);
    const get = (type: Intl.DateTimeFormatPartTypes): string =>
      parts.find((part) => part.type === type)?.value ?? "";
    return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")}`;
  } catch {
    return when.toISOString();
  }
}

/** The receiver-local calendar date for an ISO instant — e.g. `"2026-04-02"`
 * — for daily-bucketed chart axis labels. Falls back to the bare ISO string
 * on any error. */
export function formatReceiverLocalDate(iso: string, timezone: string): string {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) {
    return iso;
  }
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: timezone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(when);
  } catch {
    return when.toISOString();
  }
}

const CARDINALS = [
  "N",
  "NNE",
  "NE",
  "ENE",
  "E",
  "ESE",
  "SE",
  "SSE",
  "S",
  "SSW",
  "SW",
  "WSW",
  "W",
  "WNW",
  "NW",
  "NNW",
] as const;

/** 16-point compass cardinal for a 0-360 degree bearing. */
export function cardinalFromDegrees(degrees: number): string {
  const normalized = ((degrees % 360) + 360) % 360;
  const index = Math.round(normalized / 22.5) % 16;
  return CARDINALS[index] as string;
}
