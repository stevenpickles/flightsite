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
 *    zooms out or the picture gets crowded.
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

/** Live aircraft count above which every non-priority label drops to
 * callsign-only regardless of zoom (the density override). Chosen well
 * under the 500-aircraft rendering target (roadmap slice 014): a dense
 * scene reads as a wall of three-line labels long before it reads as 500
 * individual aircraft, so decluttering has to kick in far earlier than the
 * performance ceiling does. */
export const DENSITY_CALLSIGN_THRESHOLD = 60;

export interface LabelTierInput {
  /** Current map zoom (`map.getZoom()`). */
  zoom: number;
  /** Count of live aircraft in the picture
   * (`Object.keys(store.aircraft).length`) — cheap, and a reasonable proxy
   * for "how much text is about to compete for the same screen" without a
   * per-frame viewport query. */
  liveCount: number;
  /** True for the selected aircraft or one carrying an active interesting
   * match — both always get the full stack, in and out of zoom/density. */
  priority: boolean;
}

/** Resolves how much of the label stack an aircraft gets this frame. */
export function deriveLabelTier({
  zoom,
  liveCount,
  priority,
}: LabelTierInput): LabelTier {
  if (priority) {
    return "full";
  }
  if (zoom < ZOOM_LABELS_MIN) {
    return "none";
  }
  if (liveCount > DENSITY_CALLSIGN_THRESHOLD) {
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
