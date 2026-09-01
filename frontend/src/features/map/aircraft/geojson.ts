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
import {
  buildAircraftLabelLines,
  renderLabelText,
} from "@/features/map/labels/labelContent";
import {
  deriveLabelTier,
  ZOOM_LABELS_FULL,
} from "@/features/map/labels/priority";

/** Opacity of a stale aircraft. SPEC §36 asks for staleness to read visually;
 * fading rather than hiding keeps a Mode S contact that has gone quiet on the
 * map, which is what an observer wants to see. */
export const STALE_OPACITY = 0.45;

/** Multiplier applied on top of the normal/stale opacity when the ground
 * traffic filter is set to "dim" (`features/filters`) — de-emphasized
 * rather than excluded, so an aircraft that just landed does not blink off
 * the map. Multiplicative with `STALE_OPACITY` so a stale, dimmed ground
 * contact reads as even quieter than either alone. */
export const GROUND_DIM_OPACITY = 0.55;

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
  /** True when the aircraft carries an active alert match (slice 038).
   * Always `false` today — `interesting` is `null` on every live payload
   * this slice can receive — but the label priority tiering and the
   * indicator glyph are both wired to it now. */
  interesting: boolean;
  /** Newline-delimited label text, already tiered for the current
   * zoom/density (`@/features/map/labels`) and empty when nothing should
   * render — the style layers filter on that rather than testing for an
   * empty text-field themselves. */
  label: string;
}

export type AircraftFeature = Feature<Point, AircraftFeatureProperties>;

export interface AircraftFrameInput {
  aircraft: Record<string, LiveAircraftRecord>;
  departing: Record<string, DepartingRecord>;
  selectedIcao: string | null;
  /** UTC milliseconds this frame is being drawn for. */
  now: number;
  /** Current map zoom (`map.getZoom()`), driving the label tier's
   * zoom band. Defaults to a zoom inside the full-label band so callers
   * that do not care about label decluttering (most existing tests) do
   * not have to supply one. */
  zoom?: number;
  /** ICAOs the live filters (`features/filters`) let through — an
   * aircraft in `aircraft` but not this set is skipped entirely.
   * `undefined` means "no filtering," so every existing caller that never
   * heard of filters keeps drawing everything. Departing aircraft are
   * never filtered (see the departing-loop comment below): a fade-out is
   * not part of the live picture filters describe. */
  visibleIcaos?: ReadonlySet<string>;
  /** Subset of `visibleIcaos` that should render de-emphasized rather
   * than at full strength — the ground-traffic filter's "dim" mode. */
  dimmedIcaos?: ReadonlySet<string>;
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
  const {
    aircraft,
    departing,
    selectedIcao,
    now,
    zoom = ZOOM_LABELS_FULL,
    visibleIcaos,
    dimmedIcaos,
  } = input;
  const features: AircraftFeature[] = [];
  // Cheap density signal: the *drawn* picture's size (post-filter, when
  // filtering is in play), not a viewport query — see `labels/priority.ts`'s
  // `deriveLabelTier` doc comment. A filtered-down picture should tier
  // toward fuller labels the same way a genuinely quiet sky does.
  const liveCount = visibleIcaos
    ? visibleIcaos.size
    : Object.keys(aircraft).length;

  for (const icao in aircraft) {
    const record = aircraft[icao];
    if (!record) {
      continue;
    }
    if (visibleIcaos && !visibleIcaos.has(icao)) {
      continue;
    }
    const position = displayPosition(record, now);
    if (!position) {
      continue;
    }
    const view = record.aircraft;
    const stale = view.state === "stale";
    const dimmed = dimmedIcaos?.has(icao) ?? false;
    const selected = icao === selectedIcao;
    const interesting = view.interesting !== null;
    const tier = deriveLabelTier({
      zoom,
      liveCount,
      priority: selected || interesting,
    });
    features.push(
      feature(position.lon, position.lat, {
        icao,
        callsign: view.callsign,
        track: view.track_deg ?? 0,
        icon: iconImageId(resolveAircraftIcon(view).shape),
        opacity:
          (stale ? STALE_OPACITY : 1) * (dimmed ? GROUND_DIM_OPACITY : 1),
        stale,
        mlat: view.position_source === "mlat",
        selected,
        onGround: view.on_ground === true,
        interesting,
        label: renderLabelText(buildAircraftLabelLines(view), tier),
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
        // Fading out rather than a live part of the picture: a departing
        // aircraft never carries a label, selected or not (it cannot be
        // selected — `selectAircraft` only ever targets `aircraft`).
        interesting: false,
        label: "",
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
