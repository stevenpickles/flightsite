import { useId } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";
import {
  conditionKindMeta,
  type ConditionDraft,
} from "@/features/alerts/lib/conditions";
import { MISSION_OPTIONS } from "@/features/alerts/lib/vocabulary";
import type { AlertMissionCategory } from "@/lib/api/alertRules";
import type { Watchlist } from "@/lib/api/watchlists";

/** Shared with `EntryForm` in the watchlists feature — a native `<select>`
 * dressed to match the `Input` primitive, there being no shadcn select in
 * this build. */
const SELECT_CLASSES =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50";

const CHECKBOX_CLASSES =
  "size-4 rounded border-input accent-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";

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

      {(draft.kind === "distance" || draft.kind === "altitude") && (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${fieldId}-min`}>
              {draft.kind === "distance" ? "At least (nm)" : "At or above (ft)"}
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
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${fieldId}-max`}>
              {draft.kind === "distance" ? "Within (nm)" : "At or below (ft)"}
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
          </div>
        </div>
      )}

      <FieldError id={errorId} message={error} />
    </fieldset>
  );
}
