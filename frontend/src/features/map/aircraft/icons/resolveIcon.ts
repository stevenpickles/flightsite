/**
 * The hierarchical icon resolver: **type → category → generic**.
 *
 * Roadmap slice 014 scopes this as *plumbing*. The hierarchy, its fallbacks,
 * and the tests that pin them ship now; the data that would let the first two
 * levels fire does not exist yet. `aircraft_type` and
 * `classification.icon_category` are both `null` on every payload this slice
 * can receive (`backend/src/flightsite/api/serializers.py` returns the metadata
 * half of the §3.3 object as `null` until slices 021–024 land), so in practice
 * every aircraft resolves at the generic level today.
 *
 * Building it this way round is the point: when slice 024 starts populating
 * those fields, activating type-specific silhouettes is filling in
 * {@link TYPE_ICON_SHAPES}, not rewriting the layer.
 *
 * **No heuristics.** The resolver reads the two metadata fields and nothing
 * else. Guessing "rotorcraft" from a low ground speed, say, would invent a
 * classification the data does not support, and SPEC §39 requires
 * classification to carry provenance and not claim certainty on weak evidence.
 * A helicopter therefore renders as the generic silhouette until real metadata
 * says otherwise — honest, and visibly fixed by slice 024.
 */

import type { AircraftIconShape } from "@/features/map/aircraft/icons/silhouettes";
import type { LiveAircraft } from "@/lib/api/live";

/** Which level of the hierarchy produced the icon. Exposed because it is the
 * thing worth asserting on: the fallback chain is the behaviour, the shape is
 * just today's consequence of it. */
export type IconResolutionLevel = "type" | "category" | "generic";

export interface IconResolution {
  shape: AircraftIconShape;
  level: IconResolutionLevel;
}

/**
 * ICAO type designator → silhouette.
 *
 * Empty by design. Populating it needs a type designator on the payload, which
 * arrives with the metadata database in slice 024; keys are upper-case ICAO
 * designators (`"B738"`, `"EC35"`).
 */
export const TYPE_ICON_SHAPES: Readonly<Record<string, AircraftIconShape>> = {};

/**
 * Icon category → silhouette, keyed by lower-case
 * `classification.icon_category`. The categories named here are the ones SPEC
 * §39's vocabulary maps onto a silhouette this slice actually draws; every
 * other category legitimately falls through to the generic shape.
 */
export const CATEGORY_ICON_SHAPES: Readonly<Record<string, AircraftIconShape>> =
  {
    helicopter: "rotorcraft",
    rotorcraft: "rotorcraft",
    gyrocopter: "rotorcraft",
  };

/** The end of the chain: an aircraft with no usable metadata, airborne. */
export const GENERIC_ICON_SHAPE: AircraftIconShape = "airliner";

/** The end of the chain for an aircraft the decoder reports as on the ground. */
export const GROUND_ICON_SHAPE: AircraftIconShape = "ground";

function normalize(value: string | null | undefined): string | null {
  if (typeof value !== "string") {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

/** The fields the resolver reads — a structural subset of {@link LiveAircraft},
 * so callers can resolve an icon without constructing a whole payload. */
export type IconResolverInput = Pick<
  LiveAircraft,
  "aircraft_type" | "classification" | "on_ground"
>;

/**
 * Resolves the silhouette for one aircraft.
 *
 * The `on_ground` variant applies at the **generic level only**: it is the
 * fallback's own ground form, not a level of the hierarchy. A known type or
 * category is a stronger statement about what the aircraft *is* than the
 * decoder's ground flag is about how it should be drawn, so a metadata-resolved
 * silhouette keeps its shape while taxiing.
 */
export function resolveAircraftIcon(
  aircraft: IconResolverInput,
): IconResolution {
  const type = normalize(aircraft.aircraft_type)?.toUpperCase();
  const byType = type === undefined ? undefined : TYPE_ICON_SHAPES[type];
  if (byType) {
    return { shape: byType, level: "type" };
  }

  const category = normalize(
    aircraft.classification?.icon_category,
  )?.toLowerCase();
  const byCategory =
    category === undefined ? undefined : CATEGORY_ICON_SHAPES[category];
  if (byCategory) {
    return { shape: byCategory, level: "category" };
  }

  return {
    shape: aircraft.on_ground === true ? GROUND_ICON_SHAPE : GENERIC_ICON_SHAPE,
    level: "generic",
  };
}
