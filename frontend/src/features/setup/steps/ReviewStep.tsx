import { ALERT_TEMPLATES } from "@/features/setup/constants";
import type { DecoderTestState, WizardDraft } from "@/features/setup/types";

export interface ReviewStepProps {
  draft: WizardDraft;
  testState: DecoderTestState;
  hasStoredKey: boolean;
  submitError: string | null;
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 py-1.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="text-right font-medium">{value}</span>
    </div>
  );
}

/** Step (h): a read-only summary of every value collected so far, and
 * (via `WizardNav`'s Finish button, outside this component) the single
 * `PUT /api/internal/config` that saves it all at once. */
export function ReviewStep({
  draft,
  testState,
  hasStoredKey,
  submitError,
}: ReviewStepProps) {
  const selectedTemplateLabels = ALERT_TEMPLATES.filter((template) =>
    draft.enabledTemplateIds.includes(template.id),
  ).map((template) => template.label);

  const decoderStatus = testState.skipped
    ? "Skipped"
    : testState.status === "success"
      ? "Passed"
      : testState.status === "error"
        ? "Failed (will still save)"
        : "Not tested";

  const willHaveKey = draft.aerodataboxKeyTouched
    ? draft.aerodataboxKeyInput.trim().length > 0
    : hasStoredKey;

  return (
    <div className="flex max-w-lg flex-col gap-6">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight">Review</h2>
        <p className="text-sm text-muted-foreground">
          Everything below is saved together when you finish setup.
        </p>
      </div>

      <div className="divide-y divide-border rounded-lg border border-border bg-card px-4">
        <SummaryRow label="Site name" value={draft.siteName || "—"} />
        <SummaryRow
          label="Location"
          value={
            draft.latitude && draft.longitude
              ? `${draft.latitude}, ${draft.longitude}`
              : "—"
          }
        />
        <SummaryRow
          label="Decoder"
          value={`${draft.receiverHost}:${draft.receiverPort}${draft.receiverPath}`}
        />
        <SummaryRow label="Poll interval" value={`${draft.pollIntervalS} s`} />
        <SummaryRow label="Connection test" value={decoderStatus} />
        <SummaryRow
          label="Units"
          value={draft.units === "metric" ? "Metric" : "Aviation"}
        />
        <SummaryRow label="Timezone" value={draft.timezone} />
        <SummaryRow
          label="Browser notifications"
          value={draft.notifications.enabled ? "Enabled" : "Disabled"}
        />
        <SummaryRow
          label="AeroDataBox key"
          value={willHaveKey ? "Set" : "Not set"}
        />
        <SummaryRow
          label="Alert templates"
          value={
            selectedTemplateLabels.length > 0
              ? selectedTemplateLabels.join(", ")
              : "None"
          }
        />
      </div>

      {submitError && (
        <p role="alert" className="text-sm text-destructive">
          {submitError}
        </p>
      )}
    </div>
  );
}
