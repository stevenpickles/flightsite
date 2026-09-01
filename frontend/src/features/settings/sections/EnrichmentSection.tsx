import { KeyRound } from "lucide-react";
import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SectionSaveBar } from "@/features/settings/components/SectionSaveBar";
import { SettingsSection } from "@/features/settings/components/SettingsSection";
import {
  buildEnrichmentPatch,
  draftFromConfig,
  isSectionDirty,
  pickEnrichment,
} from "@/features/settings/lib/draft";
import {
  fieldErrorsFrom,
  generalErrorMessage,
} from "@/features/settings/lib/errors";
import { usePutConfigMutation } from "@/lib/api/config";
import type { FlightSiteConfig } from "@/lib/api/config";

export interface EnrichmentSectionProps {
  config: FlightSiteConfig;
  /** Whether an AeroDataBox key is currently stored server-side
   * (`secrets_set["enrichment.aerodatabox_api_key"]`). The real value is
   * never sent to the frontend (SPEC §29) — this is all there is to show. */
  hasStoredKey: boolean;
}

/**
 * Online route enrichment (SPEC §28): the AeroDataBox API key, masked, plus
 * whether enrichment is enabled. Applies immediately. The key input is
 * always empty on load — only `hasStoredKey` says whether one exists — and
 * an explicit "Clear stored key" is the only way to remove one, so a
 * left-blank-and-saved field never silently wipes a stored secret.
 */
export function EnrichmentSection({
  config,
  hasStoredKey,
}: EnrichmentSectionProps) {
  const [baseline, setBaseline] = useState(() =>
    pickEnrichment(draftFromConfig(config)),
  );
  const [draft, setDraft] = useState(baseline);
  const [storedKeyPresent, setStoredKeyPresent] = useState(hasStoredKey);
  const mutation = usePutConfigMutation();

  const isDirty = isSectionDirty(draft, baseline);
  const fieldErrors = fieldErrorsFrom(mutation.error);
  const enabledError = fieldErrors["enrichment.aerodatabox_enabled"] ?? null;

  const hasUsableKey =
    storedKeyPresent || draft.aerodataboxKeyInput.trim().length > 0;

  function handleKeyChange(value: string) {
    const patch: Partial<typeof draft> = {
      aerodataboxKeyInput: value,
      aerodataboxKeyTouched: true,
    };
    if (value.trim().length > 0) {
      patch.aerodataboxEnabled = true;
    } else if (!storedKeyPresent) {
      patch.aerodataboxEnabled = false;
    }
    setDraft({ ...draft, ...patch });
  }

  function handleClearStoredKey() {
    setDraft({
      ...draft,
      aerodataboxKeyInput: "",
      aerodataboxKeyTouched: true,
      aerodataboxEnabled: false,
    });
  }

  function handleSave() {
    mutation.mutate(buildEnrichmentPatch(draft), {
      onSuccess: (response) => {
        const next = pickEnrichment(draftFromConfig(response.config));
        setBaseline(next);
        setDraft(next);
        setStoredKeyPresent(
          response.secrets_set["enrichment.aerodatabox_api_key"] ?? false,
        );
      },
    });
  }

  return (
    <SettingsSection
      id="settings-enrichment"
      title="Enrichment"
      description="Optional AeroDataBox route enrichment (origin/destination lookups)."
    >
      <div className="flex max-w-lg flex-col gap-3 rounded-lg border border-border bg-background p-3">
        <div className="flex gap-3">
          <KeyRound
            className="mt-0.5 size-5 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <div className="space-y-1">
            <p className="text-sm font-medium">AeroDataBox API key</p>
            <p className="text-xs text-muted-foreground">
              Never displayed once saved — only whether one is stored.
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="settings-aerodatabox-key">API key</Label>
          <Input
            id="settings-aerodatabox-key"
            type="password"
            autoComplete="off"
            value={draft.aerodataboxKeyInput}
            placeholder={
              storedKeyPresent
                ? "•••••••• (configured — leave blank to keep)"
                : "Not configured"
            }
            onChange={(event) => {
              handleKeyChange(event.target.value);
            }}
          />
          {storedKeyPresent && !draft.aerodataboxKeyTouched && (
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground">
                A key is currently stored.
              </p>
              <button
                type="button"
                onClick={handleClearStoredKey}
                className="text-xs font-medium text-destructive hover:underline"
              >
                Clear stored key
              </button>
            </div>
          )}
          {!storedKeyPresent && !draft.aerodataboxKeyTouched && (
            <p className="text-xs text-muted-foreground">Not configured.</p>
          )}
        </div>

        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={draft.aerodataboxEnabled}
            disabled={!hasUsableKey}
            onChange={(event) => {
              setDraft({ ...draft, aerodataboxEnabled: event.target.checked });
            }}
          />
          <span className="flex flex-col gap-0.5">
            <span className="text-sm">Enable route enrichment</span>
            <span className="text-xs text-muted-foreground">
              Requires a key above
              {hasUsableKey ? "" : " — enter one to enable this"}.
            </span>
          </span>
        </label>
        {enabledError && (
          <p role="alert" className="text-xs text-destructive">
            {enabledError}
          </p>
        )}
      </div>

      <SectionSaveBar
        isDirty={isDirty}
        isPending={mutation.isPending}
        justSaved={mutation.isSuccess && !isDirty}
        errorMessage={generalErrorMessage(mutation.error, fieldErrors)}
        hasBlockingError={false}
        onSave={handleSave}
      />
    </SettingsSection>
  );
}
