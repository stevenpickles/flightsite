/**
 * Receiver baselines (roadmap slice 047, SPEC §83).
 *
 * The scorecard, the nine chart cards, and the lifetime statistics section,
 * at the page's default 7-day window.
 *
 * Note what a demo stack legitimately produces here: the four time-series
 * charts are empty ("No data for this window."), because demo mode disables
 * the receiver stats poller (`backend/src/flightsite/app.py`), while the
 * scorecard, the range-by-bearing polar chart, the signal-strength
 * histogram and the lifetime records all carry real values. That mix is the
 * honest appearance of this page on demo data, and locking the empty-chart
 * rendering is worth as much as locking the populated one — it is exactly
 * the state a careless empty-state change would break.
 *
 * The scorecard polls every 5 s (`SCORECARD_POLL_MS`). Under HAR replay each
 * poll is answered from the same recorded response, so the poll repaints
 * identical values and cannot move the screenshot.
 */

import {
  expect,
  expectFitsWithoutScrolling,
  expectNoLoadFailures,
  openView,
  test,
} from "./support/replay";
import { VISUAL_THEMES } from "./support/stabilize";

/** The tallest view in the suite: scorecard, nine chart cards and the
 * lifetime section. See `expectFitsWithoutScrolling`, which fails the run
 * if this stops being enough. */
const VIEWPORT_HEIGHT = 2700;

for (const theme of VISUAL_THEMES) {
  test(`receiver — ${theme}`, async ({ page }) => {
    await openView(page, "/receiver", theme, VIEWPORT_HEIGHT);

    await expect(
      page.getByRole("heading", { level: 1, name: "Receiver" }),
    ).toBeVisible();
    await expect(
      page.getByRole("group", { name: "Receiver scorecard" }),
    ).toBeVisible();
    await expect(page.getByRole("heading", { name: "Charts" })).toBeVisible();

    // The two charts that genuinely have data on a demo stack — asserting
    // them keeps a fixture regression from quietly baselining a page of
    // nine empty charts.
    await expect(
      page.getByRole("img", { name: "Maximum range by bearing polar chart" }),
    ).toBeVisible();
    await expect(
      page.getByRole("img", { name: "Signal strength distribution chart" }),
    ).toBeVisible();
    await expect(page.getByText(/^Loading/)).toHaveCount(0);

    await expectNoLoadFailures(page);
    await expectFitsWithoutScrolling(page);

    await expect(page).toHaveScreenshot(`receiver-${theme}.png`);
  });
}
