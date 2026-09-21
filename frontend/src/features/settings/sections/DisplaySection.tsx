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
  fieldMessage,
  generalErrorMessage,
} from "@/features/settings/lib/errors";
import { usePutConfigMutation } from "@/lib/api/config";
import type { FlightSiteConfig } from "@/lib/api/config";

export interface DisplaySectionProps {
  config: FlightSiteConfig;
}

const NM_TO_KM = 1.852;

/** A live "≈ metric" readout for a nautical-mile field, shown only when the
 * Units & time section's preference is metric (R4-13). Storage and the API
 * stay nm regardless (`CLAUDE.md`) — this is a hint, not a second input —
 * but a metric-preference user should not have to do the arithmetic
 * themselves every time they read a distance measured in a unit they did
 * not choose. `null` for anything that is not a plain number yet (blank,
 * mid-edit, or already flagged invalid by the field's own validator). */
function metricRadiusHint(rawNm: string): string | null {
  const value = Number(rawNm);
  if (rawNm.trim().length === 0 || !Number.isFinite(value)) {
    return null;
  }
  const km = value * NM_TO_KM;
  return `≈ ${km.toLocaleString(undefined, { maximumFractionDigits: 1 })} km`;
}

/** The same hint for a comma-separated list of nm values (range rings) —
 * one converted list rather than one hint per ring. */
function metricRadiiListHint(rawList: string): string | null {
  const parts = rawList
    .split(",")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
  if (parts.length === 0) {
    return null;
  }
  const values = parts.map(Number);
  if (values.some((value) => !Number.isFinite(value))) {
    return null;
  }
  const km = values.map((value) =>
    (value * NM_TO_KM).toLocaleString(undefined, { maximumFractionDigits: 1 }),
  );
  return `≈ ${km.join(", ")} km`;
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

  // R4-02: `hasBlockingError` is derived from the client-side validators
  // only — a server rejection is shown but never disables Save, or a 422
  // here would leave the section unsavable until an unrelated edit or a
  // page reload (`docs/reviews/2026-09-20-site-review.md`).
  const displayRadius = fieldMessage(
    validateDisplayRadius(draft.displayRadiusNm),
    fieldErrors.display_radius_nm,
  );
  const radii = fieldMessage(
    validateRangeRingRadii(draft.rangeRingRadiiNm),
    fieldErrors["map.range_ring_radii_nm"],
  );
  const displayRadiusError = displayRadius.message;
  const radiiError = radii.message;
  const hasBlockingError = displayRadius.blocking || radii.blocking;
  const showMetricHints = config.units === "metric";

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
          {showMetricHints && metricRadiusHint(draft.displayRadiusNm) && (
            <p className="text-xs text-muted-foreground">
              {metricRadiusHint(draft.displayRadiusNm)}
            </p>
          )}
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
          {showMetricHints && metricRadiiListHint(draft.rangeRingRadiiNm) && (
            <p className="text-xs text-muted-foreground">
              {metricRadiiListHint(draft.rangeRingRadiiNm)}
            </p>
          )}
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
