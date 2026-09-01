/**
 * The live-filter model (roadmap slice 017).
 *
 * Every field composes with every other by AND — `applyFilters`
 * (`lib/applyFilters.ts`) is the one place that order is decided, and the
 * map, the non-positioned panel, and the drawer's own counts all read its
 * result rather than each re-deriving "what's visible."
 *
 * Several fields target data that stays present-and-`null` on every live
 * payload until a later slice populates it (`docs/API.md` §2.7):
 * `categoryText`/`operatorText`/`operatorGroupText` match `aircraft_type`
 * / `operator` / `operator_group` (slice 024), `classifications` and
 * `missionCategories` match `classification` (slice 024), and
 * `interestingOnly` matches `interesting` (slice 038). The UI keeps them
 * fully wired — this is plumbing, not a stub — but until that data exists,
 * a non-empty `classifications`/`missionCategories` selection or
 * `interestingOnly: true` matches nothing, by design (see
 * `lib/applyFilters.ts`'s doc comment on why "nothing" and not
 * "everything").
 */

import type { LiveAircraft } from "@/lib/api/live";

/** A military/government/law-enforcement flag from `Classification`
 * (`lib/api/live.ts`). */
export type ClassificationFlag = "military" | "government" | "law_enforcement";

/** How ground traffic renders: normally, de-emphasized in place, or not at
 * all. "dim" never removes a feature from the render set — only "hide"
 * does — so it is not itself an exclusion filter. */
export type GroundTrafficMode = "show" | "dim" | "hide";

export interface LiveFilters {
  /** Inclusive lower bound in feet, or `null` for no floor. An aircraft
   * with unknown altitude always passes — a range can only exclude what it
   * can compare. */
  altitudeMinFt: number | null;
  /** Inclusive upper bound in feet, or `null` for no ceiling. */
  altitudeMaxFt: number | null;
  /** Explicit user override for the display-radius default distance cap
   * (`MapConfig.displayRadiusNm`), in nm. `null` means "use the config
   * default." Set larger or smaller than the default to override it
   * either way; unknown distance always passes, same rationale as
   * altitude. */
  maxDistanceNm: number | null;
  /** Case-insensitive substring match against `aircraft_type`. */
  categoryText: string;
  /** Case-insensitive substring match against `operator`. */
  operatorText: string;
  /** Case-insensitive substring match against `operator_group`. */
  operatorGroupText: string;
  /** OR-matched against `classification`'s boolean flags; empty means no
   * classification filtering. A non-empty selection excludes every
   * aircraft whose `classification` is `null` (see `lib/applyFilters.ts`). */
  classifications: ClassificationFlag[];
  /** OR-matched against `classification.mission`; empty means no mission
   * filtering. Same null-excludes behavior as `classifications`. */
  missionCategories: string[];
  /** Only aircraft with an active alert match (`interesting !== null`,
   * slice 038). */
  interestingOnly: boolean;
  /** Only aircraft broadcasting an emergency squawk (`emergency !== null`)
   * — real decoder data today, unlike the metadata-gated fields above. */
  emergencyOnly: boolean;
  /** Excludes aircraft with no position (Mode S only). */
  hideNonPositioned: boolean;
  groundTraffic: GroundTrafficMode;
  /** Excludes aircraft whose lifecycle state is `"stale"`. */
  hideStale: boolean;
  /** Narrows the live set only (not a global search) by a case-insensitive
   * prefix match against callsign, registration, or ICAO. */
  liveSetQuery: string;
}

export const DEFAULT_FILTERS: LiveFilters = {
  altitudeMinFt: null,
  altitudeMaxFt: null,
  maxDistanceNm: null,
  categoryText: "",
  operatorText: "",
  operatorGroupText: "",
  classifications: [],
  missionCategories: [],
  interestingOnly: false,
  emergencyOnly: false,
  hideNonPositioned: false,
  groundTraffic: "show",
  hideStale: false,
  liveSetQuery: "",
};

/** The slice of map configuration `applyFilters` needs — just enough to
 * resolve the display-radius default, so the pure filtering function does
 * not have to import the whole `MapConfig` shape. */
export interface FilterRuntimeConfig {
  displayRadiusNm: number;
}

export interface FilterResult {
  /** Every aircraft — positioned and non-positioned — that passes every
   * filter, AND-composed. Ground traffic in "dim" mode is included here
   * (dimming is a render hint, not an exclusion); "hide" mode excludes it. */
  aircraft: LiveAircraft[];
  /** ICAOs of every aircraft in `aircraft`, for O(1) map/panel lookups. */
  visibleIcaos: ReadonlySet<string>;
  /** ICAOs of the subset of `aircraft` that should render de-emphasized
   * (ground traffic, `groundTraffic: "dim"`). */
  dimmedIcaos: ReadonlySet<string>;
  /** How many input aircraft were excluded specifically by the distance
   * cap (independent of whether they would also have failed another
   * filter) — drives the "N aircraft beyond the display radius" hint. */
  distanceCappedCount: number;
  /** The distance cap actually applied: `maxDistanceNm` if the user set
   * one, else `config.displayRadiusNm`. */
  effectiveDistanceCapNm: number;
}
