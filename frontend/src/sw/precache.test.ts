import { describe, expect, it } from "vitest";

import { selectShellFiles } from "@/sw/precache";

describe("selectShellFiles", () => {
  it("keeps index.html, hashed assets, icons, manifest and favicon, sorted", () => {
    expect(
      selectShellFiles([
        "manifest.webmanifest",
        "index.html",
        "assets/index-abc123.js",
        "assets/index-def456.css",
        "assets/inter-latin-400-normal-a1b2.woff2",
        "icons/icon-512.png",
        "favicon.svg",
      ]),
    ).toEqual([
      "/assets/index-abc123.js",
      "/assets/index-def456.css",
      "/assets/inter-latin-400-normal-a1b2.woff2",
      "/favicon.svg",
      "/icons/icon-512.png",
      "/index.html",
      "/manifest.webmanifest",
    ]);
  });

  it("leaves out the worker itself, the MapLibre worker scripts and source maps", () => {
    expect(
      selectShellFiles([
        "sw.js",
        "maplibre-gl-worker.mjs",
        "maplibre-gl-shared.mjs",
        "assets/index-abc123.js.map",
        "robots.txt",
        "nested/index.html",
      ]),
    ).toEqual([]);
  });
});
