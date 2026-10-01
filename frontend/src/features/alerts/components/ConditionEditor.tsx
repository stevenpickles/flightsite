import { useId } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";
import { AreaEditor } from "@/features/alerts/components/AreaEditor";
import { ChipsInput } from "@/features/alerts/components/ChipsInput";
import {
  conditionKindMeta,
  validateEmitterCategory,
  validateSquawkCode,
  type ConditionDraft,
} from "@/features/alerts/lib/conditions";
import { MISSION_OPTIONS } from "@/features/alerts/lib/vocabulary";
import type { AlertMissionCategory } from "@/lib/api/alertRules";
import { useConfigQuery } from "@/lib/api/config";
import type { Watchlist } from "@/lib/api/watchlists";
import {
  EMITTER_CATEGORY_LABELS,
  formatEmitterCategory,
} from "@/lib/emitterCategory";

/** Shared with `EntryForm` in the watchlists feature — a native `<select>`
 * dressed to match the `Input` primitive, there being no shadcn select in
 * this build. */
const SELECT_CLASSES =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50";

const CHECKBOX_CLASSES =
  "size-4 rounded border-input accent-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";

const NM_TO_KM = 1.852;
const FT_TO_M = 1 / 3.28084;
/** Knots to km/h is the same factor as nautical miles to kilometres. */
const KT_TO_KMH = NM_TO_KM;
/** Feet per minute to metres per second. */
const FPM_TO_MS = FT_TO_M / 60;

type WindowKind = "distance" | "altitude" | "ground_speed" | "vertical_rate";

/** The two labels of each window's halves, units in the label (R4-13). */
const WINDOW_LABELS: Record<WindowKind, { min: string; max: string }> = {
  distance: { min: "At least (nm)", max: "Within (nm)" },
  altitude: { min: "At or above (ft)", max: "At or below (ft)" },
  ground_speed: { min: "At least (kt)", max: "At most (kt)" },
  vertical_rate: { min: "At or above (ft/min)", max: "At or below (ft/min)" },
};

/**
 * A live "≈ metric" readout for a window field (R4-13): the builder's
 * inputs are always the canonical nm/ft/kt/ft-per-minute (`CLAUDE.md` —
 * storage and the API never change), but a receiver configured for metric
 * display should not have to convert "within 250 nm" by hand to know what it
 * means. `null` for anything that is not a plain number yet (blank,
 * mid-edit, "Any").
 */
function metricConversionHint(raw: string, kind: WindowKind): string | null {
  const value = Number(raw);
  if (raw.trim().length === 0 || !Number.isFinite(value)) {
    return null;
  }
  const format = (converted: number): string =>
    converted.toLocaleString(undefined, { maximumFractionDigits: 1 });
  switch (kind) {
    case "distance":
      return `≈ ${format(value * NM_TO_KM)} km`;
    case "altitude":
      return `≈ ${format(value * FT_TO_M)} m`;
    case "ground_speed":
      return `≈ ${format(value * KT_TO_KMH)} km/h`;
    case "vertical_rate":
      return `≈ ${format(value * FPM_TO_MS)} m/s`;
  }
}

/** The emitter categories worth suggesting: everything but the "no
 * information" and reserved codes, which are valid but never what a rule
 * is about. */
const EMITTER_SUGGESTIONS = Object.entries(EMITTER_CATEGORY_LABELS)
  .filter(([, label]) => label !== "Reserved" && !label.startsWith("No "))
  .map(([value, label]) => ({ value, label }));

export interface ConditionEditorProps {
  draft: ConditionDraft;
  /** What is wrong with this condition right now, or `null`. Passed in
   * rather than derived here so the builder decides *when* to show it —
   * an error on a field the user has not reached yet is noise. */
  error: string | null;
  /** The watchlists a `watchlist` condition may name. Empty while the list
   * is still loading, or on an install that has none. */
  watchlists: readonly Watchlist[];
  onChange: (next: ConditionDraft) => void;
  onRemove: () => void;
}

/**
 * One condition of a rule, edited in place.
 *
 * A `<fieldset>` with a `<legend>` rather than a styled `<div>`: a condition
 * is a group of inputs that only means anything together, which is what a
 * fieldset is for, and it gives the group an accessible name without any
 * ARIA. Numeric fields are plain text inputs holding strings — the form owns
 * parsing and its own error messages, so the browser's native number
 * validation cannot refuse a submit before this build's messages are shown.
 */
export function ConditionEditor({
  draft,
  error,
  watchlists,
  onChange,
  onRemove,
}: ConditionEditorProps) {
  const fieldId = useId();
  const meta = conditionKindMeta(draft.kind);
  const errorId = `${fieldId}-error`;
  const describedBy = error ? errorId : undefined;
  const configQuery = useConfigQuery();
  const showMetricHints = configQuery.data?.config.units === "metric";

  return (
    <fieldset className="flex flex-col gap-3 rounded-md border border-border bg-background p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <legend className="text-sm font-medium text-foreground">
            {meta.label}
          </legend>
          <p className="text-xs text-muted-foreground">{meta.summary}</p>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          aria-label={`Remove the ${meta.label} condition`}
          onClick={onRemove}
        >
          Remove
        </Button>
      </div>

      {draft.kind === "classification" && (
        <div className="flex flex-col gap-3">
          <div
            role="group"
            aria-label="Required classifications"
            className="flex flex-wrap gap-4"
          >
            {(
              [
                ["military", "Military", draft.military],
                ["government", "Government", draft.government],
                ["lawEnforcement", "Law enforcement", draft.lawEnforcement],
              ] as const
            ).map(([field, label, checked]) => (
              <label
                key={field}
                className="flex items-center gap-2 text-sm text-foreground"
              >
                <input
                  type="checkbox"
                  className={CHECKBOX_CLASSES}
                  checked={checked}
                  aria-describedby={describedBy}
                  onChange={(event) => {
                    onChange({ ...draft, [field]: event.target.checked });
                  }}
                />
                {label}
              </label>
            ))}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={fieldId}>Mission category</Label>
            <select
              id={fieldId}
              className={SELECT_CLASSES}
              value={draft.mission}
              aria-describedby={describedBy}
              onChange={(event) => {
                onChange({
                  ...draft,
                  mission: event.target.value as AlertMissionCategory | "",
                });
              }}
            >
              <option value="">No mission requirement</option>
              {MISSION_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {(draft.kind === "type_code" || draft.kind === "model") && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={fieldId}>
            {draft.kind === "type_code" ? "Type designator" : "Model contains"}
          </Label>
          <Input
            id={fieldId}
            value={draft.text}
            placeholder={draft.kind === "type_code" ? "C17" : "Globemaster"}
            aria-invalid={error !== null}
            aria-describedby={describedBy}
            onChange={(event) => {
              onChange({ ...draft, text: event.target.value });
            }}
          />
        </div>
      )}

      {draft.kind === "watchlist" && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={fieldId}>Watchlist</Label>
          <select
            id={fieldId}
            className={SELECT_CLASSES}
            value={draft.watchlistId}
            aria-invalid={error !== null}
            aria-describedby={describedBy}
            onChange={(event) => {
              onChange({ ...draft, watchlistId: event.target.value });
            }}
          >
            <option value="" disabled>
              Choose a watchlist…
            </option>
            {watchlists.map((list) => (
              <option key={list.id} value={String(list.id)}>
                {list.name}
              </option>
            ))}
          </select>
          {watchlists.length === 0 && (
            <p className="text-xs text-muted-foreground">
              No watchlists yet. Create one on the Watchlists tab, or use “On
              any watchlist” instead.
            </p>
          )}
        </div>
      )}

      {draft.kind === "watchlist_any" && (
        <p className="text-xs text-muted-foreground">
          Nothing to configure — this matches an aircraft on any watchlist.
        </p>
      )}

      {(draft.kind === "rare_aircraft" || draft.kind === "rare_type") && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={fieldId}>
            {draft.kind === "rare_aircraft"
              ? "At most this many sightings here"
              : "At most this many airframes of the type here"}
          </Label>
          <Input
            id={fieldId}
            inputMode="numeric"
            value={draft.maxSightings}
            placeholder="2"
            aria-invalid={error !== null}
            aria-describedby={describedBy}
            onChange={(event) => {
              onChange({ ...draft, maxSightings: event.target.value });
            }}
          />
        </div>
      )}

      {(draft.kind === "callsign_glob" ||
        draft.kind === "registration_glob") && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={fieldId}>
            {draft.kind === "callsign_glob"
              ? "Callsign matches"
              : "Registration matches"}
          </Label>
          <Input
            id={fieldId}
            value={draft.text}
            autoCapitalize="characters"
            spellCheck={false}
            placeholder={draft.kind === "callsign_glob" ? "RCH*" : "N?23AB"}
            aria-invalid={error !== null}
            aria-describedby={[`${fieldId}-glob-help`, describedBy]
              .filter(Boolean)
              .join(" ")}
            onChange={(event) => {
              onChange({ ...draft, text: event.target.value });
            }}
          />
          <p
            id={`${fieldId}-glob-help`}
            className="text-xs text-muted-foreground"
          >
            The whole value must match, ignoring case. <code>*</code> stands for
            any run of characters (or none), <code>?</code> for exactly one;
            every other character means itself.
          </p>
        </div>
      )}

      {draft.kind === "squawk" && (
        <ChipsInput
          label="Squawk codes"
          values={draft.values}
          placeholder="7000"
          validate={validateSquawkCode}
          describedBy={describedBy}
          invalid={error !== null}
          onChange={(values) => {
            onChange({ ...draft, values });
          }}
        />
      )}

      {draft.kind === "emitter_category" && (
        <ChipsInput
          label="Emitter categories"
          values={draft.values}
          placeholder="A7"
          normalize={(raw) => raw.trim().toUpperCase()}
          formatChip={(value) => formatEmitterCategory(value) ?? value}
          suggestions={EMITTER_SUGGESTIONS}
          validate={validateEmitterCategory}
          describedBy={describedBy}
          invalid={error !== null}
          onChange={(values) => {
            onChange({ ...draft, values });
          }}
        />
      )}

      {draft.kind === "within_area" && (
        <AreaEditor
          text={draft.text}
          describedBy={describedBy}
          invalid={error !== null}
          onChange={(text) => {
            onChange({ ...draft, text });
          }}
        />
      )}

      {(draft.kind === "distance" ||
        draft.kind === "altitude" ||
        draft.kind === "ground_speed" ||
        draft.kind === "vertical_rate") && (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${fieldId}-min`}>
              {WINDOW_LABELS[draft.kind].min}
            </Label>
            <Input
              id={`${fieldId}-min`}
              inputMode="decimal"
              value={draft.min}
              placeholder="Any"
              aria-invalid={error !== null}
              aria-describedby={describedBy}
              onChange={(event) => {
                onChange({ ...draft, min: event.target.value });
              }}
            />
            {showMetricHints && metricConversionHint(draft.min, draft.kind) && (
              <p className="text-xs text-muted-foreground">
                {metricConversionHint(draft.min, draft.kind)}
              </p>
            )}
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${fieldId}-max`}>
              {WINDOW_LABELS[draft.kind].max}
            </Label>
            <Input
              id={`${fieldId}-max`}
              inputMode="decimal"
              value={draft.max}
              placeholder="Any"
              aria-invalid={error !== null}
              aria-describedby={describedBy}
              onChange={(event) => {
                onChange({ ...draft, max: event.target.value });
              }}
            />
            {showMetricHints && metricConversionHint(draft.max, draft.kind) && (
              <p className="text-xs text-muted-foreground">
                {metricConversionHint(draft.max, draft.kind)}
              </p>
            )}
          </div>
          {draft.kind === "vertical_rate" && (
            <p className="text-xs text-muted-foreground sm:col-span-2">
              Negative is descending: “At or below -1000” matches an aircraft
              descending at 1000 ft/min or faster.
            </p>
          )}
        </div>
      )}

      <FieldError id={errorId} message={error} />
    </fieldset>
  );
}
