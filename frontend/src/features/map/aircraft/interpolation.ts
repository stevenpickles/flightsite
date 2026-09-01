/**
 * Position smoothing between 1 Hz updates.
 *
 * The socket delivers a batch about once a second (`docs/API.md` §4.3). Drawn
 * as-is, a 450 kt airliner jumps ~0.13 nm at a time — clearly a stutter at any
 * useful zoom. Between updates each aircraft is therefore dead-reckoned along
 * its last reported velocity: `track_deg` for direction, `ground_speed_kt` for
 * rate, and the store's `receivedAt` for elapsed time.
 *
 * **Why dead reckoning rather than tweening between the last two positions.**
 * Tweening is smooth but wrong twice over: it renders the aircraft a full
 * update *behind* where it was last reported, and it needs two positions, which
 * a newly appeared aircraft does not have. Projecting forward from the latest
 * report keeps the marker at the receiver's best estimate of *now*, and the
 * next update simply supersedes it. Reported values are never modified — the
 * detail panel and every other consumer read the payload, not this projection.
 *
 * **Bounds.** Projection stops after {@link INTERPOLATION_MAX_MS}. If the
 * stream stalls — a suspended tab, a dead backend, a client mid-reconnect —
 * extrapolation would otherwise fly aircraft across the map on the strength of
 * a stale velocity, which is fabricated data, not smoothing. Stale aircraft are
 * never projected at all: staleness means the receiver has stopped hearing
 * them, so their last known position is the honest thing to draw.
 *
 * The flat-earth conversion (1 nm = 1/60°, longitude scaled by cos φ) is exact
 * enough by orders of magnitude at these distances: one second at 600 kt is
 * 0.17 nm, where the error against a great-circle projection is well under a
 * metre outside the polar regions the `cos φ` clamp already guards.
 */

import type { LiveAircraftRecord } from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { GeoPosition } from "@/lib/api/live";

/** How far past the last update an aircraft may be projected. Four seconds is
 * a few missed deltas — enough to ride out a hiccup, short enough that a
 * genuinely dead stream freezes rather than inventing motion. */
export const INTERPOLATION_MAX_MS = 4_000;

/** Nautical miles per degree of latitude. */
const NM_PER_DEGREE = 60;

const MS_PER_HOUR = 3_600_000;

/** Keeps the longitude scaling finite near the poles (cos φ → 0). At 89.4°
 * the scale factor is already ~100×, past which "smoothing" is noise. */
const MIN_COS_LATITUDE = 0.01;

const DEG_TO_RAD = Math.PI / 180;

/** Wraps a longitude back into [-180, 180) so a projection across the
 * antimeridian produces a drawable coordinate rather than 181°. */
export function normalizeLongitude(lon: number): number {
  const wrapped = (((lon + 180) % 360) + 360) % 360;
  return wrapped - 180;
}

/**
 * The position reached by travelling `elapsedMs` from `from` on a constant
 * `trackDeg` heading at `groundSpeedKt`.
 *
 * @param trackDeg - degrees clockwise from true north.
 */
export function projectPosition(
  from: GeoPosition,
  trackDeg: number,
  groundSpeedKt: number,
  elapsedMs: number,
): GeoPosition {
  const distanceNm = (groundSpeedKt * elapsedMs) / MS_PER_HOUR;
  const radians = trackDeg * DEG_TO_RAD;
  const deltaLat = (distanceNm * Math.cos(radians)) / NM_PER_DEGREE;
  const cosLat = Math.max(
    MIN_COS_LATITUDE,
    Math.abs(Math.cos(from.lat * DEG_TO_RAD)),
  );
  const deltaLon = (distanceNm * Math.sin(radians)) / (NM_PER_DEGREE * cosLat);
  return {
    lat: Math.max(-90, Math.min(90, from.lat + deltaLat)),
    lon: normalizeLongitude(from.lon + deltaLon),
  };
}

/**
 * Where to draw `record` at `now`: its projected position when it is airborne,
 * live, moving and positioned; its reported position otherwise; `null` when it
 * has no position at all (a Mode S-only entry, SPEC §20 — part of the live
 * picture, but not something the map can place).
 */
export function displayPosition(
  record: LiveAircraftRecord,
  now: number,
): GeoPosition | null {
  const { aircraft, receivedAt } = record;
  const position = aircraft.position;
  if (!position) {
    return null;
  }
  if (aircraft.state === "stale" || aircraft.on_ground === true) {
    return position;
  }
  const { track_deg: track, ground_speed_kt: speed } = aircraft;
  if (track === null || speed === null || speed <= 0) {
    return position;
  }
  const elapsed = Math.min(INTERPOLATION_MAX_MS, Math.max(0, now - receivedAt));
  if (elapsed === 0) {
    return position;
  }
  return projectPosition(position, track, speed, elapsed);
}
