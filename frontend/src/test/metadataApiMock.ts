import { vi } from "vitest";

import type {
  MetadataSourceStatusEntry,
  MetadataStatusResponse,
  MetadataUpdateTriggerResponse,
} from "@/lib/api/metadata";

/** A `MetadataSourceStatusEntry`, defaulting to a fresh, never-run source —
 * override just the fields a test cares about. */
export function metadataSource(
  overrides: Partial<MetadataSourceStatusEntry> = {},
): MetadataSourceStatusEntry {
  return {
    name: "mictronics",
    status: "never-run",
    last_success_ms: null,
    dataset_version: null,
    row_count: null,
    last_error: null,
    ...overrides,
  };
}

export interface MockMetadataApiOptions {
  /** Documents `GET /metadata/status` returns, in call order — the last
   * entry repeats for every call past the end of the list. Lets a test
   * script a run's progression (e.g. never-run → running → ok) across the
   * mount fetch, the post-trigger refetch, and subsequent polls. */
  statusSequence?: MetadataStatusResponse[];
  /** Response `POST /metadata/update` returns. */
  triggerResult?: MetadataUpdateTriggerResponse;
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/** Installs a `global.fetch` stub serving `GET`/`POST
 * /api/internal/metadata/*` from a scripted sequence, so `MetadataSection`
 * tests can exercise the real `lib/api/metadata` client + TanStack Query
 * hooks — including the trigger-then-poll flow — without a running backend.
 * Any other URL throws, surfacing an un-mocked request as a test failure. */
export function installMetadataApiMock(options: MockMetadataApiOptions = {}) {
  const sequence = options.statusSequence ?? [{ sources: [] }];
  let statusCalls = 0;

  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();

      if (url === "/api/internal/metadata/status" && method === "GET") {
        const index = Math.min(statusCalls, sequence.length - 1);
        statusCalls += 1;
        return jsonResponse(sequence[index]);
      }
      if (url === "/api/internal/metadata/update" && method === "POST") {
        return jsonResponse(
          options.triggerResult ?? {
            started: true,
            already_running: false,
            started_ms: 1_756_600_000_000,
          },
          202,
        );
      }

      throw new Error(`Unhandled fetch in test: ${method} ${url}`);
    },
  );

  vi.stubGlobal("fetch", fetchMock);

  return { fetchMock };
}
