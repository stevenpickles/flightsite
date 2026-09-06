/**
 * Priority and tiering rules for aircraft map labels (roadmap slice 015).
 *
 * Two independent decisions live here, both pure functions so they are
 * testable without a renderer or a map instance:
 *
 * 1. **Sort-key** — which label MapLibre keeps when two collide. Lower wins:
 *    MapLibre's own `symbol-sort-key` convention places lower values first,
 *    and a later, colliding symbol is the one hidden — so selected and
 *    interesting aircraft get the lowest values.
 * 2. **Tier** — how much of the label stack renders at all, decided from
 *    zoom and the live picture's density before MapLibre ever sees a
 *    feature. Selected and interesting aircraft always get the full stack;
 *    everyone else steps from full → callsign-only → nothing as the view
 *    zooms out or the picture gets crowded. The density step is latched
 *    through a hysteresis band (issue #143) so a labelled count sitting on the
 *    edge cannot toggle the label content frame after frame; the latch
 *    itself lives with the caller, not here.
 *
 * Roadmap slice 015 asks for "suppress operator first, then secondary
 * text". The operator line already suppresses itself whenever the metadata
 * field is null (`labelContent.ts`), which is every payload this slice can
 * receive — slice 024 has not landed. The "callsign" tier below therefore
 * drops the operator and altitude lines together rather than adding a
 * fourth, untestable state for an intermediate "operator gone, altitude
 * still shown" step that no data this slice can observe would ever
 * distinguish from "full". Whichever slice can actually see a live operator
 * string is the one that can test a finer split.
 */

export type LabelTier = "none" | "callsign" | "full";

/** Below this zoom, no aircraft carries a label — a wide 250 nm view is
 * dense enough that any text would be noise over the silhouettes. */
export const ZOOM_LABELS_MIN = 7;

/** At and above this zoom, non-priority aircraft get the full label stack.
 * Between {@link ZOOM_LABELS_MIN} and this, callsign only. */
export const ZOOM_LABELS_FULL = 10;

/**
 * The density override's hysteresis band (issue #143).
 *
 * Every non-priority label drops to callsign-only, regardless of zoom, once
 * the labelled count rises *above* {@link DENSITY_CALLSIGN_ENTER}, and the
 * full stack only comes back once it falls *below*
 * {@link DENSITY_CALLSIGN_EXIT}. Between the two edges the previous decision
 * stands.
 *
 * The count is of aircraft that will actually carry a label — what
 * `aircraft/geojson.ts`'s `countLabelledAircraft` returns — not the size of
 * the live set (issue #147). Labels are what crowd a label, so a
 * position-less Mode S contact is not part of the crowd.
 *
 * The upper edge is where the override has always sat: well under the
 * 500-aircraft rendering target (roadmap slice 014), because a dense scene
 * reads as a wall of three-line labels long before it reads as 500
 * individual aircraft, so decluttering has to kick in far earlier than the
 * performance ceiling does.
 *
 * The lower edge is what stops the labels blinking. A single threshold means
 * a picture hovering at the edge — which is the *normal* state of a busy
 * receiver, gaining and losing a contact every second or two — toggles the
 * altitude line on and off continuously. A ten-aircraft band is wide enough
 * that ordinary churn cannot cross it, and narrow enough that a picture
 * genuinely thinning out gets its full labels back within a frame or two of
 * actually being sparse.
 *
 * The zoom edges ({@link ZOOM_LABELS_MIN}, {@link ZOOM_LABELS_FULL}) get no
 * such band, deliberately: zoom only changes because the viewer changed it,
 * so a boundary crossing there is an intended act rather than the picture
 * flapping under its own noise.
 */
export const DENSITY_CALLSIGN_ENTER = 60;

/** The band's lower edge — see {@link DENSITY_CALLSIGN_ENTER}. */
export const DENSITY_CALLSIGN_EXIT = 50;

/**
 * The density override's next latch state, given the previous one and this
 * frame's labelled count.
 *
 * Pure, and the *only* place the band is interpreted: `deriveLabelTier` takes
 * the answer, so the latch's owner is whoever is drawing frames in sequence
 * (`aircraft/frame.ts` via `labels/densityLatch.ts`) rather than this module.
 * A one-off caller with no history passes `false` and gets the plain
 * "is this picture dense right now" answer.
 */
export function nextDensityLatched(
  previous: boolean,
  labelledCount: number,
): boolean {
  if (labelledCount > DENSITY_CALLSIGN_ENTER) {
    return true;
  }
  if (labelledCount < DENSITY_CALLSIGN_EXIT) {
    return false;
  }
  return previous;
}

export interface LabelTierInput {
  /** Current map zoom (`map.getZoom()`). */
  zoom: number;
  /**
   * Whether the density override is currently latched on — the resolved
   * output of {@link nextDensityLatched} for this frame's labelled count.
   *
   * A boolean rather than the count itself so this function stays pure while
   * the decision it depends on is stateful: the count is cheap (the size of
   * the drawn picture, not a per-frame viewport query), but "is the picture
   * dense" is only answerable with reference to what it was a frame ago.
   */
  densityLatched: boolean;
  /** True for the selected aircraft or one carrying an active interesting
   * match — both always get the full stack, in and out of zoom/density. */
  priority: boolean;
}

/** Resolves how much of the label stack an aircraft gets this frame. */
export function deriveLabelTier({
  zoom,
  densityLatched,
  priority,
}: LabelTierInput): LabelTier {
  if (priority) {
    return "full";
  }
  if (zoom < ZOOM_LABELS_MIN) {
    return "none";
  }
  if (densityLatched) {
    return "callsign";
  }
  return zoom >= ZOOM_LABELS_FULL ? "full" : "callsign";
}

/** Collision priority for the label layers — selected first, interesting
 * second, everyone else last. Lower is higher priority, per MapLibre's
 * `symbol-sort-key` semantics; mirrored in the style expressions that drive
 * the actual layers (`aircraftLayers.ts`) so both stay provably in sync
 * with this function. */
export const SORT_KEY_SELECTED = 0;
export const SORT_KEY_INTERESTING = 1;
export const SORT_KEY_DEFAULT = 2;

/** Resolves the collision-priority sort key for one aircraft's label. */
export function deriveLabelSortKey(
  selected: boolean,
  interesting: boolean,
): number {
  if (selected) {
    return SORT_KEY_SELECTED;
  }
  if (interesting) {
    return SORT_KEY_INTERESTING;
  }
  return SORT_KEY_DEFAULT;
}
