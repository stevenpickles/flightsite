/**
 * Static catalogues the Alerts page renders: the severity ladder, the
 * mission categories a classification condition may require, and the
 * built-in detector keys the history can show.
 *
 * Data, not logic, and keyed rather than listed wherever a lookup happens,
 * so `noUncheckedIndexedAccess` never forces a fallback for a value the type
 * system already knows is present — the shape `features/watchlists/lib/
 * vocabulary.ts` established.
 */
import type { AlertSeverity } from "@/lib/api/sightings";
import type { AlertMissionCategory } from "@/lib/api/alertRules";

export interface SeverityOption {
  value: AlertSeverity;
  label: string;
  /** What choosing this level means, in SPEC §46's terms. Shown beside the
   * selector so a user picks a level by its consequence rather than by
   * guessing at a word's rank. */
  hint: string;
}

/** The four levels of §2.8's ladder, lowest first — the order SPEC §46
 * states them in, and the order a selector should offer them. */
export const SEVERITY_OPTIONS: SeverityOption[] = [
  {
    value: "info",
    label: "Info",
    hint: "Worth recording. Happens often on a new receiver.",
  },
  {
    value: "interesting",
    label: "Interesting",
    hint: "Worth a glance when you are already looking.",
  },
  {
    value: "high",
    label: "High",
    hint: "Worth interrupting for — military, government, police.",
  },
  {
    value: "critical",
    label: "Critical",
    hint: "Emergencies. Reserve this for things that cannot wait.",
  },
];

export interface MissionOption {
  value: AlertMissionCategory;
  label: string;
}

/** The mission categories a rule may require. `unknown` is deliberately
 * absent — the backend refuses it, because a rule matching every airframe no
 * metadata source has heard of would be a rule about FlightSite's ignorance
 * rather than about aircraft. */
export const MISSION_OPTIONS: MissionOption[] = [
  { value: "commercial_passenger", label: "Commercial passenger" },
  { value: "cargo", label: "Cargo" },
  { value: "general_aviation", label: "General aviation" },
  { value: "business_aviation", label: "Business aviation" },
  { value: "military", label: "Military" },
  { value: "government", label: "Government" },
  { value: "law_enforcement", label: "Law enforcement" },
  { value: "medical", label: "Medical" },
  { value: "firefighting", label: "Firefighting" },
  { value: "training", label: "Training" },
  { value: "helicopter", label: "Helicopter" },
];

/** What each built-in detector key means, for a history row that has no rule
 * to name (SPEC §47). Mirrors
 * `flightsite.alerts.vocabulary.EMERGENCY_MEANINGS`. */
export const BUILTIN_KEY_LABELS: Record<string, string> = {
  emergency_7500: "Squawk 7500 — unlawful interference",
  emergency_7600: "Squawk 7600 — radio failure",
  emergency_7700: "Squawk 7700 — general emergency",
};

/** A readable name for a built-in detector, falling back to the raw key so a
 * newer backend's detector still renders as something rather than blank. */
export function builtinKeyLabel(key: string): string {
  return BUILTIN_KEY_LABELS[key] ?? key;
}
