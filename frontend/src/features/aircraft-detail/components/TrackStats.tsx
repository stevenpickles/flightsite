/**
 * Current-track mini stats (scope item 7): how much track the client has
 * watched arrive since the aircraft was selected. Deliberately subtle — a
 * by-product of the map's own accumulation, not a stored history record, so it
 * reads as a small aside rather than a headline stat.
 *
 * Fed from the store's `trackLive`, **not** from the drawn track's `points`.
 * Since slice 061 those are different things: the drawn track is backfilled
 * from the open sighting's checkpointed path, so its first point is where the
 * sighting began — timestamped by the *receiver's* clock — and reading a
 * duration off it made this line claim a 20-minute-old flight had been
 * selected for 20 minutes, from the instant it was clicked. `trackLive` is the
 * one list actually dated by the selection, so both numbers here come from it
 * and the "since selection" clause governs the whole sentence. The drawn
 * track's own extent is on the map, where it can be seen rather than counted.
 */

import { formatDurationShort } from "@/features/aircraft-detail/lib/format";
import type { TrackPoint } from "@/features/map/aircraft/track";

export interface TrackStatsProps {
  /** Positions watched arriving since selection — `useLiveAircraftStore`'s
   * `trackLive`. */
  points: readonly TrackPoint[];
}

export function TrackStats({ points }: TrackStatsProps) {
  if (points.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">No track accumulated yet.</p>
    );
  }

  const first = points[0];
  const last = points[points.length - 1];
  const durationMs = first && last ? last.at - first.at : 0;

  return (
    <p className="text-xs text-muted-foreground">
      {points.length} point{points.length === 1 ? "" : "s"} ·{" "}
      {formatDurationShort(durationMs)} since selection
    </p>
  );
}
