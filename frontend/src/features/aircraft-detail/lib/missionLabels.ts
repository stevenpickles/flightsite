/**
 * Human-readable labels for SPEC §39's mission/use category enum.
 *
 * `docs/DATA_MODEL.md` §3.4's `mission_category` column, spelled identically
 * in `flightsite.classification.vocabulary.MissionCategory` (the backend
 * enum the API's `classification.mission` field carries verbatim). Slice 024
 * shipped the raw enum value straight to the screen ("military",
 * "commercial_passenger") as a queued follow-up — this is that follow-up,
 * and the map both the detail panel and the Aircraft page render through.
 */
export const MISSION_LABELS: Record<string, string> = {
  commercial_passenger: "Commercial passenger",
  cargo: "Cargo",
  general_aviation: "General aviation",
  business_aviation: "Business aviation",
  military: "Military",
  government: "Government",
  law_enforcement: "Law enforcement",
  medical: "Medical / air ambulance",
  firefighting: "Firefighting",
  training: "Training",
  helicopter: "Helicopter",
  unknown: "Unknown",
};

/** Title-cases an unrecognized mission slug ("some_new_mission" → "Some New
 * Mission"), the same fallback `describeProvenance` uses for an
 * undocumented provenance source — the vocabulary only grows (§6), so an
 * enum value this map hasn't caught up with still reads as a name. */
function titleCase(value: string): string {
  return value
    .split(/[_\s-]+/)
    .filter(Boolean)
    .map((word) => (word[0] ?? "").toUpperCase() + word.slice(1))
    .join(" ");
}

/** `mission`'s display label — `null` (an aircraft classified before its
 * mission was ever asserted) reads the same as the `"unknown"` the API
 * always sends today. */
export function missionLabel(mission: string | null): string {
  if (mission === null) {
    return MISSION_LABELS.unknown as string;
  }
  return MISSION_LABELS[mission] ?? titleCase(mission);
}
