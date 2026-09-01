/**
 * Filter state <-> query string, round-tripped through the terse key set
 * below. Only fields that differ from `DEFAULT_FILTERS` are ever written —
 * a default-valued filter leaves no trace in the URL — so a plain `/`
 * (or any URL a user hand-edits) always parses back to the defaults rather
 * than an implicit "everything," and sharing a filtered view's link stays
 * short.
 *
 * Pure `URLSearchParams` in and out: `hooks/useFilterUrlSync.ts` is the
 * only thing that touches `react-router`'s `useSearchParams`, so this half
 * is unit-testable without a router.
 */

import {
  DEFAULT_FILTERS,
  type ClassificationFlag,
  type GroundTrafficMode,
  type LiveFilters,
} from "@/features/filters/types";

const KEYS = {
  altitudeMinFt: "alt_min",
  altitudeMaxFt: "alt_max",
  maxDistanceNm: "dist",
  categoryText: "cat",
  operatorText: "op",
  operatorGroupText: "opg",
  classifications: "cls",
  missionCategories: "mission",
  interestingOnly: "interesting",
  emergencyOnly: "emergency",
  hideNonPositioned: "hide_np",
  groundTraffic: "ground",
  hideStale: "hide_stale",
  liveSetQuery: "q",
} as const;

const CLASSIFICATION_FLAGS: readonly ClassificationFlag[] = [
  "military",
  "government",
  "law_enforcement",
];
const GROUND_MODES: readonly GroundTrafficMode[] = ["show", "dim", "hide"];

function parseFiniteNumber(value: string | null): number | null {
  if (value === null || value.trim().length === 0) {
    return null;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function parseList(value: string | null): string[] {
  if (value === null || value.trim().length === 0) {
    return [];
  }
  return value
    .split(",")
    .map((entry) => entry.trim())
    .filter((entry) => entry.length > 0);
}

/** Builds the query-string representation of `filters` — only the fields
 * that differ from `DEFAULT_FILTERS`. Any other params already in the URL
 * are the caller's concern (`useFilterUrlSync` merges rather than
 * replaces wholesale). */
export function serializeFiltersToSearchParams(
  filters: LiveFilters,
): URLSearchParams {
  const params = new URLSearchParams();

  if (filters.altitudeMinFt !== null) {
    params.set(KEYS.altitudeMinFt, String(filters.altitudeMinFt));
  }
  if (filters.altitudeMaxFt !== null) {
    params.set(KEYS.altitudeMaxFt, String(filters.altitudeMaxFt));
  }
  if (filters.maxDistanceNm !== null) {
    params.set(KEYS.maxDistanceNm, String(filters.maxDistanceNm));
  }
  if (filters.categoryText.trim().length > 0) {
    params.set(KEYS.categoryText, filters.categoryText);
  }
  if (filters.operatorText.trim().length > 0) {
    params.set(KEYS.operatorText, filters.operatorText);
  }
  if (filters.operatorGroupText.trim().length > 0) {
    params.set(KEYS.operatorGroupText, filters.operatorGroupText);
  }
  if (filters.classifications.length > 0) {
    params.set(KEYS.classifications, filters.classifications.join(","));
  }
  if (filters.missionCategories.length > 0) {
    params.set(KEYS.missionCategories, filters.missionCategories.join(","));
  }
  if (filters.interestingOnly) {
    params.set(KEYS.interestingOnly, "1");
  }
  if (filters.emergencyOnly) {
    params.set(KEYS.emergencyOnly, "1");
  }
  if (filters.hideNonPositioned) {
    params.set(KEYS.hideNonPositioned, "1");
  }
  if (filters.groundTraffic !== DEFAULT_FILTERS.groundTraffic) {
    params.set(KEYS.groundTraffic, filters.groundTraffic);
  }
  if (filters.hideStale) {
    params.set(KEYS.hideStale, "1");
  }
  if (filters.liveSetQuery.trim().length > 0) {
    params.set(KEYS.liveSetQuery, filters.liveSetQuery);
  }

  return params;
}

/** Restores `LiveFilters` from a query string, defaulting anything absent
 * or malformed rather than rejecting the whole URL — a filter link that
 * has bit-rotted (a param renamed, a stray hand-edit) should degrade to
 * "no filter," never to an error page. */
export function parseFiltersFromSearchParams(
  params: URLSearchParams,
): LiveFilters {
  const groundRaw = params.get(KEYS.groundTraffic);
  const groundTraffic: GroundTrafficMode =
    groundRaw !== null && GROUND_MODES.includes(groundRaw as GroundTrafficMode)
      ? (groundRaw as GroundTrafficMode)
      : DEFAULT_FILTERS.groundTraffic;

  const classifications = parseList(params.get(KEYS.classifications)).filter(
    (entry): entry is ClassificationFlag =>
      CLASSIFICATION_FLAGS.includes(entry as ClassificationFlag),
  );

  return {
    altitudeMinFt: parseFiniteNumber(params.get(KEYS.altitudeMinFt)),
    altitudeMaxFt: parseFiniteNumber(params.get(KEYS.altitudeMaxFt)),
    maxDistanceNm: parseFiniteNumber(params.get(KEYS.maxDistanceNm)),
    categoryText: params.get(KEYS.categoryText) ?? DEFAULT_FILTERS.categoryText,
    operatorText: params.get(KEYS.operatorText) ?? DEFAULT_FILTERS.operatorText,
    operatorGroupText:
      params.get(KEYS.operatorGroupText) ?? DEFAULT_FILTERS.operatorGroupText,
    classifications,
    missionCategories: parseList(params.get(KEYS.missionCategories)),
    interestingOnly: params.get(KEYS.interestingOnly) === "1",
    emergencyOnly: params.get(KEYS.emergencyOnly) === "1",
    hideNonPositioned: params.get(KEYS.hideNonPositioned) === "1",
    groundTraffic,
    hideStale: params.get(KEYS.hideStale) === "1",
    liveSetQuery: params.get(KEYS.liveSetQuery) ?? DEFAULT_FILTERS.liveSetQuery,
  };
}

/** All keys `serializeFiltersToSearchParams` may write — used by
 * `useFilterUrlSync` to strip stale filter params from the URL before
 * writing the current set, without disturbing any unrelated param. */
export const FILTER_URL_KEYS: readonly string[] = Object.values(KEYS);
