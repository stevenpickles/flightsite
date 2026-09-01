/**
 * Turns a sighting's decoded path into the GeoJSON `SightingPathLayer` draws:
 * one line (segmented for altitude coloring when that is cheap to compute,
 * a single feature otherwise) and two point features for the start/end
 * markers. Pure and synchronous — computed once when a sighting's path
 * arrives, not per frame, since a stored path never changes.
 */

import type { Feature, FeatureCollection, LineString, Point } from "geojson";

import type { SightingPathPoint } from "@/lib/api/sightings";

export interface PathSegmentProperties {
  /** Mean altitude of the segment's two endpoints, in feet — the value the
   * line-color expression interpolates over. `null` when the sighting has
   * no altitude data to color by. */
  altitude_ft: number | null;
}

export interface PathPointProperties {
  kind: "start" | "end";
  t: string;
}

export interface PathGeojson {
  /** One feature per consecutive pair of points ("altitude-colored" mode) or
   * one feature for the whole path ("plain accent" mode, when fewer than
   * two points carry an altitude). */
  line: FeatureCollection<LineString, PathSegmentProperties>;
  /** The start and end points, for the two markers. Empty when `path` is
   * empty. */
  endpoints: FeatureCollection<Point, PathPointProperties>;
  /** `[min, max]` altitude across the path, or `null` when fewer than two
   * points carry an altitude (not worth coloring by). */
  altitudeRangeFt: [number, number] | null;
  /** `[[minLon, minLat], [maxLon, maxLat]]`, or `null` for an empty path —
   * what `SightingPathLayer` fits the camera to. */
  bounds: [[number, number], [number, number]] | null;
}

export function buildPathGeojson(
  path: readonly SightingPathPoint[],
): PathGeojson {
  if (path.length === 0) {
    return {
      line: { type: "FeatureCollection", features: [] },
      endpoints: { type: "FeatureCollection", features: [] },
      altitudeRangeFt: null,
      bounds: null,
    };
  }

  const altitudes = path
    .map((point) => point.altitude_ft)
    .filter((value): value is number => value !== null);
  const altitudeRangeFt: [number, number] | null =
    altitudes.length >= 2
      ? [Math.min(...altitudes), Math.max(...altitudes)]
      : null;

  const lineFeatures: Feature<LineString, PathSegmentProperties>[] = [];
  if (path.length === 1) {
    // A single-point path has no line to draw — only the (coincident)
    // start/end markers below.
  } else if (altitudeRangeFt === null) {
    lineFeatures.push({
      type: "Feature",
      properties: { altitude_ft: null },
      geometry: {
        type: "LineString",
        coordinates: path.map((point) => [point.lon, point.lat]),
      },
    });
  } else {
    for (let index = 0; index < path.length - 1; index += 1) {
      const start = path[index];
      const end = path[index + 1];
      if (!start || !end) {
        continue;
      }
      const segmentAltitudes = [start.altitude_ft, end.altitude_ft].filter(
        (value): value is number => value !== null,
      );
      const meanAltitude =
        segmentAltitudes.length > 0
          ? segmentAltitudes.reduce((sum, value) => sum + value, 0) /
            segmentAltitudes.length
          : null;
      lineFeatures.push({
        type: "Feature",
        properties: { altitude_ft: meanAltitude },
        geometry: {
          type: "LineString",
          coordinates: [
            [start.lon, start.lat],
            [end.lon, end.lat],
          ],
        },
      });
    }
  }

  const first = path[0] as SightingPathPoint;
  const last = path[path.length - 1] as SightingPathPoint;
  const endpoints: FeatureCollection<Point, PathPointProperties> = {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        properties: { kind: "start", t: first.t },
        geometry: { type: "Point", coordinates: [first.lon, first.lat] },
      },
      {
        type: "Feature",
        properties: { kind: "end", t: last.t },
        geometry: { type: "Point", coordinates: [last.lon, last.lat] },
      },
    ],
  };

  const lons = path.map((point) => point.lon);
  const lats = path.map((point) => point.lat);
  const bounds: [[number, number], [number, number]] = [
    [Math.min(...lons), Math.min(...lats)],
    [Math.max(...lons), Math.max(...lats)],
  ];

  return {
    line: { type: "FeatureCollection", features: lineFeatures },
    endpoints,
    altitudeRangeFt,
    bounds,
  };
}
