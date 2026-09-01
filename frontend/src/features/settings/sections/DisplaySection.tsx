import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { BASEMAPS } from "@/features/map/basemaps";
import { FieldError } from "@/features/setup/components/FieldError";
import { SectionSaveBar } from "@/features/settings/components/SectionSaveBar";
import { SettingsSection } from "@/features/settings/components/SettingsSection";
import {
  buildDisplayPatch,
  draftFromConfig,
  isSectionDirty,
  pickDisplay,
} from "@/features/settings/lib/draft";
import {
  validateDisplayRadius,
  validateRangeRingRadii,
} from "@/features/settings/lib/validation";
import {
  fieldErrorsFrom,
  generalErrorMessage,
} from "@/features/settings/lib/errors";
import { usePutConfigMutation } from "@/lib/api/config";
import type { FlightSiteConfig } from "@/lib/api/config";

export interface DisplaySectionProps {
  config: FlightSiteConfig;
}

/** How far the Live Map shows traffic, the default basemap, and range-ring
 * display (SPEC §32/§33). Applies immediately — no restart required. */
export function DisplaySection({ config }: DisplaySectionProps) {
  const [baseline, setBaseline] = useState(() =>
    pickDisplay(draftFromConfig(config)),
  );
  const [draft, setDraft] = useState(baseline);
  const mutation = usePutConfigMutation();

  const isDirty = isSectionDirty(draft, baseline);
  const fieldErrors = fieldErrorsFrom(mutation.error);

  const displayRadiusError =
    validateDisplayRadius(draft.displayRadiusNm) ??
    fieldErrors.display_radius_nm ??
    null;
  const radiiError =
    validateRangeRingRadii(draft.rangeRingRadiiNm) ??
    fieldErrors["map.range_ring_radii_nm"] ??
    null;
  const hasBlockingError = Boolean(displayRadiusError ?? radiiError);

  function handleSave() {
    mutation.mutate(buildDisplayPatch(draft), {
      onSuccess: (response) => {
        const next = pickDisplay(draftFromConfig(response.config));
        setBaseline(next);
        setDraft(next);
      },
    });
  }

  return (
    <SettingsSection
      id="settings-display"
      title="Display"
      description="Live Map traffic radius, default basemap, and range rings."
    >
      <div className="flex max-w-lg flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="settings-display-radius">Display radius (nm)</Label>
          <Input
            id="settings-display-radius"
            inputMode="decimal"
            value={draft.displayRadiusNm}
            aria-invalid={displayRadiusError !== null}
            aria-describedby={
              displayRadiusError ? "settings-display-radius-error" : undefined
            }
            onChange={(event) => {
              setDraft({ ...draft, displayRadiusNm: event.target.value });
            }}
          />
          <FieldError
            id="settings-display-radius-error"
            message={displayRadiusError}
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="settings-basemap">Default basemap</Label>
          <select
            id="settings-basemap"
            value={draft.basemap}
            onChange={(event) => {
              setDraft({ ...draft, basemap: event.target.value });
            }}
            className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
          >
            {BASEMAPS.map((basemap) => (
              <option key={basemap.id} value={basemap.id}>
                {basemap.label}
              </option>
            ))}
          </select>
        </div>

        <label className="flex items-start gap-3">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={draft.rangeRingsEnabled}
            onChange={(event) => {
              setDraft({ ...draft, rangeRingsEnabled: event.target.checked });
            }}
          />
          <span className="flex flex-col gap-0.5">
            <span className="text-sm font-medium">Show range rings</span>
            <span className="text-xs text-muted-foreground">
              Concentric distance rings centered on the receiver.
            </span>
          </span>
        </label>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="settings-range-rings">
            Range ring radii (nm, comma-separated)
          </Label>
          <Input
            id="settings-range-rings"
            value={draft.rangeRingRadiiNm}
            disabled={!draft.rangeRingsEnabled}
            aria-invalid={radiiError !== null}
            aria-describedby={
              radiiError ? "settings-range-rings-error" : undefined
            }
            onChange={(event) => {
              setDraft({ ...draft, rangeRingRadiiNm: event.target.value });
            }}
          />
          <FieldError id="settings-range-rings-error" message={radiiError} />
        </div>
      </div>

      <SectionSaveBar
        isDirty={isDirty}
        isPending={mutation.isPending}
        justSaved={mutation.isSuccess && !isDirty}
        errorMessage={generalErrorMessage(mutation.error, fieldErrors)}
        hasBlockingError={hasBlockingError}
        onSave={handleSave}
      />
    </SettingsSection>
  );
}
