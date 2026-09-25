/**
 * The one line that says what the drawn path actually is (review R2-12).
 *
 * The Path section rendered eleven vertices next to a Reception block
 * reading "Position reports 543", with nothing anywhere to say the line was
 * a sample — so a reader comparing the two numbers on one screen could only
 * conclude that one of them was wrong. Both are right, for different
 * reasons, and the difference is worth one sentence:
 *
 * - A **closed** sighting's path is simplified on purpose (SPEC §19,
 *   "simplify the historical path using an appropriate geometry reduction
 *   algorithm"), so the sentence names the reduction.
 * - An **open** sighting's path is the crash-recovery checkpoint tail from
 *   `sighting_track_checkpoints` — roughly one point every 30 seconds — so
 *   the sentence names the cadence and points at the Live Map, which has the
 *   full current track (§19 again: "retain the full current track").
 */

function points(count: number): string {
  return `${count.toLocaleString()} ${count === 1 ? "point" : "points"}`;
}

/** `null` when there is nothing drawn to describe — the map is showing its
 * own "no path was recorded" message in that case, which says more. */
export function describePathSample(
  pathPoints: number,
  positionCount: number,
  isOpen: boolean,
): string | null {
  if (pathPoints === 0) {
    return null;
  }
  if (isOpen) {
    return `${points(pathPoints)} so far, checkpointed about every 30 seconds — the Live Map has this aircraft's full current track.`;
  }
  const reports =
    positionCount === 1
      ? "1 position report"
      : `${positionCount.toLocaleString()} position reports`;
  return `${points(pathPoints)}, simplified from ${reports}.`;
}
