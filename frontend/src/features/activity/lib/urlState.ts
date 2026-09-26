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

/** The vocabulary the filter offers, in the order the chips appear — the
 * whole of §3.9's event vocabulary, with nothing held back.
 *
 * Alerts and emergencies lead because they are what the feed is mostly made
 * of once slice 038's engine is running: the review found "Alert: …" on six
 * of the first thirteen rows while the filter offered no way to isolate them
 * *or* to filter them out and see the firsts and records underneath (R2-05).
 * They were gated out before slice 039 shipped a producer for them, on the
 * reasoning that a chip which can only return an empty page is worse than no
 * chip; that slice is merged, so the premise is gone. */
export const FILTERABLE_TYPES: readonly ActivityEventType[] = [
  "alert_triggered",
  "emergency_squawk",
  "first_ever_aircraft",
  "new_type",
  "milestone",
  "range_record",
  "receiver_record",
  "receiver_offline",
  "receiver_restored",
  "metadata_updated",
  // Slice 077 — the Feeders page's own pair, listed after the receiver's
  // for the same reason it has its own icons and chip wording: a feeder
  // outage is a different fact than a decoder outage.
  "feeder_offline",
  "feeder_restored",
];

/** Every type a URL may name. Identical to {@link FILTERABLE_TYPES} today,
 * and kept as its own name because the two answer different questions: what
 * a link is allowed to say, and what the chip row offers. */
const KNOWN_TYPES: readonly ActivityEventType[] = FILTERABLE_TYPES;

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
