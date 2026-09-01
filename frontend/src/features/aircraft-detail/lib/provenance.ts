/**
 * Plain-language descriptions for the §2.6 provenance vocabulary.
 *
 * `docs/API.md` §2.6 pins the current value set (`decoder | derived |
 * mictronics | faa | aerodatabox | heuristic`) but explicitly says a field
 * without an entry in the `provenance` map is decoder-direct — so "decoder"
 * is a synthesized label here, not a value the API ever sends. §6 promises
 * the key set only grows, so an unrecognized string (a future source) falls
 * back to a readable label instead of rendering nothing.
 */

export interface ProvenanceInfo {
  /** The raw provenance value, or `"decoder"` when the field carried no
   * entry in the map. */
  source: string;
  /** Human title, e.g. `"AeroDataBox"` for `"aerodatabox"`. */
  label: string;
  /** One plain-language sentence explaining where the value came from. */
  description: string;
}

const KNOWN_DESCRIPTIONS: Record<string, string> = {
  decoder: "Decoded directly from the aircraft's own transponder signal.",
  derived: "Calculated by FlightSite from other decoded fields.",
  mictronics: "Matched against the Mictronics aircraft database.",
  faa: "Matched against the FAA aircraft registry.",
  aerodatabox: "Looked up from the AeroDataBox flight-data service.",
  heuristic: "Inferred using a best-effort heuristic — may be imprecise.",
};

const KNOWN_LABELS: Record<string, string> = {
  decoder: "Decoder",
  derived: "Derived",
  mictronics: "Mictronics",
  faa: "FAA",
  aerodatabox: "AeroDataBox",
  heuristic: "Heuristic",
};

/** Title-cases an unrecognized source string (`"some_new_source"` →
 * `"Some New Source"`) so a future provenance value still reads as a name
 * rather than a raw enum slug. */
function titleCase(source: string): string {
  return source
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((word) => word[0]?.toUpperCase() + word.slice(1))
    .join(" ");
}

/** Resolves one provenance source string to a display label and plain-word
 * description, with a graceful fallback for any source `docs/API.md` has
 * not documented yet. */
export function describeProvenance(source: string): ProvenanceInfo {
  const label = KNOWN_LABELS[source] ?? titleCase(source) ?? source;
  const description =
    KNOWN_DESCRIPTIONS[source] ??
    `Sourced from "${label}", a data provider FlightSite doesn't have a description for yet.`;
  return { source, label, description };
}

/** Looks up a field's provenance in the §3.3 aircraft object's `provenance`
 * map, defaulting to `"decoder"` when the field has no entry — the API's
 * documented meaning of an absent key. */
export function fieldProvenance(
  provenance: Record<string, string>,
  field: string,
): ProvenanceInfo {
  return describeProvenance(provenance[field] ?? "decoder");
}
