import { useState } from "react";

import { Button } from "@/components/ui/button";
import { RuleBuilderForm } from "@/features/alerts/components/RuleBuilderForm";
import { RuleCard } from "@/features/alerts/components/RuleCard";
import {
  useAlertRulesQuery,
  useAlertTemplatesQuery,
  useCreateAlertRuleMutation,
  type AlertRule,
  type AlertRuleWriteInput,
} from "@/lib/api/alertRules";

function errorMessage(error: unknown): string | null {
  if (!error) {
    return null;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

export interface AlertRulesSectionProps {
  /** Called when a card's "Show matches" control is used (issue #98). The
   * history it opens lives in a sibling area, so this section only reports
   * the choice; the page above decides what to do with it. Omit it and the
   * cards offer no such control. */
  onShowMatches?: (rule: AlertRule) => void;
}

/**
 * Alert rule management (SPEC §43, roadmap slice 041): the rule list, and
 * the visual builder that creates one.
 *
 * The builder is behind a button rather than always open, the way the
 * Watchlists tab keeps its create form: the list is what a returning user
 * came for, and a permanently-open form pushes it below the fold.
 *
 * Template provenance is resolved here, from the catalogue, because a
 * `template_key` is a key and a card wants a name. The catalogue is static
 * data compiled into the backend, so this costs one cached read for the
 * whole list rather than a lookup per rule.
 */
export function AlertRulesSection({ onShowMatches }: AlertRulesSectionProps) {
  const [creating, setCreating] = useState(false);

  const rulesQuery = useAlertRulesQuery();
  const templatesQuery = useAlertTemplatesQuery();
  const createMutation = useCreateAlertRuleMutation();

  const rules = rulesQuery.data?.rules ?? [];
  const templateNames = new Map(
    (templatesQuery.data?.templates ?? []).map((template) => [
      template.key,
      template.name,
    ]),
  );

  function handleCreate(input: AlertRuleWriteInput): void {
    createMutation.mutate(input, {
      onSuccess: () => {
        setCreating(false);
      },
    });
  }

  return (
    <div className="flex flex-col gap-4">
      {creating ? (
        <RuleBuilderForm
          submitLabel="Create rule"
          isPending={createMutation.isPending}
          serverError={errorMessage(createMutation.error)}
          onSubmit={handleCreate}
          onCancel={() => {
            setCreating(false);
          }}
        />
      ) : (
        <div>
          <Button
            type="button"
            size="sm"
            onClick={() => {
              setCreating(true);
            }}
          >
            New rule
          </Button>
        </div>
      )}

      {rulesQuery.isPending && (
        <p className="text-sm text-muted-foreground">Loading alert rules…</p>
      )}

      {rulesQuery.isError && (
        <p role="alert" className="text-sm text-destructive">
          Could not load alert rules
          {rulesQuery.error instanceof Error
            ? `: ${rulesQuery.error.message}`
            : "."}
        </p>
      )}

      {rulesQuery.data && rules.length === 0 && (
        <p className="text-sm text-muted-foreground">
          No alert rules yet. Build one above, or enable a shipped template on
          the Templates tab.
        </p>
      )}

      {rules.length > 0 && (
        <ul className="flex flex-col gap-3">
          {rules.map((rule) => (
            <li key={rule.id}>
              <RuleCard
                rule={rule}
                onShowMatches={onShowMatches}
                templateName={
                  rule.template_key === null
                    ? null
                    : (templateNames.get(rule.template_key) ??
                      rule.template_key)
                }
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
