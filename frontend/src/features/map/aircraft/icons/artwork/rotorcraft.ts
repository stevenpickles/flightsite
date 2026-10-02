/**
 * Rotary-wing silhouettes. The rotor disc — a faint circle for the swept area
 * with two cased crossed blades — is the family's signature, and each shape
 * places it differently:
 *
 * - **Helicopter.** One disc over a teardrop cabin, a tapering tail boom with
 *   a stabiliser and the tail rotor off to one side.
 * - **Tiltrotor.** Two discs on nacelles at the tips of a straight wing, with
 *   an H-tail — the V-22 read.
 * - **Tandem rotor.** Two overlapping discs fore and aft of a long boxy
 *   fuselage with a rear pylon and no tail rotor — the Chinook read.
 */

import type { IconArtwork } from "@/features/map/aircraft/icons/artwork/types";
import {
  blob,
  line,
  part,
  pod,
  rotor,
} from "@/features/map/aircraft/icons/artwork/types";

export const ROTORCRAFT_ARTWORK = {
  rotorcraft: (c) =>
    part("M30 37h4L33.5 53h-3Z", c) +
    part("M27 47h10v3H27z", c) +
    line("M33 54h7", c, 2.5) +
    blob(32, 27, 9.5, 12, c) +
    rotor(32, 27, 20, c),

  tiltrotor: (c) =>
    part(
      "M32 14C35.5 14 37 18 37 22L37 44L35 50L32 52L29 50L27 44L27 22C27 18 28.5 14 32 14Z",
      c,
    ) +
    `<rect x="10" y="26" width="44" height="7" rx="1.5" fill="${c.body}" stroke="${c.ink}" stroke-width="2"/>` +
    part("M22 46h20v4H22z", c) +
    line("M24 44v8M40 44v8", c, 2.5) +
    pod(13, 19, 37, 7, c) +
    pod(51, 19, 37, 7, c) +
    rotor(13, 23, 10, c) +
    rotor(51, 23, 10, c),

  "tandem-rotor": (c) =>
    `<rect x="25" y="10" width="14" height="44" rx="5" fill="${c.body}" stroke="${c.ink}" stroke-width="2"/>` +
    // Rear pylon, wider than the cabin.
    `<rect x="22" y="40" width="20" height="8" rx="3" fill="${c.body}" stroke="${c.ink}" stroke-width="2"/>` +
    rotor(32, 19, 12, c) +
    rotor(32, 46, 12, c),
} satisfies Record<"rotorcraft" | "tiltrotor" | "tandem-rotor", IconArtwork>;
