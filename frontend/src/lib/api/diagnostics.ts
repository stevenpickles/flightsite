/**
 * Typed client for `GET /api/v1/diagnostics` — `docs/API.md` §3.10, SPEC §67
 * (roadmap slice 042).
 *
 * The shapes mirror `flightsite.api.schemas.DiagnosticsResponse` field for
 * field. Everything the backend cannot know is `null` rather than absent
 * (§2.7), so the health page renders "unknown" from a value instead of a
 * missing key.
 *
 * Reuses the `ApiV1Error`/`apiV1Fetch` pattern `lib/api/sightings.ts`
 * established for the external `/api/v1` surface's `{"error": {...}}`
 * envelope (§2.5) — duplicated rather than imported, the same call
 * `receiverStats.ts` makes relative to it.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

/** Roll-up health, for the whole install and for individual sections. */
export type DiagnosticsStatus = "ok" | "degraded" | "down";

/** `unconfigured` is a first-run install with no receiver yet — deliberately
 * distinct from `down`, which is a receiver that should be answering. */
export type DecoderState = "unconfigured" | "connected" | "degraded" | "down";

export type MetadataSourceState = "never_run" | "ok" | "failed";

export type MaintenanceJobOutcome = "ok" | "skipped" | "failed";

export type DiagnosticsErrorCategory =
  "ingestion" | "database" | "enrichment" | "websocket" | "feeders" | "other";

export interface DiagnosticsVersions {
  backend: string;
  frontend: string;
  api: string;
  schema_revision: string | null;
}

export interface DiagnosticsUptime {
  backend_s: number | null;
  started_at: string | null;
  decoder_s: number | null;
}

export interface DiagnosticsDecoder {
  configured: boolean;
  state: DecoderState;
  last_success: string | null;
  last_failure: string | null;
  last_error: string | null;
  consecutive_failures: number;
  total_failures: number;
  total_successes: number;
  next_retry_delay_s: number | null;
  batches_ingested: number;
  updates_ingested: number;
  demo_mode: boolean;
}

export interface DiagnosticsLive {
  last_aircraft_update: string | null;
  last_aircraft_update_age_s: number | null;
  total: number;
  positioned: number;
  non_positioned: number;
  stale: number;
}

/** One live-event consumer's shedding and backlog (slice 075). `dropped` is
 * cumulative for the *name* and survives the service restarting, so a
 * consumer that stopped and resubscribed does not read as having a clean
 * record. `overflowed` is true only while it has an unacknowledged gap and is
 * resyncing from a snapshot. */
export interface DiagnosticsLiveEventSubscriber {
  name: string;
  dropped: number;
  pending: number;
  capacity: number;
  overflowed: boolean;
}

/** The live event stream, attributed per consumer. Absent from a backend
 * older than slice 075, which published only a process-wide total — and
 * published it under `websocket` (issue #185). */
export interface DiagnosticsLiveEvents {
  published: number;
  dropped: number;
  subscribers: DiagnosticsLiveEventSubscriber[];
}

export interface DiagnosticsQuickCheck {
  healthy: boolean | null;
  checked_at: string | null;
  error: string | null;
  rows: string[];
}

export interface DiagnosticsStorage {
  database_bytes: number | null;
  file_bytes: number | null;
  wal_bytes: number | null;
  reclaimable_bytes: number | null;
  reclaimable_ratio: number | null;
  disk_free_bytes: number | null;
  page_count: number | null;
  page_size: number | null;
}

export interface DiagnosticsRowCounts {
  aircraft: number | null;
  sightings: number | null;
  sighting_tracks: number | null;
  activity_events: number | null;
  alert_matches: number | null;
  aircraft_metadata: number | null;
  airports: number | null;
  receiver_metrics_raw: number | null;
}

export interface DiagnosticsMaintenanceJob {
  outcome: MaintenanceJobOutcome;
  started_at: string | null;
  duration_ms: number;
  detail: Record<string, unknown>;
}

/** Why the guarded `VACUUM` last declined to run. `required_free_bytes`
 * against `available_free_bytes` is the point: `VACUUM` builds a complete
 * second copy, so on a large database the requirement can exceed anything the
 * card will ever have free — a refusal that never clears on its own. */
export interface DiagnosticsVacuumRefusal {
  reason: string;
  required_free_bytes: number;
  available_free_bytes: number;
}

export interface DiagnosticsMaintenance {
  cycles: number;
  last_cycle_at: string | null;
  healthy: boolean | null;
  running: boolean;
  jobs: Record<string, DiagnosticsMaintenanceJob>;
  /** `null` when the last evaluation let a `VACUUM` run, or before the job
   * has ever been due. */
  vacuum_refusal: DiagnosticsVacuumRefusal | null;
}

export interface DiagnosticsRecovery {
  recovered: number;
  continued: number;
  points_recovered: number;
  orphan_checkpoints: number;
  orphan_sightings: number;
  failed: number;
  anomalies: number;
}

export interface DiagnosticsDatabase {
  status: DiagnosticsStatus;
  reachable: boolean;
  quick_check: DiagnosticsQuickCheck;
  storage: DiagnosticsStorage;
  row_counts: DiagnosticsRowCounts;
  maintenance: DiagnosticsMaintenance;
  recovery: DiagnosticsRecovery;
}

export interface DiagnosticsMetadataSource {
  source: string;
  status: MetadataSourceState;
  last_attempt_at: string | null;
  last_success_at: string | null;
  age_s: number | null;
  dataset_version: string | null;
  row_count: number | null;
  last_error: string | null;
  running: boolean;
}

export interface DiagnosticsMetadata {
  sources: DiagnosticsMetadataSource[];
  newest_success_at: string | null;
  age_s: number | null;
}

/** What the *backend* knows about notifications. Browser permission is a
 * client fact no server can observe, which is what `permission_known_by`
 * says out loud; the health page joins this with slice 040's store. */
export interface DiagnosticsNotifications {
  configured_enabled: boolean;
  severities: Record<string, boolean>;
  permission_known_by: "client";
}

/** The daily provider-call allowance (slice 070). `limit` and `remaining`
 * are `null` together when no cap is configured; `resets_at` is the ISO-8601
 * UTC instant the counter next rolls over (midnight UTC). */
export interface DiagnosticsEnrichmentBudget {
  limit: number | null;
  used_today: number;
  remaining: number | null;
  resets_at: string;
}

/** Route-cache effectiveness (slice 070): `learned` counts routes the cache
 * holds that were never paid for with a provider call. `directory_hits` and
 * `stale_served` are offline-route additions (slice 071) — absent from a
 * backend that predates them. */
export interface DiagnosticsEnrichmentCache {
  hits: number;
  misses: number;
  learned: number;
  /** Routes answered from the bundled VRS standing-data directory rather
   * than a cache row or a provider call. */
  directory_hits?: number;
  /** Routes answered from a last-known route rather than a fresh lookup. */
  stale_served?: number;
}

export interface DiagnosticsEnrichment {
  enabled: boolean;
  running: boolean;
  circuit_open: boolean;
  lookups: number;
  dropped: number;
  pending: number;
  failures: number;
  /** `"aerodatabox"` when the provider key is configured, `null` when the
   * worker runs key-less off the offline route directory alone. Absent from
   * a backend older than slice 071 (§67). */
  provider?: "aerodatabox" | null;
  /** Absent from a backend older than slice 070 — the Health card renders
   * the rows it has rather than inventing zeroes for the ones it does not. */
  budget?: DiagnosticsEnrichmentBudget;
  cache?: DiagnosticsEnrichmentCache;
}

export interface DiagnosticsWebSocket {
  clients: number;
  running: boolean;
  /** Clients the server had to shed; a clean disconnect is not counted. */
  disconnects: number;
  /** Live events shed from the **WebSocket broadcaster's own** queue since
   * slice 075. Before that this carried the process-wide
   * `live_events_dropped` counter, so it reported the persistence and alert
   * queues' drops under the WebSocket's name too (issue #185). For the
   * process total read `counters.live_events_dropped`, and for the
   * per-consumer breakdown `live_events.subscribers`. */
  events_dropped: number;
}

export interface DiagnosticsErrorEntry {
  at: string;
  category: DiagnosticsErrorCategory;
  event: string;
  level: string;
  logger: string;
  detail: string | null;
}

/** Docker socket read-state, reused verbatim from the design record's
 * `feeders` diagnostics section (roadmap slice 077,
 * `docs/design/077-feeders-page.md` "Backend package"): `"unset"` is the
 * default opt-out, `"unreachable"` is a configured path the backend could
 * not open, and only `"available"` means log/health-only feeder signals
 * are actually being read. */
export type FeedersDockerSocketState = "available" | "unset" | "unreachable";

/** SPEC §67's feeder roll-up (roadmap slice 077) — declared here rather than
 * in `lib/api/feeders.ts` because this block only ever arrives inside
 * `GET /api/v1/diagnostics`, and the Health page is this type's only reader
 * (`FeedersHealthCard`). Optional on `Diagnostics` for the same reason
 * `live_events` is: absent from any backend built before this slice, so the
 * card disappears rather than rendering a row of invented zeroes. */
export interface DiagnosticsFeeders {
  configured: number;
  up: number;
  degraded: number;
  down: number;
  unknown: number;
  docker_socket: FeedersDockerSocketState;
}

export interface Diagnostics {
  generated_at: string;
  status: DiagnosticsStatus;
  ready: boolean;
  subsystems: Record<string, boolean>;
  versions: DiagnosticsVersions;
  uptime: DiagnosticsUptime;
  decoder: DiagnosticsDecoder;
  live: DiagnosticsLive;
  /** Absent from a backend older than slice 075 — the Health page renders
   * the card it has rather than a row of invented zeroes. */
  live_events?: DiagnosticsLiveEvents;
  database: DiagnosticsDatabase;
  metadata: DiagnosticsMetadata;
  notifications: DiagnosticsNotifications;
  enrichment: DiagnosticsEnrichment;
  websocket: DiagnosticsWebSocket;
  counters: Record<string, number>;
  recent_errors: Record<string, DiagnosticsErrorEntry[]>;
  /** Absent from a backend older than roadmap slice 077. */
  feeders?: DiagnosticsFeeders;
}

interface ApiV1ErrorBody {
  error?: { code?: string; message?: string; detail?: unknown };
}

/** Thrown for any non-2xx response. `code` is the §2.5 machine-readable
 * slug, `null` when the response did not carry the documented envelope. */
export class DiagnosticsApiError extends Error {
  readonly status: number;
  readonly code: string | null;

  constructor(status: number, body: ApiV1ErrorBody | undefined) {
    super(body?.error?.message ?? `Request failed with status ${status}`);
    this.name = "DiagnosticsApiError";
    this.status = status;
    this.code = body?.error?.code ?? null;
  }
}

async function apiV1Fetch<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    let body: ApiV1ErrorBody | undefined;
    try {
      body = (await response.json()) as ApiV1ErrorBody;
    } catch {
      body = undefined;
    }
    throw new DiagnosticsApiError(response.status, body);
  }
  return (await response.json()) as T;
}

/**
 * Slower than the scorecard's 5s: diagnostics counts rows and stats the
 * database file, and nothing on this page changes second to second. The
 * point of the page is answering "is it healthy right now", which ten
 * seconds serves without making a read-only endpoint feel like a hot path.
 */
export const DIAGNOSTICS_POLL_MS = 10_000;

export const diagnosticsQueryKey = ["diagnostics"] as const;

export function getDiagnostics(): Promise<Diagnostics> {
  return apiV1Fetch<Diagnostics>("/api/v1/diagnostics");
}

export function useDiagnosticsQuery(): UseQueryResult<Diagnostics> {
  return useQuery({
    queryKey: diagnosticsQueryKey,
    queryFn: getDiagnostics,
    refetchInterval: DIAGNOSTICS_POLL_MS,
  });
}
