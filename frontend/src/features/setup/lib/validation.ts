/**
 * Client-side field validation for the wizard's manually-entered values.
 * Bounds mirror the backend's Pydantic model
 * (`backend/src/flightsite/config/models.py`) exactly, so a value the
 * wizard accepts is one `PUT /api/internal/config` will also accept — this
 * only exists to give inline feedback before that round trip, not to be a
 * second source of truth for what's valid.
 */

export const LATITUDE_MIN = -90;
export const LATITUDE_MAX = 90;
export const LONGITUDE_MIN = -180;
export const LONGITUDE_MAX = 180;
export const SITE_NAME_MAX_LENGTH = 120;
export const ANTENNA_HEIGHT_MIN_FT = -1400;
export const ANTENNA_HEIGHT_MAX_FT = 30000;
export const PORT_MIN = 1;
export const PORT_MAX = 65535;
export const POLL_INTERVAL_MAX_S = 60;

/** Parses a trimmed numeric string; `null` for blank or non-numeric input
 * (never `NaN`, so callers can use a plain `=== null` check). */
export function parseNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return null;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

export function validateSiteName(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return "Site name is required.";
  }
  if (trimmed.length > SITE_NAME_MAX_LENGTH) {
    return `Site name must be ${SITE_NAME_MAX_LENGTH} characters or fewer.`;
  }
  return null;
}

export function validateLatitude(raw: string): string | null {
  const value = parseNumber(raw);
  if (value === null || value < LATITUDE_MIN || value > LATITUDE_MAX) {
    return `Enter a latitude between ${LATITUDE_MIN} and ${LATITUDE_MAX}.`;
  }
  return null;
}

export function validateLongitude(raw: string): string | null {
  const value = parseNumber(raw);
  if (value === null || value < LONGITUDE_MIN || value > LONGITUDE_MAX) {
    return `Enter a longitude between ${LONGITUDE_MIN} and ${LONGITUDE_MAX}.`;
  }
  return null;
}

/** Antenna height is optional — blank is valid. */
export function validateAntennaHeight(raw: string): string | null {
  if (raw.trim().length === 0) {
    return null;
  }
  const value = parseNumber(raw);
  if (
    value === null ||
    value < ANTENNA_HEIGHT_MIN_FT ||
    value > ANTENNA_HEIGHT_MAX_FT
  ) {
    return `Enter a height between ${ANTENNA_HEIGHT_MIN_FT} and ${ANTENNA_HEIGHT_MAX_FT} ft, or leave blank.`;
  }
  return null;
}

export function validateHost(raw: string): string | null {
  return raw.trim().length === 0 ? "Host is required." : null;
}

export function validatePort(raw: string): string | null {
  const value = parseNumber(raw);
  if (
    value === null ||
    !Number.isInteger(value) ||
    value < PORT_MIN ||
    value > PORT_MAX
  ) {
    return `Enter a port between ${PORT_MIN} and ${PORT_MAX}.`;
  }
  return null;
}

export function validatePath(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return "Path is required.";
  }
  if (!trimmed.startsWith("/")) {
    return "Path must start with '/' (e.g. '/data/aircraft.json').";
  }
  return null;
}

export function validatePollInterval(raw: string): string | null {
  const value = parseNumber(raw);
  if (value === null || value <= 0 || value > POLL_INTERVAL_MAX_S) {
    return `Enter a poll interval greater than 0 and at most ${POLL_INTERVAL_MAX_S} seconds.`;
  }
  return null;
}
