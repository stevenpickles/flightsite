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
 * silently enabled").
 *
 * Every `id` here MUST be a key in the backend's own catalogue
 * (`backend/src/flightsite/alerts/templates.py`), because an id that is not
 * one selects nothing: the backend skips a key it does not recognize rather
 * than failing the save, so a wrong id costs the user a rule they asked for
 * and tells no one. That is exactly what happened with issue #111 — this list
 * said `law_enforcement`, the catalogue says `police`, and ticking "Police /
 * law enforcement aircraft" did nothing at all. The backend now warns about an
 * unrecognized key, and `tests/alerts/test_frontend_contract.py` asserts this
 * list against the catalogue so the two cannot drift apart again. */
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
    id: "police",
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
    label: "Locally rare aircraft",
    description: "An airframe seen here only a handful of times.",
  },
  {
    // SPEC §45 writes rarity as one entry, "locally rare aircraft/type", but a
    // v1 rule combines conditions with AND only — so one rule carrying both
    // halves would mean "a rare airframe OF a rare type", far narrower than
    // either. The backend therefore ships them as two templates, and this list
    // has to offer both: it previously offered one box labelled "aircraft or
    // type" that sent only `locally_rare`, promising a rule it never created.
    id: "locally_rare_type",
    label: "Locally rare type",
    description: "A type seen here on only a handful of airframes.",
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
