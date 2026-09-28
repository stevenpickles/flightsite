/**
 * Aircraft page state <-> query string, round-tripped through four keys:
 * `sort`, `order`, `page` (1-indexed — an offset would be an implementation
 * detail leaking into a URL a user might read or hand-edit) and `q`, the
 * filter box (roadmap slice 083). Only fields that differ from the default
 * are ever written, so `/aircraft` and
 * `/aircraft?sort=last_seen&order=desc&page=1` are the same page and a
 * shared link stays short.
 *
 * `q` is stored the way the API reads it (`docs/API.md` §3.5): trimmed,
 * blank meaning absent, at most {@link MAX_SEARCH_LENGTH} characters — so a
 * hand-edited or over-long link degrades to a search the server accepts
 * rather than a 422.
 *
 * Pure `URLSearchParams` in and out, mirroring
 * `features/filters/lib/urlSync.ts`'s split: the hook that touches
 * `react-router`'s `useSearchParams` is the only router-dependent piece,
 * so this half is unit-testable without one.
 */

import type { AircraftSortKey, SortOrder } from "@/lib/api/aircraft";

export const DEFAULT_SORT: AircraftSortKey = "last_seen";
export const DEFAULT_ORDER: SortOrder = "desc";
export const PAGE_SIZE = 50;

/** The API's cap on `q` (`MAX_QUERY_LENGTH` in `flightsite.api.search`). */
export const MAX_SEARCH_LENGTH = 32;

const SORT_KEYS: readonly AircraftSortKey[] = [
  "registration",
  "icao",
  "type",
  "operator",
  "classification",
  "first_seen",
  "last_seen",
  "sighting_count",
  "closest_approach_nm",
  "max_range_nm",
];

const KEYS = { sort: "sort", order: "order", page: "page", q: "q" } as const;

export interface AircraftTableState {
  sort: AircraftSortKey;
  order: SortOrder;
  /** 1-indexed page number. */
  page: number;
  /** The filter box's prefix search, already normalized
   * ({@link normalizeSearch}), or `undefined` for none. */
  q?: string | undefined;
}

export const DEFAULT_TABLE_STATE: AircraftTableState = {
  sort: DEFAULT_SORT,
  order: DEFAULT_ORDER,
  page: 1,
  q: undefined,
};

function isSortKey(value: string): value is AircraftSortKey {
  return (SORT_KEYS as readonly string[]).includes(value);
}

/** A search as the API will read it: trimmed, capped at
 * {@link MAX_SEARCH_LENGTH}, and `undefined` when nothing is left — so an
 * input holding only spaces is "no search", not a search for spaces. */
export function normalizeSearch(
  raw: string | null | undefined,
): string | undefined {
  const trimmed = (raw ?? "").trim().slice(0, MAX_SEARCH_LENGTH).trim();
  return trimmed === "" ? undefined : trimmed;
}

/** Restores table state from a query string, defaulting anything absent or
 * malformed rather than rejecting the whole URL. */
export function parseAircraftTableState(
  params: URLSearchParams,
): AircraftTableState {
  const sortRaw = params.get(KEYS.sort);
  const sort = sortRaw !== null && isSortKey(sortRaw) ? sortRaw : DEFAULT_SORT;

  const orderRaw = params.get(KEYS.order);
  const order: SortOrder =
    orderRaw === "asc" || orderRaw === "desc" ? orderRaw : DEFAULT_ORDER;

  const pageRaw = Number(params.get(KEYS.page));
  const page =
    Number.isInteger(pageRaw) && pageRaw > 0
      ? pageRaw
      : DEFAULT_TABLE_STATE.page;

  const q = normalizeSearch(params.get(KEYS.q));

  return { sort, order, page, q };
}

/** Builds the query-string representation of `state` — only the fields that
 * differ from the default. Any other params already in the URL are the
 * caller's concern. */
export function serializeAircraftTableState(
  state: AircraftTableState,
): URLSearchParams {
  const params = new URLSearchParams();
  if (state.sort !== DEFAULT_SORT) {
    params.set(KEYS.sort, state.sort);
  }
  if (state.order !== DEFAULT_ORDER) {
    params.set(KEYS.order, state.order);
  }
  if (state.page !== DEFAULT_TABLE_STATE.page) {
    params.set(KEYS.page, String(state.page));
  }
  const q = normalizeSearch(state.q);
  if (q !== undefined) {
    params.set(KEYS.q, q);
  }
  return params;
}

/** Every key {@link serializeAircraftTableState} may write. */
export const AIRCRAFT_TABLE_URL_KEYS: readonly string[] = Object.values(KEYS);
