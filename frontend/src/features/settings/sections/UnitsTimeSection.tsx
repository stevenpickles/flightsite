import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  detectBrowserTimezone,
  listTimezones,
} from "@/features/setup/lib/timezones";
import { SectionSaveBar } from "@/features/settings/components/SectionSaveBar";
import { SettingsSection } from "@/features/settings/components/SettingsSection";
import {
  buildUnitsAndTimePatch,
  draftFromConfig,
  isSectionDirty,
  pickUnitsAndTime,
} from "@/features/settings/lib/draft";
import { validateTimezone } from "@/features/settings/lib/validation";
import {
  fieldErrorsFrom,
  generalErrorMessage,
} from "@/features/settings/lib/errors";
import { usePutConfigMutation } from "@/lib/api/config";
import type { FlightSiteConfig, UnitSystem } from "@/lib/api/config";
import { cn } from "@/lib/utils";

export interface UnitsTimeSectionProps {
  config: FlightSiteConfig;
}

const UNIT_OPTIONS: readonly { value: UnitSystem; label: string }[] = [
  { value: "aviation", label: "Aviation (nm / ft / kt)" },
  { value: "metric", label: "Metric (km / m / km/h)" },
];

/** Display units and IANA timezone. A display preference only — storage
 * stays UTC / nm / ft / kt regardless, and this applies immediately
 * (no restart required). */
export function UnitsTimeSection({ config }: UnitsTimeSectionProps) {
  const [baseline, setBaseline] = useState(() =>
    pickUnitsAndTime(draftFromConfig(config)),
  );
  const [draft, setDraft] = useState(baseline);
  const mutation = usePutConfigMutation();
  const timezones = useMemo(() => listTimezones(), []);

  const isDirty = isSectionDirty(draft, baseline);
  const fieldErrors = fieldErrorsFrom(mutation.error);
  const timezoneError =
    validateTimezone(draft.timezone) ?? fieldErrors.timezone ?? null;

  function handleSave() {
    mutation.mutate(buildUnitsAndTimePatch(draft), {
      onSuccess: (response) => {
        const next = pickUnitsAndTime(draftFromConfig(response.config));
        setBaseline(next);
        setDraft(next);
      },
    });
  }

  return (
    <SettingsSection
      id="settings-units-time"
      title="Units & time"
      description="Display units and the timezone used to present times; storage stays UTC."
    >
      <div className="flex max-w-lg flex-col gap-6">
        <div
          role="radiogroup"
          aria-label="Units"
          className="flex flex-col gap-2"
        >
          {UNIT_OPTIONS.map((option) => {
            const selected = draft.units === option.value;
            return (
              <label
                key={option.value}
                className={cn(
                  "flex cursor-pointer items-center gap-2 rounded-lg border p-2.5 text-sm transition-colors",
                  selected
                    ? "border-accent bg-accent/10"
                    : "border-border hover:bg-secondary",
                )}
              >
                <input
                  type="radio"
                  name="settings-units"
                  value={option.value}
                  checked={selected}
                  onChange={() => {
                    setDraft({ ...draft, units: option.value });
                  }}
                />
                {option.label}
              </label>
            );
          })}
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <Label htmlFor="settings-timezone">Timezone</Label>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setDraft({ ...draft, timezone: detectBrowserTimezone() });
              }}
            >
              Detect from browser
            </Button>
          </div>
          <select
            id="settings-timezone"
            value={draft.timezone}
            aria-invalid={timezoneError !== null}
            aria-describedby={
              timezoneError ? "settings-timezone-error" : undefined
            }
            onChange={(event) => {
              setDraft({ ...draft, timezone: event.target.value });
            }}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            {!timezones.includes(draft.timezone) &&
              draft.timezone.length > 0 && (
                <option value={draft.timezone}>{draft.timezone}</option>
              )}
            {timezones.map((zone) => (
              <option key={zone} value={zone}>
                {zone}
              </option>
            ))}
          </select>
          {timezoneError && (
            <p
              id="settings-timezone-error"
              role="alert"
              className="text-xs text-destructive"
            >
              {timezoneError}
            </p>
          )}
        </div>
      </div>

      <SectionSaveBar
        isDirty={isDirty}
        isPending={mutation.isPending}
        justSaved={mutation.isSuccess && !isDirty}
        errorMessage={generalErrorMessage(mutation.error, fieldErrors)}
        hasBlockingError={timezoneError !== null}
        onSave={handleSave}
      />
    </SettingsSection>
  );
}
