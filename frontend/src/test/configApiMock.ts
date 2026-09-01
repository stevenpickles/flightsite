import { vi } from "vitest";

import type { ConfigResponse, FlightSiteConfig } from "@/lib/api/config";
import type { ConnectionTestResult } from "@/lib/api/decoder";

/** A schema-default `FlightSiteConfig`, mirroring
 * `flightsite.config.models.Settings()` — used as the base every test
 * starts from and overrides piecemeal. */
export function defaultFlightSiteConfig(
  overrides: Partial<FlightSiteConfig> = {},
): FlightSiteConfig {
  return {
    log_level: "INFO",
    units: "aviation",
    timezone: "UTC",
    display_radius_nm: 250,
    alert_radius_nm: null,
    receiver: {
      host: "127.0.0.1",
      port: 8080,
      path: "/data/aircraft.json",
      poll_interval_s: 1,
    },
    location: {
      latitude: null,
      longitude: null,
      site_name: null,
      antenna_height_ft: null,
    },
    sighting: { stale_s: 15, remove_s: 60, close_s: 600 },
    retention: { high_res_metric_days: 14 },
    map: {
      basemap: "dark-aviation",
      range_rings_enabled: true,
      range_ring_radii_nm: [50, 100, 150, 200],
    },
    enrichment: { aerodatabox_enabled: false, aerodatabox_api_key: null },
    notifications: {
      enabled: true,
      info: false,
      interesting: true,
      high: true,
      critical: true,
    },
    alerts: { enabled_templates: [] },
    ...overrides,
  };
}

export function successConnectionTestResult(
  overrides: Partial<ConnectionTestResult> = {},
): ConnectionTestResult {
  return {
    ok: true,
    url: "http://127.0.0.1:8080/data/aircraft.json",
    elapsed_ms: 12.5,
    error: null,
    detail: null,
    aircraft_count: 37,
    positioned_count: 24,
    flavor: "readsb",
    decoder_time: "2026-08-31T00:00:00Z",
    ...overrides,
  };
}

export function failureConnectionTestResult(
  overrides: Partial<ConnectionTestResult> = {},
): ConnectionTestResult {
  return {
    ok: false,
    url: "http://127.0.0.1:8080/data/aircraft.json",
    elapsed_ms: 8000,
    error: "unreachable",
    detail: "Connection refused",
    aircraft_count: null,
    positioned_count: null,
    flavor: null,
    decoder_time: null,
    ...overrides,
  };
}

export interface MockConfigApiOptions {
  firstRun?: boolean;
  config?: Partial<FlightSiteConfig>;
  secretsSet?: Record<string, boolean>;
  /** Result returned by `POST /api/internal/decoder/test`, or a function
   * of the request body for tests that need to vary the outcome. */
  decoderTestResult?:
    ConnectionTestResult | ((body: unknown) => ConnectionTestResult);
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Shallow-merges a `PUT /api/internal/config` patch into the in-memory
 * config, mirroring `ConfigStore.apply_update`'s "partial or full document"
 * semantics closely enough for these tests: each top-level section in the
 * patch replaces (via a one-level merge) the corresponding section of the
 * current config; sections the patch omits are left untouched. */
function applyPatch(
  base: ConfigResponse,
  patch: Record<string, unknown>,
): ConfigResponse {
  const config: Record<string, unknown> = { ...base.config };
  for (const [key, value] of Object.entries(patch)) {
    const existing = config[key];
    if (isPlainObject(existing) && isPlainObject(value)) {
      config[key] = { ...existing, ...value };
    } else {
      config[key] = value;
    }
  }

  const secretsSet = { ...base.secrets_set };
  const enrichmentPatch = patch.enrichment;
  if (
    isPlainObject(enrichmentPatch) &&
    "aerodatabox_api_key" in enrichmentPatch
  ) {
    secretsSet["enrichment.aerodatabox_api_key"] =
      enrichmentPatch.aerodatabox_api_key !== null;
  }

  return {
    first_run: false,
    config: config as unknown as FlightSiteConfig,
    secrets_set: secretsSet,
  };
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Installs a `global.fetch` stub that serves `GET`/`PUT
 * /api/internal/config` and `POST /api/internal/decoder/test` from an
 * in-memory document, so component/integration tests can exercise the real
 * `lib/api/*` client + TanStack Query hooks without a running backend.
 * Any other URL throws, surfacing an un-mocked request as a test failure
 * instead of a silent network error. */
export function installConfigApiMock(options: MockConfigApiOptions = {}) {
  let current: ConfigResponse = {
    first_run: options.firstRun ?? false,
    config: defaultFlightSiteConfig(options.config),
    secrets_set: {
      "enrichment.aerodatabox_api_key": false,
      ...options.secretsSet,
    },
  };

  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();

      if (url === "/api/internal/config" && method === "GET") {
        return jsonResponse(current);
      }
      if (url === "/api/internal/config" && method === "PUT") {
        const patch = init?.body
          ? (JSON.parse(String(init.body)) as Record<string, unknown>)
          : {};
        current = applyPatch(current, patch);
        return jsonResponse(current);
      }
      if (url === "/api/internal/decoder/test" && method === "POST") {
        const body: unknown = init?.body
          ? JSON.parse(String(init.body))
          : undefined;
        const result =
          typeof options.decoderTestResult === "function"
            ? options.decoderTestResult(body)
            : (options.decoderTestResult ?? successConnectionTestResult());
        return jsonResponse(result);
      }

      throw new Error(`Unhandled fetch in test: ${method} ${url}`);
    },
  );

  vi.stubGlobal("fetch", fetchMock);

  return {
    fetchMock,
    getCurrentConfig: () => current,
  };
}
