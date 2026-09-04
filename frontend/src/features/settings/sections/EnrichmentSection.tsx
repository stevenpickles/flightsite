import { KeyRound } from "lucide-react";
import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";
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
import {
  ROUTE_TTL_MAX_DAYS,
  ROUTE_TTL_MIN_DAYS,
  validateDailyLookupBudget,
  validateRouteTtlDays,
} from "@/features/settings/lib/validation";
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
 * Online route enrichment (SPEC §28): the AeroDataBox API key, masked,
 * whether enrichment is enabled, and the two dials that decide what it
 * costs — the daily lookup budget and how long a cached route is reused
 * (slice 070).
 *
 * Deliberately carries no "Applies on next restart" badge: the backend
 * rebuilds the enrichment provider on save, so a key, a toggle, a budget or
 * a cache lifetime takes effect on the next lookup. It is the only section on this page that
 * changes a startup-built service without a restart, which is why the
 * absence of a badge here is a claim worth testing rather than an oversight.
 *
 * The key input is always empty on load — only `hasStoredKey` says whether
 * one exists — and an explicit "Clear stored key" is the only way to remove
 * one, so a left-blank-and-saved field never silently wipes a stored secret.
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

  // Client-side bounds are what block a save; a server-side message for the
  // same field is still shown, but never disables the button — a rejection
  // the user cannot see the cause of would otherwise leave the section
  // unsavable until an unrelated edit.
  const budgetBoundsError = validateDailyLookupBudget(draft.dailyLookupBudget);
  const ttlBoundsError = validateRouteTtlDays(draft.routeTtlDays);
  const budgetError =
    budgetBoundsError ?? fieldErrors["enrichment.daily_lookup_budget"] ?? null;
  const ttlError =
    ttlBoundsError ?? fieldErrors["enrichment.route_ttl_days"] ?? null;

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

      {/* The lookup economy (slice 070). Both fields apply on save for the
       * same reason the key does — the provider is rebuilt, not restarted —
       * so neither carries a restart caveat. */}
      <div className="flex max-w-lg flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="settings-enrichment-budget">
            Daily lookup budget
          </Label>
          <Input
            id="settings-enrichment-budget"
            inputMode="numeric"
            value={draft.dailyLookupBudget}
            aria-invalid={budgetError !== null}
            aria-describedby={
              budgetError !== null
                ? "settings-enrichment-budget-error"
                : "settings-enrichment-budget-help"
            }
            onChange={(event) => {
              setDraft({ ...draft, dailyLookupBudget: event.target.value });
            }}
          />
          <p
            id="settings-enrichment-budget-help"
            className="text-xs text-muted-foreground"
          >
            A lookup is one call to the provider for a flight whose route is not
            already cached. The count resets at midnight UTC. Use 0 for
            unlimited.
          </p>
          <FieldError
            id="settings-enrichment-budget-error"
            message={budgetError}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="settings-enrichment-ttl">
            Route cache lifetime (days)
          </Label>
          <Input
            id="settings-enrichment-ttl"
            inputMode="numeric"
            value={draft.routeTtlDays}
            aria-invalid={ttlError !== null}
            aria-describedby={
              ttlError !== null
                ? "settings-enrichment-ttl-error"
                : "settings-enrichment-ttl-help"
            }
            onChange={(event) => {
              setDraft({ ...draft, routeTtlDays: event.target.value });
            }}
          />
          <p
            id="settings-enrichment-ttl-help"
            className="text-xs text-muted-foreground"
          >
            How long a cached route is reused before it is looked up again (
            {ROUTE_TTL_MIN_DAYS}–{ROUTE_TTL_MAX_DAYS} days). Longer spends less
            budget; shorter picks up schedule changes sooner.
          </p>
          <FieldError id="settings-enrichment-ttl-error" message={ttlError} />
        </div>
      </div>

      <SectionSaveBar
        isDirty={isDirty}
        isPending={mutation.isPending}
        justSaved={mutation.isSuccess && !isDirty}
        errorMessage={generalErrorMessage(mutation.error, fieldErrors)}
        hasBlockingError={budgetBoundsError !== null || ttlBoundsError !== null}
        onSave={handleSave}
      />
    </SettingsSection>
  );
}
