import { useState } from "react";
import { Link } from "react-router-dom";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  fieldMessage,
  generalErrorMessage,
} from "@/features/settings/lib/errors";
import { usePutConfigMutation } from "@/lib/api/config";
import type { FlightSiteConfig } from "@/lib/api/config";

export interface AlertsSectionProps {
  config: FlightSiteConfig;
}

/**
 * Alert radius (SPEC §66). Applies immediately.
 *
 * R4-03: this section used to also carry a checkbox per shipped template,
 * backed by `config.alerts.enabled_templates` — a second, contradictory
 * control for the same thing the Alerts page's Templates gallery manages.
 * The two never reconciled: adding a rule from the gallery left the
 * checkbox unticked, and the config key has no delete path, so unticking a
 * box here never removed the rule it once seeded. The gallery is the
 * honest source (it resolves "added" from real rule provenance) and is now
 * the only surface — this section only links to it.
 * `config.alerts.enabled_templates` still exists and is still read, once,
 * by the setup wizard as the first-run seed for which templates to
 * instantiate; it is simply no longer editable from here.
 */
export function AlertsSection({ config }: AlertsSectionProps) {
  const [baseline, setBaseline] = useState(() =>
    pickAlerts(draftFromConfig(config)),
  );
  const [draft, setDraft] = useState(baseline);
  const mutation = usePutConfigMutation();

  const isDirty = isSectionDirty(draft, baseline);
  const fieldErrors = fieldErrorsFrom(mutation.error);
  // R4-02: only the client-side check blocks Save — a server rejection of
  // the radius stays visible but retryable.
  const alertRadius = fieldMessage(
    validateAlertRadius(draft.alertRadiusNm),
    fieldErrors.alert_radius_nm,
  );
  const alertRadiusError = alertRadius.message;

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
      description="How far alerts consider aircraft."
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

        <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-background p-3">
          <p className="text-sm font-medium">Alert templates</p>
          <p className="text-xs text-muted-foreground">
            Ready-made rules for military, government, emergency-squawk and
            other traffic are managed on the Alerts page now, where adding or
            removing one changes a real rule instead of a checkbox that could
            disagree with it.
          </p>
          <Link
            to="/alerts?tab=templates"
            className="text-xs font-medium text-accent hover:underline"
          >
            Manage templates on the Alerts page
          </Link>
        </div>
      </div>

      <SectionSaveBar
        isDirty={isDirty}
        isPending={mutation.isPending}
        justSaved={mutation.isSuccess && !isDirty}
        errorMessage={generalErrorMessage(mutation.error, fieldErrors)}
        hasBlockingError={alertRadius.blocking}
        onSave={handleSave}
      />
    </SettingsSection>
  );
}
