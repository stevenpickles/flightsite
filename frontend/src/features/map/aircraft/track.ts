/**
 * The selected aircraft's track polyline.
 *
 * Roadmap slice 014 asks for the *current sighting's* track for the selected
 * aircraft, and this slice has no way to fetch one: `/api/v1` exposes the live
 * picture and nothing historical, so the only positions the client can draw are
 * the ones it has watched arrive. Accumulation therefore starts at the moment
 * of selection.
 *
 * **The backfill seam, now filled (slice 061, issue #133).** The history read
 * API landed in slice 052, and {@link mergeTrackPoints} is the merge the seam
 * was left open for: `features/map/aircraft/useTrackBackfill` resolves the
 * selected aircraft's open sighting, maps its checkpointed `path` to
 * {@link TrackPoint}s, and hands them to the store's `backfillTrack`, which
 * merges them under the live-accumulated points. Every assumption the seam
 * relied on held: points are still plain `{lat, lon, at}` with a
 * UTC-millisecond timestamp, still kept in ascending `at` order, and `points`
 * is still a value the store swaps whole rather than a structure the renderer
 * mutates — so the backfill is a merge of two sorted lists into a new array,
 * and the renderer, the layer, and the store's state shape are untouched.
 */

/** One observed position of the selected aircraft. */
export interface TrackPoint {
  lat: number;
  lon: number;
  /** UTC milliseconds at which the client applied the update carrying it. */
  at: number;
}

/** The accumulating track, tied to the ICAO it was accumulated for so a stale
 * track can never be drawn against a newly selected aircraft. */
export interface SelectedTrack {
  icao: string;
  points: TrackPoint[];
}

/**
 * Cap on retained points.
 *
 * Positions arrive at roughly 1 Hz, so this is about fifteen minutes of flight
 * — comfortably longer than an aircraft stays inside a 250 nm display radius at
 * jet speeds, and short enough that the LineString handed to MapLibre stays
 * trivial to re-serialize on every frame.
 */
export const TRACK_MAX_POINTS = 900;

/** True when `point` is far enough from the last one to be worth keeping.
 * ADS-B repeats an unchanged position while an aircraft sits on a stand; those
 * repeats would otherwise consume the whole retention window. */
function isDistinct(
  previous: TrackPoint | undefined,
  point: TrackPoint,
): boolean {
  if (!previous) {
    return true;
  }
  return previous.lat !== point.lat || previous.lon !== point.lon;
}

/**
 * Returns the track with `point` appended, oldest points dropped past
 * {@link TRACK_MAX_POINTS}. Returns the original array unchanged when the point
 * repeats the last one, so an unchanged position costs no allocation and no
 * `setData` churn.
 */
export function appendTrackPoint(
  points: readonly TrackPoint[],
  point: TrackPoint,
): TrackPoint[] {
  if (!isDistinct(points[points.length - 1], point)) {
    return points as TrackPoint[];
  }
  const next = [...points, point];
  return next.length > TRACK_MAX_POINTS
    ? next.slice(next.length - TRACK_MAX_POINTS)
    : next;
}

/**
 * Merges a backfilled history track with the live-accumulated one.
 *
 * A straight two-pointer merge of two ascending-`at` lists, emitting only
 * strictly increasing timestamps. That single rule covers all three things the
 * backfill has to survive:
 *
 * * **Overlap.** The server's checkpoint lags the live picture, so the tail of
 *   `older` and the head of `newer` describe the same stretch of flight. Equal
 *   timestamps collapse to one point, and `newer` wins the tie — the client
 *   watched that fix arrive, where the checkpoint is a periodic summary of it.
 * * **Out-of-order input.** Neither list is trusted to be perfectly sorted (a
 *   response is server data, not an invariant this module established), and a
 *   naive merge of an unsorted list would draw a polyline that doubles back.
 *   A point that does not advance the clock is dropped instead.
 * * **Retention.** The merged result is capped at {@link TRACK_MAX_POINTS},
 *   keeping the newest — the same rule {@link appendTrackPoint} applies, so a
 *   long sighting's history yields to the part of the flight on screen now.
 *
 * The two lists date their points from *different clocks*: `older` carries the
 * receiver's timestamps and `newer` the browser's (see the store's docstring on
 * why the live picture is dated locally). A skew between them can only shift
 * where the two lists interleave inside the short overlap window, and both
 * describe the same trajectory there, so the drawn line is unaffected.
 *
 * Returns `newer` unchanged when the merge would add nothing, so a backfill
 * that turns out to be redundant costs no allocation and no `setData` churn.
 */
export function mergeTrackPoints(
  older: readonly TrackPoint[],
  newer: readonly TrackPoint[],
): TrackPoint[] {
  const merged: TrackPoint[] = [];
  let oldIndex = 0;
  let newIndex = 0;
  let keptFromOlder = 0;
  let keptFromNewer = 0;

  const push = (point: TrackPoint, fromNewer: boolean): void => {
    const last = merged[merged.length - 1];
    if (last !== undefined && point.at <= last.at) {
      return;
    }
    merged.push(point);
    if (fromNewer) {
      keptFromNewer += 1;
    } else {
      keptFromOlder += 1;
    }
  };

  while (oldIndex < older.length || newIndex < newer.length) {
    const left = older[oldIndex];
    const right = newer[newIndex];
    // `<=`, not `<`: on a tie the live-accumulated point is the one kept.
    if (right !== undefined && (left === undefined || right.at <= left.at)) {
      push(right, true);
      newIndex += 1;
    } else if (left !== undefined) {
      push(left, false);
      oldIndex += 1;
    } else {
      break;
    }
  }

  if (keptFromOlder === 0 && keptFromNewer === newer.length) {
    return newer as TrackPoint[];
  }
  return merged.length > TRACK_MAX_POINTS
    ? merged.slice(merged.length - TRACK_MAX_POINTS)
    : merged;
}
