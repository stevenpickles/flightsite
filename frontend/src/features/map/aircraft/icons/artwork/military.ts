/**
 * Military fixed-wing silhouettes and the UAV.
 *
 * - **Fighter.** The "arrow": long pointed nose, a body that widens at the
 *   intakes, a small highly swept wing set far aft, twin canted fins drawn as
 *   two ink strokes diverging aft, and small tailplanes.
 * - **Bomber.** A long slim tube under a thin, high-aspect swept wing with
 *   four paired engine pods — the B-52 read.
 * - **Tanker.** A 707-family planform (four pods on a swept wing) with the
 *   one thing no airliner has: a refuelling boom trailing straight aft of the
 *   tail, ruddevators and all.
 * - **Military transport.** A fat fuselage under a long high wing with four
 *   pods, and a big T-tail — C-17 and C-130 alike.
 * - **Maritime patrol.** A straight low wing with four nacelles and props, a
 *   slim tube and the MAD stinger trailing aft — the P-3 read.
 * - **UAV.** A very high-aspect wing on a tiny fuselage with a bulbous sensor
 *   nose, an inverted-V tail and a pusher propeller.
 */

import type { IconArtwork } from "@/features/map/aircraft/icons/artwork/types";
import {
  blob,
  line,
  part,
  pod,
  propeller,
} from "@/features/map/aircraft/icons/artwork/types";

export const MILITARY_ARTWORK = {
  fighter: (c) =>
    part("M13 46L29 30h6L51 46v4L35 46h-6L13 50Z", c) +
    part("M22 57L29 52.5h6L42 57v2.5L35 57.5h-6L22 59.5Z", c) +
    part(
      "M32 4C33.8 4 34.8 8 34.8 14L35 28L37 32L37 54L34 58L30 58L27 54L27 32L29 28L29.2 14C29.2 8 30.2 4 32 4Z",
      c,
    ) +
    // Twin canted fins.
    line("M28.5 44L25 56M35.5 44L39 56", c, 2.5),

  bomber: (c) =>
    part("M4 41L28 17h8L60 41v4L36 31h-8L4 45Z", c) +
    pod(11, 31, 39, 3.5, c) +
    pod(16.5, 25.5, 34, 3.5, c) +
    pod(47.5, 25.5, 34, 3.5, c) +
    pod(53, 31, 39, 3.5, c) +
    part("M18 55L28 50h8L46 55v3L36 54h-8L18 58Z", c) +
    part(
      "M32 4C34.5 4 35.5 8 35.5 13L35.5 52L34 59L32 60L30 59L28.5 52L28.5 13C28.5 8 29.5 4 32 4Z",
      c,
    ),

  tanker: (c) =>
    part("M7 40L28 21h8L57 40v5L36 36h-8L7 45Z", c) +
    pod(14, 30, 39, 4.5, c) +
    pod(22, 23, 32, 4.5, c) +
    pod(42, 23, 32, 4.5, c) +
    pod(50, 30, 39, 4.5, c) +
    part("M19 52L29 47h6L45 52v3L35 51h-6L19 55Z", c) +
    part(
      "M32 6C35 6 36 9.5 36 14L36 48L34 54L32 56L30 54L28 48L28 14C28 9.5 29 6 32 6Z",
      c,
    ) +
    // The boom: cased like every other part, ink under body.
    line("M32 55v7", c, 3.5) +
    `<path d="M32 55v7" fill="none" stroke="${c.body}" stroke-width="1.5" stroke-linecap="round"/>` +
    line("M28.5 59.5L32 62L35.5 59.5", c, 2),

  "military-transport": (c) =>
    part(
      "M32 8C36.3 8 38 12 38 17L38 44L35.5 54L32 56L28.5 54L26 44L26 17C26 12 27.7 8 32 8Z",
      c,
    ) +
    // High wing over the body, mild sweep, four pods.
    part("M5 31L27 24h10L59 31v5L37 32h-10L5 36Z", c) +
    pod(14, 23, 36, 5.5, c) +
    pod(22, 20, 34, 5.5, c) +
    pod(42, 20, 34, 5.5, c) +
    pod(50, 23, 36, 5.5, c) +
    part("M18 48h28v5H18z", c),

  patrol: (c) =>
    `<rect x="7" y="24" width="50" height="8" rx="1" fill="${c.body}" stroke="${c.ink}" stroke-width="2"/>` +
    pod(15, 16, 35, 5, c) +
    pod(23, 16, 35, 5, c) +
    pod(41, 16, 35, 5, c) +
    pod(49, 16, 35, 5, c) +
    part("M20 45.5h24v4H20z", c) +
    part(
      "M32 6C34.5 6 35.5 9.5 35.5 14L35.5 42L34 50L32 52L30 50L28.5 42L28.5 14C28.5 9.5 29.5 6 32 6Z",
      c,
    ) +
    propeller(15, 15, 4, c) +
    propeller(23, 15, 4, c) +
    propeller(41, 15, 4, c) +
    propeller(49, 15, 4, c) +
    // MAD stinger.
    line("M32 52v8", c, 2.5),

  uav: (c) =>
    part(
      "M32 14C34 14 35 17 35 21L35 42L33.5 50L32 51L30.5 50L29 42L29 21C29 17 30 14 32 14Z",
      c,
    ) +
    part("M2 29L30 28h4L62 29v2.5L34 32h-4L2 31.5Z", c) +
    blob(32, 19, 3.8, 5.5, c) +
    // Inverted-V tail and the pusher propeller behind it.
    line("M32 44L25.5 54M32 44L38.5 54", c, 2.5) +
    propeller(32, 52, 5, c),
} satisfies Record<
  "fighter" | "bomber" | "tanker" | "military-transport" | "patrol" | "uav",
  IconArtwork
>;
