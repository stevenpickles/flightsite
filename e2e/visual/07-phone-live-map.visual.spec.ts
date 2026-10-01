/**
 * Phone Live Map baselines (roadmap slice 084, issue #227).
 *
 * What these lock: the layout below 768 px — the top-left connection chip,
 * quick-filter chips and recentre button, and the bottom dock that replaces
 * the desktop's floating cards (the five-button toolbar, one sheet at a time,
 * the notification pill above it). The collapsed shot proves nothing
 * overlaps and the map keeps the viewport; the Today shot locks one open
 * sheet above the toolbar. The canvas is hidden exactly as on desktop
 * (`support/mapCanvas.ts`).
 */

import { browserHasWebGl } from "../tests/support/liveMap";
import { hideMapCanvas } from "./support/mapCanvas";
import { VISUAL_THEMES } from "./support/stabilize";
import { expect, expectNoLoadFailures, openView, test } from "./support/replay";

/** iPhone 12-15 class portrait viewport, the roadmap's 390 x 844 target. */
const PHONE_VIEWPORT = { width: 390, height: 844 };

for (const theme of VISUAL_THEMES) {
  test(`live map phone — ${theme}`, async ({ page }) => {
    await page.setViewportSize(PHONE_VIEWPORT);
    await openView(page, "/", theme);
    test.skip(
      !(await browserHasWebGl(page)),
      "browser has no WebGL — the app renders its map-unavailable notice, not the map",
    );

    await expect(page.locator('[role="status"][data-status]')).toHaveAttribute(
      "data-status",
      "live",
    );
    await expect(page.getByTestId("live-aircraft-count")).toHaveText(
      /[1-9]\d* aircraft/,
    );
    await expect(page.getByTestId("phone-map-toolbar")).toBeVisible();

    await expectNoLoadFailures(page);
    await hideMapCanvas(page);
    await expect(page).toHaveScreenshot(`live-map-phone-${theme}.png`);

    // One sheet open above the toolbar. The Today card's summary badge only
    // renders once the analytics replay has answered, so it doubles as the
    // proof the HTTP fixtures reached this view.
    await page
      .getByTestId("phone-map-toolbar")
      .getByRole("button", { name: "Today" })
      .click();
    await expect(page.getByTestId("today-sightings-badge")).toBeVisible();
    await expect(page).toHaveScreenshot(`live-map-phone-today-${theme}.png`);
  });
}
