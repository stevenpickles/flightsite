/**
 * Alerts baselines (roadmap slice 047, SPEC §83).
 *
 * Two of the page's four tabs, in both themes — see
 * `ALERT_SCREENSHOT_TABS` in `support/fixtureContract.ts` for the choice.
 * `watchlists` is where the page opens and, on a fresh install, is the empty
 * state a user actually meets first. `history` is the only tab with
 * populated rows on demo data and carries the severity styling that SPEC
 * §80's non-color severity signaling depends on — the thing a contrast or
 * focus-visibility change is most likely to disturb.
 *
 * `rules` and `templates` are captured into the HAR but not photographed:
 * the roadmap's out-of-scope line for this slice is "pixel-perfect coverage
 * of every state", and adding either later needs a new spec, not a new
 * capture.
 */

import { ALERT_SCREENSHOT_TABS } from "./support/fixtureContract";
import {
  expect,
  expectFitsWithoutScrolling,
  expectNoLoadFailures,
  openView,
  test,
} from "./support/replay";
import { VISUAL_THEMES } from "./support/stabilize";

/** Covers the taller of the two photographed tabs (history) without
 * scrolling — see `expectFitsWithoutScrolling`. */
const VIEWPORT_HEIGHT = 700;

for (const theme of VISUAL_THEMES) {
  for (const tab of ALERT_SCREENSHOT_TABS) {
    test(`alerts (${tab}) — ${theme}`, async ({ page }) => {
      await openView(page, "/alerts", theme, VIEWPORT_HEIGHT);

      await expect(
        page.getByRole("heading", { level: 1, name: "Alerts" }),
      ).toBeVisible();

      // The tabs are client-side state, not routes, so the tab has to be
      // clicked rather than linked to. `watchlists` is already active on
      // load; clicking it anyway keeps the two cases on one path and
      // asserts the selected state either way.
      const trigger = page.locator(`#alerts-tab-${tab}`);
      await trigger.click();
      await expect(trigger).toHaveAttribute("aria-selected", "true");
      await expect(page.locator(`#alerts-tabpanel-${tab}`)).toBeVisible();
      await expect(page.getByText(/^Loading/)).toHaveCount(0);

      // Clicking leaves the trigger focused, and a focus ring is a visual
      // difference that has nothing to do with this baseline's subject —
      // it would also make every one of these screenshots need
      // regenerating for slice 048's focus-visibility work on top of the
      // changes that slice genuinely makes. Blur first so the shot shows
      // the tab's resting appearance.
      await trigger.blur();

      await expectNoLoadFailures(page);
      await expectFitsWithoutScrolling(page);

      await expect(page).toHaveScreenshot(`alerts-${tab}-${theme}.png`);
    });
  }
}
