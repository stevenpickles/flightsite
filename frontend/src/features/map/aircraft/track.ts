/**
 * The selected aircraft's track polyline.
 *
 * Roadmap slice 014 asks for the *current sighting's* track for the selected
 * aircraft, and this slice has no way to fetch one: `/api/v1` exposes the live
 * picture and nothing historical, so the only positions the client can draw are
 * the ones it has watched arrive. Accumulation therefore starts at the moment
 * of selection.
 *
 * **The backfill seam.** A history read API lands in slice 052; when it does,
 * the track for the open sighting can be fetched and *prepended* to whatever
 * has accumulated here. Everything this module needs for that is already true:
 * points are plain `{lat, lon, at}` with a UTC-millisecond timestamp, they are
 * kept in ascending `at` order, and `points` is a value the store swaps whole
 * rather than a structure the renderer mutates. A backfill is then a merge of
 * two sorted point lists into a new array, with no change to the renderer, the
 * layer, or the store's shape.
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
