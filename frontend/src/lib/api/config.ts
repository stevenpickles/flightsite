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

/** Mirrors `Settings.dump_public()` — the full effective configuration
 * with secrets masked. */
export interface FlightSiteConfig {
  log_level: "CRITICAL" | "ERROR" | "WARNING" | "INFO" | "DEBUG";
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
  notifications: NotificationConfig;
  alerts: AlertConfig;
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
