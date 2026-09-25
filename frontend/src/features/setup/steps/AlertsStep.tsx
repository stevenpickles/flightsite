import { ALERT_TEMPLATES } from "@/features/setup/constants";
import type { WizardDraft } from "@/features/setup/types";

export interface AlertsStepProps {
  draft: WizardDraft;
  onChange: (patch: Partial<WizardDraft>) => void;
}

/**
 * Step (g): initial alert template selection (SPEC §45). Each template
 * ticked here becomes a real, editable rule the moment setup finishes —
 * `alerts.enabled_templates` is read exactly once, as this install's
 * first-run seed, by `AlertService.apply_enabled_templates`. After that the
 * Alerts page's Templates gallery is the only place templates are managed
 * (R4-03): this step's selection has no further effect once setup
 * completes, so re-running the wizard does not re-add or remove anything.
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
          with. Each one you tick becomes a rule you can retune or switch off on
          the Alerts page after setup — this is only the starting point, not an
          ongoing setting.
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
