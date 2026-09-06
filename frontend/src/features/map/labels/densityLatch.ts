/**
 * The one piece of memory the label tiering needs (issue #143).
 *
 * `labels/priority.ts` decides the density tier from a *latch* rather than
 * from a bare count, so a picture hovering on the threshold cannot toggle
 * the altitude line on and off every frame. Something has to remember
 * which side of the band the last frame landed on, and this module is that
 * something — deliberately the smallest possible amount of state, kept out of
 * both the pure tier function and the pure GeoJSON builder.
 *
 * Module-level rather than per-map, the same shape (and for the same reason)
 * as `features/filters/lib/filteredLiveAircraftCache`: the frame loop is a
 * single imperative path with no instance to hang state off, there is exactly
 * one live picture per tab, and a `let` here is a great deal cheaper than
 * threading a mutable box through `drawAircraftFrame` on every tick.
 *
 * It self-clears without help — an empty picture is a count of zero, which is
 * below the band's lower edge — so a store reset already unlatches on the
 * next drawn frame. {@link resetDensityLatch} exists so teardown does not
 * have to *wait* for that frame — `features/map/aircraft/AircraftLayer` calls
 * it on unmount, beside clearing the selection, as the map's own half of the
 * teardown ADR-0015 split from the socket's — and so one test's dense picture
 * can never leak into the next test's sparse one.
 */

import { nextDensityLatched } from "@/features/map/labels/priority";

let latched = false;

/**
 * Advances the latch with this frame's labelled count and returns the new
 * state — what `deriveLabelTier` takes as `densityLatched`.
 *
 * "Labelled", not "live" (issue #147): the number of aircraft that will
 * actually carry a label this frame, which `aircraft/geojson.ts`'s
 * `countLabelledAircraft` derives. A position-less Mode S contact is part of
 * the live picture but occupies no label and crowds nothing, so it has no
 * business pushing the labels of the aircraft that *are* drawn down a tier.
 */
export function updateDensityLatch(labelledCount: number): boolean {
  latched = nextDensityLatched(latched, labelledCount);
  return latched;
}

/** Drops the latch back to "not dense", so the next frame is judged with no
 * history behind it. */
export function resetDensityLatch(): void {
  latched = false;
}
