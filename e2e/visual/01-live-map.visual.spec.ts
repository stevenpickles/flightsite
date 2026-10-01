/**
 * Live Map baselines (roadmap slice 047, SPEC §83).
 *
 * What these lock: the app shell, the Live Map's overlay chrome, and every
 * side panel fed by the frozen live picture — the connection chip and its
 * aircraft count, Today at a glance, Activity, Interesting, the filter
 * chips, the radius indicator and the map's own controls and attribution.
 *
 * What they deliberately do NOT lock: the pixels inside the MapLibre canvas
 * (see `mapCanvasMask`).
 */

import { browserHasWebGl } from "../tests/support/liveMap";
import { hideMapCanvas } from "./support/mapCanvas";
import { VISUAL_THEMES } from "./support/stabilize";
import { expect, expectNoLoadFailures, openView, test } from "./support/replay";

for (const theme of VISUAL_THEMES) {
  test(`live map — ${theme}`, async ({ page }) => {
    await openView(page, "/", theme);

    // The capability probe, not an app-behavior signal — the same guard the
    // flow suite uses (`tests/support/liveMap.ts`). Without WebGL the app
    // renders its `map-unsupported` notice instead of a canvas, so the
    // layout is a different view entirely and the canvas mask would match
    // nothing. Skipping is correct there; the degraded path is unit-tested.
    test.skip(
      !(await browserHasWebGl(page)),
      "browser has no WebGL — the app renders its map-unavailable notice, not the map",
    );

    // Assert the frozen picture actually arrived before photographing it.
    // These are the values from the committed snapshot, so if the fixture
    // set ever stops covering this view the spec fails on a readable
    // assertion rather than quietly baselining an empty map.
    await expect(page.locator('[role="status"][data-status]')).toHaveAttribute(
      "data-status",
      "live",
    );
    await expect(page.getByTestId("live-aircraft-count")).toHaveText(
      /[1-9]\d* aircraft/,
    );
    await expect(page.getByTestId("today-panel")).toBeVisible();
    await expect(page.getByTestId("activity-panel")).toBeVisible();
    await expect(page.getByTestId("interesting-panel")).toBeVisible();
    // The panels above render whether or not their queries resolve. This
    // badge does not — it only appears once the analytics summary response
    // has arrived — so it is what actually proves the HTTP replay reached
    // this view, as opposed to only the WebSocket stub having worked.
    await expect(page.getByTestId("today-sightings-badge")).toBeVisible();

    await expectNoLoadFailures(page);
    await hideMapCanvas(page);

    await expect(page).toHaveScreenshot(`live-map-${theme}.png`);
  });
}
