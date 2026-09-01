import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ALERT_TEMPLATES } from "@/features/setup/constants";
import { FieldError } from "@/features/setup/components/FieldError";
import { SectionSaveBar } from "@/features/settings/components/SectionSaveBar";
import { SettingsSection } from "@/features/settings/components/SettingsSection";
import {
  buildAlertsPatch,
  draftFromConfig,
  isSectionDirty,
  pickAlerts,
} from "@/features/settings/lib/draft";
import { validateAlertRadius } from "@/features/settings/lib/validation";
import {
  fieldErrorsFrom,
  generalErrorMessage,
} from "@/features/settings/lib/errors";
import { usePutConfigMutation } from "@/lib/api/config";
import type { FlightSiteConfig } from "@/lib/api/config";

export interface AlertsSectionProps {
  config: FlightSiteConfig;
}

/** Alert radius (SPEC §66) and which built-in alert templates are enabled
 * (SPEC §45). Applies immediately. */
export function AlertsSection({ config }: AlertsSectionProps) {
  const [baseline, setBaseline] = useState(() =>
    pickAlerts(draftFromConfig(config)),
  );
  const [draft, setDraft] = useState(baseline);
  const mutation = usePutConfigMutation();

  const isDirty = isSectionDirty(draft, baseline);
  const fieldErrors = fieldErrorsFrom(mutation.error);
  const alertRadiusError =
    validateAlertRadius(draft.alertRadiusNm) ??
    fieldErrors.alert_radius_nm ??
    null;

  function toggleTemplate(id: string, checked: boolean) {
    const next = checked
      ? [...draft.enabledTemplateIds, id]
      : draft.enabledTemplateIds.filter((existing) => existing !== id);
    setDraft({ ...draft, enabledTemplateIds: next });
  }

  function handleSave() {
    mutation.mutate(buildAlertsPatch(draft), {
      onSuccess: (response) => {
        const next = pickAlerts(draftFromConfig(response.config));
        setBaseline(next);
        setDraft(next);
      },
    });
  }

  return (
    <SettingsSection
      id="settings-alerts"
      title="Alerts"
      description="How far alerts consider aircraft, and which built-in templates are enabled."
    >
      <div className="flex max-w-lg flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="settings-alert-radius">
            Alert radius (nm, optional)
          </Label>
          <Input
            id="settings-alert-radius"
            inputMode="decimal"
            placeholder="Unlimited"
            value={draft.alertRadiusNm}
            aria-invalid={alertRadiusError !== null}
            aria-describedby={
              alertRadiusError ? "settings-alert-radius-error" : undefined
            }
            onChange={(event) => {
              setDraft({ ...draft, alertRadiusNm: event.target.value });
            }}
          />
          <FieldError
            id="settings-alert-radius-error"
            message={alertRadiusError}
          />
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

      <SectionSaveBar
        isDirty={isDirty}
        isPending={mutation.isPending}
        justSaved={mutation.isSuccess && !isDirty}
        errorMessage={generalErrorMessage(mutation.error, fieldErrors)}
        hasBlockingError={alertRadiusError !== null}
        onSave={handleSave}
      />
    </SettingsSection>
  );
}
