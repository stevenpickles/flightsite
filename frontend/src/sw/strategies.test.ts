/**
 * The service worker's cache strategies against in-memory `caches` and
 * `fetch` fakes (roadmap slice 084): what install stores, what activate
 * deletes, and — the property the slice exists to guarantee — that API,
 * WebSocket, tile and cross-origin requests never reach either the cache or
 * the worker's own `fetch`.
 */

import { describe, expect, it, vi } from "vitest";

import { isSkipWaitingMessage, SKIP_WAITING_MESSAGE } from "@/sw/messages";
import {
  deleteStaleShellCaches,
  handleFetch,
  precacheShell,
  shellCacheName,
  type SwDeps,
} from "@/sw/strategies";

const ORIGIN = "https://flightsite.local";
const VERSION = "v2";
const SHELL = ["/index.html", "/assets/index-abc123.js"];
const context = { origin: ORIGIN, shellPaths: new Set(SHELL) };

function pathOf(input: RequestInfo | URL): string {
  const url =
    typeof input === "string" || input instanceof URL
      ? new URL(input, ORIGIN)
      : new URL(input.url);
  return url.pathname;
}

class FakeCache {
  readonly entries = new Map<string, string>();

  async addAll(urls: RequestInfo[]): Promise<void> {
    for (const url of urls) {
      this.entries.set(pathOf(url), `cached ${pathOf(url)}`);
    }
  }

  async match(input: RequestInfo | URL): Promise<Response | undefined> {
    const body = this.entries.get(pathOf(input));
    return body === undefined ? undefined : new Response(body);
  }
}

class FakeCacheStorage {
  readonly byName = new Map<string, FakeCache>();

  async open(name: string): Promise<FakeCache> {
    let cache = this.byName.get(name);
    if (!cache) {
      cache = new FakeCache();
      this.byName.set(name, cache);
    }
    return cache;
  }

  async keys(): Promise<string[]> {
    return [...this.byName.keys()];
  }

  async delete(name: string): Promise<boolean> {
    return this.byName.delete(name);
  }
}

function makeDeps(fetchImpl?: (request: Request) => Promise<Response>) {
  const storage = new FakeCacheStorage();
  const fetch = vi.fn(
    fetchImpl ??
      (async (request: Request) => new Response(`network ${pathOf(request)}`)),
  );
  const deps: SwDeps = {
    caches: storage as unknown as CacheStorage,
    fetch,
  };
  return { storage, fetch, deps };
}

function request(
  path: string,
  init: RequestInit & { navigate?: boolean } = {},
) {
  const url = path.startsWith("http") ? path : `${ORIGIN}${path}`;
  const req = new Request(url, init);
  // Node's `Request` cannot be constructed with `mode: "navigate"`, which is
  // exactly what a browser sets on a page load; the routing reads the field.
  return init.navigate
    ? (Object.defineProperty(req, "mode", { value: "navigate" }) as Request)
    : req;
}

describe("precacheShell", () => {
  it("stores every shell file in this build's own cache", async () => {
    const { storage, deps } = makeDeps();
    await precacheShell(deps, VERSION, SHELL);
    const cache = storage.byName.get(shellCacheName(VERSION));
    expect([...(cache?.entries.keys() ?? [])]).toEqual(SHELL);
  });
});

describe("deleteStaleShellCaches", () => {
  it("drops earlier builds' shell caches and nothing else", async () => {
    const { storage, deps } = makeDeps();
    await storage.open(shellCacheName("v1"));
    await storage.open(shellCacheName(VERSION));
    await storage.open("someone-elses-cache");

    await deleteStaleShellCaches(deps, VERSION);

    expect([...storage.byName.keys()].sort()).toEqual(
      [shellCacheName(VERSION), "someone-elses-cache"].sort(),
    );
  });
});

describe("handleFetch", () => {
  it.each([
    ["/api/v1/aircraft", {}],
    ["/api/internal/config", { method: "POST", body: "{}" }],
    ["/api/v1/ws/live", {}],
    ["/ws/live", {}],
    ["https://tiles.openfreemap.org/planet/5/16/11.pbf", {}],
    ["https://tile.openstreetmap.org/5/16/11.png", {}],
    ["/maplibre-gl-worker.mjs", {}],
  ])("does not answer %s at all", async (path, init) => {
    const { storage, fetch, deps } = makeDeps();
    await precacheShell(deps, VERSION, SHELL);

    expect(handleFetch(request(path, init), context, deps, VERSION)).toBeNull();
    expect(fetch).not.toHaveBeenCalled();
    // Nothing new was written anywhere.
    expect(storage.byName.get(shellCacheName(VERSION))?.entries.size).toBe(
      SHELL.length,
    );
  });

  it("serves a shell file from the cache without the network", async () => {
    const { fetch, deps } = makeDeps();
    await precacheShell(deps, VERSION, SHELL);

    const response = await handleFetch(
      request("/assets/index-abc123.js"),
      context,
      deps,
      VERSION,
    );
    expect(await response?.text()).toBe("cached /assets/index-abc123.js");
    expect(fetch).not.toHaveBeenCalled();
  });

  it("falls back to the network for a shell file the cache has lost", async () => {
    const { fetch, deps } = makeDeps();
    const response = await handleFetch(
      request("/assets/index-abc123.js"),
      context,
      deps,
      VERSION,
    );
    expect(await response?.text()).toBe("network /assets/index-abc123.js");
    expect(fetch).toHaveBeenCalledOnce();
  });

  it("loads pages from the network first and never caches them", async () => {
    const { storage, deps } = makeDeps();
    await precacheShell(deps, VERSION, SHELL);

    const response = await handleFetch(
      request("/aircraft/abc123", { navigate: true }),
      context,
      deps,
      VERSION,
    );
    expect(await response?.text()).toBe("network /aircraft/abc123");
    expect(
      storage.byName
        .get(shellCacheName(VERSION))
        ?.entries.has("/aircraft/abc123"),
    ).toBe(false);
  });

  it("falls back to the precached index.html when a page load fails offline", async () => {
    const { deps } = makeDeps(async () => {
      throw new TypeError("Failed to fetch");
    });
    await precacheShell(deps, VERSION, SHELL);

    const response = await handleFetch(
      request("/settings", { navigate: true }),
      context,
      deps,
      VERSION,
    );
    expect(await response?.text()).toBe("cached /index.html");
  });

  it("surfaces the network error when offline with nothing precached", async () => {
    const { deps } = makeDeps(async () => {
      throw new TypeError("Failed to fetch");
    });
    await expect(
      handleFetch(request("/", { navigate: true }), context, deps, VERSION),
    ).rejects.toThrow("Failed to fetch");
  });
});

describe("isSkipWaitingMessage", () => {
  it("recognises only the skip-waiting message", () => {
    expect(isSkipWaitingMessage(SKIP_WAITING_MESSAGE)).toBe(true);
    expect(isSkipWaitingMessage({ type: "SKIP_WAITING" })).toBe(true);
    expect(isSkipWaitingMessage({ type: "OTHER" })).toBe(false);
    expect(isSkipWaitingMessage("SKIP_WAITING")).toBe(false);
    expect(isSkipWaitingMessage(null)).toBe(false);
  });
});
