/**
 * Fixture capture for the visual regression suite (roadmap slice 047).
 *
 * NOT a test — it asserts only enough to refuse to write a fixture set that
 * would produce useless screenshots. Run it via `npm run visual:capture`,
 * which brings up a fresh seeded demo stack first (`scripts/stack.mjs`) and
 * tears it down after.
 *
 * What it produces, all under `visual/fixtures/`:
 *
 *   api.har           every `/api/v1` and `/api/internal` response the five
 *                     target views request, recorded by Playwright's own HAR
 *                     recorder
 *   live-snapshot.json the first `snapshot` frame from `/api/v1/ws/live`
 *   manifest.json     what was captured, from which seed, and the instant the
 *                     replayed clock must be frozen at
 *
 * Why record rather than hand-author the fixtures: the visual suite has to
 * screenshot views that are fully populated, and the shape of "populated"
 * here spans ~40 endpoints across two API surfaces with non-trivial nested
 * types. Hand-written stubs would drift from the real responses silently —
 * a mistyped field renders an empty card, and the baseline happily locks in
 * the empty card. Recording from the real seeded demo backend means the
 * fixtures are true by construction, and re-recording is one command when
 * the API changes.
 *
 * Why the recording is stable enough to commit: demo mode is a pure function
 * of `(seed, tick)` with a pinned scenario epoch
 * (`backend/src/flightsite/demo/scenario.py`), so what gets recorded is a
 * genuine demo picture rather than an arbitrary one. It is nonetheless a
 * point-in-time recording — the committed file, not the generator, is what
 * the baselines are pinned to.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

import {
  ANALYTICS_PRESET,
  ALERT_TAB_IDS,
  FIXTURE_DIR_NAME,
  HAR_FILE_NAME,
  LIVE_SNAPSHOT_FILE_NAME,
  MANIFEST_FILE_NAME,
  RECEIVER_LAT,
  RECEIVER_LON,
  SITE_NAME,
  type FixtureManifest,
} from "../support/fixtureContract";

const here = path.dirname(fileURLToPath(import.meta.url));
const fixtureDir = path.resolve(here, "..", FIXTURE_DIR_NAME);

/** Path of the live socket — mirrors `LIVE_WS_PATH` in
 * `frontend/src/lib/ws/protocol.ts`. */
const LIVE_WS_PATH = "/api/v1/ws/live";

interface CapturedSnapshot {
  seq: number;
  ts: string;
  data: { aircraft: unknown[]; receiver: unknown };
}

/**
 * Waits until a view has finished asking for things.
 *
 * This is the difference between a usable fixture set and a broken one. The
 * HAR is flushed when the browser context closes, and a request still in
 * flight at that moment is written with status -1 — an entry the replay
 * router will happily match and then serve as a failed response, so the
 * card that needed it renders its error state in the baseline. Navigating
 * on a heading being visible is not enough: every one of these pages paints
 * its headings immediately and fills the cards in later.
 *
 * Two conditions, because neither alone is sufficient. Every loading state
 * in the app is a plain "Loading…"-prefixed paragraph (there are no
 * skeletons or spinners), so their absence means each mounted query has
 * resolved — but a query that resolves into an empty card leaves no trace,
 * hence also waiting for the network to fall quiet. `networkidle` is the
 * wrong tool in a normal test and the right one here: this file's whole job
 * is to observe traffic.
 */
async function settle(
  page: import("@playwright/test").Page,
  { networkIdle = true }: { networkIdle?: boolean } = {},
): Promise<void> {
  await expect(page.getByText(/^Loading/)).toHaveCount(0, { timeout: 60_000 });
  if (networkIdle) {
    // Skipped on the Live Map: its WebSocket is open for the life of the
    // page and the airports overlay refetches on every debounced viewport
    // change, so "no connections for 500 ms" is not a state that view
    // reaches. Its own explicit waits cover it instead.
    await page.waitForLoadState("networkidle", { timeout: 60_000 });
  }
}

test("capture visual fixtures from a seeded demo stack", async ({
  page,
  request,
}) => {
  mkdirSync(fixtureDir, { recursive: true });

  // ---------------------------------------------------------------------
  // 1. Complete first-run setup.
  //
  // `stack.mjs` always creates a fresh data directory, so the stack is in
  // first-run state and `RootLayout` would redirect every route to /setup.
  // Driving the eight-step wizard through the UI is flow (a)'s job in the
  // E2E suite; here the same end state is reached by writing the config
  // directly, which is faster and cannot fail for wizard-layout reasons.
  //
  // The location must match the demo roster's center: the roster is built
  // once at process startup around `DEFAULT_CENTER`
  // (`backend/src/flightsite/demo/adapter.py`) and does NOT recenter when
  // the config later names a different site, so any other coordinates would
  // put the map somewhere the traffic isn't.
  // ---------------------------------------------------------------------
  const configResponse = await request.put("/api/internal/config", {
    data: {
      location: {
        latitude: RECEIVER_LAT,
        longitude: RECEIVER_LON,
        site_name: SITE_NAME,
      },
      units: "aviation",
      timezone: "UTC",
    },
  });
  expect(
    configResponse.ok(),
    `PUT /api/internal/config failed: ${configResponse.status()}`,
  ).toBeTruthy();

  // ---------------------------------------------------------------------
  // 2. Arm the recorders before the first navigation.
  // ---------------------------------------------------------------------
  const harPath = path.join(fixtureDir, HAR_FILE_NAME);
  await page.routeFromHAR(harPath, {
    url: "**/api/**",
    update: true,
    updateContent: "embed",
  });

  // The HAR recorder does not capture WebSocket traffic, so the live
  // picture is captured separately: the first `snapshot` frame is the
  // complete live state (`docs/API.md` §4.2), which is exactly what the
  // replay stub needs to serve.
  let snapshot: CapturedSnapshot | null = null;
  page.on("websocket", (ws) => {
    if (!ws.url().includes(LIVE_WS_PATH)) {
      return;
    }
    ws.on("framereceived", (frame) => {
      if (snapshot) {
        return;
      }
      try {
        const parsed = JSON.parse(frame.payload as string) as CapturedSnapshot & {
          type?: string;
        };
        if (parsed.type === "snapshot") {
          snapshot = parsed;
        }
      } catch {
        // Non-JSON or binary frame — not the snapshot.
      }
    });
  });

  // Basemap tiles are blocked here exactly as the flow suite blocks them
  // (`tests/support/fixtures.ts`) and as the replay does: the recording
  // must not contain third-party tile responses, and the map's degraded
  // path is what the baselines lock.
  await page.route("https://tiles.openfreemap.org/**", (route) => route.abort());
  await page.route("https://tile.openstreetmap.org/**", (route) => route.abort());

  // ---------------------------------------------------------------------
  // 3. Live Map — wait for a genuinely populated live picture.
  // ---------------------------------------------------------------------
  await page.goto("/");
  await expect(page.locator('[role="status"][data-status]')).toHaveAttribute(
    "data-status",
    "live",
    { timeout: 60_000 },
  );
  await expect(page.getByTestId("live-aircraft-count")).toHaveText(
    /[1-9]\d* aircraft/,
    { timeout: 60_000 },
  );
  // The side panels each own a query; give them a beat to resolve so their
  // responses land in the HAR rather than being requested for the first
  // time during replay (where they would abort).
  await expect(page.getByTestId("today-panel")).toBeVisible();
  await expect(page.getByTestId("activity-panel")).toBeVisible();
  await expect(page.getByTestId("interesting-panel")).toBeVisible();
  await expect(page.getByTestId("today-sightings-badge")).toBeVisible();
  await settle(page, { networkIdle: false });

  expect(
    snapshot,
    "no `snapshot` frame arrived on /api/v1/ws/live — cannot capture the live picture",
  ).not.toBeNull();
  const captured = snapshot as CapturedSnapshot | null;
  expect(
    captured?.data?.aircraft?.length ?? 0,
    "the captured live snapshot contains no aircraft",
  ).toBeGreaterThan(0);

  // ---------------------------------------------------------------------
  // 4. Aircraft detail — pick one deterministically.
  //
  // Lowest ICAO among aircraft that have a callsign AND a position: sorting
  // by a stable key (rather than taking items[0]) means a re-capture picks
  // the same aircraft whenever that aircraft is still in the roster, which
  // keeps re-captured fixtures diffable. The callsign requirement just
  // makes the detail view show a name rather than a bare hex code.
  // ---------------------------------------------------------------------
  const currentResponse = await request.get(
    "/api/v1/aircraft/current?positioned=true",
  );
  expect(currentResponse.ok()).toBeTruthy();
  const current = (await currentResponse.json()) as {
    items: { icao: string; callsign: string | null; position: unknown }[];
  };
  const detailIcao = current.items
    .filter((item) => item.callsign && item.position)
    .map((item) => item.icao.toLowerCase())
    .sort()[0];
  expect(
    detailIcao,
    "no positioned aircraft with a callsign to use for the detail view",
  ).toBeTruthy();

  await page.goto(`/aircraft/${detailIcao}`);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  // `DetailSection` renders each section title as an <h3>. "History" is
  // `LifetimeSection`'s title (SPEC §53 lifetime records); "Recent
  // sightings" resolves only once its own paged query has returned, so
  // waiting on it is what keeps that request in the HAR.
  await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Recent sightings" }),
  ).toBeVisible();
  await settle(page);

  // ---------------------------------------------------------------------
  // 5. Analytics.
  //
  // Captured at the `t0` ("since first sighting") preset rather than the
  // default `today`. Demo sightings are stamped from the scenario epoch
  // (2026-01-01, `demo/scenario.py`) while the server computes `today`
  // against the real wall clock, so `today` is legitimately empty on a demo
  // stack — a baseline of eight "No data for this window." cards would lock
  // nothing worth locking. `t0` spans the epoch and renders populated
  // charts and tables, which is the view worth regression-testing.
  // ---------------------------------------------------------------------
  await page.goto(`/analytics?preset=${ANALYTICS_PRESET}`);
  await expect(page.getByRole("heading", { level: 1, name: "Analytics" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Top aircraft" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Never seen before" })).toBeVisible();
  await settle(page);

  // ---------------------------------------------------------------------
  // 6. Receiver.
  // ---------------------------------------------------------------------
  await page.goto("/receiver");
  await expect(page.getByRole("heading", { level: 1, name: "Receiver" })).toBeVisible();
  await expect(page.getByRole("group", { name: "Receiver scorecard" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Charts" })).toBeVisible();
  await settle(page);

  // ---------------------------------------------------------------------
  // 7. Alerts — every tab, because each mounts its own queries and an
  // unvisited tab's endpoints would be missing from the HAR.
  // ---------------------------------------------------------------------
  await page.goto("/alerts");
  await expect(page.getByRole("heading", { level: 1, name: "Alerts" })).toBeVisible();
  for (const tabId of ALERT_TAB_IDS) {
    await page.locator(`#alerts-tab-${tabId}`).click();
    await expect(page.locator(`#alerts-tabpanel-${tabId}`)).toBeVisible();
    await settle(page);
  }

  // ---------------------------------------------------------------------
  // 8. Write the non-HAR fixtures. The HAR itself is flushed when the
  // context closes, after this test body returns.
  // ---------------------------------------------------------------------
  writeFileSync(
    path.join(fixtureDir, LIVE_SNAPSHOT_FILE_NAME),
    `${JSON.stringify(captured, null, 2)}\n`,
    "utf8",
  );

  const manifest: FixtureManifest = {
    // Freeze the replayed clock at the instant of capture — the same
    // instant the backend used to compute every analytics window and
    // relative timestamp now sitting in the HAR. Any other value would put
    // the UI's idea of "now" out of step with the responses it renders.
    frozenClock: new Date().toISOString(),
    detailIcao: detailIcao!,
    analyticsPreset: ANALYTICS_PRESET,
    aircraftInSnapshot: captured?.data?.aircraft?.length ?? 0,
    note:
      "Generated by `npm run visual:capture` against a seeded demo stack. " +
      "Do not hand-edit: re-capture instead.",
  };
  writeFileSync(
    path.join(fixtureDir, MANIFEST_FILE_NAME),
    `${JSON.stringify(manifest, null, 2)}\n`,
    "utf8",
  );
});
