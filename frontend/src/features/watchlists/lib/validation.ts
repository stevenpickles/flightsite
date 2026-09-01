/**
 * Client-side field validation for watchlist and entry forms. Bounds mirror
 * `backend/src/flightsite/watchlists/vocabulary.py` exactly, so a value the
 * form accepts is one the backend will also accept — this only exists to
 * give inline feedback before that round trip, not to be a second source of
 * truth for what's valid.
 */
import type { WatchlistEntryKind } from "@/lib/api/watchlists";
import { CATEGORY_OPTIONS } from "@/features/watchlists/lib/vocabulary";

export const MAX_NAME_LENGTH = 100;
export const MAX_DESCRIPTION_LENGTH = 500;
export const MAX_NOTE_LENGTH = 500;
export const MAX_VALUE_LENGTH = 100;

const ICAO24_RE = /^[0-9a-fA-F]{6}$/;
const REGISTRATION_RE = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,8}[A-Za-z0-9])?$/;
const TYPE_CODE_RE = /^[A-Za-z0-9]{2,6}$/;
const VALID_CATEGORIES = new Set(
  CATEGORY_OPTIONS.map((option) => option.value),
);

export function validateWatchlistName(raw: string): string | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return "A watchlist name is required.";
  }
  if (trimmed.length > MAX_NAME_LENGTH) {
    return `Name must be ${MAX_NAME_LENGTH} characters or fewer.`;
  }
  return null;
}

export function validateWatchlistDescription(raw: string): string | null {
  if (raw.trim().length > MAX_DESCRIPTION_LENGTH) {
    return `Description must be ${MAX_DESCRIPTION_LENGTH} characters or fewer.`;
  }
  return null;
}

export function validateEntryNote(raw: string): string | null {
  if (raw.trim().length > MAX_NOTE_LENGTH) {
    return `Note must be ${MAX_NOTE_LENGTH} characters or fewer.`;
  }
  return null;
}

/** Validates a raw entry value against the format `kind` requires. Returns
 * `null` when valid, else a human-readable message — never rewrites the
 * value itself; normalization (case-folding) is the backend's job. */
export function validateEntryValue(
  kind: WatchlistEntryKind,
  raw: string,
): string | null {
  const trimmed = raw.trim();
  if (trimmed.length === 0) {
    return "A value is required.";
  }
  if (trimmed.length > MAX_VALUE_LENGTH) {
    return `Value must be ${MAX_VALUE_LENGTH} characters or fewer.`;
  }
  switch (kind) {
    case "icao24":
      return ICAO24_RE.test(trimmed)
        ? null
        : "Enter exactly six hex digits (e.g. 'ae1463').";
    case "registration":
      return REGISTRATION_RE.test(trimmed)
        ? null
        : "Enter a tail number (e.g. 'N12345', 'G-ABCD').";
    case "type_code":
      return TYPE_CODE_RE.test(trimmed)
        ? null
        : "Enter an ICAO type designator (e.g. 'B738', 'A320').";
    case "operator":
      return null;
    case "category":
      return VALID_CATEGORIES.has(trimmed) ? null : "Choose a category.";
    default:
      return null;
  }
}
