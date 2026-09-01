/**
 * The one place "does this filter set let this aircraft through" is
 * decided (roadmap slice 017). `applyFilters` is a single pure function
 * over a plain array — no store, no React, no MapLibre — so the frame-
 * building path (`features/map/aircraft/frame.ts`, through
 * `lib/filteredLiveAircraftCache.ts`), the non-positioned panel, and the
 * drawer's active-count badge all read one answer instead of three
 * independently-maintained ones.
 *
 * Null-field philosophy (`docs/API.md` §2.7: absent data is `null`, never
 * fabricated): a *scalar range* filter (altitude, the distance cap) treats
 * an unknown value as unfilterable and lets it through — hiding an
 * aircraft because a number never arrived would be inventing a judgment
 * the data does not support. A *categorical* filter over a field that is
 * itself a structured "we know and it says no" value — `classification`,
 * `classification.mission` — does the opposite: a `null` classification
 * means FlightSite has not looked, not that the aircraft failed the check,
 * so selecting "Military" against an unclassified aircraft cannot honestly
 * show it. Concretely: today, every live payload's `classification` is
 * `null` (it arrives with slice 024), so turning on any classification or
 * mission filter selects nothing rather than everything — the UI
 * (`components/FilterDrawer.tsx`) says so next to those controls, rather
 * than leaving an empty map unexplained.
 *
 * Perf: one pass, `continue`-based short-circuiting, no per-aircraft
 * allocation beyond the output array/sets. `applyFilters.perf.test.ts`
 * budgets 500 aircraft at a small fraction of the 100 ms acceptance
 * criterion. `lib/filteredLiveAircraftCache.ts` adds a single-slot memo on
 * top for the ~12.5 Hz frame loop, so an interpolation-only redraw (no new
 * store data) never re-runs this at all.
 */

import type { Classification, LiveAircraft } from "@/lib/api/live";

import type {
  ClassificationFlag,
  FilterResult,
  FilterRuntimeConfig,
  LiveFilters,
} from "@/features/filters/types";

function effectiveDistanceCap(
  filters: LiveFilters,
  config: FilterRuntimeConfig,
): number {
  return filters.maxDistanceNm ?? config.displayRadiusNm;
}

function matchesText(value: string | null, rawQuery: string): boolean {
  if (value === null) {
    return false;
  }
  return value.toLowerCase().includes(rawQuery.trim().toLowerCase());
}

function matchesClassification(
  classification: Classification | null,
  flags: readonly ClassificationFlag[],
): boolean {
  if (classification === null) {
    return false;
  }
  return flags.some((flag) => classification[flag] === true);
}

function matchesMission(
  classification: Classification | null,
  missions: readonly string[],
): boolean {
  if (classification === null || classification.mission === null) {
    return false;
  }
  return missions.includes(classification.mission);
}

function matchesLiveSetQuery(view: LiveAircraft, rawQuery: string): boolean {
  const query = rawQuery.trim().toLowerCase();
  if (query.length === 0) {
    return true;
  }
  const icao = view.icao.toLowerCase();
  const callsign = view.callsign?.trim().toLowerCase() ?? "";
  const registration = view.registration?.trim().toLowerCase() ?? "";
  return (
    icao.startsWith(query) ||
    callsign.startsWith(query) ||
    registration.startsWith(query)
  );
}

/**
 * Whether one aircraft passes every active filter, AND-composed. Exported
 * (in addition to the batch `applyFilters`) so a caller with a single
 * aircraft in hand — `geojson.ts`'s departing-aircraft loop, which is
 * exempt from batch filtering because it draws a fade-out rather than the
 * live picture — never has to duplicate this logic to stay consistent
 * with it if it opts in later.
 */
export function passesFilters(
  view: LiveAircraft,
  filters: LiveFilters,
  config: FilterRuntimeConfig,
): boolean {
  const cap = effectiveDistanceCap(filters, config);
  if (view.distance_nm !== null && view.distance_nm > cap) {
    return false;
  }
  if (
    filters.altitudeMinFt !== null &&
    view.altitude_ft !== null &&
    view.altitude_ft < filters.altitudeMinFt
  ) {
    return false;
  }
  if (
    filters.altitudeMaxFt !== null &&
    view.altitude_ft !== null &&
    view.altitude_ft > filters.altitudeMaxFt
  ) {
    return false;
  }
  if (
    filters.categoryText.trim().length > 0 &&
    !matchesText(view.aircraft_type, filters.categoryText)
  ) {
    return false;
  }
  if (
    filters.operatorText.trim().length > 0 &&
    !matchesText(view.operator, filters.operatorText)
  ) {
    return false;
  }
  if (
    filters.operatorGroupText.trim().length > 0 &&
    !matchesText(view.operator_group, filters.operatorGroupText)
  ) {
    return false;
  }
  if (
    filters.classifications.length > 0 &&
    !matchesClassification(view.classification, filters.classifications)
  ) {
    return false;
  }
  if (
    filters.missionCategories.length > 0 &&
    !matchesMission(view.classification, filters.missionCategories)
  ) {
    return false;
  }
  if (filters.interestingOnly && view.interesting === null) {
    return false;
  }
  if (filters.emergencyOnly && view.emergency === null) {
    return false;
  }
  if (filters.hideNonPositioned && view.position === null) {
    return false;
  }
  if (filters.groundTraffic === "hide" && view.on_ground === true) {
    return false;
  }
  if (filters.hideStale && view.state === "stale") {
    return false;
  }
  if (!matchesLiveSetQuery(view, filters.liveSetQuery)) {
    return false;
  }
  return true;
}

/** Filters a live set in one pass. See the module doc comment for the
 * null-field rules and the perf budget. */
export function applyFilters(
  aircraft: readonly LiveAircraft[],
  filters: LiveFilters,
  config: FilterRuntimeConfig,
): FilterResult {
  const cap = effectiveDistanceCap(filters, config);
  const passed: LiveAircraft[] = [];
  const visibleIcaos = new Set<string>();
  const dimmedIcaos = new Set<string>();
  let distanceCappedCount = 0;

  for (const view of aircraft) {
    if (view.distance_nm !== null && view.distance_nm > cap) {
      distanceCappedCount += 1;
      continue;
    }
    if (!passesFilters(view, filters, config)) {
      continue;
    }
    passed.push(view);
    visibleIcaos.add(view.icao);
    if (filters.groundTraffic === "dim" && view.on_ground === true) {
      dimmedIcaos.add(view.icao);
    }
  }

  return {
    aircraft: passed,
    visibleIcaos,
    dimmedIcaos,
    distanceCappedCount,
    effectiveDistanceCapNm: cap,
  };
}
