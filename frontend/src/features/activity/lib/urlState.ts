/**
 * Activity page state <-> query string: `page` plus the repeatable `type`
 * filter — mirroring `features/sightings/lib/urlState.ts`'s split (pure
 * `URLSearchParams` in and out; the router-dependent hook is its own module).
 *
 * Only fields that differ from the default are written, so `/activity` and
 * `/activity?page=1` are the same page and a shared link carries exactly the
 * filters the sharer had on.
 *
 * `type` is repeated rather than comma-joined, which is what the endpoint
 * accepts (`docs/API.md` §3.9) and what keeps each value a value: a comma
 * inside a type slug would otherwise become a parsing problem for both ends.
 * Unknown slugs are dropped on parse rather than rejecting the whole URL, so a
 * link from a newer build degrades to a narrower filter instead of an error.
 */

import type { ActivityEventType } from "@/lib/api/activity";

export const PAGE_SIZE = 50;

/** The vocabulary the filter offers, in the order the chips appear.
 *
 * The two phase-6 types (`alert_triggered`, `emergency_squawk`) are
 * deliberately absent: nothing emits them until roadmap slice 039, and a chip
 * that can only ever return an empty page is a worse answer than no chip.
 * They still parse from a URL and still render in a row — only the filter
 * control omits them, which is the one place where "no producer yet" is
 * visible to a user. */
export const FILTERABLE_TYPES: readonly ActivityEventType[] = [
  "first_ever_aircraft",
  "new_type",
  "milestone",
  "range_record",
  "receiver_record",
  "receiver_offline",
  "receiver_restored",
  "metadata_updated",
];

/** Every type a URL may name, including the phase-6 pair. */
const KNOWN_TYPES: readonly ActivityEventType[] = [
  ...FILTERABLE_TYPES,
  "alert_triggered",
  "emergency_squawk",
];

const KEYS = {
  page: "page",
  type: "type",
} as const;

export interface ActivityPageState {
  /** 1-indexed page number. */
  page: number;
  /** Selected event types; empty means "no filter". */
  types: readonly ActivityEventType[];
}

export const DEFAULT_ACTIVITY_STATE: ActivityPageState = {
  page: 1,
  types: [],
};

function isActivityType(value: string): value is ActivityEventType {
  return (KNOWN_TYPES as readonly string[]).includes(value);
}

/** Restores page state from a query string, defaulting anything absent or
 * malformed rather than rejecting the whole URL. */
export function parseActivityPageState(
  params: URLSearchParams,
): ActivityPageState {
  const pageRaw = Number(params.get(KEYS.page));
  const page =
    Number.isInteger(pageRaw) && pageRaw > 0
      ? pageRaw
      : DEFAULT_ACTIVITY_STATE.page;

  // De-duplicated, and ordered by the canonical list rather than by the order
  // the URL happened to name them, so two links selecting the same filters
  // produce the same query key and share one cache entry.
  const named = new Set(params.getAll(KEYS.type).filter(isActivityType));
  const types = KNOWN_TYPES.filter((type) => named.has(type));

  return { page, types };
}

/** Builds the query-string representation of `state` — only the fields that
 * differ from the default. */
export function serializeActivityPageState(
  state: ActivityPageState,
): URLSearchParams {
  const params = new URLSearchParams();
  if (state.page !== DEFAULT_ACTIVITY_STATE.page) {
    params.set(KEYS.page, String(state.page));
  }
  for (const type of state.types) {
    params.append(KEYS.type, type);
  }
  return params;
}

/** Every key {@link serializeActivityPageState} may write. */
export const ACTIVITY_URL_KEYS: readonly string[] = Object.values(KEYS);
