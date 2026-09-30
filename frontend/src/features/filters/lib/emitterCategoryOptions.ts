/**
 * The emitter-category filter's options (roadmap slice 086).
 *
 * SPEC §37 asks for an "aircraft category/type" filter and warns off "complex
 * faceted-search". Offering all 32 ADS-B codes would be exactly that — most
 * never appear over a given receiver, and half of them are reserved — so the
 * drawer offers the categories the live picture actually contains, plus any
 * the user has already selected (a selection must stay visible and removable
 * after the last aircraft of that category has left, or it becomes an
 * invisible filter hiding everything).
 *
 * `presentEmitterCategoriesKey` returns a *string* on purpose: it is used as a
 * Zustand selector over the live store, which updates about once a second,
 * and a primitive compares equal by value — so the drawer re-renders only
 * when the set of categories actually changes, not on every position update.
 */

import type { LiveAircraftRecord } from "@/features/map/aircraft/store/useLiveAircraftStore";

/** The sorted, distinct emitter categories in the live picture, joined by
 * `,` (`""` when none). See the module comment for why a string. */
export function presentEmitterCategoriesKey(
  aircraft: Readonly<Record<string, LiveAircraftRecord>>,
): string {
  const present = new Set<string>();
  for (const record of Object.values(aircraft)) {
    const category = record.aircraft.emitter_category;
    if (typeof category === "string" && category.length > 0) {
      present.add(category);
    }
  }
  return [...present].sort().join(",");
}

/** The options to offer: what is present, plus what is selected, sorted. */
export function emitterCategoryOptions(
  presentKey: string,
  selected: readonly string[],
): string[] {
  const options = new Set(presentKey.length > 0 ? presentKey.split(",") : []);
  for (const category of selected) {
    options.add(category);
  }
  return [...options].sort();
}
