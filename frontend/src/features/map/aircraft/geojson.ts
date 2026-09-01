/**
 * Turning the live store into the two GeoJSON payloads the map draws.
 *
 * This is the hot path: it runs on every rendered frame for every positioned
 * aircraft, so it is deliberately plain — one pass, no intermediate arrays, no
 * per-feature closures, primitive-only feature properties. Everything the
 * layers need to style a feature is decided here and published as a property,
 * which keeps the style expressions to `["get", …]` lookups and keeps the
 * decisions in code that can be unit-tested without a renderer.
 *
 * Non-positioned aircraft (Mode S only, `position: null`) are part of the live
 * picture but not of this collection — SPEC §20 keeps them tracked, and the
 * aircraft list of a later slice is where they surface.
 */

import type { Feature, FeatureCollection, LineString, Point } from "geojson";

import { resolveAircraftIcon } from "@/features/map/aircraft/icons/resolveIcon";
import { iconImageId } from "@/features/map/aircraft/icons/silhouettes";
import { displayPosition } from "@/features/map/aircraft/interpolation";
import type {
  DepartingRecord,
  LiveAircraftRecord,
} from "@/features/map/aircraft/store/useLiveAircraftStore";
import { REMOVAL_FADE_MS } from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { SelectedTrack } from "@/features/map/aircraft/track";

/** Opacity of a stale aircraft. SPEC §36 asks for staleness to read visually;
 * fading rather than hiding keeps a Mode S contact that has gone quiet on the
 * map, which is what an observer wants to see. */
export const STALE_OPACITY = 0.45;

/**
 * Feature properties consumed by the aircraft layers' style expressions.
 *
 * All primitives: MapLibre serializes feature properties across to the worker,
 * and nested values there are both slower and awkward to address from a style
 * expression.
 */
export interface AircraftFeatureProperties {
  icao: string;
  callsign: string | null;
  /** Degrees clockwise from north, fed straight to `icon-rotate`. */
  track: number;
  /** MapLibre image id from the icon hierarchy. */
  icon: string;
  /** Final icon opacity: staleness and removal fade folded into one number. */
  opacity: number;
  stale: boolean;
  /** True for a multilaterated position — drawn with the dashed ring. */
  mlat: boolean;
  selected: boolean;
  onGround: boolean;
}

export type AircraftFeature = Feature<Point, AircraftFeatureProperties>;

export interface AircraftFrameInput {
  aircraft: Record<string, LiveAircraftRecord>;
  departing: Record<string, DepartingRecord>;
  selectedIcao: string | null;
  /** UTC milliseconds this frame is being drawn for. */
  now: number;
}

function feature(
  lon: number,
  lat: number,
  properties: AircraftFeatureProperties,
): AircraftFeature {
  return {
    type: "Feature",
    geometry: { type: "Point", coordinates: [lon, lat] },
    properties,
  };
}

/**
 * The aircraft symbol source for one frame.
 *
 * An aircraft with no reported `track_deg` is drawn unrotated (0°) rather than
 * hidden or given a placeholder shape: the position is known and worth showing,
 * and pointing north is the one direction that reads as "unstated" rather than
 * as a wrong heading.
 */
export function buildAircraftFeatureCollection(
  input: AircraftFrameInput,
): FeatureCollection<Point, AircraftFeatureProperties> {
  const { aircraft, departing, selectedIcao, now } = input;
  const features: AircraftFeature[] = [];

  for (const icao in aircraft) {
    const record = aircraft[icao];
    if (!record) {
      continue;
    }
    const position = displayPosition(record, now);
    if (!position) {
      continue;
    }
    const view = record.aircraft;
    const stale = view.state === "stale";
    features.push(
      feature(position.lon, position.lat, {
        icao,
        callsign: view.callsign,
        track: view.track_deg ?? 0,
        icon: iconImageId(resolveAircraftIcon(view).shape),
        opacity: stale ? STALE_OPACITY : 1,
        stale,
        mlat: view.position_source === "mlat",
        selected: icao === selectedIcao,
        onGround: view.on_ground === true,
      }),
    );
  }

  for (const icao in departing) {
    const record = departing[icao];
    const position = record?.aircraft.position;
    if (!record || !position) {
      continue;
    }
    // Departing aircraft are drawn where they were last seen, never projected:
    // the server has said they are gone, so moving them would be invention.
    const remaining = 1 - (now - record.removedAt) / REMOVAL_FADE_MS;
    if (remaining <= 0) {
      continue;
    }
    const view = record.aircraft;
    features.push(
      feature(position.lon, position.lat, {
        icao,
        callsign: view.callsign,
        track: view.track_deg ?? 0,
        icon: iconImageId(resolveAircraftIcon(view).shape),
        opacity: STALE_OPACITY * remaining,
        stale: true,
        mlat: view.position_source === "mlat",
        selected: false,
        onGround: view.on_ground === true,
      }),
    );
  }

  return { type: "FeatureCollection", features };
}

/**
 * The selected aircraft's track as a single LineString, or an empty collection
 * when nothing is selected or only one position has been observed (a two-point
 * minimum: a one-point LineString is not valid GeoJSON).
 */
export function buildTrackFeatureCollection(
  track: SelectedTrack | null,
): FeatureCollection<LineString, { icao: string }> {
  if (!track || track.points.length < 2) {
    return { type: "FeatureCollection", features: [] };
  }
  return {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: {
          type: "LineString",
          coordinates: track.points.map((point) => [point.lon, point.lat]),
        },
        properties: { icao: track.icao },
      },
    ],
  };
}
