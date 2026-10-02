/**
 * Civil fixed-wing silhouettes, from a two-seat trainer to a four-engine
 * widebody. Each is a planform — the aircraft seen from directly above — built
 * from a handful of cased parts in a deliberate draw order (see `types.ts`).
 *
 * What tells them apart at map scale, family by family:
 *
 * - **Light singles.** A high wing drawn over the fuselage (Cessna) versus a
 *   low wing drawn under it (Piper, Beech, Mooney). The Cirrus is the low-wing
 *   drawing with its own tells: a rounder, wider cabin, a tapered wing, a
 *   larger tailplane and the dorsal strake running down the rear fuselage.
 * - **Light twin.** The low-wing single with two short nacelles close inboard
 *   and a longer nose.
 * - **Twin turboprop.** High wing, long span, big nacelles well outboard with
 *   prop discs, a T-tail and a slender fuselage.
 * - **Business jet.** Slender fuselage, moderately swept wing, two engine pods
 *   on the rear fuselage, T-tail.
 * - **Airliners.** Swept wing with underwing pods: two pods and a slim tube
 *   (narrowbody), two bigger pods on a wider tube and a longer span (widebody
 *   twin), four pods on the widest tube (widebody three/four-engine — one
 *   drawing serves tri-jets too, since at this size the third engine is the
 *   fuselage).
 * - **Glider.** An extremely high-aspect wing on a pencil fuselage with a
 *   cockpit bulge and a T-tail.
 */

import type { IconArtwork } from "@/features/map/aircraft/icons/artwork/types";
import {
  blob,
  line,
  part,
  pod,
  propeller,
} from "@/features/map/aircraft/icons/artwork/types";

/** Light single fuselage: round nose, cabin, tapering tail cone. */
const LIGHT_FUSELAGE =
  "M32 10C35.2 10 36.5 13.5 36.5 17.5L36.5 38L34.5 50L32 52L29.5 50L27.5 38" +
  "L27.5 17.5C27.5 13.5 28.8 10 32 10Z";

/** The same with a pointed spinner and a slightly longer nose. */
const LIGHT_FUSELAGE_SPINNER =
  "M32 9C35.2 9.5 36.5 13.5 36.5 17.5L36.5 38L34.5 50L32 52L29.5 50L27.5 38" +
  "L27.5 17.5C27.5 13.5 28.8 9.5 32 9Z";

/** Straight tailplane, for the high-wing single. */
const LIGHT_TAILPLANE = "M21 47h22v4.5H21z";

/** Slightly swept tailplane, for the low-wing singles and the twin. */
const LIGHT_TAILPLANE_SWEPT = "M21 47L32 45.5L43 47v4.5H21z";

export const CIVIL_ARTWORK = {
  "light-high-wing": (c) =>
    part(LIGHT_TAILPLANE, c) +
    part(LIGHT_FUSELAGE, c) +
    // Constant-chord strut-braced wing, drawn over the body.
    `<rect x="11" y="20" width="42" height="7" rx="2" fill="${c.body}" stroke="${c.ink}" stroke-width="2"/>` +
    propeller(32, 9, 6, c),

  "light-low-wing": (c) =>
    // Tapered low wing, drawn under the body.
    part("M12 24h40v4.5L32 33L12 28.5Z", c) +
    part(LIGHT_TAILPLANE_SWEPT, c) +
    part(LIGHT_FUSELAGE_SPINNER, c) +
    propeller(32, 8, 6, c),

  "light-cirrus": (c) =>
    // Tapered on both edges, with the wider, rounder cabin over it.
    part("M11 25L28 23.5h8L53 25v3L36 31.5h-8L11 28Z", c) +
    part("M20 47.5L32 46L44 47.5v4H20z", c) +
    part(
      "M32 9C36 9 38 13 38 18L38 38L35 50L32 52L29 50L26 38L26 18C26 13 28 9 32 9Z",
      c,
    ) +
    // The dorsal strake — the one line that reads "Cirrus" from above.
    line("M32 36v11", c, 1.75) +
    propeller(32, 8, 6, c),

  "light-twin": (c) =>
    part("M10 24.5h44v4L32 32.5L10 28.5Z", c) +
    pod(21.5, 17, 33, 6.5, c) +
    pod(42.5, 17, 33, 6.5, c) +
    part(LIGHT_TAILPLANE_SWEPT, c) +
    part(
      "M32 8C35.2 8 36.5 12 36.5 17L36.5 38L34.5 50L32 52L29.5 50L27.5 38L27.5 17C27.5 12 28.8 8 32 8Z",
      c,
    ) +
    propeller(21.5, 16, 4.5, c) +
    propeller(42.5, 16, 4.5, c),

  "turboprop-twin": (c) =>
    part(
      "M32 8C34.5 8 35.5 11.5 35.5 15.5L35.5 42L34 52L32 54L30 52L28.5 42L28.5 15.5C28.5 11.5 29.5 8 32 8Z",
      c,
    ) +
    // Long high wing over the body, nacelles well outboard.
    `<rect x="8" y="22" width="48" height="7" rx="1.5" fill="${c.body}" stroke="${c.ink}" stroke-width="2"/>` +
    pod(20, 14, 36, 7, c) +
    pod(44, 14, 36, 7, c) +
    // T-tail, over the fin.
    part("M19 48h26v4.5H19z", c) +
    propeller(20, 13, 6, c) +
    propeller(44, 13, 6, c),

  "business-jet": (c) =>
    part("M11 37L28 27.5h8L53 37v3.5L36 35.5h-8L11 40.5Z", c) +
    part(
      "M32 8C34.5 8 35.5 11 35.5 15L35.5 44L34 54L32 56L30 54L28.5 44L28.5 15C28.5 11 29.5 8 32 8Z",
      c,
    ) +
    // Rear-mounted pods on the fuselage sides.
    pod(26, 40, 50, 4.5, c) +
    pod(38, 40, 50, 4.5, c) +
    part("M21 52L29 49.5h6L43 52v3L35 53.5h-6L21 55Z", c),

  narrowbody: (c) =>
    part("M7 41L28 23h8L57 41v5L36 38h-8L7 46Z", c) +
    pod(19, 26, 37, 5, c) +
    pod(45, 26, 37, 5, c) +
    part("M20 55L29 49h6L44 55v3L35 55h-6L20 58Z", c) +
    part(
      "M32 7C35 7 36 10.5 36 15L36 52L34 57L32 58L30 57L28 52L28 15C28 10.5 29 7 32 7Z",
      c,
    ),

  "widebody-twin": (c) =>
    part("M4 42L27 21h10L60 42v6L37 38h-10L4 48Z", c) +
    pod(16, 24, 38, 7, c) +
    pod(48, 24, 38, 7, c) +
    part("M16 56L28 48h8L48 56v3L36 55h-8L16 59Z", c) +
    part(
      "M32 4C36 4 37.5 8 37.5 13L37.5 52L35 59L32 60L29 59L26.5 52L26.5 13C26.5 8 28 4 32 4Z",
      c,
    ),

  "widebody-quad": (c) =>
    part("M3 43L27 21h10L61 43v6L37 38h-10L3 49Z", c) +
    pod(12, 31, 41, 5.5, c) +
    pod(21, 23, 35, 5.5, c) +
    pod(43, 23, 35, 5.5, c) +
    pod(52, 31, 41, 5.5, c) +
    part("M16 56L28 48h8L48 56v3L36 55h-8L16 59Z", c) +
    part(
      "M32 4C36.3 4 38 8 38 13L38 52L35.5 59L32 60L28.5 59L26 52L26 13C26 8 27.7 4 32 4Z",
      c,
    ),

  glider: (c) =>
    part(
      "M32 12C33.5 12 34 15 34 19L34 44L33 52L32 53L31 52L30 44L30 19C30 15 30.5 12 32 12Z",
      c,
    ) +
    // Wing over the body: gliders are shoulder-winged, and the unbroken span
    // is the whole point of the drawing.
    part("M2 26.5L30 25h4L62 26.5v2.5L34 30h-4L2 29Z", c) +
    blob(32, 20, 3, 6, c) +
    part("M24 49h16v3H24z", c),
} satisfies Record<
  | "light-high-wing"
  | "light-low-wing"
  | "light-cirrus"
  | "light-twin"
  | "turboprop-twin"
  | "business-jet"
  | "narrowbody"
  | "widebody-twin"
  | "widebody-quad"
  | "glider",
  IconArtwork
>;
