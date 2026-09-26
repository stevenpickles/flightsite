/**
 * Client-side field validation for the Settings-only fields — those the
 * setup wizard does not manage. Bounds mirror the backend's Pydantic model
 * (`backend/src/flightsite/config/models.py`) exactly, same rationale as
 * `@/features/setup/lib/validation`: a value this module accepts is one
 * `PUT /api/internal/config` will also accept. Fields the wizard already
 * validates (site name, lat/lon, antenna height, decoder host/port/path/poll
 * interval) are reused directly from that module rather than duplicated.
 */
import {
  parseNumber,
  PORT_MAX,
  PORT_MIN,
} from "@/features/setup/lib/validation";
import { feederKindFields } from "@/features/settings/lib/feederKinds";
import type {
  FeederEntryDraft,
  LocalPageDraft,
} from "@/features/settings/types";

export const DISPLAY_RADIUS_MAX_NM = 10000;
export const ALERT_RADIUS_MAX_NM = 10000;
export const RETENTION_MIN_DAYS = 7;
export const RETENTION_MAX_DAYS = 30;
export const MAX_RANGE_RINGS = 10;
export const ROUTE_TTL_MIN_DAYS = 1;
export const ROUTE_TTL_MAX_DAYS = 30;

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

/** The daily provider-lookup allowance (slice 070). Zero is a legitimate
 * value meaning "uncapped", not an empty field, so it is accepted rather
 * than treated as the absence of an answer. */
export function validateDailyLookupBudget(raw: string): string | null {
  const value = parseNumber(raw);
  if (value === null || !Number.isInteger(value) || value < 0) {
    return "Enter a whole number of lookups per day, or 0 for unlimited.";
  }
  return null;
}

/** How long a cached route stays usable. Mirrors the backend's 1–30 bound:
 * below a day the cache would never absorb a repeat flight, and beyond a
 * month a schedule change would outlive its own correction. */
export function validateRouteTtlDays(raw: string): string | null {
  const value = parseNumber(raw);
  if (
    value === null ||
    !Number.isInteger(value) ||
    value < ROUTE_TTL_MIN_DAYS ||
    value > ROUTE_TTL_MAX_DAYS
  ) {
    return `Enter a whole number of days between ${ROUTE_TTL_MIN_DAYS} and ${ROUTE_TTL_MAX_DAYS}.`;
  }
  return null;
}

/**
 * Feeders (roadmap slice 077, `docs/design/077-feeders-page.md`). Bounds and
 * shape rules mirror the design record's "Config" section and its `feeders:
 * poll_interval_s # 5–120` comment; the slug pattern, URL scheme check and
 * per-kind required-field rules below are this module's own reading of "shape
 * only" and "kind-dependent fields" — there is no backend model to check them
 * against yet (work packages A/B build it in parallel), so a real save is
 * still the final word and a rejection is always shown even when this
 * validator saw nothing wrong (see `fieldMessage`).
 */
export const FEEDERS_POLL_INTERVAL_MIN_S = 5;
export const FEEDERS_POLL_INTERVAL_MAX_S = 120;

export function validateFeedersPollInterval(raw: string): string | null {
  const value = parseNumber(raw);
  if (
    value === null ||
    !Number.isInteger(value) ||
    value < FEEDERS_POLL_INTERVAL_MIN_S ||
    value > FEEDERS_POLL_INTERVAL_MAX_S
  ) {
    return `Enter a whole number of seconds between ${FEEDERS_POLL_INTERVAL_MIN_S} and ${FEEDERS_POLL_INTERVAL_MAX_S}.`;
  }
  return null;
}

/** Blank means unset (`docker_socket: null`) — opt-in, off by default. A
 * non-blank value must at least look like the absolute path the helper text
 * asks for (`/var/run/docker.sock`). */
export function validateDockerSocketPath(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return null;
  }
  if (!trimmed.startsWith("/")) {
    return 'Enter an absolute path (e.g. "/var/run/docker.sock"), or leave blank to disable.';
  }
  return null;
}

const FEEDER_SLUG_PATTERN = /^[a-z][a-z0-9_-]*$/;

/** A feeder entry's `name` is a slug (it keys `secrets_set` and the wire
 * config), so it gets its own, stricter rule than a free-text label:
 * lowercase, starting with a letter, and only letters/digits/hyphen/
 * underscore afterward. */
export function validateFeederSlug(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return "Name is required.";
  }
  if (!FEEDER_SLUG_PATTERN.test(trimmed)) {
    return "Use lowercase letters, digits, hyphens or underscores, starting with a letter.";
  }
  return null;
}

export function validateFeederLabel(raw: string): string | null {
  return raw.trim().length === 0 ? "Label is required." : null;
}

/** `http(s)://…` only, and only when the caller says the field is required
 * for the row's kind — an unused field left blank is not an error. */
export function validateFeederUrl(
  raw: string,
  required: boolean,
): string | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return required ? "A URL is required for this kind." : null;
  }
  if (!/^https?:\/\//i.test(trimmed)) {
    return "Enter a URL starting with http:// or https://.";
  }
  try {
    new URL(trimmed);
  } catch {
    return "Enter a valid URL.";
  }
  return null;
}

export function validateFeederContainer(
  raw: string,
  required: boolean,
): string | null {
  return required && raw.trim().length === 0
    ? "Container name is required for this kind."
    : null;
}

export function validateFeederHost(
  raw: string,
  required: boolean,
): string | null {
  return required && raw.trim().length === 0
    ? "Host is required for this kind."
    : null;
}

export function validateFeederPort(
  raw: string,
  required: boolean,
): string | null {
  if (!required && raw.trim().length === 0) {
    return null;
  }
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

/** Per-field messages for one entries-table row, keyed the way the row's
 * own cells are — `null` for a field with nothing wrong. */
export interface FeederEntryFieldErrors {
  name: string | null;
  label: string | null;
  url: string | null;
  container: string | null;
  host: string | null;
  mlatPort: string | null;
  beastPort: string | null;
  webUrl: string | null;
}

/**
 * Validates one entries-table row against the rules its `kind` implies
 * (`lib/feederKinds.ts`'s field map) plus name-uniqueness across the whole
 * table — the one rule that needs every row, not just this one.
 */
export function validateFeederEntry(
  entry: FeederEntryDraft,
  allEntries: readonly FeederEntryDraft[],
): FeederEntryFieldErrors {
  const fields = feederKindFields(entry.kind);
  const trimmedName = entry.name.trim();
  const isDuplicate =
    trimmedName.length > 0 &&
    allEntries.filter((other) => other.name.trim() === trimmedName).length > 1;

  return {
    name:
      validateFeederSlug(entry.name) ??
      (isDuplicate ? "Name must be unique." : null),
    label: validateFeederLabel(entry.label),
    url: validateFeederUrl(entry.url, fields.url),
    container: validateFeederContainer(entry.container, fields.container),
    host: validateFeederHost(entry.host, fields.hostPorts),
    mlatPort: validateFeederPort(entry.mlatPort, fields.hostPorts),
    beastPort: validateFeederPort(entry.beastPort, fields.hostPorts),
    webUrl: validateFeederUrl(entry.webUrl, false),
  };
}

export function feederEntryHasError(errors: FeederEntryFieldErrors): boolean {
  return Object.values(errors).some((message) => message !== null);
}

/** Per-field messages for one local-pages row. A row left entirely blank —
 * the state every trailing "add another" row starts in — is not an error:
 * `buildFeedersPatch` drops it rather than the section refusing to save. */
export interface LocalPageFieldErrors {
  label: string | null;
  url: string | null;
}

export function validateLocalPage(page: LocalPageDraft): LocalPageFieldErrors {
  const isBlank =
    page.label.trim().length === 0 && page.url.trim().length === 0;
  if (isBlank) {
    return { label: null, url: null };
  }
  return {
    label: page.label.trim().length === 0 ? "Label is required." : null,
    url: validateFeederUrl(page.url, true),
  };
}

export function localPageHasError(errors: LocalPageFieldErrors): boolean {
  return errors.label !== null || errors.url !== null;
}
