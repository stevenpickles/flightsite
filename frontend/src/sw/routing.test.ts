import { describe, expect, it } from "vitest";

import { routeRequest, type RoutableRequest } from "@/sw/routing";

const ORIGIN = "https://flightsite.local";
const context = {
  origin: ORIGIN,
  shellPaths: new Set([
    "/index.html",
    "/assets/index-abc123.js",
    "/assets/index-def456.css",
    "/assets/inter-latin-400.woff2",
    "/icons/icon-192.png",
    "/manifest.webmanifest",
  ]),
};

function get(url: string, mode = "cors"): RoutableRequest {
  return { url, method: "GET", mode };
}

describe("routeRequest", () => {
  describe("never intercepts live data", () => {
    it.each([
      `${ORIGIN}/api/v1/aircraft`,
      `${ORIGIN}/api/internal/config`,
      `${ORIGIN}/api/v1/analytics/summary?preset=today`,
      `${ORIGIN}/api`,
    ])("passes %s through", (url) => {
      expect(routeRequest(get(url), context)).toBe("passthrough");
    });

    it("passes the live WebSocket handshake through", () => {
      expect(
        routeRequest(get(`${ORIGIN}/api/v1/ws/live`, "websocket"), context),
      ).toBe("passthrough");
      expect(routeRequest(get(`${ORIGIN}/ws/live`), context)).toBe(
        "passthrough",
      );
      expect(routeRequest(get(`${ORIGIN}/ws`), context)).toBe("passthrough");
    });

    it("passes a page navigation into the API through rather than serving the shell", () => {
      expect(
        routeRequest(get(`${ORIGIN}/api/v1/docs`, "navigate"), context),
      ).toBe("passthrough");
    });

    it("passes an API path through even if it were ever listed as shell", () => {
      const poisoned = {
        origin: ORIGIN,
        shellPaths: new Set(["/api/v1/aircraft"]),
      };
      expect(routeRequest(get(`${ORIGIN}/api/v1/aircraft`), poisoned)).toBe(
        "passthrough",
      );
    });
  });

  describe("never intercepts cross-origin requests", () => {
    it.each([
      "https://tiles.openfreemap.org/planet/20250101/5/16/11.pbf",
      "https://tiles.openfreemap.org/styles/liberty",
      "https://tile.openstreetmap.org/5/16/11.png",
      "https://tiles.openfreemap.org/fonts/Noto%20Sans%20Regular/0-255.pbf",
      // Same path as a shell file, different origin.
      "https://cdn.example.com/assets/index-abc123.js",
    ])("passes %s through", (url) => {
      expect(routeRequest(get(url), context)).toBe("passthrough");
    });

    it("passes a cross-origin navigation through", () => {
      expect(
        routeRequest(
          get("https://globe.adsbexchange.com/", "navigate"),
          context,
        ),
      ).toBe("passthrough");
    });
  });

  it("passes every non-GET request through", () => {
    for (const method of ["POST", "PUT", "PATCH", "DELETE", "HEAD"]) {
      expect(
        routeRequest(
          { url: `${ORIGIN}/assets/index-abc123.js`, method, mode: "cors" },
          context,
        ),
      ).toBe("passthrough");
    }
  });

  it("serves the precached shell files", () => {
    for (const path of context.shellPaths) {
      expect(routeRequest(get(`${ORIGIN}${path}`), context)).toBe("shell");
    }
    // A query string does not change which file a path names.
    expect(
      routeRequest(get(`${ORIGIN}/assets/index-abc123.js?v=1`), context),
    ).toBe("shell");
  });

  it("routes same-origin page loads to the network-first navigation strategy", () => {
    for (const path of ["/", "/aircraft/abc123", "/settings", "/index.html"]) {
      expect(routeRequest(get(`${ORIGIN}${path}`, "navigate"), context)).toBe(
        "navigation",
      );
    }
  });

  it("passes same-origin files the build did not list through", () => {
    for (const path of [
      "/maplibre-gl-worker.mjs",
      "/maplibre-gl-shared.mjs",
      "/sw.js",
      "/assets/index-old999.js",
      "/robots.txt",
    ]) {
      expect(routeRequest(get(`${ORIGIN}${path}`), context)).toBe(
        "passthrough",
      );
    }
  });

  it("passes an unparseable URL through", () => {
    expect(routeRequest(get("not a url"), context)).toBe("passthrough");
  });
});
