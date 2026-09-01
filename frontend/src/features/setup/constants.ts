/** Static catalogues the setup wizard renders from: wizard step order and
 * the SPEC §45 alert template list. Both are plain data so tests can assert
 * against them directly instead of re-deriving expectations from markup. */

export type WizardStepId =
  | "welcome"
  | "location"
  | "decoder"
  | "units-timezone"
  | "notifications"
  | "metadata"
  | "alerts"
  | "review";

export interface WizardStepDefinition {
  id: WizardStepId;
  /** Short label shown in the progress indicator. */
  label: string;
}

/** The eight wizard steps, in display/navigation order. */
export const WIZARD_STEPS: readonly WizardStepDefinition[] = [
  { id: "welcome", label: "Welcome" },
  { id: "location", label: "Location" },
  { id: "decoder", label: "Decoder" },
  { id: "units-timezone", label: "Units & Timezone" },
  { id: "notifications", label: "Notifications" },
  { id: "metadata", label: "Metadata" },
  { id: "alerts", label: "Alerts" },
  { id: "review", label: "Review" },
] as const;

/** Looks up a step by its index in `WIZARD_STEPS`. Throws for an
 * out-of-range index — a programming error (a bad `stepIndex`), never user
 * input — which also sidesteps `noUncheckedIndexedAccess` narrowing
 * `WIZARD_STEPS[i]` to possibly-`undefined` everywhere it's read. */
export function stepAt(index: number): WizardStepDefinition {
  const step = WIZARD_STEPS[index];
  if (!step) {
    throw new Error(`Wizard step index ${index} is out of range`);
  }
  return step;
}

export interface AlertTemplateDefinition {
  /** Matches the id `alerts.enabled_templates` stores and slice 038
   * instantiates from (SPEC §45). */
  id: string;
  label: string;
  description: string;
}

/** The v1 alert template catalogue, in the order shown to the wizard
 * (SPEC §45: "user chooses which to enable during setup — nothing
 * silently enabled"). */
export const ALERT_TEMPLATES: readonly AlertTemplateDefinition[] = [
  {
    id: "military",
    label: "Military aircraft",
    description: "Aircraft classified as military.",
  },
  {
    id: "government",
    label: "Government aircraft",
    description: "Aircraft classified as government-operated.",
  },
  {
    id: "law_enforcement",
    label: "Police / law enforcement aircraft",
    description: "Aircraft classified as police or other law enforcement.",
  },
  {
    id: "emergency_squawk",
    label: "Emergency squawk",
    description:
      "Squawk 7500 (hijack), 7600 (radio failure), or 7700 (general emergency).",
  },
  {
    id: "first_ever",
    label: "First-ever aircraft",
    description: "An aircraft this receiver has never seen before.",
  },
  {
    id: "locally_rare",
    label: "Locally rare aircraft or type",
    description:
      "An aircraft or type seen fewer than a threshold number of times.",
  },
  {
    id: "watchlist",
    label: "Watchlist match",
    description: "Any aircraft that matches one of your watchlists.",
  },
] as const;

/** Checked by default: the highest-signal, lowest-noise templates. Every
 * other template starts unchecked, consistent with SPEC §45. */
export const DEFAULT_ENABLED_TEMPLATE_IDS: readonly string[] = [
  "emergency_squawk",
  "military",
  "first_ever",
];
