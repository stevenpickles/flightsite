import { vi } from "vitest";

import type {
  Diagnostics,
  DiagnosticsDatabase,
  DiagnosticsDecoder,
  DiagnosticsEnrichment,
  DiagnosticsErrorEntry,
  DiagnosticsMetadata,
  DiagnosticsMetadataSource,
} from "@/lib/api/diagnostics";

import { defaultFlightSiteConfig } from "@/test/configApiMock";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function decoder(
  overrides: Partial<DiagnosticsDecoder> = {},
): DiagnosticsDecoder {
  return {
    configured: true,
    state: "connected",
    last_success: "2026-08-31T14:03:22.000Z",
    last_failure: null,
    last_error: null,
    consecutive_failures: 0,
    total_failures: 3,
    total_successes: 8410,
    next_retry_delay_s: null,
    batches_ingested: 8410,
    updates_ingested: 194_233,
    demo_mode: false,
    ...overrides,
  };
}

export function metadataSource(
  overrides: Partial<DiagnosticsMetadataSource> = {},
): DiagnosticsMetadataSource {
  return {
    source: "mictronics",
    status: "ok",
    last_attempt_at: "2026-08-29T02:00:00.000Z",
    last_success_at: "2026-08-29T02:00:00.000Z",
    age_s: 180_000,
    dataset_version: "2026-08-29",
    row_count: 412_003,
    last_error: null,
    running: false,
    ...overrides,
  };
}

export function metadata(
  overrides: Partial<DiagnosticsMetadata> = {},
): DiagnosticsMetadata {
  return {
    sources: [metadataSource()],
    newest_success_at: "2026-08-29T02:00:00.000Z",
    age_s: 180_000,
    ...overrides,
  };
}

export function database(
  overrides: Partial<DiagnosticsDatabase> = {},
): DiagnosticsDatabase {
  return {
    status: "ok",
    reachable: true,
    quick_check: {
      healthy: true,
      checked_at: "2026-08-31T13:00:00.000Z",
      error: null,
      rows: [],
    },
    storage: {
      database_bytes: 268_435_456,
      file_bytes: 268_435_456,
      wal_bytes: 4_194_304,
      reclaimable_bytes: 8_388_608,
      reclaimable_ratio: 0.031,
      disk_free_bytes: 12_884_901_888,
      page_count: 65_536,
      page_size: 4096,
    },
    row_counts: {
      aircraft: 5821,
      sightings: 41_233,
      sighting_tracks: 902_114,
      activity_events: 1204,
      alert_matches: 87,
      aircraft_metadata: 412_003,
      airports: 74_112,
      receiver_metrics_raw: 60_480,
    },
    maintenance: {
      cycles: 42,
      last_cycle_at: "2026-08-31T13:00:00.000Z",
      healthy: true,
      running: true,
      jobs: {
        quick_check: {
          outcome: "ok",
          started_at: "2026-08-31T13:00:00.000Z",
          duration_ms: 84,
          detail: {},
        },
      },
      vacuum_refusal: null,
    },
    recovery: {
      recovered: 0,
      continued: 0,
      points_recovered: 0,
      orphan_checkpoints: 0,
      orphan_sightings: 0,
      failed: 0,
      anomalies: 0,
    },
    ...overrides,
  };
}

export function errorEntry(
  overrides: Partial<DiagnosticsErrorEntry> = {},
): DiagnosticsErrorEntry {
  return {
    at: "2026-08-31T13:59:00.000Z",
    category: "ingestion",
    event: "decoder_poll_failed",
    level: "WARNING",
    logger: "flightsite.ingest.readsb",
    detail: "url=http://decoder.invalid, attempt=3",
    ...overrides,
  };
}

/** Enrichment as a slice-071 backend reports it: switched off, with a
 * capped daily budget, a provider configured, and a cache that has seen
 * some traffic including offline-directory and last-known-route hits.
 * Tests for an older backend drop `provider`/`budget`/`cache` (or the
 * cache's `directory_hits`/`stale_served`) explicitly. */
export function enrichment(
  overrides: Partial<DiagnosticsEnrichment> = {},
): DiagnosticsEnrichment {
  return {
    enabled: false,
    running: false,
    circuit_open: false,
    lookups: 0,
    dropped: 0,
    pending: 0,
    failures: 0,
    provider: "aerodatabox",
    budget: {
      limit: 100,
      used_today: 12,
      remaining: 88,
      resets_at: "2026-09-01T00:00:00.000Z",
    },
    cache: {
      hits: 340,
      misses: 42,
      learned: 17,
      directory_hits: 91,
      stale_served: 6,
    },
    ...overrides,
  };
}

/** A healthy install. Every test starts here and overrides the one thing it
 * is about, which is what keeps a degraded-state test readable. */
export function diagnostics(overrides: Partial<Diagnostics> = {}): Diagnostics {
  return {
    generated_at: "2026-08-31T14:03:22.418Z",
    status: "ok",
    ready: true,
    subsystems: { database: true, ingestion: true },
    versions: {
      backend: "0.9.2",
      frontend: "0.9.2",
      api: "v1",
      schema_revision: "0012",
    },
    uptime: {
      backend_s: 91_004,
      started_at: "2026-08-30T12:46:38.000Z",
      decoder_s: 356_412,
    },
    decoder: decoder(),
    live: {
      last_aircraft_update: "2026-08-31T14:03:20.000Z",
      last_aircraft_update_age_s: 2,
      total: 12,
      positioned: 9,
      non_positioned: 3,
      stale: 0,
    },
    database: database(),
    metadata: metadata(),
    notifications: {
      configured_enabled: true,
      severities: {
        info: false,
        interesting: true,
        high: true,
        critical: true,
      },
      permission_known_by: "client",
    },
    enrichment: enrichment(),
    websocket: {
      clients: 1,
      running: true,
      disconnects: 0,
      events_dropped: 0,
    },
    counters: {
      ingestion_failures: 3,
      db_errors: 0,
      enrichment_failures: 0,
      ws_disconnects: 0,
      live_events_dropped: 0,
    },
    recent_errors: {
      ingestion: [],
      database: [],
      enrichment: [],
      websocket: [],
      other: [],
    },
    ...overrides,
  };
}

export interface MockDiagnosticsApiOptions {
  diagnostics?: Diagnostics;
  /** Serve this status instead of a body, for error-path tests. */
  status?: number;
}

export function installDiagnosticsApiMock(
  options: MockDiagnosticsApiOptions = {},
) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const raw = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();
      const url = new URL(raw, "http://localhost");

      if (url.pathname === "/api/v1/diagnostics" && method === "GET") {
        if (options.status !== undefined && options.status >= 400) {
          return jsonResponse(
            { error: { code: "unavailable", message: "Backend is down" } },
            options.status,
          );
        }
        return jsonResponse(options.diagnostics ?? diagnostics());
      }
      // The health page reads the configured timezone for its timestamps.
      if (url.pathname === "/api/internal/config" && method === "GET") {
        return jsonResponse({
          first_run: false,
          config: defaultFlightSiteConfig(),
          secrets_set: {},
        });
      }

      throw new Error(`Unhandled fetch in test: ${method} ${raw}`);
    },
  );

  vi.stubGlobal("fetch", fetchMock);

  return { fetchMock };
}
