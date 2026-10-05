/**
 * Sightings page state <-> query string: the time window (`preset`), how the
 * window is grouped (`group`), `sort`, `order`, `page`, and the filters
 * (`icao`, `q`, `open`, `type`) — mirroring
 * `features/aircraft-page/lib/urlState.ts`'s split (pure `URLSearchParams`
 * in/out, the router-dependent hook is a separate module). Only fields that
 * differ from the default are ever written, so `/sightings` and
 * `/sightings?sort=started_at&order=desc&page=1` are the same page.
 *
 * **The window is a preset, not a pair of dates** (slice 098). The page used
 * to take two `<input type="date">` values and convert them to UTC-day bounds
 * in the browser — a UTC day, not the receiver's, because this pure module
 * had no timezone to resolve one against. It now names one of the Analytics
 * presets and lets the server resolve it in receiver-local time, so "today"
 * means the receiver's today on every surface.
 *
 * The default preset is `today` — except when the URL carries an exact `icao`
 * and no preset of its own. That is the shape of the aircraft detail page's
 * "all sightings" link, written before presets existed; it means *all* of
 * that aircraft's sightings, so it reads as `t0`. An explicit `preset` in the
 * URL always wins.
 *
 * **Each grouping sorts by its own columns** (slice 100): the log by a
 * sighting's, the aircraft list by an airframe's, the type list by a type's.
 * They share the `sort` / `order` keys, read against the grouping the URL
 * names — a key that belongs to another grouping falls back to this one's
 * default rather than being sent to an endpoint that would reject it.
 *
 * Two aircraft filters, deliberately (slice 083): `q` is what the filter box
 * writes — an ICAO-address *or* callsign prefix, normalized like the
 * Aircraft page's (`features/history/lib/search.ts`) — and `icao` stays the
 * exact six-hex-digit match that links such as the aircraft detail page's
 * "all sightings" already put in the URL, so every existing link keeps
 * meaning exactly what it did.
 */

import { normalizeSearch, searchFromUrl } from "@/features/history/lib/search";
import {
  ANALYTICS_PRESETS,
  type AnalyticsPreset,
  type SeenAircraftSortKey,
  type SeenTypeSortKey,
} from "@/lib/api/analytics";
import type { SightingSortKey, SortOrder } from "@/lib/api/sightings";

export const DEFAULT_SORT: SightingSortKey = "started_at";
export const DEFAULT_ORDER: SortOrder = "desc";
export const PAGE_SIZE = 50;

/** Any grouping's sort key. Which ones are valid depends on the grouping —
 * {@link SORT_KEYS_BY_GROUP}. */
export type SightingsSort =
  SightingSortKey | SeenAircraftSortKey | SeenTypeSortKey;

/** How the window's sightings are grouped: the log itself, one row per
 * distinct aircraft, or one row per distinct type. */
export type SightingsGroup = "sightings" | "aircraft" | "types";

export const SIGHTINGS_GROUPS: readonly SightingsGroup[] = [
  "sightings",
  "aircraft",
  "types",
];

export const DEFAULT_GROUP: SightingsGroup = "sightings";

const LOG_SORT_KEYS: readonly SightingSortKey[] = [
  "started_at",
  "ended_at",
  "duration_s",
  "tail",
  "aircraft_type",
  "operator",
  "closest_approach_nm",
  "max_range_nm",
  "lowest_altitude_ft",
  "highest_altitude_ft",
  "position_count",
];

const AIRCRAFT_SORT_KEYS: readonly SeenAircraftSortKey[] = [
  "sightings",
  "registration",
  "type",
  "operator",
  "first_seen",
  "last_seen",
];

const TYPE_SORT_KEYS: readonly SeenTypeSortKey[] = [
  "sightings",
  "type",
  "aircraft",
  "first_seen",
  "last_seen",
];

/** The columns each grouping can be ordered by. */
export const SORT_KEYS_BY_GROUP: Record<
  SightingsGroup,
  readonly SightingsSort[]
> = {
  sightings: LOG_SORT_KEYS,
  aircraft: AIRCRAFT_SORT_KEYS,
  types: TYPE_SORT_KEYS,
};

/** What each grouping is ordered by until a header is clicked: the log
 * newest first, the two lists busiest first. */
export const DEFAULT_SORT_BY_GROUP: Record<SightingsGroup, SightingsSort> = {
  sightings: DEFAULT_SORT,
  aircraft: "sightings",
  types: "sightings",
};

/** Sort keys whose values are words rather than quantities or times. */
const TEXT_SORT_KEYS: ReadonlySet<SightingsSort> = new Set<SightingsSort>([
  "tail",
  "aircraft_type",
  "operator",
  "registration",
  "type",
]);

/** The direction a column sorts in on its first click: words read A to Z,
 * everything else leads with its largest or latest. */
export function firstOrderFor(sort: SightingsSort): SortOrder {
  return TEXT_SORT_KEYS.has(sort) ? "asc" : "desc";
}

const ICAO_PATTERN = /^[0-9a-f]{6}$/;
const TYPE_PATTERN = /^[A-Z0-9]{2,4}$/;

const KEYS = {
  preset: "preset",
  group: "group",
  sort: "sort",
  order: "order",
  page: "page",
  icao: "icao",
  q: "q",
  open: "open",
  type: "type",
} as const;

export interface SightingsTableState {
  /** The time window, as one of the Analytics presets. */
  preset: AnalyticsPreset;
  group: SightingsGroup;
  /** One of the current grouping's sort keys ({@link SORT_KEYS_BY_GROUP}). */
  sort: SightingsSort;
  order: SortOrder;
  /** 1-indexed page number. */
  page: number;
  /** Exact lowercase ICAO match, or `undefined` for no filter. */
  icao: string | undefined;
  /** ICAO-or-callsign prefix search (slice 083), normalized, or
   * `undefined` for none. */
  q?: string | undefined;
  /** `true` to show only sightings still open. */
  open: boolean;
  /** One upper-case ICAO type designator the aircraft grouping is narrowed
   * to, or `undefined`. */
  type: string | undefined;
}

/** The preset a URL without one means: everything for an exact-aircraft
 * link, today otherwise (module docstring). */
export function defaultPresetFor(icao: string | undefined): AnalyticsPreset {
  return icao === undefined ? "today" : "t0";
}

export const DEFAULT_TABLE_STATE: SightingsTableState = {
  preset: defaultPresetFor(undefined),
  group: DEFAULT_GROUP,
  sort: DEFAULT_SORT,
  order: DEFAULT_ORDER,
  page: 1,
  icao: undefined,
  q: undefined,
  open: false,
  type: undefined,
};

function isSortKeyOf(
  group: SightingsGroup,
  value: string | null,
): value is SightingsSort {
  return (
    value !== null &&
    (SORT_KEYS_BY_GROUP[group] as readonly string[]).includes(value)
  );
}

function isPreset(value: string | null): value is AnalyticsPreset {
  return (
    value !== null && (ANALYTICS_PRESETS as readonly string[]).includes(value)
  );
}

function isGroup(value: string | null): value is SightingsGroup {
  return (
    value !== null && (SIGHTINGS_GROUPS as readonly string[]).includes(value)
  );
}

/** Restores table state from a query string, defaulting anything absent or
 * malformed rather than rejecting the whole URL. */
export function parseSightingsTableState(
  params: URLSearchParams,
): SightingsTableState {
  const groupRaw = params.get(KEYS.group);
  const group = isGroup(groupRaw) ? groupRaw : DEFAULT_GROUP;

  const sortRaw = params.get(KEYS.sort);
  const sort = isSortKeyOf(group, sortRaw)
    ? sortRaw
    : DEFAULT_SORT_BY_GROUP[group];

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

  const q = searchFromUrl(params.get(KEYS.q));

  const open = params.get(KEYS.open) === "true";

  const presetRaw = params.get(KEYS.preset);
  const preset = isPreset(presetRaw) ? presetRaw : defaultPresetFor(icao);

  const typeRaw = params.get(KEYS.type)?.toUpperCase();
  const type =
    typeRaw !== undefined && TYPE_PATTERN.test(typeRaw) ? typeRaw : undefined;

  return { preset, group, sort, order, page, icao, q, open, type };
}

/** Builds the query-string representation of `state` — only the fields that
 * differ from the default. */
export function serializeSightingsTableState(
  state: SightingsTableState,
): URLSearchParams {
  const params = new URLSearchParams();
  // Written whenever it is not what the URL would mean without it — which
  // depends on `icao`, so `?icao=…&preset=today` is a real, distinct page.
  if (state.preset !== defaultPresetFor(state.icao)) {
    params.set(KEYS.preset, state.preset);
  }
  if (state.group !== DEFAULT_GROUP) {
    params.set(KEYS.group, state.group);
  }
  if (state.sort !== DEFAULT_SORT_BY_GROUP[state.group]) {
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
  const q = normalizeSearch(state.q);
  if (q !== undefined) {
    params.set(KEYS.q, q);
  }
  if (state.open) {
    params.set(KEYS.open, "true");
  }
  if (state.type !== undefined) {
    params.set(KEYS.type, state.type);
  }
  return params;
}

/** Every key {@link serializeSightingsTableState} may write. */
export const SIGHTINGS_TABLE_URL_KEYS: readonly string[] = Object.values(KEYS);
