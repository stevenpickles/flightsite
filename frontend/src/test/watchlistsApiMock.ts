import { vi } from "vitest";

import type {
  Watchlist,
  WatchlistEntry,
  WatchlistEntryKind,
} from "@/lib/api/watchlists";

/** A `Watchlist`, defaulting to an empty, freshly-created one — override
 * just the fields a test cares about. */
export function watchlist(overrides: Partial<Watchlist> = {}): Watchlist {
  return {
    id: 1,
    name: "Test Watchlist",
    description: null,
    created_at: "2026-08-31T00:00:00.000Z",
    entry_count: 0,
    ...overrides,
  };
}

/** A `WatchlistEntry`, defaulting to an ICAO-hex entry — override just the
 * fields a test cares about. */
export function watchlistEntry(
  overrides: Partial<WatchlistEntry> = {},
): WatchlistEntry {
  return {
    id: 1,
    watchlist_id: 1,
    kind: "icao24",
    value: "ae1463",
    note: null,
    created_at: "2026-08-31T00:00:00.000Z",
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  if (status === 204) {
    return new Response(null, { status });
  }
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function parseBody(
  init: RequestInit | undefined,
): Record<string, unknown> | undefined {
  if (!init?.body) {
    return undefined;
  }
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

export interface InstallWatchlistsApiMockOptions {
  watchlists?: Watchlist[];
  entriesByWatchlistId?: Record<number, WatchlistEntry[]>;
}

/**
 * Installs a stateful `global.fetch` stub over an in-memory store, serving
 * the full `/api/internal/watchlists*` CRUD surface (`docs/API.md` §5) the
 * way `backend/src/flightsite/api/internal.py` does — validation-adjacent
 * status codes included (`409` for a name/entry collision, `404` for an
 * unknown id). This lets a `WatchlistsSection`/`WatchlistCard` test exercise
 * the real `lib/api/watchlists` client and its mutations end to end (create
 * → appears in the list; delete → gone) instead of asserting against a
 * single scripted response.
 */
export function installWatchlistsApiMock(
  options: InstallWatchlistsApiMockOptions = {},
) {
  let watchlists = [...(options.watchlists ?? [])];
  const entriesByWatchlistId = new Map<number, WatchlistEntry[]>(
    Object.entries(options.entriesByWatchlistId ?? {}).map(([id, entries]) => [
      Number(id),
      [...entries],
    ]),
  );
  let nextWatchlistId = Math.max(0, ...watchlists.map((entry) => entry.id)) + 1;
  let nextEntryId =
    Math.max(
      0,
      ...[...entriesByWatchlistId.values()].flat().map((entry) => entry.id),
    ) + 1;

  function entryCount(watchlistId: number): number {
    return entriesByWatchlistId.get(watchlistId)?.length ?? 0;
  }

  function withEntryCount(record: Watchlist): Watchlist {
    return { ...record, entry_count: entryCount(record.id) };
  }

  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      const method = (init?.method ?? "GET").toUpperCase();
      const body = parseBody(init);

      const entriesMatch =
        /^\/api\/internal\/watchlists\/(\d+)\/entries(?:\/(\d+))?$/.exec(url);
      if (entriesMatch) {
        const watchlistId = Number(entriesMatch[1]);
        const entryId =
          entriesMatch[2] === undefined ? undefined : Number(entriesMatch[2]);
        const target = watchlists.find((entry) => entry.id === watchlistId);

        if (method === "GET") {
          if (!target) {
            return jsonResponse({ detail: "not found" }, 404);
          }
          return jsonResponse({
            entries: entriesByWatchlistId.get(watchlistId) ?? [],
          });
        }
        if (method === "POST") {
          if (!target) {
            return jsonResponse({ detail: "not found" }, 404);
          }
          const kind = body?.kind as WatchlistEntryKind;
          const value = String(body?.value ?? "").toUpperCase();
          const existing = entriesByWatchlistId.get(watchlistId) ?? [];
          if (
            existing.some(
              (entry) => entry.kind === kind && entry.value === value,
            )
          ) {
            return jsonResponse({ detail: "already on this watchlist" }, 409);
          }
          const entry = watchlistEntry({
            id: nextEntryId++,
            watchlist_id: watchlistId,
            kind,
            value,
            note: (body?.note as string | null) ?? null,
          });
          entriesByWatchlistId.set(watchlistId, [...existing, entry]);
          return jsonResponse(entry, 201);
        }
        if (method === "DELETE" && entryId !== undefined) {
          if (!target) {
            return jsonResponse({ detail: "not found" }, 404);
          }
          const existing = entriesByWatchlistId.get(watchlistId) ?? [];
          const filtered = existing.filter((entry) => entry.id !== entryId);
          if (filtered.length === existing.length) {
            return jsonResponse({ detail: "not found" }, 404);
          }
          entriesByWatchlistId.set(watchlistId, filtered);
          return jsonResponse(undefined, 204);
        }
      }

      const watchlistMatch = /^\/api\/internal\/watchlists(?:\/(\d+))?$/.exec(
        url,
      );
      if (watchlistMatch) {
        const watchlistId =
          watchlistMatch[1] === undefined
            ? undefined
            : Number(watchlistMatch[1]);

        if (method === "GET" && watchlistId === undefined) {
          return jsonResponse({ watchlists: watchlists.map(withEntryCount) });
        }
        if (method === "POST" && watchlistId === undefined) {
          const name = String(body?.name ?? "");
          if (watchlists.some((entry) => entry.name === name)) {
            return jsonResponse(
              { detail: `a watchlist named '${name}' already exists` },
              409,
            );
          }
          const record = watchlist({
            id: nextWatchlistId++,
            name,
            description: (body?.description as string | null) ?? null,
            entry_count: 0,
          });
          watchlists = [...watchlists, record];
          return jsonResponse(record, 201);
        }
        if (method === "PUT" && watchlistId !== undefined) {
          const target = watchlists.find((entry) => entry.id === watchlistId);
          if (!target) {
            return jsonResponse({ detail: "not found" }, 404);
          }
          const name = String(body?.name ?? target.name);
          if (
            watchlists.some(
              (entry) => entry.id !== watchlistId && entry.name === name,
            )
          ) {
            return jsonResponse(
              { detail: `a watchlist named '${name}' already exists` },
              409,
            );
          }
          const updated: Watchlist = {
            ...target,
            name,
            description: (body?.description as string | null) ?? null,
          };
          watchlists = watchlists.map((entry) =>
            entry.id === watchlistId ? updated : entry,
          );
          return jsonResponse(withEntryCount(updated));
        }
        if (method === "DELETE" && watchlistId !== undefined) {
          const existed = watchlists.some((entry) => entry.id === watchlistId);
          if (!existed) {
            return jsonResponse({ detail: "not found" }, 404);
          }
          watchlists = watchlists.filter((entry) => entry.id !== watchlistId);
          entriesByWatchlistId.delete(watchlistId);
          return jsonResponse(undefined, 204);
        }
      }

      throw new Error(`Unhandled fetch in test: ${method} ${url}`);
    },
  );

  vi.stubGlobal("fetch", fetchMock);

  return { fetchMock };
}
