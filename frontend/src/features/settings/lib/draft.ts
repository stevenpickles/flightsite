/**
 * Converts between the Settings page's `SettingsDraft` (all-string,
 * form-friendly) and the API's `FlightSiteConfig` / `ConfigPatch` shapes.
 * Mirrors `@/features/setup/lib/draft` in spirit, but split per section
 * rather than assembled into one document: each section on the Settings
 * page saves independently (see roadmap slice 019), so each gets its own
 * "current value" reader and its own patch builder, all sourced from one
 * `SettingsDraft` shape for consistency.
 */
import { parseNumber } from "@/features/setup/lib/validation";
import { parseRangeRingRadii } from "@/features/settings/lib/validation";
import type { SettingsDraft } from "@/features/settings/types";
import type { ConfigPatch, FlightSiteConfig } from "@/lib/api/config";

/** Builds the initial (and post-save) draft from the effective config.
 * Every section reads its slice of this via the `pick*` helpers below, so
 * a fresh load and a post-save resync are the same code path. */
export function draftFromConfig(config: FlightSiteConfig): SettingsDraft {
  const { location, receiver, map } = config;
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
    timezone: config.timezone,

    displayRadiusNm: String(config.display_radius_nm),
    basemap: map.basemap,
    rangeRingsEnabled: map.range_rings_enabled,
    rangeRingRadiiNm: map.range_ring_radii_nm.join(", "),

    alertRadiusNm:
      config.alert_radius_nm !== null ? String(config.alert_radius_nm) : "",
    enabledTemplateIds: [...config.alerts.enabled_templates],

    notifications: { ...config.notifications },

    aerodataboxEnabled: config.enrichment.aerodatabox_enabled,
    aerodataboxKeyInput: "",
    aerodataboxKeyTouched: false,
    dailyLookupBudget: String(config.enrichment.daily_lookup_budget),
    routeTtlDays: String(config.enrichment.route_ttl_days),

    openskyEnabled: config.metadata.opensky_enabled,

    highResMetricDays: String(config.retention.high_res_metric_days),
  };
}

/** The receiver-location fields, as a `SettingsDraft`-shaped slice — used
 * both to seed a section's local state and to detect whether it has
 * unsaved edits. */
export function pickReceiverLocation(draft: SettingsDraft) {
  return {
    siteName: draft.siteName,
    latitude: draft.latitude,
    longitude: draft.longitude,
    antennaHeightFt: draft.antennaHeightFt,
  };
}

export function pickDecoder(draft: SettingsDraft) {
  return {
    receiverHost: draft.receiverHost,
    receiverPort: draft.receiverPort,
    receiverPath: draft.receiverPath,
    pollIntervalS: draft.pollIntervalS,
  };
}

export function pickUnitsAndTime(draft: SettingsDraft) {
  return { units: draft.units, timezone: draft.timezone };
}

export function pickDisplay(draft: SettingsDraft) {
  return {
    displayRadiusNm: draft.displayRadiusNm,
    basemap: draft.basemap,
    rangeRingsEnabled: draft.rangeRingsEnabled,
    rangeRingRadiiNm: draft.rangeRingRadiiNm,
  };
}

export function pickAlerts(draft: SettingsDraft) {
  return {
    alertRadiusNm: draft.alertRadiusNm,
    enabledTemplateIds: draft.enabledTemplateIds,
  };
}

export function pickNotifications(draft: SettingsDraft) {
  return { notifications: draft.notifications };
}

export function pickEnrichment(draft: SettingsDraft) {
  return {
    aerodataboxEnabled: draft.aerodataboxEnabled,
    aerodataboxKeyInput: draft.aerodataboxKeyInput,
    aerodataboxKeyTouched: draft.aerodataboxKeyTouched,
    dailyLookupBudget: draft.dailyLookupBudget,
    routeTtlDays: draft.routeTtlDays,
  };
}

export function pickMetadata(draft: SettingsDraft) {
  return { openskyEnabled: draft.openskyEnabled };
}

export function pickRetention(draft: SettingsDraft) {
  return { highResMetricDays: draft.highResMetricDays };
}

/** Whether two picked slices differ — plain structural equality via JSON,
 * which is exact for the string/boolean/string-array shapes every `pick*`
 * helper above returns. */
export function isSectionDirty<T>(current: T, baseline: T): boolean {
  return JSON.stringify(current) !== JSON.stringify(baseline);
}

export function buildReceiverPatch(
  draft: ReturnType<typeof pickReceiverLocation>,
): ConfigPatch {
  return {
    location: {
      site_name: draft.siteName.trim(),
      latitude: parseNumber(draft.latitude),
      longitude: parseNumber(draft.longitude),
      antenna_height_ft:
        draft.antennaHeightFt.trim().length > 0
          ? parseNumber(draft.antennaHeightFt)
          : null,
    },
  };
}

export function buildDecoderPatch(
  draft: ReturnType<typeof pickDecoder>,
): ConfigPatch {
  return {
    receiver: {
      host: draft.receiverHost.trim(),
      port: Math.trunc(parseNumber(draft.receiverPort) ?? 0),
      path: draft.receiverPath.trim(),
      poll_interval_s: parseNumber(draft.pollIntervalS) ?? 1,
    },
  };
}

export function buildUnitsAndTimePatch(
  draft: ReturnType<typeof pickUnitsAndTime>,
): ConfigPatch {
  return { units: draft.units, timezone: draft.timezone };
}

export function buildDisplayPatch(
  draft: ReturnType<typeof pickDisplay>,
): ConfigPatch {
  return {
    display_radius_nm: parseNumber(draft.displayRadiusNm) ?? 0,
    map: {
      basemap: draft.basemap,
      range_rings_enabled: draft.rangeRingsEnabled,
      range_ring_radii_nm: parseRangeRingRadii(draft.rangeRingRadiiNm),
    },
  };
}

export function buildAlertsPatch(
  draft: ReturnType<typeof pickAlerts>,
): ConfigPatch {
  return {
    alert_radius_nm:
      draft.alertRadiusNm.trim().length > 0
        ? parseNumber(draft.alertRadiusNm)
        : null,
    alerts: { enabled_templates: draft.enabledTemplateIds },
  };
}

export function buildNotificationsPatch(
  draft: ReturnType<typeof pickNotifications>,
): ConfigPatch {
  return { notifications: { ...draft.notifications } };
}

/** Only includes `aerodatabox_api_key` when the user actually edited the
 * field this session (see `SettingsDraft.aerodataboxKeyTouched`) — an
 * untouched field must never overwrite a previously-stored key. An
 * explicit clear sends `null`, which the backend treats as "remove the
 * stored secret" rather than "leave unchanged" (that's what the mask
 * string is for, and this UI never sends it back). */
export function buildEnrichmentPatch(
  draft: ReturnType<typeof pickEnrichment>,
): ConfigPatch {
  const patch: ConfigPatch = {
    enrichment: {
      aerodatabox_enabled: draft.aerodataboxEnabled,
      daily_lookup_budget: Math.trunc(
        parseNumber(draft.dailyLookupBudget) ?? 0,
      ),
      route_ttl_days: Math.trunc(
        parseNumber(draft.routeTtlDays) ?? ROUTE_TTL_DEFAULT_DAYS,
      ),
    },
  };
  if (draft.aerodataboxKeyTouched) {
    const trimmed = draft.aerodataboxKeyInput.trim();
    patch.enrichment = {
      ...patch.enrichment,
      aerodatabox_api_key: trimmed.length > 0 ? trimmed : null,
    };
  }
  return patch;
}

/** The metadata-sources patch. No secret and no coupled field, so unlike
 * `buildEnrichmentPatch` this is an unconditional one-key document. */
export function buildMetadataPatch(
  draft: ReturnType<typeof pickMetadata>,
): ConfigPatch {
  return { metadata: { opensky_enabled: draft.openskyEnabled } };
}

export function buildRetentionPatch(
  draft: ReturnType<typeof pickRetention>,
): ConfigPatch {
  return {
    retention: {
      high_res_metric_days: Math.trunc(
        parseNumber(draft.highResMetricDays) ?? RETENTION_DEFAULT_DAYS,
      ),
    },
  };
}

const RETENTION_DEFAULT_DAYS = 14;

/** Only ever reached when the field is unparseable, which the section's own
 * validation blocks before a save can fire — a value rather than a throw so
 * the patch builder stays total. */
const ROUTE_TTL_DEFAULT_DAYS = 7;
