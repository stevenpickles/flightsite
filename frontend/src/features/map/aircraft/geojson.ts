/**
 * Turning the live store into the GeoJSON payloads the map draws: the
 * aircraft symbols, the selected aircraft's track and, since roadmap slice
 * 085, every other visible aircraft's short trail.
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

import { meritsAttention } from "@/features/interesting/lib/ordering";
import { resolveAircraftIconImageId } from "@/features/map/aircraft/icons/resolveIcon";
import { displayPosition } from "@/features/map/aircraft/interpolation";
import type {
  DepartingRecord,
  LiveAircraftRecord,
} from "@/features/map/aircraft/store/useLiveAircraftStore";
import { REMOVAL_FADE_MS } from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { SelectedTrack } from "@/features/map/aircraft/track";
import type { TrailSource } from "@/features/map/aircraft/trails";
import {
  buildAircraftLabelLines,
  DEFAULT_LABEL_PRESET,
  renderLabelText,
  type LabelPreset,
} from "@/features/map/labels/labelContent";
import {
  deriveLabelTier,
  nextDensityLatched,
  ZOOM_LABELS_FULL,
} from "@/features/map/labels/priority";
import type { UnitSystem } from "@/lib/api/config";

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
  /** MapLibre image id: the silhouette from the icon hierarchy in the
   * palette the classification flags choose (`icons/resolveIcon.ts`). */
  icon: string;
  /** Final icon opacity: staleness and removal fade folded into one number. */
  opacity: number;
  stale: boolean;
  /** True for a multilaterated position — drawn with the dashed ring. */
  mlat: boolean;
  selected: boolean;
  onGround: boolean;
  /** True when the aircraft carries an active alert match (slice 038,
   * populated on the wire since that slice landed). Drives the label's
   * indicator glyph — presence, which is what SPEC §35 asks the label for. */
  interesting: boolean;
  /**
   * True when that match is at or above `ATTENTION_SEVERITY_FLOOR` — the
   * attention ring, the label priority tier and the collision sort key all
   * key off this rather than off {@link AircraftFeatureProperties.interesting}.
   *
   * Issue R1-10: on a new install the default templates include
   * `first_ever`, which matches every airframe the receiver has not heard
   * before, so 76 of 77 aircraft carried a ring and won every label
   * collision. "Distinct attention styling" (SPEC §36) that applies to
   * everything is not styling, and a label priority that applies to
   * everything defeats the zoom/density declutter it overrides. Resolved in
   * TypeScript against the ladder table, exactly as this property's
   * `severity` sibling says severity ordering always is.
   */
  attention: boolean;
  /** The active match's severity (`docs/API.md` §2.8), or `""` when nothing
   * is matching — the attention ring's style expressions read this.
   *
   * A string rather than a rank number because the layer expressions
   * `match` on it and read far better for it, and `""` rather than `null`
   * because MapLibre feature properties are compared, not narrowed: the
   * ring layer's filter is `["!=", ["get", "severity"], ""]`, and a `null`
   * property would have to be tested with `has`/`!has` instead. Severity
   * *ordering* is never asked of a style expression — that is
   * `features/interesting/lib/ordering.ts`'s job, in TypeScript, where the
   * ladder is a table rather than a string comparison. */
  severity: string;
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
  /**
   * Whether the label-density override is currently latched on
   * (`labels/densityLatch.ts`), carried in because the hysteresis band that
   * decides it (issue #143) needs to know what the *previous* frame chose,
   * and this builder is pure.
   *
   * `undefined` means "no history": the frame is judged on its own count
   * alone, which is exactly right for a one-off caller — and for every test
   * that hands over a picture without drawing a sequence.
   */
  densityLatched?: boolean;
  /** The receiver's display units, for the altitude line of each label.
   * Defaults to aviation units, which is also what the backend defaults to
   * before a config has loaded. */
  units?: UnitSystem;
  /** The user's label content preset (roadmap slice 085,
   * `labels/labelContent.ts`), applied on top of each aircraft's tier to
   * every aircraft except the selected one, whose label stays complete.
   * Defaults to `"full"` — the labels as they were before presets existed. */
  labelPreset?: LabelPreset;
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
 * How many aircraft this frame will actually put a label on — the density
 * signal `labels/densityLatch.ts` latches (issue #147).
 *
 * Cheap by construction: the *drawn* picture's size (post-filter, when
 * filtering is in play), not a viewport query — see `labels/priority.ts`'s
 * `deriveLabelTier` doc comment. A filtered-down picture should tier toward
 * fuller labels the same way a genuinely quiet sky does.
 *
 * The position test is the correction issue #147 asked for. The filters'
 * `visibleIcaos` is the *live* set, which includes Mode S contacts with no
 * position (SPEC §20 keeps them tracked and the aircraft list shows them);
 * the loop below skips exactly those, so they occupy no label and crowd
 * nothing. Counting them pushed the latch toward "dense" on a picture that
 * was not, and on a receiver hearing a lot of position-less traffic that is
 * the difference between full labels and callsign-only.
 *
 * Testing `position` rather than calling `displayPosition` is not an
 * approximation: `displayPosition` returns `null` for a null position and a
 * projected point for every other case, so the two agree exactly — and this
 * way the count costs a property read per aircraft rather than a second run
 * of the interpolation maths on the hot path.
 */
export function countLabelledAircraft(
  aircraft: Record<string, LiveAircraftRecord>,
  visibleIcaos?: ReadonlySet<string>,
): number {
  let count = 0;
  for (const icao in aircraft) {
    const record = aircraft[icao];
    if (!record || record.aircraft.position === null) {
      continue;
    }
    if (visibleIcaos && !visibleIcaos.has(icao)) {
      continue;
    }
    count += 1;
  }
  return count;
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
    units = "aviation",
    labelPreset = DEFAULT_LABEL_PRESET,
  } = input;
  const features: AircraftFeature[] = [];
  // One decision for the whole frame, resolved once rather than per feature.
  // The count is only derived when nobody carried a latch in — the frame loop
  // always does, so the hot path never pays for this pass twice.
  const densityLatched =
    input.densityLatched ??
    nextDensityLatched(false, countLabelledAircraft(aircraft, visibleIcaos));

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
    const attention = meritsAttention(view.interesting?.severity);
    const tier = deriveLabelTier({
      zoom,
      densityLatched,
      priority: selected || attention,
    });
    features.push(
      feature(position.lon, position.lat, {
        icao,
        callsign: view.callsign,
        track: view.track_deg ?? 0,
        icon: resolveAircraftIconImageId(view),
        opacity:
          (stale ? STALE_OPACITY : 1) * (dimmed ? GROUND_DIM_OPACITY : 1),
        stale,
        mlat: view.position_source === "mlat",
        selected,
        onGround: view.on_ground === true,
        interesting,
        attention,
        severity: view.interesting?.severity ?? "",
        label: renderLabelText(
          buildAircraftLabelLines(view, units),
          tier,
          // The preset narrows every label but the selected one (see
          // `renderLabelText`); an attention-worthy aircraft keeps its
          // priority *tier* — labelled at any zoom and density — under
          // whatever content the user chose.
          selected ? "full" : labelPreset,
        ),
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
        icon: resolveAircraftIconImageId(view),
        opacity: STALE_OPACITY * remaining,
        stale: true,
        mlat: view.position_source === "mlat",
        selected: false,
        onGround: view.on_ground === true,
        // Fading out rather than a live part of the picture: a departing
        // aircraft never carries a label, selected or not (it cannot be
        // selected — `selectAircraft` only ever targets `aircraft`), and it
        // never carries the attention ring either. "Interesting" is a
        // statement about what is matching *now*, and an aircraft the server
        // has said is gone is not matching anything.
        interesting: false,
        attention: false,
        severity: "",
        label: "",
      }),
    );
  }

  return { type: "FeatureCollection", features };
}

/** Feature properties for one trail (roadmap slice 085). */
export interface TrailFeatureProperties {
  icao: string;
  /** Staleness and the ground-dim filter folded into one multiplier — the
   * same factors the aircraft's icon opacity carries, so a stale or dimmed
   * aircraft's trail recedes with it. The layer multiplies this by its own
   * base opacity. */
  opacity: number;
}

export type TrailFeature = Feature<LineString, TrailFeatureProperties>;

export interface TrailFrameInput {
  aircraft: Record<string, LiveAircraftRecord>;
  /** The recorded trails (`trails.ts`), read and never written here. */
  trails: TrailSource;
  selectedIcao: string | null;
  /** UTC milliseconds this frame is being drawn for — trail points older
   * than `TRAIL_MAX_AGE_MS` before it are not drawn. */
  now: number;
  /** Same meaning as {@link AircraftFrameInput.visibleIcaos}: a filtered-out
   * aircraft draws no trail. */
  visibleIcaos?: ReadonlySet<string>;
  /** Same meaning as {@link AircraftFrameInput.dimmedIcaos}. */
  dimmedIcaos?: ReadonlySet<string>;
}

/**
 * Every visible aircraft's trail as one LineString per aircraft, drawn as a
 * single layer beneath the icons (`aircraftLayers.ts`).
 *
 * Skipped, deliberately:
 *
 * - the **selected** aircraft, which already draws its full sighting track
 *   (`buildTrackFeatureCollection`) — two lines over the same path would just
 *   thicken the newer part of it;
 * - any aircraft the **filters** exclude, like its icon;
 * - **departing** aircraft: `departing` is not even an input, since a removed
 *   aircraft's ring is dropped from the buffer the moment it leaves the store
 *   (`TrailBuffer.record`);
 * - a trail with fewer than two points, which is not a valid LineString.
 *
 * Trails end at the last *reported* position, not the interpolated one the
 * icon is drawn at, so this only needs rebuilding when the picture changes
 * (`frame.ts`'s `includeTrails`), not on every interpolation frame — at
 * 500 aircraft x 30 points that is the difference between re-serializing
 * 15,000 vertices once a second and a dozen times a second. The gap it leaves
 * is at most the ~1 s of dead reckoning in front of the last fix, a few pixels
 * at the zooms where a trail is legible at all.
 */
export function buildTrailFeatureCollection(
  input: TrailFrameInput,
): FeatureCollection<LineString, TrailFeatureProperties> {
  const { aircraft, trails, selectedIcao, now, visibleIcaos, dimmedIcaos } =
    input;
  const features: TrailFeature[] = [];
  for (const icao in aircraft) {
    if (icao === selectedIcao) {
      continue;
    }
    if (visibleIcaos && !visibleIcaos.has(icao)) {
      continue;
    }
    const record = aircraft[icao];
    if (!record) {
      continue;
    }
    const coordinates = trails.coordinates(icao, now);
    if (coordinates.length < 2) {
      continue;
    }
    const stale = record.aircraft.state === "stale";
    const dimmed = dimmedIcaos?.has(icao) ?? false;
    features.push({
      type: "Feature",
      geometry: { type: "LineString", coordinates },
      properties: {
        icao,
        opacity:
          (stale ? STALE_OPACITY : 1) * (dimmed ? GROUND_DIM_OPACITY : 1),
      },
    });
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
