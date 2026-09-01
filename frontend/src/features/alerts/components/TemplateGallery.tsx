import { useId, useState } from "react";

import { Button } from "@/components/ui/button";
import { AlertSeverityBadge } from "@/features/sightings/components/AlertSeverityBadge";
import {
  useAlertRulesQuery,
  useAlertTemplatesQuery,
  useInstantiateAlertTemplateMutation,
  type AlertTemplate,
} from "@/lib/api/alertRules";

function errorMessage(error: unknown): string | null {
  if (!error) {
    return null;
  }
  return error instanceof Error ? error.message : "Something went wrong.";
}

interface TemplateCardProps {
  template: AlertTemplate;
  /** Whether a rule already carries this template's provenance. */
  instantiated: boolean;
  isPending: boolean;
  error: string | null;
  onAdd: () => void;
}

function TemplateCard({
  template,
  instantiated,
  isPending,
  error,
  onAdd,
}: TemplateCardProps) {
  const headingId = useId();

  return (
    <article
      aria-labelledby={headingId}
      className="flex flex-col gap-2 rounded-lg border border-border bg-card p-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h3 id={headingId} className="text-sm font-semibold text-foreground">
            {template.name}
          </h3>
          <div className="flex flex-wrap items-center gap-2">
            <AlertSeverityBadge severity={template.severity} />
            {template.builtin && (
              <span className="inline-flex items-center rounded-full border border-accent/60 px-2 py-0.5 text-xs font-semibold text-accent">
                Always on
              </span>
            )}
            {!template.builtin && instantiated && (
              <span className="inline-flex items-center rounded-full border border-border px-2 py-0.5 text-xs font-semibold text-muted-foreground">
                Added
              </span>
            )}
          </div>
        </div>

        {/* A card carries a button only while there is something to do with
            it. A built-in template never has one — SPEC §47 makes emergency
            alerting fire without a rule and gives a user nothing to switch —
            and an added one no longer does, its rule having moved to the
            Rules tab. A disabled button in either place would read as "not
            yet" when the answer is "never" and "already". */}
        {!template.builtin && !instantiated && (
          <Button
            type="button"
            size="sm"
            disabled={isPending}
            aria-label={`Add a rule from the ${template.name} template`}
            onClick={onAdd}
          >
            {isPending ? "Adding…" : "Add rule"}
          </Button>
        )}
      </div>

      <p className="text-xs text-muted-foreground">{template.description}</p>

      {!template.builtin && instantiated && (
        <p className="text-xs text-muted-foreground">
          A rule from this template is on the Rules tab, where it can be
          retuned or turned off.
        </p>
      )}

      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </article>
  );
}

/**
 * The shipped-template gallery (SPEC §45, roadmap slice 041).
 *
 * Adding a template creates a real rule carrying its `template_key`, so a
 * template is "added" exactly when a rule with that provenance exists —
 * which is read from the rule list rather than tracked here. That is what
 * lets a user delete a shipped rule and see the template offer itself again,
 * rather than the gallery insisting it is still enabled.
 *
 * The emergency template is the odd one out and is shown anyway: a user
 * opening this gallery must be able to see that emergency alerting exists.
 * It is rendered as a statement rather than as a switch, because SPEC §47
 * makes 7500/7600/7700 fire without any rule and with nothing to disable.
 */
export function TemplateGallery() {
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  const templatesQuery = useAlertTemplatesQuery();
  const rulesQuery = useAlertRulesQuery();
  const instantiateMutation = useInstantiateAlertTemplateMutation();

  const instantiatedKeys = new Set(
    (rulesQuery.data?.rules ?? [])
      .map((rule) => rule.template_key)
      .filter((key): key is string => key !== null),
  );

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Ready-made rules for the things most receivers are set up to catch.
        Adding one creates a normal rule you can retune on the Rules tab.
      </p>

      {templatesQuery.isPending && (
        <p className="text-sm text-muted-foreground">Loading templates…</p>
      )}

      {templatesQuery.isError && (
        <p role="alert" className="text-sm text-destructive">
          Could not load templates
          {templatesQuery.error instanceof Error
            ? `: ${templatesQuery.error.message}`
            : "."}
        </p>
      )}

      {templatesQuery.data && (
        <ul className="flex flex-col gap-3">
          {templatesQuery.data.templates.map((template) => (
            <li key={template.key}>
              <TemplateCard
                template={template}
                instantiated={instantiatedKeys.has(template.key)}
                isPending={
                  instantiateMutation.isPending && pendingKey === template.key
                }
                error={
                  pendingKey === template.key
                    ? errorMessage(instantiateMutation.error)
                    : null
                }
                onAdd={() => {
                  setPendingKey(template.key);
                  instantiateMutation.mutate(template.key);
                }}
              />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
