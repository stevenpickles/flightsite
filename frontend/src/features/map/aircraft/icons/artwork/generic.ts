/**
 * The two shapes that are not a statement about what the aircraft is: the
 * generic fallback for an airframe nothing describes, and its on-the-ground
 * form. Both are slice 014's original drawings, kept verbatim so an untyped
 * aircraft looks exactly as it always has.
 */

import type { IconArtwork } from "@/features/map/aircraft/icons/artwork/types";
import { part } from "@/features/map/aircraft/icons/artwork/types";

/**
 * Generic swept-wing aircraft: pointed nose, swept leading edges out to the
 * wingtips at y = 41, a straight trailing edge back to the fuselage, and a
 * tailplane. The end of the resolver's chain for anything airborne whose type,
 * category and emitter category are all unknown.
 */
const GENERIC_PATH =
  "M32 4C34.2 4 36 8.2 36 13.5L36 25L60 41L60 47L36 39L36 50L43 56L43 60" +
  "L32 57L21 60L21 56L28 50L28 39L4 47L4 41L28 25L28 13.5C28 8.2 29.8 4 32 4Z";

/**
 * On-the-ground variant: the same planform, drawn smaller, sitting on a ground
 * bar. Ground traffic is dense, slow, and rarely the thing a watcher is looking
 * at, so it reads as "parked/taxiing" at a glance and takes up less of the
 * apron than an airborne icon would.
 */
const GROUND_PATH =
  "M32 10C34 10 35.4 12.6 35.4 16.4L35.4 25L52 34L52 38.4L35.4 33.6L35.4 40" +
  "L40 44L40 47.4L32 45.4L24 47.4L24 44L28.6 40L28.6 33.6L12 38.4L12 34" +
  "L28.6 25L28.6 16.4C28.6 12.6 30 10 32 10Z";

const GROUND_BAR = "M14 53h36a2.5 2.5 0 0 1 0 5H14a2.5 2.5 0 0 1 0-5z";

export const GENERIC_ARTWORK = {
  generic: (c) => part(GENERIC_PATH, c),
  ground: (c) => part(GROUND_PATH, c) + part(GROUND_BAR, c),
} satisfies Record<"generic" | "ground", IconArtwork>;
