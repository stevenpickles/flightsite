/**
 * Analytics baselines (roadmap slice 047, SPEC §83).
 *
 * The full card grid at the `t0` preset — see `ANALYTICS_PRESET` in
 * `support/fixtureContract.ts` for why the fixtures are captured at "since
 * first sighting" rather than the page's `today` default (short version:
 * demo sightings carry scenario-epoch dates, so `today` is genuinely empty
 * on demo data and would lock eight "No data for this window." cards).
 *
 * These screenshots include eight ECharts canvases. Their entry animation is
 * on — nothing in the app disables it — but `toHaveScreenshot` re-captures
 * until two consecutive frames are identical before it compares, so the
 * comparison happens on the settled chart. That built-in stabilization, not
 * a fixed wait, is what makes these deterministic; `maxDiffPixelRatio` in
 * the config absorbs the sub-pixel antialiasing differences canvas text can
 * still show.
 */

import {
  FIXTURE_MANIFEST,
  expect,
  expectFitsWithoutScrolling,
  expectNoLoadFailures,
  openView,
  test,
} from "./support/replay";
import { VISUAL_THEMES } from "./support/stabilize";

/** Tall enough for all three rows of the card grid without scrolling —
 * see `expectFitsWithoutScrolling`, which fails the run if it stops being. */
const VIEWPORT_HEIGHT = 1600;

for (const theme of VISUAL_THEMES) {
  test(`analytics — ${theme}`, async ({ page }) => {
    await openView(
      page,
      `/analytics?preset=${FIXTURE_MANIFEST.analyticsPreset}`,
      theme,
      VIEWPORT_HEIGHT,
    );

    await expect(
      page.getByRole("heading", { level: 1, name: "Analytics" }),
    ).toBeVisible();

    // One assertion per data-bearing card, so a fixture that stopped
    // covering an endpoint fails here instead of silently baselining that
    // card's error or empty state.
    for (const cardTitle of [
      "Top aircraft",
      "Top types",
      "Top operators",
      "Never seen before",
    ]) {
      await expect(page.getByRole("heading", { name: cardTitle })).toBeVisible();
    }
    await expect(
      page.getByRole("img", { name: "Top aircraft by sightings, horizontal bar chart" }),
    ).toBeVisible();
    await expect(page.getByText(/^Loading/)).toHaveCount(0);

    await expectNoLoadFailures(page);
    await expectFitsWithoutScrolling(page);

    await expect(page).toHaveScreenshot(`analytics-${theme}.png`);
  });
}
