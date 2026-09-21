/**
 * The key to the path map's colours and markers (review R2-17).
 *
 * The line is coloured by altitude and the two endpoints are marked, and
 * neither was explained anywhere on the page — colour as the only channel,
 * with the added trap that the markers used to be a red/green pair a few
 * pixels from an altitude ramp whose ends are green and red for an entirely
 * unrelated reason.
 *
 * The swatches read from `ALTITUDE_RAMP`, the same constant the paint
 * expression interpolates over, so the key cannot drift from the map. The
 * altitudes are formatted in the receiver's unit system like every other
 * altitude on the page, and the markers are described by shape, which is
 * what actually distinguishes them now.
 */

import { formatAltitude } from "@/features/aircraft-detail/lib/format";
import { ALTITUDE_RAMP } from "@/features/sighting-detail/lib/pathColors";
import type { UnitSystem } from "@/lib/api/config";

export interface SightingPathLegendProps {
  units: UnitSystem;
  /** `false` when fewer than two points carried an altitude, in which case
   * the line is drawn in a single accent colour and an altitude key would
   * describe something that is not on screen. */
  altitudeColored: boolean;
}

export function SightingPathLegend({
  units,
  altitudeColored,
}: SightingPathLegendProps) {
  return (
    <ul
      data-testid="path-legend"
      className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground"
    >
      {altitudeColored &&
        ALTITUDE_RAMP.map((stop) => (
          <li key={stop.ft} className="flex items-center gap-1.5">
            <span
              aria-hidden="true"
              style={{ backgroundColor: stop.color }}
              className="inline-block h-1.5 w-4 rounded-full"
            />
            {formatAltitude(stop.ft, units)}
          </li>
        ))}
      <li className="flex items-center gap-1.5">
        <span
          aria-hidden="true"
          className="inline-block size-2.5 rounded-full border-2 border-accent bg-card"
        />
        Start
      </li>
      <li className="flex items-center gap-1.5">
        <span
          aria-hidden="true"
          className="inline-block size-2.5 rounded-full bg-accent"
        />
        End
      </li>
    </ul>
  );
}
