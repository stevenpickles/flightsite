/**
 * The Live Map canvas mask shared by the desktop and phone Live Map
 * baselines (moved here from `01-live-map.visual.spec.ts` in roadmap slice
 * 084 so both specs hide exactly the same things).
 */

import type { Page } from "@playwright/test";

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
export async function hideMapCanvas(page: Page): Promise<void> {
  await page.addStyleTag({
    content: [
      '[data-testid="maplibre-container"] canvas { visibility: hidden !important; }',
      // The replay aborts every tile request (support/replay.ts), and since
      // slice 076 (R1-05) the map keeps its "Basemap unavailable" notice up
      // while that is true. Whether the first tile failure has landed by the
      // time the frames above are asserted differs between renderers and
      // runs, so the notice is masked like the canvas: it is a consequence
      // of the suite's own tile blocking, not a state of the view under
      // test, and its wording has a unit test of its own.
      '[data-testid="map-degraded-notice"] { visibility: hidden !important; }',
    ].join("\n"),
  });
}
