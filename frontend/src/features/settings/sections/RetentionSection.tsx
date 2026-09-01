import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";
import { SectionSaveBar } from "@/features/settings/components/SectionSaveBar";
import { SettingsSection } from "@/features/settings/components/SettingsSection";
import {
  buildRetentionPatch,
  draftFromConfig,
  isSectionDirty,
  pickRetention,
} from "@/features/settings/lib/draft";
import { validateHighResMetricDays } from "@/features/settings/lib/validation";
import {
  fieldErrorsFrom,
  generalErrorMessage,
} from "@/features/settings/lib/errors";
import { usePutConfigMutation } from "@/lib/api/config";
import type { FlightSiteConfig } from "@/lib/api/config";

export interface RetentionSectionProps {
  config: FlightSiteConfig;
}

/** High-resolution receiver-metric retention window (SPEC §64 / ADR-0009).
 * Sighting history itself is retained indefinitely and is not user-tunable
 * (SPEC §65). Applies immediately — the next retention sweep uses the new
 * window. */
export function RetentionSection({ config }: RetentionSectionProps) {
  const [baseline, setBaseline] = useState(() =>
    pickRetention(draftFromConfig(config)),
  );
  const [draft, setDraft] = useState(baseline);
  const mutation = usePutConfigMutation();

  const isDirty = isSectionDirty(draft, baseline);
  const fieldErrors = fieldErrorsFrom(mutation.error);
  const daysError =
    validateHighResMetricDays(draft.highResMetricDays) ??
    fieldErrors["retention.high_res_metric_days"] ??
    null;

  function handleSave() {
    mutation.mutate(buildRetentionPatch(draft), {
      onSuccess: (response) => {
        const next = pickRetention(draftFromConfig(response.config));
        setBaseline(next);
        setDraft(next);
      },
    });
  }

  return (
    <SettingsSection
      id="settings-retention"
      title="Retention"
      description="How long high-resolution receiver metrics are kept (7–30 days)."
    >
      <div className="flex max-w-lg flex-col gap-1.5">
        <Label htmlFor="settings-retention-days">
          High-resolution metric retention (days)
        </Label>
        <Input
          id="settings-retention-days"
          inputMode="numeric"
          value={draft.highResMetricDays}
          aria-invalid={daysError !== null}
          aria-describedby={
            daysError ? "settings-retention-days-error" : undefined
          }
          onChange={(event) => {
            setDraft({ highResMetricDays: event.target.value });
          }}
        />
        <FieldError id="settings-retention-days-error" message={daysError} />
      </div>

      <SectionSaveBar
        isDirty={isDirty}
        isPending={mutation.isPending}
        justSaved={mutation.isSuccess && !isDirty}
        errorMessage={generalErrorMessage(mutation.error, fieldErrors)}
        hasBlockingError={daysError !== null}
        onSave={handleSave}
      />
    </SettingsSection>
  );
}
