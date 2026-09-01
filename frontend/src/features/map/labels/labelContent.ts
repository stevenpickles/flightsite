/**
 * Builds the text for one aircraft's map label (roadmap slice 015).
 *
 * Three content slots, in priority order:
 *
 * 1. **Identity** — callsign, falling back to registration (slice 024),
 *    falling back to the upper-cased ICAO hex the decoder always supplies.
 *    Prefixed with the interesting-match indicator whenever the aircraft
 *    carries an active match — slice 038 populates `interesting`, and slice
 *    039 is where the indicator starts appearing on real aircraft.
 * 2. **Operator** — renders only when the metadata field is non-null.
 *    Always null until slice 024 supplies it.
 * 3. **Altitude** — flight level above the ~FL180 transition altitude, feet
 *    with a thousands separator below it. `null` (and so no third line) for
 *    an altitude-unknown aircraft.
 *
 * Kept as plain string functions, independent of MapLibre or a map
 * instance — the same split `icons/resolveIcon.ts` already uses for the
 * icon hierarchy, and for the same reason: the fallback chain is the
 * behaviour worth testing, not a style expression.
 */

import type { LabelTier } from "@/features/map/labels/priority";
import type { LiveAircraft } from "@/lib/api/live";

/** Prefixed onto line 1 when an aircraft carries an active interesting
 * match. A glyph reads as "notable" without relying on colour alone,
 * consistent with the MLAT ring's dash-pattern-over-colour approach
 * (`icons/silhouettes.ts`).
 *
 * One glyph for every severity, deliberately. SPEC §35 asks the label for an
 * *"interesting-status indicator"* — presence, not rank — and the label is
 * the one surface here whose glyphs come from the basemap style's SDF font
 * atlas rather than the UI font, so a four-glyph ladder would be four
 * chances to render a tofu box on some basemap. Severity is carried where it
 * can be carried reliably: the attention ring's radius and stroke width on
 * the map (`aircraft/aircraftLayers.ts`), and the severity word itself in
 * the interesting panel and the detail view. */
export const INTERESTING_INDICATOR = "★";

/** The altitude at and above which the label switches from feet to flight
 * levels. Close enough to the common ~18,000 ft transition altitude for a
 * map label, which does not need to track any one jurisdiction's exact
 * published value. */
export const TRANSITION_ALTITUDE_FT = 18000;

const THOUSANDS_FORMATTER = new Intl.NumberFormat("en-US");

/** The fields the label builder reads — a structural subset of
 * {@link LiveAircraft}, so callers (and tests) can build a label without a
 * whole payload. */
export type LabelSourceAircraft = Pick<
  LiveAircraft,
  | "icao"
  | "callsign"
  | "registration"
  | "operator"
  | "altitude_ft"
  | "interesting"
>;

export interface AircraftLabelLines {
  /** Callsign/registration/ICAO fallback chain, indicator-prefixed. Never
   * empty — the ICAO hex is always present. */
  line1: string;
  /** Operator, or `null` when the metadata field has not arrived yet. */
  line2: string | null;
  /** Formatted altitude, or `null` when altitude is unknown. */
  line3: string | null;
}

/** Trims a nullable string field, treating whitespace-only as absent. */
function normalize(value: string | null): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

/** Line 1: identity. Falls back callsign → registration → ICAO, then
 * prefixes the interesting indicator when the aircraft has an active
 * match. */
export function buildIdentityLine(aircraft: LabelSourceAircraft): string {
  const core =
    normalize(aircraft.callsign) ??
    normalize(aircraft.registration) ??
    aircraft.icao.toUpperCase();
  return aircraft.interesting ? `${INTERESTING_INDICATOR} ${core}` : core;
}

/** Line 2: operator. `null` — nothing rendered — until the metadata field
 * carries a value. */
export function buildOperatorLine(
  aircraft: LabelSourceAircraft,
): string | null {
  return normalize(aircraft.operator);
}

/** Line 3: altitude, flight-level notation above the transition altitude,
 * feet with a thousands separator below it. `null` when altitude is
 * unknown. */
export function formatAltitude(altitudeFt: number | null): string | null {
  if (altitudeFt === null) {
    return null;
  }
  if (altitudeFt >= TRANSITION_ALTITUDE_FT) {
    return `FL${Math.round(altitudeFt / 100)}`;
  }
  return `${THOUSANDS_FORMATTER.format(Math.round(altitudeFt))} ft`;
}

/** All three label lines for one aircraft. */
export function buildAircraftLabelLines(
  aircraft: LabelSourceAircraft,
): AircraftLabelLines {
  return {
    line1: buildIdentityLine(aircraft),
    line2: buildOperatorLine(aircraft),
    line3: formatAltitude(aircraft.altitude_ft),
  };
}

/**
 * Joins the label lines into the newline-delimited string a MapLibre
 * `text-field` renders, respecting `tier` (`priority.ts`): `"none"` is the
 * empty string (the layer filters those features out entirely), `"callsign"`
 * keeps line 1 only, and `"full"` keeps every line the aircraft has data
 * for — `line2`/`line3` being `null` already drops them, so no aircraft
 * shows a blank line for a field it does not have.
 */
export function renderLabelText(
  lines: AircraftLabelLines,
  tier: LabelTier,
): string {
  if (tier === "none") {
    return "";
  }
  if (tier === "callsign") {
    return lines.line1;
  }
  return [lines.line1, lines.line2, lines.line3]
    .filter((line): line is string => line !== null)
    .join("\n");
}
