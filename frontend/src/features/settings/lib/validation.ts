/**
 * Client-side field validation for the Settings-only fields — those the
 * setup wizard does not manage. Bounds mirror the backend's Pydantic model
 * (`backend/src/flightsite/config/models.py`) exactly, same rationale as
 * `@/features/setup/lib/validation`: a value this module accepts is one
 * `PUT /api/internal/config` will also accept. Fields the wizard already
 * validates (site name, lat/lon, antenna height, decoder host/port/path/poll
 * interval) are reused directly from that module rather than duplicated.
 */
import { parseNumber } from "@/features/setup/lib/validation";

export const DISPLAY_RADIUS_MAX_NM = 10000;
export const ALERT_RADIUS_MAX_NM = 10000;
export const RETENTION_MIN_DAYS = 7;
export const RETENTION_MAX_DAYS = 30;
export const MAX_RANGE_RINGS = 10;

export function validateDisplayRadius(raw: string): string | null {
  const value = parseNumber(raw);
  if (value === null || value <= 0 || value > DISPLAY_RADIUS_MAX_NM) {
    return `Enter a display radius greater than 0 and at most ${DISPLAY_RADIUS_MAX_NM} nm.`;
  }
  return null;
}

/** Alert radius is optional — blank means "unlimited" (`alert_radius_nm:
 * null`, SPEC §66). */
export function validateAlertRadius(raw: string): string | null {
  if (raw.trim().length === 0) {
    return null;
  }
  const value = parseNumber(raw);
  if (value === null || value <= 0 || value > ALERT_RADIUS_MAX_NM) {
    return `Enter an alert radius greater than 0 and at most ${ALERT_RADIUS_MAX_NM} nm, or leave blank for unlimited.`;
  }
  return null;
}

export function validateHighResMetricDays(raw: string): string | null {
  const value = parseNumber(raw);
  if (
    value === null ||
    !Number.isInteger(value) ||
    value < RETENTION_MIN_DAYS ||
    value > RETENTION_MAX_DAYS
  ) {
    return `Enter a whole number of days between ${RETENTION_MIN_DAYS} and ${RETENTION_MAX_DAYS}.`;
  }
  return null;
}

export function validateTimezone(raw: string): string | null {
  return raw.trim().length === 0 ? "Timezone is required." : null;
}

/** Parses a comma-separated list of range-ring radii into numbers,
 * discarding blank segments (so a trailing comma doesn't produce a bogus
 * `NaN` entry). */
export function parseRangeRingRadii(raw: string): number[] {
  return raw
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part.length > 0)
    .map(Number);
}

/** Mirrors `MapSettings.range_ring_radii_nm`'s validator: at most 10
 * entries, all positive, all unique. Unlike the backend, this does not sort
 * the result — that happens server-side and is reflected back on save. */
export function validateRangeRingRadii(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return "Enter at least one ring radius (nm), comma-separated.";
  }
  const values = parseRangeRingRadii(raw);
  if (values.some((value) => !Number.isFinite(value))) {
    return 'Enter a comma-separated list of numbers, e.g. "50, 100, 150".';
  }
  if (values.length > MAX_RANGE_RINGS) {
    return `At most ${MAX_RANGE_RINGS} range rings may be configured.`;
  }
  if (values.some((value) => value <= 0)) {
    return "Range ring radii must be greater than 0 nm.";
  }
  if (new Set(values).size !== values.length) {
    return "Range ring radii must be unique.";
  }
  return null;
}
