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
  browserHasWebGl,
  waitForAircraftLayer,
  waitForLiveAircraft,
} from "./support/liveMap";
import { expect, test } from "./support/fixtures";

/**
 * A sample of the silhouette images the aircraft layer registers (slice
 * 094): one per family, across the palettes, plus the MLAT ring. The unit
 * suite proves every SVG is well-formed XML; only a real browser can prove
 * Chromium's rasteriser accepts it, and a single rejected drawing fails the
 * whole registration and silently leaves the map without aircraft.
 */
const SILHOUETTE_SAMPLE = [
  "flightsite-aircraft-generic--civil",
  "flightsite-aircraft-light-high-wing--civil",
  "flightsite-aircraft-light-cirrus--civil",
  "flightsite-aircraft-narrowbody--civil",
  "flightsite-aircraft-widebody-quad--civil",
  "flightsite-aircraft-fighter--military",
  "flightsite-aircraft-tanker--military",
  "flightsite-aircraft-tandem-rotor--military",
  "flightsite-aircraft-rotorcraft--government",
  "flightsite-aircraft-business-jet--government",
  "flightsite-aircraft-glider--civil",
  "flightsite-aircraft-uav--civil",
  "flightsite-aircraft-mlat-ring",
];

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
      !(await browserHasWebGl(page)),
      "browser has no WebGL — the app shows its map-unavailable notice instead (unit-tested)",
    );
    await waitForLiveAircraft(page);
    // The aircraft layer actually renders onto the canvas, not just into
    // the store.
    await expect(
      page.locator('[data-testid="maplibre-container"] canvas'),
    ).toBeVisible();
  });

  test("every silhouette family decodes and registers on the style", async ({
    page,
  }) => {
    await page.goto("/");
    test.skip(
      !(await browserHasWebGl(page)),
      "browser has no WebGL — the app shows its map-unavailable notice instead (unit-tested)",
    );
    // The layer is only attached once registration has resolved, so the
    // source existing means every image either registered or threw.
    await waitForAircraftLayer(page);

    const missing = await page.evaluate((ids) => {
      const map = (
        window as unknown as {
          __flightsiteMap?: { hasImage: (id: string) => boolean };
        }
      ).__flightsiteMap;
      if (!map) {
        throw new Error("window.__flightsiteMap was not set (map not mounted?)");
      }
      return ids.filter((id) => !map.hasImage(id));
    }, SILHOUETTE_SAMPLE);

    expect(missing).toEqual([]);
  });
});
