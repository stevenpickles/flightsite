import { useMemo } from "react";

import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  detectBrowserTimezone,
  listTimezones,
} from "@/features/setup/lib/timezones";
import type { WizardDraft } from "@/features/setup/types";
import { cn } from "@/lib/utils";
import type { UnitSystem } from "@/lib/api/config";

export interface UnitsTimezoneStepProps {
  draft: WizardDraft;
  onChange: (patch: Partial<WizardDraft>) => void;
}

const UNIT_OPTIONS: readonly {
  value: UnitSystem;
  label: string;
  description: string;
}[] = [
  {
    value: "aviation",
    label: "Aviation (default)",
    description:
      "Nautical miles, feet, and knots — the canonical units FlightSite stores internally.",
  },
  {
    value: "metric",
    label: "Metric",
    description:
      "Kilometers, meters, and km/h for display only; storage stays nm/ft/kt either way.",
  },
];

/** Step (d): display units and timezone. */
export function UnitsTimezoneStep({ draft, onChange }: UnitsTimezoneStepProps) {
  const timezones = useMemo(() => listTimezones(), []);

  return (
    <div className="flex max-w-lg flex-col gap-8">
      <div className="flex flex-col gap-3">
        <div className="space-y-2">
          <h2 className="text-xl font-semibold tracking-tight">Units</h2>
          <p className="text-sm text-muted-foreground">
            A display preference only — timestamps and canonical values are
            always stored UTC / nm / ft / kt.
          </p>
        </div>
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
                  "flex cursor-pointer flex-col gap-0.5 rounded-lg border p-3 transition-colors",
                  selected
                    ? "border-accent bg-accent/10"
                    : "border-border hover:bg-secondary",
                )}
              >
                <span className="flex items-center gap-2 text-sm font-medium">
                  <input
                    type="radio"
                    name="setup-units"
                    value={option.value}
                    checked={selected}
                    onChange={() => {
                      onChange({ units: option.value });
                    }}
                  />
                  {option.label}
                </span>
                <span className="text-xs text-muted-foreground">
                  {option.description}
                </span>
              </label>
            );
          })}
        </div>
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between">
          <Label htmlFor="setup-timezone">Timezone</Label>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => {
              onChange({ timezone: detectBrowserTimezone() });
            }}
          >
            Detect from browser
          </Button>
        </div>
        <select
          id="setup-timezone"
          value={draft.timezone}
          onChange={(event) => {
            onChange({ timezone: event.target.value });
          }}
          className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
        >
          {!timezones.includes(draft.timezone) && draft.timezone.length > 0 && (
            <option value={draft.timezone}>{draft.timezone}</option>
          )}
          {timezones.map((zone) => (
            <option key={zone} value={zone}>
              {zone}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">
          Used to present times in your local zone; storage stays UTC.
        </p>
      </div>
    </div>
  );
}
