import { Database, KeyRound } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { WizardDraft } from "@/features/setup/types";

export interface MetadataStepProps {
  draft: WizardDraft;
  /** Whether an AeroDataBox key is already stored server-side
   * (`secrets_set["enrichment.aerodatabox_api_key"]`) — the real value is
   * never sent to the frontend (SPEC §29), so this is all there is to show. */
  hasStoredKey: boolean;
  onChange: (patch: Partial<WizardDraft>) => void;
}

/**
 * Step (f): an informational pointer to the (separate, Settings-driven)
 * aircraft metadata download, plus the optional AeroDataBox API key. Both
 * are entirely optional, so this step is always valid.
 */
export function MetadataStep({
  draft,
  hasStoredKey,
  onChange,
}: MetadataStepProps) {
  const hasUsableKey =
    hasStoredKey || draft.aerodataboxKeyInput.trim().length > 0;

  function handleKeyChange(value: string) {
    const patch: Partial<WizardDraft> = {
      aerodataboxKeyInput: value,
      aerodataboxKeyTouched: true,
    };
    // A newly-typed key implies wanting enrichment on; clearing the field
    // with no stored key left behind implies wanting it off. Either way
    // this only sets a sensible default — the checkbox below still lets
    // the user override it.
    if (value.trim().length > 0) {
      patch.aerodataboxEnabled = true;
    } else if (!hasStoredKey) {
      patch.aerodataboxEnabled = false;
    }
    onChange(patch);
  }

  function handleClearStoredKey() {
    onChange({
      aerodataboxKeyInput: "",
      aerodataboxKeyTouched: true,
      aerodataboxEnabled: false,
    });
  }

  return (
    <div className="flex max-w-lg flex-col gap-6">
      <div className="space-y-2">
        <h2 className="text-xl font-semibold tracking-tight">
          Metadata & enrichment
        </h2>
        <p className="text-sm text-muted-foreground">
          Both of these are entirely optional.
        </p>
      </div>

      <div className="flex gap-3 rounded-lg border border-border bg-card p-4">
        <Database
          className="mt-0.5 size-5 shrink-0 text-muted-foreground"
          aria-hidden="true"
        />
        <div className="space-y-1">
          <p className="text-sm font-medium">Aircraft metadata</p>
          <p className="text-xs text-muted-foreground">
            Offline registration/type metadata (Mictronics/tar1090, optional
            FAA) is downloaded from Settings after setup finishes — nothing to
            do here.
          </p>
        </div>
      </div>

      <div className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
        <div className="flex gap-3">
          <KeyRound
            className="mt-0.5 size-5 shrink-0 text-muted-foreground"
            aria-hidden="true"
          />
          <div className="space-y-1">
            <p className="text-sm font-medium">AeroDataBox API key</p>
            <p className="text-xs text-muted-foreground">
              Enables optional online route enrichment (origin/destination
              lookups). Leave blank to skip — this can be added later in
              Settings.
            </p>
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="setup-aerodatabox-key">API key</Label>
          <Input
            id="setup-aerodatabox-key"
            type="password"
            autoComplete="off"
            value={draft.aerodataboxKeyInput}
            placeholder={
              hasStoredKey
                ? "•••••••• (stored — leave blank to keep)"
                : "Optional"
            }
            onChange={(event) => {
              handleKeyChange(event.target.value);
            }}
          />
          {hasStoredKey && !draft.aerodataboxKeyTouched && (
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
        </div>

        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={draft.aerodataboxEnabled}
            disabled={!hasUsableKey}
            onChange={(event) => {
              onChange({ aerodataboxEnabled: event.target.checked });
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
      </div>
    </div>
  );
}
