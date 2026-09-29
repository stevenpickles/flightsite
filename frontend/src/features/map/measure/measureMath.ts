/**
 * The maths behind the Live Map's measure tool (roadmap slice 085, issue
 * #228): great-circle distance and initial bearing between two points, and
 * the densified great-circle line the map draws between them.
 *
 * Spherical-earth throughout, reusing `geo/rings.ts`'s haversine distance
 * and direct-geodesic `destinationPoint` — the same approximation the range
 * rings are drawn with, so a measured 100 nm lands exactly on the 100 nm
 * ring. The error against WGS84 is a small fraction of a percent at receiver
 * scales, well under what a click on a map can resolve.
 *
 * Distances are nautical miles here, as everywhere below the display layer
 * (`CLAUDE.md`); {@link describeMeasurement} converts to the receiver's
 * display units only when it formats, with the same unit-aware formatter the
 * Receiver page uses (`features/receiver/lib/format.ts`).
 */

import {
  destinationPoint,
  greatCircleDistanceNm,
  type LatLon,
} from "@/features/map/geo/rings";
import {
  cardinalFromDegrees,
  formatDistance,
} from "@/features/receiver/lib/format";
import type { UnitSystem } from "@/lib/api/config";

function toRadians(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

function toDegrees(radians: number): number {
  return (radians * 180) / Math.PI;
}

/**
 * The initial (forward) great-circle bearing from `from` to `to`, in degrees
 * clockwise from true north, `[0, 360)`. The bearing a navigator would set
 * off on — on a long line the heading drifts along the way, which is why it
 * is "initial". `0` for coincident points, which have no direction.
 */
export function initialBearingDeg(from: LatLon, to: LatLon): number {
  const lat1 = toRadians(from.lat);
  const lat2 = toRadians(to.lat);
  const dLon = toRadians(to.lon - from.lon);
  const y = Math.sin(dLon) * Math.cos(lat2);
  const x =
    Math.cos(lat1) * Math.sin(lat2) -
    Math.sin(lat1) * Math.cos(lat2) * Math.cos(dLon);
  if (x === 0 && y === 0) {
    return 0;
  }
  return (toDegrees(Math.atan2(y, x)) + 360) % 360;
}

/** How many straight segments approximate the great-circle line. Enough that
 * a 250 nm line's chords sit well under a pixel off the true curve at any
 * zoom the whole line fits on screen; cheap because it is built once per
 * click, not per frame. */
export const MEASURE_LINE_SEGMENTS = 64;

export interface Measurement {
  from: LatLon;
  to: LatLon;
  distanceNm: number;
  /** Initial bearing, degrees true, `[0, 360)`. */
  bearingDeg: number;
}

export function measure(from: LatLon, to: LatLon): Measurement {
  return {
    from,
    to,
    distanceNm: greatCircleDistanceNm(from, to),
    bearingDeg: initialBearingDeg(from, to),
  };
}

/** The great-circle line from `from` to `to` as `[lon, lat]` pairs, both
 * endpoints included — what the measure layer draws. */
export function greatCircleLine(
  measurement: Measurement,
  segments: number = MEASURE_LINE_SEGMENTS,
): [number, number][] {
  const { from, to, distanceNm, bearingDeg } = measurement;
  const coordinates: [number, number][] = [[from.lon, from.lat]];
  for (let step = 1; step < segments; step += 1) {
    const point = destinationPoint(
      from,
      bearingDeg,
      (distanceNm * step) / segments,
    );
    coordinates.push([point.lon, point.lat]);
  }
  coordinates.push([to.lon, to.lat]);
  return coordinates;
}

/** The point halfway along the great circle — where the map puts the
 * measurement's label. */
export function greatCircleMidpoint(measurement: Measurement): LatLon {
  return destinationPoint(
    measurement.from,
    measurement.bearingDeg,
    measurement.distanceNm / 2,
  );
}

/** A whole-degree bearing as the three-digit form aviation reads bearings
 * in: `5.4` → `"005°"`, `359.6` → `"000°"` (360 is north, and north is 000). */
export function formatBearing(bearingDeg: number): string {
  const whole = Math.round(bearingDeg) % 360;
  return `${whole.toString().padStart(3, "0")}°`;
}

/**
 * The one-line readout for a measurement: distance in the receiver's units,
 * then the initial bearing in degrees and as a 16-point cardinal, e.g.
 * `"42.7 nm · 045° NE"` or, metric, `"79.1 km · 045° NE"`.
 */
export function describeMeasurement(
  measurement: Measurement,
  units: UnitSystem,
): string {
  const distance = formatDistance(measurement.distanceNm, units) ?? "";
  const cardinal = cardinalFromDegrees(measurement.bearingDeg);
  return `${distance} · ${formatBearing(measurement.bearingDeg)} ${cardinal}`;
}
