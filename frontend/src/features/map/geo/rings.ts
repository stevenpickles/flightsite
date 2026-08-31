import type { Feature, FeatureCollection, LineString, Point } from "geojson";

import type {
  DistanceUnit,
  MapConfig,
  ReceiverPosition,
} from "@/features/map/types";

/** Mean earth radius in nautical miles (6371 km / 1.852 km-per-nm). Range
 * rings use a spherical-earth great-circle approximation — accurate to a
 * small fraction of a percent at the scales a receiver's display radius
 * covers, and consistent with how the rest of the map treats geography.
 * Full WGS84 ellipsoidal geodesy is not warranted for a visual ring aid. */
export const EARTH_RADIUS_NM = 3440.065;

const NM_PER_KM = 1 / 1.852;

function toRadians(degrees: number): number {
  return (degrees * Math.PI) / 180;
}

function toDegrees(radians: number): number {
  return (radians * 180) / Math.PI;
}

/** Normalizes a longitude to the [-180, 180] range. */
function normalizeLongitude(lon: number): number {
  return ((lon + 540) % 360) - 180;
}

export interface LatLon {
  lat: number;
  lon: number;
}

/**
 * Computes the point reached by travelling `distanceNm` along a great
 * circle from `origin` on initial bearing `bearingDeg` (0 = north, 90 =
 * east). Standard spherical direct-geodesic ("destination point") formula.
 */
export function destinationPoint(
  origin: LatLon,
  bearingDeg: number,
  distanceNm: number,
): LatLon {
  const angularDistance = distanceNm / EARTH_RADIUS_NM;
  const bearing = toRadians(bearingDeg);
  const lat1 = toRadians(origin.lat);
  const lon1 = toRadians(origin.lon);

  const sinLat2 =
    Math.sin(lat1) * Math.cos(angularDistance) +
    Math.cos(lat1) * Math.sin(angularDistance) * Math.cos(bearing);
  const lat2 = Math.asin(sinLat2);

  const y = Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(lat1);
  const x = Math.cos(angularDistance) - Math.sin(lat1) * sinLat2;
  const lon2 = lon1 + Math.atan2(y, x);

  return { lat: toDegrees(lat2), lon: normalizeLongitude(toDegrees(lon2)) };
}

/**
 * Great-circle distance between two points, in nautical miles (haversine
 * formula). Used to sanity-check ring geometry independently of
 * `destinationPoint`'s bearing-walk construction.
 */
export function greatCircleDistanceNm(a: LatLon, b: LatLon): number {
  const lat1 = toRadians(a.lat);
  const lat2 = toRadians(b.lat);
  const dLat = toRadians(b.lat - a.lat);
  const dLon = toRadians(b.lon - a.lon);

  const sinDLat = Math.sin(dLat / 2);
  const sinDLon = Math.sin(dLon / 2);
  const h =
    sinDLat * sinDLat + Math.cos(lat1) * Math.cos(lat2) * sinDLon * sinDLon;
  const c = 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h));
  return EARTH_RADIUS_NM * c;
}

/** Default number of segments used to draw a ring polygon. High enough to
 * look smooth at any zoom level a receiver's display radius is viewed at. */
export const DEFAULT_RING_STEPS = 128;

/**
 * Generates the closed line of `[lon, lat]` coordinate pairs (GeoJSON
 * order) approximating a geodesic circle of `radiusNm` around `center`.
 */
export function generateRingCoordinates(
  center: LatLon,
  radiusNm: number,
  steps: number = DEFAULT_RING_STEPS,
): [number, number][] {
  const coordinates: [number, number][] = [];
  for (let i = 0; i <= steps; i += 1) {
    const bearing = (360 * i) / steps;
    const point = destinationPoint(center, bearing, radiusNm);
    coordinates.push([point.lon, point.lat]);
  }
  return coordinates;
}

export function nmToKm(nm: number): number {
  return nm * 1.852;
}

export function kmToNm(km: number): number {
  return km * NM_PER_KM;
}

/** Formats a ring's radius as a unit-aware label, e.g. "100 nm" or "185 km". */
export function formatRingLabel(radiusNm: number, unit: DistanceUnit): string {
  if (unit === "km") {
    return `${Math.round(nmToKm(radiusNm))} km`;
  }
  return `${radiusNm} nm`;
}

export interface RangeRingProperties {
  radiusNm: number;
  label: string;
}

/** GeoJSON FeatureCollection of range-ring outlines (one LineString per
 * configured radius), ready to hand to a MapLibre GeoJSON source. */
export function generateRangeRingsGeoJSON(
  config: Pick<MapConfig, "receiver" | "ringRadiiNm" | "unit">,
): FeatureCollection<LineString, RangeRingProperties> {
  const { receiver, ringRadiiNm, unit } = config;
  return {
    type: "FeatureCollection",
    features: ringRadiiNm.map((radiusNm) => ({
      type: "Feature",
      properties: { radiusNm, label: formatRingLabel(radiusNm, unit) },
      geometry: {
        type: "LineString",
        coordinates: generateRingCoordinates(receiver, radiusNm),
      },
    })),
  };
}

/** GeoJSON FeatureCollection of ring radius labels, one point per ring
 * placed due north of the receiver so labels stack legibly along a
 * vertical line rather than overlapping the ring itself. */
export function generateRangeRingLabelsGeoJSON(
  config: Pick<MapConfig, "receiver" | "ringRadiiNm" | "unit">,
): FeatureCollection<Point, RangeRingProperties> {
  const { receiver, ringRadiiNm, unit } = config;
  return {
    type: "FeatureCollection",
    features: ringRadiiNm.map((radiusNm) => {
      const point = destinationPoint(receiver, 0, radiusNm);
      return {
        type: "Feature",
        properties: { radiusNm, label: formatRingLabel(radiusNm, unit) },
        geometry: { type: "Point", coordinates: [point.lon, point.lat] },
      };
    }),
  };
}

export interface ReceiverMarkerProperties {
  label: string;
}

/** GeoJSON point for the receiver marker layer. */
export function generateReceiverPointGeoJSON(
  receiver: ReceiverPosition,
): Feature<Point, ReceiverMarkerProperties> {
  return {
    type: "Feature",
    properties: { label: receiver.label },
    geometry: { type: "Point", coordinates: [receiver.lon, receiver.lat] },
  };
}
