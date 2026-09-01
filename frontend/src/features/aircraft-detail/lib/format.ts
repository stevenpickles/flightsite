/**
 * Unit-aware formatting for the aircraft detail panel (roadmap slice 016).
 *
 * Storage and the wire format are always nm/ft/kt (`CLAUDE.md`), so every
 * function here starts from those canonical units and converts only for
 * display when the receiver's `units` preference (`docs/API.md` §3.2) is
 * `"metric"`. `null` always means "the decoder hasn't reported this yet"
 * (§2.7) and is the caller's job to render as `Unknown` — these functions
 * only format values that exist.
 */

import type { UnitSystem } from "@/lib/api/config";

const FT_PER_M = 3.28084;
const KT_PER_KMH = 1 / 1.852;
const NM_PER_KM = 1 / 1.852;

/** US/ICAO transition altitude: above this, altitude is conventionally
 * expressed as a flight level rather than raw feet. FlightSite has no QNH
 * feed, so this is a display convention, not a claim about indicated vs.
 * pressure altitude. */
const FLIGHT_LEVEL_THRESHOLD_FT = 18000;

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

/** `"FL350"` for `35000`. */
export function formatFlightLevel(altitudeFt: number): string {
  return `FL${Math.round(altitudeFt / 100)
    .toString()
    .padStart(3, "0")}`;
}

/** Altitude, flight-level-prefixed above {@link FLIGHT_LEVEL_THRESHOLD_FT}
 * (a universal feet-based aviation convention independent of display
 * units) followed by the localized value — e.g. `"FL350 · 35,000 ft"`
 * (aviation) or `"FL350 · 10,668 m"` (metric). */
export function formatAltitude(
  altitudeFt: number | null,
  units: UnitSystem,
): string | null {
  if (altitudeFt === null) {
    return null;
  }
  const value =
    units === "metric"
      ? `${localeNumber(round(altitudeFt / FT_PER_M))} m`
      : `${localeNumber(round(altitudeFt))} ft`;
  return altitudeFt >= FLIGHT_LEVEL_THRESHOLD_FT
    ? `${formatFlightLevel(altitudeFt)} · ${value}`
    : value;
}

export function formatSpeed(
  groundSpeedKt: number | null,
  units: UnitSystem,
): string | null {
  if (groundSpeedKt === null) {
    return null;
  }
  return units === "metric"
    ? `${localeNumber(round(groundSpeedKt / KT_PER_KMH))} km/h`
    : `${localeNumber(round(groundSpeedKt))} kt`;
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

export type VerticalTrend = "climb" | "descend" | "level";

/** Below this, a vertical rate reads as level flight rather than a genuine
 * climb/descend — dump1090-family decoders report small non-zero noise on
 * aircraft holding altitude. */
const VERTICAL_RATE_NOISE_FLOOR_FPM = 50;

export function verticalTrend(
  verticalRateFpm: number | null,
): VerticalTrend | null {
  if (verticalRateFpm === null) {
    return null;
  }
  if (verticalRateFpm > VERTICAL_RATE_NOISE_FLOOR_FPM) {
    return "climb";
  }
  if (verticalRateFpm < -VERTICAL_RATE_NOISE_FLOOR_FPM) {
    return "descend";
  }
  return "level";
}

export function formatVerticalRate(
  verticalRateFpm: number | null,
  units: UnitSystem,
): string | null {
  if (verticalRateFpm === null) {
    return null;
  }
  if (units === "metric") {
    const metersPerSecond = (verticalRateFpm * 0.3048) / 60;
    const sign = metersPerSecond > 0 ? "+" : "";
    return `${sign}${localeNumber(round(metersPerSecond, 1), 1)} m/s`;
  }
  const sign = verticalRateFpm > 0 ? "+" : "";
  return `${sign}${localeNumber(round(verticalRateFpm))} fpm`;
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

/** 16-point compass cardinal for a 0–360° heading/bearing. */
export function cardinalFromDegrees(degrees: number): string {
  const normalized = ((degrees % 360) + 360) % 360;
  const index = Math.round(normalized / 22.5) % 16;
  return CARDINALS[index] as string;
}

/** `"173° · S"` — degrees plus 16-point cardinal, shared by track and
 * bearing display. */
export function formatDegreesWithCardinal(
  degrees: number | null,
): string | null {
  if (degrees === null) {
    return null;
  }
  return `${localeNumber(round(degrees))}° · ${cardinalFromDegrees(degrees)}`;
}

export function formatRssi(rssiDb: number | null): string | null {
  if (rssiDb === null) {
    return null;
  }
  return `${localeNumber(round(rssiDb, 1), 1)} dBFS`;
}

export function formatMessageCount(messageCount: number | null): string | null {
  if (messageCount === null) {
    return null;
  }
  return localeNumber(messageCount);
}

/** `null` renders `Unknown`, otherwise "Yes"/"No" (never a guess — the
 * decoder either reported on-ground state or it did not, §2.7). */
export function formatOnGround(onGround: boolean | null): string | null {
  if (onGround === null) {
    return null;
  }
  return onGround ? "Yes" : "No";
}

const EMERGENCY_SQUAWKS = new Set(["7500", "7600", "7700"]);

export const EMERGENCY_SQUAWK_LABELS: Record<string, string> = {
  "7500": "Hijack",
  "7600": "Radio failure",
  "7700": "General emergency",
};

/** True when a squawk code is one of the three universally recognized
 * emergency codes (SPEC §47), independent of whether the decoder also
 * populated the separate `emergency` field. */
export function isEmergencySquawk(squawk: string | null): squawk is string {
  return squawk !== null && EMERGENCY_SQUAWKS.has(squawk);
}

/** Milliseconds since `lastSeenIso`, clamped to zero so a few milliseconds
 * of clock skew between the receiver and the browser never reads as a
 * negative age. */
export function msSinceLastSeen(lastSeenIso: string, now: number): number {
  const then = Date.parse(lastSeenIso);
  if (Number.isNaN(then)) {
    return 0;
  }
  return Math.max(0, now - then);
}

/** Coarse, human relative age — `"just now"`, `"12s ago"`, `"4m ago"`,
 * `"2h 5m ago"`, `"3d ago"`. Ticks in whole seconds, which is all the
 * live-update cadence (§ store docs, ~1 Hz) can usefully resolve. */
export function formatRelativeAge(ms: number): string {
  if (ms < 1000) {
    return "just now";
  }
  const totalSeconds = Math.floor(ms / 1000);
  if (totalSeconds < 60) {
    return `${totalSeconds}s ago`;
  }
  const totalMinutes = Math.floor(totalSeconds / 60);
  if (totalMinutes < 60) {
    return `${totalMinutes}m ago`;
  }
  const totalHours = Math.floor(totalMinutes / 60);
  if (totalHours < 24) {
    const remainingMinutes = totalMinutes % 60;
    return remainingMinutes > 0
      ? `${totalHours}h ${remainingMinutes}m ago`
      : `${totalHours}h ago`;
  }
  const totalDays = Math.floor(totalHours / 24);
  return `${totalDays}d ago`;
}

/** The receiver-local wall-clock time for an ISO instant, formatted with
 * the configured IANA timezone (§3.2 `timezone`) — e.g. `"14:03:22"`. Falls
 * back to the bare ISO string if the timezone or instant is unparseable
 * rather than throwing mid-render. */
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
      second: "2-digit",
      hour12: false,
    }).format(when);
  } catch {
    return when.toISOString();
  }
}

/** The receiver-local calendar date and wall-clock time for an ISO instant —
 * e.g. `"2026-04-02 18:11"` — for contexts where the instant may be months
 * or years old (the Aircraft page and the detail page's lifetime records,
 * roadmap slice 029) and a bare time-of-day would be ambiguous. Falls back
 * to the ISO string the same way {@link formatReceiverLocalTime} does. */
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

/** `"3m 12s"` for a track-duration span; used by the current-track mini
 * stats (accumulated points since selection, not a stored duration). */
export function formatDurationShort(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) {
    return `${seconds}s`;
  }
  return `${minutes}m ${seconds}s`;
}
