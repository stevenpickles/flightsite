/**
 * The drawer's active-filter badge and clear-all affordance both need one
 * answer to "how many filters is the user applying right now" and "is that
 * zero" — kept here so the two never drift.
 *
 * Each field/group away from its `DEFAULT_FILTERS` value counts once,
 * regardless of how many individual values it holds (e.g. selecting three
 * classifications is one active filter, "classification," not three) —
 * that is what reads as one control to the user in `FilterDrawer.tsx`.
 */

import { DEFAULT_FILTERS, type LiveFilters } from "@/features/filters/types";

/** Number of filter groups that differ from the defaults, 0–12. */
export function countActiveFilters(filters: LiveFilters): number {
  let count = 0;
  if (
    filters.altitudeMinFt !== DEFAULT_FILTERS.altitudeMinFt ||
    filters.altitudeMaxFt !== DEFAULT_FILTERS.altitudeMaxFt
  ) {
    count += 1;
  }
  if (filters.maxDistanceNm !== DEFAULT_FILTERS.maxDistanceNm) {
    count += 1;
  }
  if (filters.categoryText.trim().length > 0) {
    count += 1;
  }
  if (filters.operatorText.trim().length > 0) {
    count += 1;
  }
  if (filters.operatorGroupText.trim().length > 0) {
    count += 1;
  }
  if (filters.classifications.length > 0) {
    count += 1;
  }
  if (filters.missionCategories.length > 0) {
    count += 1;
  }
  if (filters.interestingOnly) {
    count += 1;
  }
  if (filters.emergencyOnly) {
    count += 1;
  }
  if (filters.hideNonPositioned) {
    count += 1;
  }
  if (filters.groundTraffic !== DEFAULT_FILTERS.groundTraffic) {
    count += 1;
  }
  if (filters.hideStale) {
    count += 1;
  }
  if (filters.liveSetQuery.trim().length > 0) {
    count += 1;
  }
  return count;
}

export function hasActiveFilters(filters: LiveFilters): boolean {
  return countActiveFilters(filters) > 0;
}
