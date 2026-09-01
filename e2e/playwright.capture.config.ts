import { defineConfig, devices } from "@playwright/test";

import { CAPTURE_BASE_URL } from "./visual/support/fixtureContract";

/**
 * Fixture capture configuration (roadmap slice 047).
 *
 * This config exists to RECORD the fixtures the visual suite later replays,
 * not to assert anything. It runs once, against a live demo stack on the
 * compose stack's published port (brought up by `scripts/visual-capture.mjs`;
 * see `stackContract.ts`), and writes `visual/fixtures/` — an HTTP archive of
 * every `/api` response the five target views ask for, one frozen WebSocket
 * snapshot, and a manifest recording what was captured and when.
 *
 * Kept separate from `playwright.visual.config.ts` so the two never run
 * together: capture needs a backend and a network, and the visual suite
 * needs neither. The visual config's `testMatch` only picks up
 * `*.visual.spec.ts`, so `visual/capture/capture.spec.ts` is invisible to it.
 *
 * Capture runs on the host (it only makes HTTP requests and reads JSON — no
 * screenshots), so it does not need the pinned container.
 */

export default defineConfig({
  testDir: "./visual/capture",
  testMatch: "**/capture.spec.ts",
  // Rewrites the recorded origins to the one the visual suite replays
  // against. Must be a teardown, not part of the spec: Playwright only
  // flushes the HAR to disk once the browser context closes.
  globalTeardown: "./visual/capture/rewriteHar.ts",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  outputDir: "./test-results-capture",
  reporter: [["list"]],

  use: {
    baseURL: CAPTURE_BASE_URL,
    // Same geometry as the visual suite: the Live Map's airports overlay
    // derives its `bbox` query parameter from the map's rendered bounds, so
    // capturing at a different viewport than replay would record a URL the
    // replay never requests.
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    locale: "en-US",
    timezoneId: "UTC",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  // Capture waits on the demo scenario populating a live picture and on
  // every panel's query resolving across five views; a cold stack makes
  // that legitimately slow.
  timeout: 180_000,
  expect: { timeout: 30_000 },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } },
    },
  ],
});
