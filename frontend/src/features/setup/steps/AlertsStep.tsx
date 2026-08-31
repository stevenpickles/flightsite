import { ALERT_TEMPLATES } from "@/features/setup/constants";
import type { WizardDraft } from "@/features/setup/types";

export interface AlertsStepProps {
  draft: WizardDraft;
  onChange: (patch: Partial<WizardDraft>) => void;
}

/**
 * Step (g): initial alert template selection (SPEC §45). Templates only
 * activate once the rule engine ships (phase 6) — this step just records
 * which ones the user wants enabled by then, into `alerts.enabled_templates`.
 * Any selection, including none, is valid: SPEC §45 is explicit that
 * nothing is silently enabled, so declining every template is a legitimate
 * choice, not an error.
 */
export function AlertsStep({ draft, onChange }: AlertsStepProps) {
  function toggleTemplate(id: string, checked: boolean) {
    const next = checked
      ? [...draft.enabledTemplateIds, id]
      : draft.enabledTemplateIds.filter((existing) => existing !== id);
    onChange({ enabledTemplateIds: next });
  }

  return (
    <div className="flex max-w-lg flex-col gap-6">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight">
          Alert templates
        </h2>
        <p className="text-sm text-muted-foreground">
          Choose which of the built-in interesting-aircraft templates to start
          with. These take effect once the alert rule engine arrives; you can
          change this anytime from Settings.
        </p>
      </div>

      <div
        role="group"
        aria-label="Alert templates"
        className="flex flex-col gap-2"
      >
        {ALERT_TEMPLATES.map((template) => {
          const checked = draft.enabledTemplateIds.includes(template.id);
          return (
            <label
              key={template.id}
              className="flex items-start gap-3 rounded-lg border border-border p-3"
            >
              <input
                type="checkbox"
                className="mt-0.5"
                checked={checked}
                onChange={(event) => {
                  toggleTemplate(template.id, event.target.checked);
                }}
              />
              <span className="flex flex-col gap-0.5">
                <span className="text-sm font-medium">{template.label}</span>
                <span className="text-xs text-muted-foreground">
                  {template.description}
                </span>
              </span>
            </label>
          );
        })}
      </div>
    </div>
  );
}
