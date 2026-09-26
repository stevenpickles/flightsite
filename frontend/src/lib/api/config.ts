/**
 * Typed client for `GET`/`PUT /api/internal/config` (docs/API.md §5). The
 * shapes below mirror `flightsite.config.models.Settings` and the response
 * envelope built by `_config_response` in
 * `backend/src/flightsite/api/internal.py` field-for-field — this is the
 * single place the frontend describes that document, so the setup wizard
 * (slice 018) and the Settings page (slice 019) share one definition.
 */
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from "@tanstack/react-query";

import { apiFetch } from "@/lib/api/client";

export type UnitSystem = "aviation" | "metric";

/** Decoder (readsb / dump1090-fa) HTTP JSON endpoint — mirrors
 * `ReceiverSettings`. */
export interface ReceiverConfig {
  host: string;
  port: number;
  path: string;
  poll_interval_s: number;
}

/** Receiver location — mirrors `LocationSettings`. Both `latitude` and
 * `longitude` are `null` until the setup wizard collects them. */
export interface LocationConfig {
  latitude: number | null;
  longitude: number | null;
  site_name: string | null;
  antenna_height_ft: number | null;
}

/** Mirrors `SightingTimingSettings`. */
export interface SightingTimingConfig {
  stale_s: number;
  remove_s: number;
  close_s: number;
}

/** Mirrors `RetentionSettings`. */
export interface RetentionConfig {
  high_res_metric_days: number;
}

/** Mirrors `MapSettings`. */
export interface MapDocConfig {
  basemap: string;
  range_rings_enabled: boolean;
  range_ring_radii_nm: number[];
}

/** Mirrors `EnrichmentSettings`. `aerodatabox_api_key` is the only v1
 * secret: `"•••"` when set, `null` when unset (SPEC §29,
 * `Settings.dump_public`) — never the real value. */
export interface EnrichmentConfig {
  aerodatabox_enabled: boolean;
  aerodatabox_api_key: string | null;
  /** Provider lookups allowed per UTC day; `0` means uncapped (slice 070).
   * Applied on save — the enrichment provider is rebuilt, not restarted. */
  daily_lookup_budget: number;
  /** How long a cached route stays usable, 1–30 days. */
  route_ttl_days: number;
}

/** Mirrors `MetadataSettings`. The two default aircraft-metadata sources need
 * no configuration; this gates the opt-in OpenSky one, off by default because
 * its licensing is ambiguous (ADR-0013). Read at backend startup, so a change
 * applies on the next restart. */
export interface MetadataConfig {
  opensky_enabled: boolean;
}

/** Mirrors `NotificationSettings`. */
export interface NotificationConfig {
  enabled: boolean;
  info: boolean;
  interesting: boolean;
  high: boolean;
  critical: boolean;
}

/** Mirrors `AlertSettings`. Ids are validated for shape only on the
 * backend; the setup wizard owns the SPEC §45 template catalogue (see
 * `src/features/setup/constants.ts`). */
export interface AlertConfig {
  enabled_templates: string[];
}

/** The seven feeder-entry kinds (slice 077 design record, "Kinds"). Each is
 * the only place its own vendor's vocabulary is read on the backend — the
 * frontend just needs to know which kind-dependent fields a card and this
 * section's entries-editor row should show. */
export type FeederKind =
  | "readsb"
  | "piaware"
  | "fr24"
  | "ultrafeeder"
  | "opensky_logs"
  | "docker_health"
  | "link_only";

/**
 * One feeder entry (`docs/design/077-feeders-page.md` "Config"). Every
 * field beyond `name`/`label`/`kind` is kind-dependent and optional here —
 * the backend validates which ones a given `kind` requires; the frontend
 * mirrors that per-kind requirement only for inline validation, not as a
 * second source of truth.
 *
 * `url` is the probe endpoint (readsb/piaware/fr24 HTTP JSON, or the
 * ultrafeeder host's HTTP for MLAT client stats); `host`/`mlat_port`/
 * `beast_port` are the ultrafeeder peer this receiver connects out to;
 * `container` names the Docker container a socket-backed kind reads logs or
 * health from; `web_url` is the "Open" link to the feeder's own locally
 * hosted page, independent of how (or whether) its status is probed.
 */
export interface FeederEntryConfig {
  name: string;
  label: string;
  kind: FeederKind;
  url?: string | null;
  container?: string | null;
  host?: string | null;
  mlat_port?: number | null;
  beast_port?: number | null;
  web_url?: string | null;
}

/** One entry in `feeders.local_pages` — a locally hosted sibling page
 * (tar1090, graphs1090, SkyAware, the FR24 feeder UI, …) with no status of
 * its own to probe, just a link. */
export interface LocalPageConfig {
  label: string;
  url: string;
}

/**
 * Mirrors `FeederSettings` (slice 077). Hot-applied on save, like
 * enrichment — the service rebuilds its probes from the new entry list
 * rather than waiting for a restart.
 *
 * `stats_urls` is the one secret-backed field here, keyed by entry `name`
 * exactly the way `EnrichmentConfig.aerodatabox_api_key` is masked: a
 * configured URL reads back as a non-null mask string (never the real
 * value — SPEC §29), an unconfigured one as `null`. **Assumption** (no
 * backend contract to check this against yet, per work package D's
 * instructions): the design record only states that `secrets.yaml` stores
 * `feeders.stats_urls.<name>` and that `secrets_set` carries one boolean
 * per configured name; it does not say whether the masked value itself
 * round-trips inside `config.feeders.stats_urls` the way
 * `aerodatabox_api_key` does inside `config.enrichment`. This type assumes
 * it does, for symmetry with the one other masked-secret field this page
 * already has to match — if agents A/B instead omit `stats_urls` from the
 * config dump entirely (relying on `secrets_set` alone), this field simply
 * never gets a non-empty value from the real backend and every consumer
 * here already treats "no mask string" the same as "not configured".
 */
export interface FeedersConfig {
  poll_interval_s: number;
  docker_socket: string | null;
  entries: FeederEntryConfig[];
  local_pages: LocalPageConfig[];
  stats_urls: Record<string, string | null>;
}

/** Mirrors `Settings.dump_public()` — the full effective configuration
 * with secrets masked. */
export interface FlightSiteConfig {
  log_level: "CRITICAL" | "ERROR" | "WARNING" | "INFO" | "DEBUG";
  /** SPEC §68's rotating local logs, written under the data directory. */
  log_file_enabled: boolean;
  units: UnitSystem;
  timezone: string;
  display_radius_nm: number;
  alert_radius_nm: number | null;
  receiver: ReceiverConfig;
  location: LocationConfig;
  sighting: SightingTimingConfig;
  retention: RetentionConfig;
  map: MapDocConfig;
  enrichment: EnrichmentConfig;
  metadata: MetadataConfig;
  notifications: NotificationConfig;
  alerts: AlertConfig;
  feeders: FeedersConfig;
}

/** `GET`/`PUT /api/internal/config` response envelope. `secrets_set` reports
 * per-secret whether a value is stored, keyed by dotted path (e.g.
 * `"enrichment.aerodatabox_api_key"`), without ever carrying the value. */
export interface ConfigResponse {
  first_run: boolean;
  config: FlightSiteConfig;
  secrets_set: Record<string, boolean>;
}

/** A partial config document: any subset of top-level sections, each
 * itself a partial of its own fields. `PUT /api/internal/config` accepts
 * exactly this shape — a masked secret sent back unchanged is a no-op, and
 * an explicit `null` clears it. */
export type ConfigPatch = {
  [K in keyof FlightSiteConfig]?: FlightSiteConfig[K] extends
    string | number | boolean | null
    ? FlightSiteConfig[K]
    : Partial<FlightSiteConfig[K]>;
};

const CONFIG_PATH = "/api/internal/config";

export function getConfig(): Promise<ConfigResponse> {
  return apiFetch<ConfigResponse>(CONFIG_PATH);
}

export function putConfig(patch: ConfigPatch): Promise<ConfigResponse> {
  return apiFetch<ConfigResponse>(CONFIG_PATH, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

/** Query key for the shared config document, exported so any consumer
 * (the setup wizard, and eventually the slice-019 Settings page) reads
 * from — and can invalidate — the same cache entry. */
export const configQueryKey = ["config"] as const;

/** Loads the effective config document. Retries are disabled: a fetch
 * failure must not spend several seconds retrying before the app renders
 * anything — see `RootLayout`, which treats "no answer yet" the same as
 * "not first-run" rather than blocking on this query. */
export function useConfigQuery(): UseQueryResult<ConfigResponse> {
  return useQuery({
    queryKey: configQueryKey,
    queryFn: getConfig,
    retry: false,
  });
}

/** Applies a config patch and refreshes every `useConfigQuery` consumer
 * with the response in one step, so a page that just wrote a change (the
 * setup wizard's review step; later, Settings) never has to separately
 * invalidate and refetch. */
export function usePutConfigMutation(): UseMutationResult<
  ConfigResponse,
  Error,
  ConfigPatch
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: putConfig,
    onSuccess: (data) => {
      queryClient.setQueryData(configQueryKey, data);
    },
  });
}
