/**
 * The one place `Unknown` is rendered (§2.7: missing data is `null` in
 * JSON, the UI renders `Unknown` — never a fabricated guess). Every field
 * in the detail panel that can be `null` routes through this component so
 * the wording, styling and screen-reader text stay identical everywhere,
 * including in fields phase 4 hasn't populated yet (registration, type,
 * model, operator, operator group, classification).
 */
export function UnknownValue() {
  return <span className="italic text-muted-foreground">Unknown</span>;
}
