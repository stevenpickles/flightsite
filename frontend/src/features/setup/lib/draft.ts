/**
 * Converts between the wizard's `WizardDraft` (all-string, form-friendly)
 * and the API's `ConfigResponse` / `ConfigPatch` shapes. Keeping both
 * directions here — not spread across the step components — is what makes
 * "prefill from current config in edit mode" and "submit the full
 * document on finish" the same code path regardless of which step a field
 * lives on.
 */
import { DEFAULT_ENABLED_TEMPLATE_IDS } from "@/features/setup/constants";
import { parseNumber } from "@/features/setup/lib/validation";
import { detectBrowserTimezone } from "@/features/setup/lib/timezones";
import type { WizardDraft } from "@/features/setup/types";
import type { ConfigPatch, ConfigResponse } from "@/lib/api/config";

/** Builds the initial wizard draft from the currently-effective config.
 * Used both for a fresh install (server defaults) and for re-running the
 * wizard from Settings against an already-configured install (edit mode)
 * — the same conversion serves both, since a fresh install's config is
 * just the schema defaults. */
export function draftFromConfig(response: ConfigResponse): WizardDraft {
  const { config } = response;
  const { location, receiver } = config;

  // Only reach for the browser's timezone when the server is still at the
  // schema default ("UTC") — an explicitly-configured "UTC" (a real
  // choice, e.g. a receiver run in UTC on purpose) is left alone.
  const timezone =
    config.timezone === "UTC" ? detectBrowserTimezone() : config.timezone;

  return {
    siteName: location.site_name ?? "",
    latitude: location.latitude !== null ? String(location.latitude) : "",
    longitude: location.longitude !== null ? String(location.longitude) : "",
    antennaHeightFt:
      location.antenna_height_ft !== null
        ? String(location.antenna_height_ft)
        : "",

    receiverHost: receiver.host,
    receiverPort: String(receiver.port),
    receiverPath: receiver.path,
    pollIntervalS: String(receiver.poll_interval_s),

    units: config.units,
    timezone,

    notifications: { ...config.notifications },

    aerodataboxKeyInput: "",
    aerodataboxKeyTouched: false,
    aerodataboxEnabled: config.enrichment.aerodatabox_enabled,

    enabledTemplateIds:
      config.alerts.enabled_templates.length > 0
        ? [...config.alerts.enabled_templates]
        : [...DEFAULT_ENABLED_TEMPLATE_IDS],
  };
}

/** Assembles the single `PUT /api/internal/config` patch the review step
 * submits. Every section the wizard manages is included — the sections it
 * does not manage (sighting timing, retention, map basemap, log level,
 * display/alert radius) are omitted so `apply_update` leaves them exactly
 * as they were. */
export function buildConfigPatch(draft: WizardDraft): ConfigPatch {
  const patch: ConfigPatch = {
    units: draft.units,
    timezone: draft.timezone,
    location: {
      site_name: draft.siteName.trim(),
      latitude: parseNumber(draft.latitude),
      longitude: parseNumber(draft.longitude),
      antenna_height_ft:
        draft.antennaHeightFt.trim().length > 0
          ? parseNumber(draft.antennaHeightFt)
          : null,
    },
    receiver: {
      host: draft.receiverHost.trim(),
      port: Math.trunc(parseNumber(draft.receiverPort) ?? 0),
      path: draft.receiverPath.trim(),
      poll_interval_s: parseNumber(draft.pollIntervalS) ?? 1,
    },
    notifications: { ...draft.notifications },
    alerts: { enabled_templates: draft.enabledTemplateIds },
    enrichment: { aerodatabox_enabled: draft.aerodataboxEnabled },
  };

  // Only include the secret when the user actually edited it this session
  // (see `WizardDraft.aerodataboxKeyTouched`) — an untouched field must
  // never overwrite a previously-stored key with an empty value.
  if (draft.aerodataboxKeyTouched) {
    const trimmed = draft.aerodataboxKeyInput.trim();
    patch.enrichment = {
      ...patch.enrichment,
      aerodatabox_api_key: trimmed.length > 0 ? trimmed : null,
    };
  }

  return patch;
}
