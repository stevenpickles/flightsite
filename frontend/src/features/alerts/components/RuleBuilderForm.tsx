import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";
import { ConditionEditor } from "@/features/alerts/components/ConditionEditor";
import {
  availableKinds,
  conditionsToDocument,
  documentToConditions,
  emptyCondition,
  isRuleDraftValid,
  validateCondition,
  validateConditionList,
  validateRuleDescription,
  validateRuleName,
  type ConditionDraft,
  type ConditionKind,
} from "@/features/alerts/lib/conditions";
import { SEVERITY_OPTIONS } from "@/features/alerts/lib/vocabulary";
import type { AlertRule, AlertRuleWriteInput } from "@/lib/api/alertRules";
import type { AlertSeverity } from "@/lib/api/sightings";
import { useWatchlistsQuery } from "@/lib/api/watchlists";

const SELECT_CLASSES =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50";

const CHECKBOX_CLASSES =
  "size-4 rounded border-input accent-accent focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring";

export interface RuleBuilderFormProps {
  /** The rule to edit. Absent when building a new one. */
  rule?: AlertRule;
  onSubmit: (input: AlertRuleWriteInput) => void;
  onCancel?: () => void;
  isPending: boolean;
  /** The backend's own rejection of the last submission, shown beside the
   * builder's checks rather than instead of them — the backend stays
   * authoritative even where this form has mirrored one of its rules. */
  serverError: string | null;
  submitLabel: string;
}

/**
 * The visual rule builder (SPEC §43, roadmap slice 041).
 *
 * Conditions are added one at a time from the v1 set and combined with
 * `AND` — every one must hold — which is the only combinator v1 has; there
 * are deliberately no OR groups or nested expressions to build here.
 *
 * Validation runs continuously but is only *shown* after the first submit
 * attempt: an error on a field nobody has reached yet is noise, and a form
 * that argues while it is being filled in is worse than one that answers
 * when asked. The submit button stays enabled for the same reason — a
 * disabled button explains nothing, whereas a click that reveals exactly
 * what is missing does. An invalid rule is never sent either way, which is
 * what "the builder prevents invalid rules" means.
 */
export function RuleBuilderForm({
  rule,
  onSubmit,
  onCancel,
  isPending,
  serverError,
  submitLabel,
}: RuleBuilderFormProps) {
  const initial = rule
    ? documentToConditions(rule.conditions)
    : { drafts: [] as ConditionDraft[], appliesOnGround: false };

  const [name, setName] = useState(rule?.name ?? "");
  const [description, setDescription] = useState(rule?.description ?? "");
  const [severity, setSeverity] = useState<AlertSeverity>(
    rule?.severity ?? "interesting",
  );
  const [enabled, setEnabled] = useState(rule?.enabled ?? true);
  const [drafts, setDrafts] = useState<ConditionDraft[]>(initial.drafts);
  const [appliesOnGround, setAppliesOnGround] = useState(
    initial.appliesOnGround,
  );
  const [nextKind, setNextKind] = useState<ConditionKind | "">("");
  const [submitted, setSubmitted] = useState(false);

  const watchlistsQuery = useWatchlistsQuery();
  const watchlists = watchlistsQuery.data?.watchlists ?? [];

  const nameId = useId();
  const descriptionId = useId();
  const severityId = useId();
  const addId = useId();

  const remaining = availableKinds(drafts);
  const nameError = submitted ? validateRuleName(name) : null;
  const descriptionError = submitted
    ? validateRuleDescription(description)
    : null;
  const listError = submitted ? validateConditionList(drafts) : null;
  const severityHint = SEVERITY_OPTIONS.find(
    (option) => option.value === severity,
  )?.hint;

  function updateDraft(index: number, next: ConditionDraft): void {
    setDrafts((current) =>
      current.map((draft, position) => (position === index ? next : draft)),
    );
  }

  function removeDraft(index: number): void {
    setDrafts((current) =>
      current.filter((_draft, position) => position !== index),
    );
  }

  function addCondition(): void {
    if (nextKind === "") {
      return;
    }
    setDrafts((current) => [...current, emptyCondition(nextKind)]);
    setNextKind("");
  }

  function handleSubmit(event: React.FormEvent): void {
    event.preventDefault();
    setSubmitted(true);
    if (!isRuleDraftValid(name, description, drafts)) {
      return;
    }
    onSubmit({
      name: name.trim(),
      description:
        description.trim().length > 0 ? description.trim() : null,
      severity,
      conditions: conditionsToDocument(drafts, appliesOnGround),
      enabled,
    });
  }

  return (
    <form
      onSubmit={handleSubmit}
      aria-label={rule ? `Edit rule ${rule.name}` : "Create an alert rule"}
      className="flex flex-col gap-4 rounded-lg border border-border bg-card p-4"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={nameId}>Name</Label>
          <Input
            id={nameId}
            value={name}
            placeholder="Military aircraft"
            aria-invalid={nameError !== null}
            aria-describedby={nameError ? `${nameId}-error` : undefined}
            onChange={(event) => {
              setName(event.target.value);
            }}
          />
          <FieldError id={`${nameId}-error`} message={nameError} />
          <p className="text-xs text-muted-foreground">
            Shown in notifications and in the alert history, so name it after
            what it detects.
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor={severityId}>Severity</Label>
          <select
            id={severityId}
            className={SELECT_CLASSES}
            value={severity}
            onChange={(event) => {
              setSeverity(event.target.value as AlertSeverity);
            }}
          >
            {SEVERITY_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
          <p className="text-xs text-muted-foreground">{severityHint}</p>
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={descriptionId}>Description (optional)</Label>
        <Input
          id={descriptionId}
          value={description}
          aria-invalid={descriptionError !== null}
          aria-describedby={
            descriptionError ? `${descriptionId}-error` : undefined
          }
          onChange={(event) => {
            setDescription(event.target.value);
          }}
        />
        <FieldError
          id={`${descriptionId}-error`}
          message={descriptionError}
        />
      </div>

      <div className="flex flex-col gap-3">
        <div className="space-y-1">
          <h4 className="text-sm font-medium text-foreground">Conditions</h4>
          <p className="text-xs text-muted-foreground">
            Every condition must hold for the rule to match.
          </p>
        </div>

        {drafts.map((draft, index) => (
          <ConditionEditor
            key={draft.kind}
            draft={draft}
            error={submitted ? validateCondition(draft) : null}
            watchlists={watchlists}
            onChange={(next) => {
              updateDraft(index, next);
            }}
            onRemove={() => {
              removeDraft(index);
            }}
          />
        ))}

        <FieldError id={`${addId}-list-error`} message={listError} />

        <div className="flex flex-wrap items-end gap-2">
          <div className="flex min-w-48 flex-1 flex-col gap-1.5">
            <Label htmlFor={addId}>Add a condition</Label>
            <select
              id={addId}
              className={SELECT_CLASSES}
              value={nextKind}
              disabled={remaining.length === 0}
              onChange={(event) => {
                setNextKind(event.target.value as ConditionKind | "");
              }}
            >
              <option value="">
                {remaining.length === 0
                  ? "Every condition is already in use"
                  : "Choose a condition…"}
              </option>
              {remaining.map((meta) => (
                <option key={meta.kind} value={meta.kind}>
                  {meta.label}
                </option>
              ))}
            </select>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={nextKind === ""}
            onClick={addCondition}
          >
            Add condition
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input
            type="checkbox"
            className={CHECKBOX_CLASSES}
            checked={appliesOnGround}
            onChange={(event) => {
              setAppliesOnGround(event.target.checked);
            }}
          />
          Also alert for aircraft on the ground
        </label>
        <p className="text-xs text-muted-foreground">
          Off by default: a rule about military aircraft usually means ones
          that are flying, not one parked on a ramp the receiver hears all
          day.
        </p>

        <label className="flex items-center gap-2 text-sm text-foreground">
          <input
            type="checkbox"
            className={CHECKBOX_CLASSES}
            checked={enabled}
            onChange={(event) => {
              setEnabled(event.target.checked);
            }}
          />
          Enabled
        </label>
      </div>

      {serverError && (
        <p role="alert" className="text-xs text-destructive">
          {serverError}
        </p>
      )}

      <div className="flex gap-2">
        <Button type="submit" size="sm" disabled={isPending}>
          {isPending ? "Saving…" : submitLabel}
        </Button>
        {onCancel && (
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  );
}
