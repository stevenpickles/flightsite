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
import {
  FEEDERS_EXAMPLE_ENTRIES,
  FEEDERS_EXAMPLE_LOCAL_PAGES,
  feederKindFields,
} from "@/features/settings/lib/feederKinds";
import { parseRangeRingRadii } from "@/features/settings/lib/validation";
import type {
  FeederEntryDraft,
  FeedersDraft,
  LocalPageDraft,
  SettingsDraft,
} from "@/features/settings/types";
import type {
  ConfigPatch,
  FeederEntryConfig,
  FlightSiteConfig,
} from "@/lib/api/config";

/** One feeder entry's config shape, converted to its editable draft row.
 * `statsUrlStored` reads `secrets_set["feeders.stats_urls.<name>"]` at the
 * moment the draft is built (load, or post-save resync) — see
 * `FeederEntryDraft`'s doc comment for why the input itself always starts
 * blank regardless. */
function feederEntryToDraft(
  entry: FeederEntryConfig,
  secretsSet: Record<string, boolean>,
): FeederEntryDraft {
  return {
    name: entry.name,
    label: entry.label,
    kind: entry.kind,
    url: entry.url ?? "",
    container: entry.container ?? "",
    host: entry.host ?? "",
    mlatPort:
      entry.mlat_port !== null && entry.mlat_port !== undefined
        ? String(entry.mlat_port)
        : "",
    beastPort:
      entry.beast_port !== null && entry.beast_port !== undefined
        ? String(entry.beast_port)
        : "",
    webUrl: entry.web_url ?? "",
    statsUrlInput: "",
    statsUrlTouched: false,
    statsUrlStored: secretsSet[`feeders.stats_urls.${entry.name}`] ?? false,
  };
}

function localPageToDraft(page: {
  label: string;
  url: string;
}): LocalPageDraft {
  return { label: page.label, url: page.url };
}

/** Builds the Feeders section's draft from its config slice — its own
 * function (rather than folded into `draftFromConfig`) because, unlike
 * every other section, it needs `secrets_set` to seed each row's
 * `statsUrlStored`, the same information `EnrichmentSection` gets as a
 * `hasStoredKey` prop rather than through this module. */
export function feedersDraftFromConfig(
  config: FlightSiteConfig,
  secretsSet: Record<string, boolean>,
): FeedersDraft {
  return {
    pollIntervalS: String(config.feeders.poll_interval_s),
    dockerSocket: config.feeders.docker_socket ?? "",
    entries: config.feeders.entries.map((entry) =>
      feederEntryToDraft(entry, secretsSet),
    ),
    localPages: config.feeders.local_pages.map(localPageToDraft),
  };
}

/** Builds the initial (and post-save) draft from the effective config.
 * Every section reads its slice of this via the `pick*` helpers below, so
 * a fresh load and a post-save resync are the same code path.
 *
 * `secretsSet` is optional and defaults to empty — every section but
 * Feeders ignores it entirely (their own secret, `aerodatabox_api_key`, is
 * read through a separate `hasStoredKey` prop, per `EnrichmentSection`).
 * Feeders is the one section whose "is this stored" state lives *inside*
 * the draft, one flag per table row rather than one section-wide prop, so
 * it is threaded through here instead. */
export function draftFromConfig(
  config: FlightSiteConfig,
  secretsSet: Record<string, boolean> = {},
): SettingsDraft {
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

    notifications: { ...config.notifications },

    aerodataboxEnabled: config.enrichment.aerodatabox_enabled,
    aerodataboxKeyInput: "",
    aerodataboxKeyTouched: false,
    dailyLookupBudget: String(config.enrichment.daily_lookup_budget),
    routeTtlDays: String(config.enrichment.route_ttl_days),

    openskyEnabled: config.metadata.opensky_enabled,

    highResMetricDays: String(config.retention.high_res_metric_days),

    feeders: feedersDraftFromConfig(config, secretsSet),
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

export function pickFeeders(draft: SettingsDraft): FeedersDraft {
  return draft.feeders;
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

/** Only ever reached when the poll interval field is unparseable, which the
 * section's own validation (5–120 s) blocks before a save can fire. */
const FEEDERS_POLL_INTERVAL_DEFAULT_S = 15;

/** One draft row -> the wire shape, dropping (as `null`) every field the
 * row's `kind` doesn't use rather than sending stray values a different
 * kind happened to leave filled in from before a kind change — `web_url` is
 * the one exception, since it applies to every kind (see
 * `lib/feederKinds.ts`'s doc comment). */
function feederEntryDraftToConfig(entry: FeederEntryDraft): FeederEntryConfig {
  const fields = feederKindFields(entry.kind);
  const mlatPort = parseNumber(entry.mlatPort);
  const beastPort = parseNumber(entry.beastPort);
  return {
    name: entry.name.trim(),
    label: entry.label.trim(),
    kind: entry.kind,
    url: fields.url && entry.url.trim().length > 0 ? entry.url.trim() : null,
    container:
      fields.container && entry.container.trim().length > 0
        ? entry.container.trim()
        : null,
    host:
      fields.hostPorts && entry.host.trim().length > 0
        ? entry.host.trim()
        : null,
    mlat_port:
      fields.hostPorts && mlatPort !== null ? Math.trunc(mlatPort) : null,
    beast_port:
      fields.hostPorts && beastPort !== null ? Math.trunc(beastPort) : null,
    web_url: entry.webUrl.trim().length > 0 ? entry.webUrl.trim() : null,
  };
}

/**
 * Builds the Feeders patch. `entries` and `local_pages` are always sent in
 * full — the design record's contract for this section ("lists replaced
 * wholesale") — so a row removed in the editor is a row absent from the
 * saved config rather than something the backend has to diff out.
 *
 * `stats_urls` mirrors `buildEnrichmentPatch`'s secret handling per row: a
 * row is only present in the patch's `stats_urls` map when its own
 * `statsUrlTouched` is true, so an untouched row's previously-stored stats
 * URL is never disturbed just by saving the rest of the section (adding or
 * editing an unrelated row, reordering, changing the poll interval, …). The
 * key is omitted from the patch entirely when nothing was touched, the same
 * "no-op means absent" rule the single-secret sections follow.
 */
export function buildFeedersPatch(draft: FeedersDraft): ConfigPatch {
  const patch: ConfigPatch = {
    feeders: {
      poll_interval_s: Math.trunc(
        parseNumber(draft.pollIntervalS) ?? FEEDERS_POLL_INTERVAL_DEFAULT_S,
      ),
      docker_socket:
        draft.dockerSocket.trim().length > 0 ? draft.dockerSocket.trim() : null,
      entries: draft.entries.map(feederEntryDraftToConfig),
      local_pages: draft.localPages
        .filter(
          (page) => page.label.trim().length > 0 || page.url.trim().length > 0,
        )
        .map((page) => ({ label: page.label.trim(), url: page.url.trim() })),
    },
  };

  const statsUrls: Record<string, string | null> = {};
  let anyTouched = false;
  for (const entry of draft.entries) {
    if (!entry.statsUrlTouched) {
      continue;
    }
    anyTouched = true;
    const trimmed = entry.statsUrlInput.trim();
    statsUrls[entry.name.trim()] = trimmed.length > 0 ? trimmed : null;
  }
  if (anyTouched) {
    patch.feeders = { ...patch.feeders, stats_urls: statsUrls };
  }

  return patch;
}

/** Fills the "Load the example for a Pi with ultrafeeder + piaware + fr24 +
 * opensky" example (`docs/design/077-feeders-page.md` "Config") into the
 * draft, replacing its entries and local pages — never saving, and never
 * touching `pollIntervalS`/`dockerSocket`, which stay whatever the section
 * already had (the Docker socket in particular is opt-in and this button is
 * not a reason to turn it on for someone who hasn't). Every example row's
 * stats-URL input starts blank and untouched, same as any other freshly
 * loaded row — the example does not (and cannot) know anyone's real stats
 * URLs. */
export function applyFeedersExample(draft: FeedersDraft): FeedersDraft {
  return {
    ...draft,
    entries: FEEDERS_EXAMPLE_ENTRIES.map((entry) =>
      feederEntryToDraft(entry, {}),
    ),
    localPages: FEEDERS_EXAMPLE_LOCAL_PAGES.map(localPageToDraft),
  };
}

/** Only ever reached when the field is unparseable, which the section's own
 * validation blocks before a save can fire — a value rather than a throw so
 * the patch builder stays total. */
const ROUTE_TTL_DEFAULT_DAYS = 7;
