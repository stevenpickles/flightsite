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
 * and the renderer and the layer are untouched.
 */

/** One observed position of the selected aircraft. */
export interface TrackPoint {
  lat: number;
  lon: number;
  /**
   * UTC milliseconds at which the position was *fixed* — not at which anything
   * learned about it.
   *
   * A live point carries the store's `positionChangedAt`, the arrival of the
   * frame that first brought this fix less the age the decoder reported for it
   * (issue #145, and see that store's docstring); a backfilled one carries the
   * receiver's own checkpoint timestamp. The two are therefore *measuring* the
   * same thing while *reading* different clocks, which is the whole of what
   * {@link mergeTrackPoints} has to reconcile.
   */
  at: number;
}

/** The accumulating track, tied to the ICAO it was accumulated for so a stale
 * track can never be drawn against a newly selected aircraft. This is the
 * whole of what the renderer needs; the bookkeeping a backfill requires lives
 * beside it in the store, not in here. */
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
 *
 * Appends in call order and never inspects `at`: keeping the list ascending is
 * the caller's job, and the store does it by holding each live point strictly
 * after the one it follows (issue #145 — a fix-dated point can otherwise
 * anchor behind its predecessor when the reported age jumps between polls).
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
 * `points` in ascending `at` order, by identity when it already is.
 *
 * The scan is the point: an already-ordered list — which is every list either
 * caller actually produces — is returned as-is, so the defensive sort costs one
 * pass and no allocation, and the identity result is what lets
 * {@link mergeTrackPoints} recognise an unchanged track.
 *
 * `Array.prototype.sort` is stable, so points sharing an `at` keep the order
 * they were given in.
 */
function ascendingByAt(points: readonly TrackPoint[]): readonly TrackPoint[] {
  for (let index = 1; index < points.length; index += 1) {
    if (
      (points[index] as TrackPoint).at < (points[index - 1] as TrackPoint).at
    ) {
      return [...points].sort((left, right) => left.at - right.at);
    }
  }
  return points;
}

/**
 * Merges a backfilled history track with the live-accumulated one.
 *
 * The pipeline, in order:
 *
 * 1. **Sort both inputs defensively** (stable, by `at`).
 * 2. **Clamp `older`** to before `newer[0].at`, when `newer` has any points.
 * 3. **Merge** the two sorted lists, de-duplicating on `at`.
 * 4. **Cap** at {@link TRACK_MAX_POINTS}, keeping the newest — the same rule
 *    {@link appendTrackPoint} applies, so a long sighting's history yields to
 *    the part of the flight on screen now.
 *
 * The two halves of that de-duplication belong to different steps. *Across*
 * the lists it is the clamp's job and already done by the time the merge runs:
 * every surviving `older` point precedes `newer[0]`, so no cross-list
 * collision reaches step 3 and its tie-break branch is unreachable — kept as a
 * defensive expression of "the live point wins", not as live logic. What step
 * 3 does de-duplicate is *within* a list: two points sharing an `at`, which
 * neither input is trusted to be free of.
 *
 * Steps 1 and 2 each exist for a specific failure:
 *
 * * **Clock skew** (step 2), and not as a corner case. The two lists are dated
 *   by *different clocks*: `older` carries the receiver's timestamps
 *   (`path[].t`) and `newer` the browser's, back-dated to the fix the point
 *   records (the store's docstring explains why the live picture is dated
 *   locally, and issue #145 why it is dated at the fix). Both lists therefore
 *   date the same event — the decode — and the residue is the skew alone,
 *   where before #145 a systematic `seen_pos_s` of offset rode on top of it.
 *   A receiver clock running ahead of the browser by more than the sighting's
 *   pre-selection age lands the *whole* history after the live points, and an
 *   unclamped merge then draws the current position, folds back to where the
 *   aircraft was minutes ago, and re-traces forward — tens of nautical miles of
 *   polyline that no aircraft flew. Clamping degrades gracefully instead: a
 *   skew that large backfills nothing, which is the pre-slice-061 picture
 *   rather than a wrong one. The clamp also subsumes the checkpoint-lag
 *   overlap, where the tail of `older` and the head of `newer` describe the
 *   same stretch of flight.
 * * **Out-of-order input** (step 1). Neither list is trusted to be sorted: a
 *   response is server data, not an invariant this module established. Sorting
 *   keeps that distrust *local* to the offending point. Dropping any point
 *   that failed to advance the clock — the previous rule, issue #137 — was not
 *   a reorder guard at all but an amplifier: one spike at `t100` in
 *   `[t1, t100, t2, t3, t4, t5]` silently swallowed the entire tail, turning a
 *   single bad point into four lost ones. A sort lands the spike in its own
 *   place and keeps everything else.
 *
 * Returns `newer` unchanged when the merge would add nothing to it and it was
 * already ordered, so a backfill that turns out to be redundant costs no
 * allocation and no `setData` churn.
 */
export function mergeTrackPoints(
  older: readonly TrackPoint[],
  newer: readonly TrackPoint[],
): TrackPoint[] {
  const history = ascendingByAt(older);
  const live = ascendingByAt(newer);

  const merged: TrackPoint[] = [];
  let oldIndex = 0;
  let newIndex = 0;
  let keptFromOlder = 0;
  let keptFromNewer = 0;

  // `newer` owns everything from its first point onwards, whatever it is: the
  // live-accumulated list on a first backfill, the already-drawn track on the
  // idempotent same-sighting path. With no points there to defer to, the whole
  // history is drawable.
  const liveFrom = live[0]?.at ?? Number.POSITIVE_INFINITY;

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

  while (oldIndex < history.length || newIndex < live.length) {
    const left = history[oldIndex];
    if (left !== undefined && left.at >= liveFrom) {
      // Inside the region `newer` owns — including, under a large enough skew,
      // the entire history.
      oldIndex += 1;
      continue;
    }
    const right = live[newIndex];
    // The `<=` half of this test is unreachable: the clamp above has already
    // dropped every `left` that could tie with a `right`. It stays as the
    // defensive statement of which point would win — the live one, watched
    // arriving, over a checkpoint that only summarises it.
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

  // `live === newer` matters: a `newer` that had to be sorted is not the array
  // the caller passed in, so returning it would keep the disorder on screen.
  if (live === newer && keptFromOlder === 0 && keptFromNewer === newer.length) {
    return newer as TrackPoint[];
  }
  return merged.length > TRACK_MAX_POINTS
    ? merged.slice(merged.length - TRACK_MAX_POINTS)
    : merged;
}
