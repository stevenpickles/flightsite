import { useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { FieldError } from "@/features/setup/components/FieldError";
import {
  validateAntennaHeight,
  validateLatitude,
  validateLongitude,
  validateSiteName,
} from "@/features/setup/lib/validation";
import { SectionSaveBar } from "@/features/settings/components/SectionSaveBar";
import { SettingsSection } from "@/features/settings/components/SettingsSection";
import {
  buildReceiverPatch,
  draftFromConfig,
  isSectionDirty,
  pickReceiverLocation,
} from "@/features/settings/lib/draft";
import {
  fieldErrorsFrom,
  generalErrorMessage,
} from "@/features/settings/lib/errors";
import type { FlightSiteConfig } from "@/lib/api/config";
import { usePutConfigMutation } from "@/lib/api/config";

export interface ReceiverSectionProps {
  config: FlightSiteConfig;
}

/** Site name, location, and antenna height (SPEC §13) — the same fields the
 * setup wizard's Location step collects, editable afterward here. Restart
 * required: bearing, distance and range rings are measured from the reference
 * point the running live store holds, so moving it here would leave every
 * already-observed aircraft carrying a distance from the old one until it was
 * seen again. (Filling the blank on a fresh install has nothing to disturb,
 * so the wizard's first save applies immediately.) */
export function ReceiverSection({ config }: ReceiverSectionProps) {
  const [baseline, setBaseline] = useState(() =>
    pickReceiverLocation(draftFromConfig(config)),
  );
  const [draft, setDraft] = useState(baseline);
  const mutation = usePutConfigMutation();

  const isDirty = isSectionDirty(draft, baseline);
  const fieldErrors = fieldErrorsFrom(mutation.error);

  const siteNameError =
    validateSiteName(draft.siteName) ??
    fieldErrors["location.site_name"] ??
    null;
  const latitudeError =
    validateLatitude(draft.latitude) ??
    fieldErrors["location.latitude"] ??
    null;
  const longitudeError =
    validateLongitude(draft.longitude) ??
    fieldErrors["location.longitude"] ??
    null;
  const antennaError =
    validateAntennaHeight(draft.antennaHeightFt) ??
    fieldErrors["location.antenna_height_ft"] ??
    null;
  const hasBlockingError = Boolean(
    siteNameError ?? latitudeError ?? longitudeError ?? antennaError,
  );

  function handleSave() {
    mutation.mutate(buildReceiverPatch(draft), {
      onSuccess: (response) => {
        const next = pickReceiverLocation(draftFromConfig(response.config));
        setBaseline(next);
        setDraft(next);
      },
    });
  }

  return (
    <SettingsSection
      id="settings-receiver"
      title="Receiver"
      description="Site name and location — anchors every bearing, distance, and range ring."
      restartRequired
    >
      <div className="grid max-w-lg grid-cols-2 gap-4">
        <div className="col-span-2 flex flex-col gap-1.5">
          <Label htmlFor="settings-site-name">Site name</Label>
          <Input
            id="settings-site-name"
            value={draft.siteName}
            aria-invalid={siteNameError !== null}
            aria-describedby={
              siteNameError ? "settings-site-name-error" : undefined
            }
            onChange={(event) => {
              setDraft({ ...draft, siteName: event.target.value });
            }}
          />
          <FieldError id="settings-site-name-error" message={siteNameError} />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="settings-latitude">Latitude</Label>
          <Input
            id="settings-latitude"
            inputMode="decimal"
            value={draft.latitude}
            aria-invalid={latitudeError !== null}
            aria-describedby={
              latitudeError ? "settings-latitude-error" : undefined
            }
            onChange={(event) => {
              setDraft({ ...draft, latitude: event.target.value });
            }}
          />
          <FieldError id="settings-latitude-error" message={latitudeError} />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="settings-longitude">Longitude</Label>
          <Input
            id="settings-longitude"
            inputMode="decimal"
            value={draft.longitude}
            aria-invalid={longitudeError !== null}
            aria-describedby={
              longitudeError ? "settings-longitude-error" : undefined
            }
            onChange={(event) => {
              setDraft({ ...draft, longitude: event.target.value });
            }}
          />
          <FieldError id="settings-longitude-error" message={longitudeError} />
        </div>

        <div className="col-span-2 flex flex-col gap-1.5">
          <Label htmlFor="settings-antenna-height">
            Antenna height (ft, optional)
          </Label>
          <Input
            id="settings-antenna-height"
            inputMode="decimal"
            value={draft.antennaHeightFt}
            aria-invalid={antennaError !== null}
            aria-describedby={
              antennaError ? "settings-antenna-height-error" : undefined
            }
            onChange={(event) => {
              setDraft({ ...draft, antennaHeightFt: event.target.value });
            }}
          />
          <FieldError
            id="settings-antenna-height-error"
            message={antennaError}
          />
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
