import { useMemo, useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { getDefaultBasemap } from "@/features/map/basemaps";
import { MapLibreMap } from "@/features/map/MapLibreMap";
import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
import type { MapConfig } from "@/features/map/types";
import { FieldError } from "@/features/setup/components/FieldError";
import {
  validateAntennaHeight,
  validateLatitude,
  validateLongitude,
} from "@/features/setup/lib/validation";
import type { WizardDraft } from "@/features/setup/types";

export interface LocationStepProps {
  draft: WizardDraft;
  onChange: (patch: Partial<WizardDraft>) => void;
}

/** Center the picker map somewhere sensible before any coordinates are
 * entered — the same placeholder position the Live Map itself falls back
 * to before a location is configured. */
const FALLBACK_CENTER = DEV_PLACEHOLDER_MAP_CONFIG.receiver;

/**
 * Step (b): receiver location, both as manual lat/lon inputs and as a
 * click-to-place marker on the existing `MapLibreMap` (SPEC §13 — this
 * anchors every bearing/distance/range-ring computation in the app). The
 * map's own degraded-mode handling means this step keeps working — the
 * client-drawn marker still updates — even if basemap tiles fail to load.
 */
export function LocationStep({ draft, onChange }: LocationStepProps) {
  // R4-21: a genuine first run has no stored coordinates, so the raw
  // validators fire on the very first render — "Enter a latitude between
  // -90 and 90." before the user has typed a character. The rule builder
  // already argues the fix for this shape of problem: "a form that argues
  // while it is being filled in is worse than one that answers when
  // asked" (`RuleBuilderForm.tsx`). `touched` gates *display* only — the
  // raw validators below still drive `mapConfig` and `isStepValid`
  // (Next stays disabled until the values are actually valid), so nothing
  // about validity itself changes, only when the message appears.
  const [latitudeTouched, setLatitudeTouched] = useState(false);
  const [longitudeTouched, setLongitudeTouched] = useState(false);
  const [antennaTouched, setAntennaTouched] = useState(false);

  const rawLatitudeError = validateLatitude(draft.latitude);
  const rawLongitudeError = validateLongitude(draft.longitude);
  const rawAntennaError = validateAntennaHeight(draft.antennaHeightFt);

  const latitudeError = latitudeTouched ? rawLatitudeError : null;
  const longitudeError = longitudeTouched ? rawLongitudeError : null;
  const antennaError = antennaTouched ? rawAntennaError : null;

  const basemap = getDefaultBasemap();

  const mapConfig: MapConfig = useMemo(() => {
    // Actual validity, not gated by `touched` — the map should center on a
    // just-typed valid coordinate immediately, and fall back to the
    // placeholder for an invalid one, whether or not the field has been
    // blurred yet.
    const lat =
      rawLatitudeError === null ? Number(draft.latitude) : FALLBACK_CENTER.lat;
    const lon =
      rawLongitudeError === null
        ? Number(draft.longitude)
        : FALLBACK_CENTER.lon;
    return {
      receiver: {
        lat,
        lon,
        label:
          draft.siteName.trim().length > 0
            ? draft.siteName
            : "Selected location",
      },
      // Only once the entered coordinates are valid is there a point to
      // mark; before that `lat`/`lon` are just the camera's fallback
      // centre, and a marker on them would be claiming the user had picked
      // a location they have not picked (issue R1-05).
      receiverConfigured: latitudeError === null && longitudeError === null,
      // No range rings here — this map is purely for picking a point, and
      // rings would just be visual noise before a display radius exists.
      ringRadiiNm: [],
      unit: "nm",
      displayRadiusNm: DEV_PLACEHOLDER_MAP_CONFIG.displayRadiusNm,
    };
  }, [
    draft.latitude,
    draft.longitude,
    draft.siteName,
    rawLatitudeError,
    rawLongitudeError,
  ]);

  function handleMapClick({ lat, lon }: { lat: number; lon: number }) {
    onChange({ latitude: lat.toFixed(5), longitude: lon.toFixed(5) });
  }

  return (
    <div className="flex flex-col gap-6 lg:flex-row">
      <div className="flex w-full flex-col gap-4 lg:max-w-sm">
        <div className="space-y-2">
          <h2 className="text-xl font-semibold tracking-tight">
            Receiver location
          </h2>
          <p className="text-sm text-muted-foreground">
            Anchors every bearing, distance, and range ring in FlightSite. Click
            the map to place a marker, or type coordinates directly.
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="setup-latitude">Latitude</Label>
          <Input
            id="setup-latitude"
            inputMode="decimal"
            value={draft.latitude}
            placeholder="47.60000"
            aria-invalid={latitudeError !== null}
            aria-describedby={
              latitudeError ? "setup-latitude-error" : undefined
            }
            onChange={(event) => {
              onChange({ latitude: event.target.value });
            }}
            onBlur={() => {
              setLatitudeTouched(true);
            }}
          />
          <FieldError id="setup-latitude-error" message={latitudeError} />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="setup-longitude">Longitude</Label>
          <Input
            id="setup-longitude"
            inputMode="decimal"
            value={draft.longitude}
            placeholder="-122.30000"
            aria-invalid={longitudeError !== null}
            aria-describedby={
              longitudeError ? "setup-longitude-error" : undefined
            }
            onChange={(event) => {
              onChange({ longitude: event.target.value });
            }}
            onBlur={() => {
              setLongitudeTouched(true);
            }}
          />
          <FieldError id="setup-longitude-error" message={longitudeError} />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="setup-antenna-height">
            Antenna height (ft, optional)
          </Label>
          <Input
            id="setup-antenna-height"
            inputMode="decimal"
            value={draft.antennaHeightFt}
            placeholder="e.g. 30"
            aria-invalid={antennaError !== null}
            aria-describedby={
              antennaError ? "setup-antenna-height-error" : undefined
            }
            onChange={(event) => {
              onChange({ antennaHeightFt: event.target.value });
            }}
            onBlur={() => {
              setAntennaTouched(true);
            }}
          />
          <FieldError id="setup-antenna-height-error" message={antennaError} />
        </div>
      </div>

      <div className="h-[320px] flex-1 overflow-hidden rounded-lg border border-border lg:h-auto">
        <MapLibreMap
          config={mapConfig}
          basemap={basemap}
          className="h-full w-full"
          onMapClick={handleMapClick}
        />
      </div>
    </div>
  );
}
