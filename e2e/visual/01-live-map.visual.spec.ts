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
import { VISUAL_THEMES } from "./support/stabilize";
import { expect, expectNoLoadFailures, openView, test } from "./support/replay";

/**
 * Hides the WebGL canvas — and nothing else — before the shot.
 *
 * The canvas is the one region whose pixels come from a GL rasterizer rather
 * than from the DOM: icon atlas packing, label collision and antialiasing
 * along every symbol edge depend on the renderer's own scheduling, and
 * headless Chromium's SwiftShader path guarantees nothing byte-identical
 * across runs even inside the same image. A baseline over that region would
 * fail intermittently, and this slice's bar is that a flaky screenshot is
 * worse than none.
 *
 * Hiding it in CSS rather than using `toHaveScreenshot`'s `mask` option is
 * the difference between a useful baseline and a useless one. `mask` paints
 * an opaque box over the element's bounding box at capture time, and the
 * canvas's box is the whole map area — so the mask also swallows everything
 * drawn *over* the map: the connection chip, the aircraft count, the Today,
 * Activity and Interesting panels, the filter chips, the radius indicator.
 * Those overlays are the most valuable thing on this view and the most
 * likely to be disturbed by a styling change. `visibility: hidden` removes
 * the canvas's pixels while preserving its layout box, so the overlays stay
 * exactly where they are and stay in the picture.
 *
 * What is given up is small: the canvas draws locally-generated GeoJSON that
 * the flow suite already asserts on (`03-live-map.spec.ts` checks the
 * aircraft layer paints; `04-aircraft-selection-detail.spec.ts` clicks a
 * projected aircraft), and icon selection and declutter have unit tests.
 */
async function hideMapCanvas(page: Parameters<typeof browserHasWebGl>[0]) {
  await page.addStyleTag({
    content:
      '[data-testid="maplibre-container"] canvas { visibility: hidden !important; }',
  });
}

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
