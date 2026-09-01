import { defineConfig, devices } from "@playwright/test";

// Origin and port the suite serves the built SPA on. Fixed, not
// configurable: the committed HAR's entry URLs carry this exact origin
// (written there by `visual/capture/rewriteHar.ts`) and Playwright's HAR
// router matches on full URL, so replaying against any other origin would
// match nothing and screenshot a wall of "Failed to fetch" cards.
import { VISUAL_BASE_URL, VISUAL_PORT } from "./visual/support/fixtureContract";

/**
 * FlightSite visual regression configuration (roadmap slice 047, SPEC §83,
 * `docs/TEST_STRATEGY.md` §5).
 *
 * Deliberately a SEPARATE config from `playwright.config.ts` rather than an
 * extra project inside it. The flow suite's four spec files encode one
 * continuous story against one shared, live Docker Compose backend, ordered
 * by filename under `workers: 1`; folding screenshots into that run would
 * couple baseline stability to first-run wizard state and to whatever tick
 * the demo scenario happened to reach. The visual suite has the opposite
 * requirement — nothing live at all — so it gets its own config, its own
 * `testDir`, and its own output directories.
 *
 * What this suite runs against: the built frontend served by `vite preview`,
 * with every `/api/v1` response replayed from a checked-in HAR and the live
 * WebSocket replaced by a frozen snapshot (see `visual/support/`). There is
 * no backend and no compose stack in a visual run — that is the point.
 * Fixtures are captured once from a seeded demo stack (`npm run
 * visual:capture`) and committed, so a screenshot only changes when the UI
 * changes.
 *
 * Chromium only. Baselines are per-browser, and the other two engines cannot
 * pay for the baselines they would add: CI Firefox has no WebGL, so MapLibre
 * never renders there at all (`browserHasWebGl` in `tests/support/liveMap.ts`),
 * and WebKit's software GL path renders the same canvas differently again.
 * Cross-browser correctness is the flow suite's job (it runs all three);
 * this suite's job is catching unintended visual change, which one engine
 * does as well as three at a third of the baselines to review.
 */


export default defineConfig({
  testDir: "./visual",
  // Only the screenshot specs. `visual/capture/capture.spec.ts` lives under
  // the same directory but belongs to `playwright.capture.config.ts`: it
  // needs a live backend, which is the one thing a visual run must not have.
  testMatch: "**/*.visual.spec.ts",
  // Refuses to run off the pinned container, and fails fast with a pointer
  // to `visual:capture` if the fixture set is missing.
  globalSetup: "./visual/support/globalSetup.ts",
  fullyParallel: false,
  // Screenshot comparison is sensitive to renderer contention: parallel
  // workers sharing one GPU/CPU produce occasional off-by-a-few-pixels
  // text rasterization. Serial is slower and boring, which is what a
  // baseline suite should be.
  workers: 1,
  forbidOnly: !!process.env.CI,
  // No retries, on purpose. A screenshot that passes on retry is a flaky
  // baseline, and a flaky baseline is worse than no baseline — it trains
  // reviewers to re-run instead of to look. Failures here should be
  // reproducible or fixed.
  retries: 0,
  outputDir: "./test-results-visual",

  // Baselines live next to the specs, addressed only by test name — no
  // `-{platform}` / `-{projectName}` suffix. Playwright's default template
  // includes the platform, which sounds safer but is the opposite here: a
  // developer running this on Windows would not find the Linux baselines,
  // so Playwright would silently WRITE a fresh `-win32` set and report
  // green. `assertPinnedRenderer()` (visual/support/stabilize.ts) refuses to
  // run outside the pinned Linux container instead, so one committed set of
  // baselines is the only set that exists.
  snapshotPathTemplate: "{testDir}/__screenshots__/{arg}{ext}",

  reporter: process.env.CI
    ? [["github"], ["html", { open: "never", outputFolder: "playwright-report-visual" }]]
    : [["list"], ["html", { open: "never", outputFolder: "playwright-report-visual" }]],

  use: {
    baseURL: VISUAL_BASE_URL,
    trace: "retain-on-failure",
    // Video/screenshot-on-failure are off: `toHaveScreenshot` already
    // writes actual/expected/diff PNGs for every failure, which is the
    // artifact a reviewer wants. Video of a static page is noise.
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
    // Locale and timezone are visual inputs — dates, numbers and the
    // UTC-vs-local rendering of every timestamp depend on them. Pinning
    // both here means a developer's machine settings cannot move a
    // baseline (SPEC: timestamps are UTC in storage and APIs).
    locale: "en-US",
    timezoneId: "UTC",
  },

  timeout: 60_000,
  expect: {
    timeout: 10_000,
    toHaveScreenshot: {
      // Playwright's own animation freeze, belt-and-braces with the
      // stylesheet injected in `stabilize.ts`: this one also finishes
      // in-flight CSS transitions and rewinds infinite ones, which a
      // stylesheet alone cannot do for animations already running.
      animations: "disabled",
      caret: "hide",
      // Compare in CSS pixels so a change in device scale factor cannot
      // silently rescale every baseline.
      scale: "css",
      // Anti-aliasing of text and of the ECharts canvas can differ by a
      // hair between otherwise identical runs of the same container. A
      // small ratio absorbs that without hiding real change: a genuine UI
      // edit moves far more than 0.2% of a 1440x900 viewport, while
      // sub-pixel noise moves far less.
      maxDiffPixelRatio: 0.002,
    },
  },

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Fixed viewport and scale factor: both are direct screenshot
        // dimensions. `devices["Desktop Chrome"]` already pins these, but
        // stating them makes the baseline geometry explicit at the place
        // someone will look when a diff is "everything moved".
        viewport: { width: 1440, height: 900 },
        deviceScaleFactor: 1,
      },
    },
  ],

  // Unlike the flow suite, this one CAN use `webServer`: with no backend in
  // the picture there is only a static bundle to serve, so Playwright's own
  // lifecycle is enough. `scripts/visual.mjs` builds `frontend/dist` before
  // invoking Playwright; `vite preview` serves it with SPA fallback so deep
  // links like /analytics resolve.
  webServer: {
    command: `npm run preview -- --port ${VISUAL_PORT} --strictPort --host 127.0.0.1`,
    cwd: "../frontend",
    url: VISUAL_BASE_URL,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
