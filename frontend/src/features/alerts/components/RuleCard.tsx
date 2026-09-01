import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { RuleBuilderForm } from "@/features/alerts/components/RuleBuilderForm";
import { AlertSeverityBadge } from "@/features/sightings/components/AlertSeverityBadge";
import {
  useDeleteAlertRuleMutation,
  useUpdateAlertRuleMutation,
  type AlertRule,
  type AlertRuleWriteInput,
} from "@/lib/api/alertRules";

function errorMessage(error: unknown): string | null {
  if (!error) {
    return null;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

/** The whole of a rule as a write body — what "toggle enabled" and "save an
 * edit" both send, because `PUT` is a full replace rather than a patch. A
 * partial update of an `AND` condition set would be ambiguous about whether
 * an omitted condition was meant to be removed. */
function writeBodyFor(
  rule: AlertRule,
  overrides: Partial<AlertRuleWriteInput> = {},
): AlertRuleWriteInput {
  return {
    name: rule.name,
    description: rule.description,
    severity: rule.severity,
    conditions: rule.conditions,
    enabled: rule.enabled,
    ...overrides,
  };
}

export interface RuleCardProps {
  rule: AlertRule;
  /** The shipped template this rule came from, by name; `null` for a
   * user-written rule, or for a `template_key` this build no longer ships. */
  templateName: string | null;
}

/**
 * One alert rule: what it is called, how loudly it fires, where it came
 * from, what it actually asks, and whether it is on.
 *
 * Status is text first (SPEC §80, never colour alone): a disabled rule says
 * "Disabled", and severity is the badge's own word rather than a tint. The
 * conditions are rendered from the backend's `describes`, so this card and a
 * notification and the alert history all say the same thing about a rule
 * instead of three renderings that drift.
 */
export function RuleCard({ rule, templateName }: RuleCardProps) {
  const [editing, setEditing] = useState(false);
  const headingId = useId();

  const updateMutation = useUpdateAlertRuleMutation();
  const deleteMutation = useDeleteAlertRuleMutation();

  const actionError =
    errorMessage(updateMutation.error) ?? errorMessage(deleteMutation.error);

  function toggleEnabled(): void {
    updateMutation.mutate({
      ruleId: rule.id,
      input: writeBodyFor(rule, { enabled: !rule.enabled }),
    });
  }

  function handleDelete(): void {
    const confirmed = window.confirm(
      `Delete “${rule.name}”? The alerts it has already recorded are deleted with it.`,
    );
    if (confirmed) {
      deleteMutation.mutate(rule.id);
    }
  }

  function handleSave(input: AlertRuleWriteInput): void {
    updateMutation.mutate(
      { ruleId: rule.id, input },
      { onSuccess: () => { setEditing(false); } },
    );
  }

  return (
    <article
      aria-labelledby={headingId}
      className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h3 id={headingId} className="text-sm font-semibold text-foreground">
            {rule.name}
          </h3>
          <div className="flex flex-wrap items-center gap-2">
            <AlertSeverityBadge severity={rule.severity} />
            <span
              className={
                rule.enabled
                  ? "inline-flex items-center rounded-full border border-border px-2 py-0.5 text-xs font-semibold text-muted-foreground"
                  : "inline-flex items-center rounded-full border border-amber-500/60 px-2 py-0.5 text-xs font-semibold text-amber-600 dark:text-amber-400"
              }
            >
              {rule.enabled ? "Enabled" : "Disabled"}
            </span>
            {templateName !== null && (
              <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-xs text-muted-foreground">
                From template: {templateName}
              </span>
            )}
          </div>
          {rule.description !== null && (
            <p className="text-xs text-muted-foreground">{rule.description}</p>
          )}
        </div>

        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={updateMutation.isPending}
            aria-label={`${rule.enabled ? "Disable" : "Enable"} ${rule.name}`}
            onClick={toggleEnabled}
          >
            {rule.enabled ? "Disable" : "Enable"}
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-expanded={editing}
            aria-label={`Edit ${rule.name}`}
            onClick={() => {
              setEditing((current) => !current);
            }}
          >
            {editing ? "Close" : "Edit"}
          </Button>
          <Button
            type="button"
            variant="destructive"
            size="sm"
            disabled={deleteMutation.isPending}
            aria-label={`Delete ${rule.name}`}
            onClick={handleDelete}
          >
            Delete
          </Button>
        </div>
      </div>

      <div className="space-y-1">
        <h4 className="text-xs font-medium text-muted-foreground">
          Matches aircraft that are
        </h4>
        <ul className="flex flex-col gap-0.5 text-xs text-foreground">
          {rule.describes.map((phrase) => (
            <li key={phrase}>{phrase}</li>
          ))}
        </ul>
        {rule.conditions.applies_on_ground === true && (
          <p className="text-xs text-muted-foreground">
            Includes aircraft on the ground.
          </p>
        )}
      </div>

      {actionError && (
        <p role="alert" className="text-xs text-destructive">
          {actionError}
        </p>
      )}

      {editing && (
        <RuleBuilderForm
          rule={rule}
          submitLabel="Save changes"
          isPending={updateMutation.isPending}
          serverError={errorMessage(updateMutation.error)}
          onSubmit={handleSave}
          onCancel={() => {
            setEditing(false);
          }}
        />
      )}
    </article>
  );
}
