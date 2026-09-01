/**
 * Sightings page state <-> query string: `sort`, `order`, `page`, plus the
 * filters (`icao`, `from`, `to`, `open`) — mirroring
 * `features/aircraft-page/lib/urlState.ts`'s split (pure `URLSearchParams`
 * in/out, the router-dependent hook is a separate module). Only fields that
 * differ from the default are ever written, so `/sightings` and
 * `/sightings?sort=started_at&order=desc&page=1` are the same page.
 *
 * `from`/`to` are stored as plain `YYYY-MM-DD` calendar dates — what an
 * `<input type="date">` produces — and converted to full UTC-day bounds only
 * where the API is actually called (`SightingsPage`). This is a UTC calendar
 * day, not a receiver-local one: `docs/API.md` §2.2 never returns
 * receiver-local time from the server, and getting a local-day boundary
 * right would need the receiver's timezone threaded through this pure
 * module — a refinement left for a later slice, noted in the roadmap.
 */

import type { SightingSortKey, SortOrder } from "@/lib/api/sightings";

export const DEFAULT_SORT: SightingSortKey = "started_at";
export const DEFAULT_ORDER: SortOrder = "desc";
export const PAGE_SIZE = 50;

const SORT_KEYS: readonly SightingSortKey[] = [
  "started_at",
  "duration_s",
  "closest_approach_nm",
  "max_range_nm",
];

const ICAO_PATTERN = /^[0-9a-f]{6}$/;
const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;

const KEYS = {
  sort: "sort",
  order: "order",
  page: "page",
  icao: "icao",
  from: "from",
  to: "to",
  open: "open",
} as const;

export interface SightingsTableState {
  sort: SightingSortKey;
  order: SortOrder;
  /** 1-indexed page number. */
  page: number;
  /** Exact lowercase ICAO match, or `undefined` for no filter. */
  icao: string | undefined;
  /** `YYYY-MM-DD`, or `undefined`. */
  from: string | undefined;
  /** `YYYY-MM-DD`, or `undefined`. */
  to: string | undefined;
  /** `true` to show only sightings still open. */
  open: boolean;
}

export const DEFAULT_TABLE_STATE: SightingsTableState = {
  sort: DEFAULT_SORT,
  order: DEFAULT_ORDER,
  page: 1,
  icao: undefined,
  from: undefined,
  to: undefined,
  open: false,
};

function isSortKey(value: string): value is SightingSortKey {
  return (SORT_KEYS as readonly string[]).includes(value);
}

/** Restores table state from a query string, defaulting anything absent or
 * malformed rather than rejecting the whole URL. */
export function parseSightingsTableState(
  params: URLSearchParams,
): SightingsTableState {
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

  const icaoRaw = params.get(KEYS.icao)?.toLowerCase();
  const icao =
    icaoRaw !== undefined && ICAO_PATTERN.test(icaoRaw) ? icaoRaw : undefined;

  const fromRaw = params.get(KEYS.from);
  const from =
    fromRaw !== null && DATE_PATTERN.test(fromRaw) ? fromRaw : undefined;

  const toRaw = params.get(KEYS.to);
  const to = toRaw !== null && DATE_PATTERN.test(toRaw) ? toRaw : undefined;

  const open = params.get(KEYS.open) === "true";

  return { sort, order, page, icao, from, to, open };
}

/** Builds the query-string representation of `state` — only the fields that
 * differ from the default. */
export function serializeSightingsTableState(
  state: SightingsTableState,
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
  if (state.icao !== undefined) {
    params.set(KEYS.icao, state.icao);
  }
  if (state.from !== undefined) {
    params.set(KEYS.from, state.from);
  }
  if (state.to !== undefined) {
    params.set(KEYS.to, state.to);
  }
  if (state.open) {
    params.set(KEYS.open, "true");
  }
  return params;
}

/** `YYYY-MM-DD` -> the inclusive UTC start-of-day ISO instant the API's
 * `from` bound expects. */
export function startOfDayIso(date: string): string {
  return `${date}T00:00:00.000Z`;
}

/** `YYYY-MM-DD` -> the inclusive UTC end-of-day ISO instant the API's `to`
 * bound expects. */
export function endOfDayIso(date: string): string {
  return `${date}T23:59:59.999Z`;
}

/** Every key {@link serializeSightingsTableState} may write. */
export const SIGHTINGS_TABLE_URL_KEYS: readonly string[] = Object.values(KEYS);
