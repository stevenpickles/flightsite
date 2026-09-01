/**
 * Current-track mini stats (scope item 7): point count and duration of the
 * track accumulated since selection, from `useLiveAircraftStore`'s
 * `track` (`features/map/aircraft/track.ts`). Deliberately subtle — this
 * is a by-product of the map's own accumulation, not a stored history
 * record (the real per-sighting track arrives with the 052 backfill seam
 * `track.ts` documents), so it reads as a small aside, not a headline stat.
 */

import { formatDurationShort } from "@/features/aircraft-detail/lib/format";
import type { SelectedTrack } from "@/features/map/aircraft/track";

export interface TrackStatsProps {
  track: SelectedTrack | null;
}

export function TrackStats({ track }: TrackStatsProps) {
  const points = track?.points ?? [];
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
