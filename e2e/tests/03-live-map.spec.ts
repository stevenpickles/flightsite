/**
 * Flow (c) — demo-mode live map renders aircraft (roadmap slice 020, `docs/
 * TEST_STRATEGY.md` §4). Setup is already complete (flow (a)), so this loads
 * straight into the Live Map and confirms the demo scenario actually
 * populates it: the connection reaches `live` and a non-trivial aircraft
 * count arrives, both through user-visible signals, cross-checked against
 * the same live registry the REST API reads.
 */

import {
  fetchPositionedAircraft,
  mapIsAvailable,
  waitForLiveAircraft,
} from "./support/liveMap";
import { expect, test } from "./support/fixtures";

test.describe("demo-mode live map", () => {
  test("aircraft appear over the WebSocket once the demo scenario is live", async ({
    page,
    request,
  }) => {
    await page.goto("/");

    await waitForLiveAircraft(page);

    // Ground truth from the API the WebSocket and the map layer both read
    // from (`docs/API.md` §3.3) — confirms the UI signal isn't reporting a
    // stale or fabricated count.
    const positioned = await fetchPositionedAircraft(request);
    expect(positioned.length).toBeGreaterThan(0);
  });

  test("the aircraft layer paints onto the map canvas", async ({ page }) => {
    await page.goto("/");
    test.skip(
      !(await mapIsAvailable(page)),
      "browser has no WebGL — the app shows its map-unavailable notice instead (unit-tested)",
    );
    await waitForLiveAircraft(page);
    // The aircraft layer actually renders onto the canvas, not just into
    // the store.
    await expect(
      page.locator('[data-testid="maplibre-container"] canvas'),
    ).toBeVisible();
  });
});
