import { defineConfig, devices } from "@playwright/test";

/**
 * FlightSite E2E configuration (roadmap slice 020).
 *
 * The stack is NOT started by Playwright: `webServer` is deliberately
 * unused. FlightSite runs as a Docker Compose stack (backend + nginx
 * frontend), not a single dev server process, and each browser project
 * needs its own fresh compose cycle so the first-run flow means what it
 * says (see scripts/stack.mjs and scripts/run-suite.mjs). `npm run e2e`
 * (chromium) / `e2e:firefox` / `e2e:webkit` each bring their own stack up
 * before invoking `playwright test --project=<browser>` and tear it down
 * after, win or lose.
 *
 * `workers: 1` and `fullyParallel: false` are load-bearing, not a
 * performance default: the four spec files encode one continuous story
 * against ONE shared backend — 01 completes first-run setup, 02 exercises
 * the decoder connection test against the now-configured install, 03 and 04
 * assume setup is already done. Spec files are numbered so a single worker
 * runs them in that exact order (Playwright enumerates test files in
 * directory order).
 */
// scripts/run-suite.mjs sets FLIGHTSITE_E2E_PROJECT to the browser project
// name before invoking Playwright. CI (e2e.yml) runs all three projects
// sequentially via three separate `run-suite.mjs` invocations in the SAME
// job — without a per-project output dir, each later run's `test-results`/
// `playwright-report` would silently overwrite an earlier failing run's
// (e.g. Firefox's traces surviving but Chromium's failure evidence lost).
// Suffixing is CI-only: a local `npm run e2e` still lands in the plain
// `test-results/`/`playwright-report/` `npm run report` (and everyone's
// muscle memory) expects, since a local run is almost always one browser
// at a time, viewed immediately.
const project = process.env.FLIGHTSITE_E2E_PROJECT;
const outputSuffix = process.env.CI && project ? `-${project}` : "";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  outputDir: `./test-results${outputSuffix}`,
  reporter: process.env.CI
    ? [["github"], ["html", { open: "never", outputFolder: `playwright-report${outputSuffix}` }]]
    : [["list"], ["html", { open: "never", outputFolder: `playwright-report${outputSuffix}` }]],

  use: {
    // 127.0.0.1, not localhost: on Linux CI runners Firefox resolves localhost
    // to ::1 while Docker publishes the compose port on IPv4 only, which made
    // every Firefox test fail at its first assertion (page never loaded).
    baseURL: "http://127.0.0.1:8080",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  // Flows that wait on the demo scenario populating the live picture and on
  // WebSocket delivery can legitimately take longer than Playwright's 30s
  // per-test default, especially on a cold container start.
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
    },
  ],
});
