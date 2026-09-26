/**
 * Feeders baselines (roadmap slice 077, SPEC §83).
 *
 * The receiver-uplink tiles, the feeder card grid, the per-feeder gap
 * timeline and metric charts, and the local-pages card, at the page's
 * default `24h` per-feeder history window.
 *
 * Mirrors `04-receiver.visual.spec.ts`'s structure. Baseline capture (the
 * demo stack's `feeders` config, the recorded HAR entries for
 * `GET /api/v1/feeders` and `GET /api/v1/feeders/{name}/history`, and this
 * spec's own `VIEWPORT_HEIGHT`) is the integrator's job once the demo probe
 * fixtures land (design record "Demo": `demo/feeders.py`) — this spec is
 * written against the replay support the rest of the suite uses, the same
 * division of labor the work package sets between agent C (this file) and
 * whoever runs `npm run visual:capture` after every agent's work merges.
 */

import {
  expect,
  expectFitsWithoutScrolling,
  expectNoLoadFailures,
  openView,
  test,
} from "./support/replay";
import { VISUAL_THEMES } from "./support/stabilize";

/** Tall: receiver-uplink tiles, several feeder cards, and a gap timeline
 * plus up to three metric charts per feeder. Raise this (and re-capture) if
 * `expectFitsWithoutScrolling` starts failing once the demo roster is
 * fixed. */
const VIEWPORT_HEIGHT = 3200;

for (const theme of VISUAL_THEMES) {
  test(`feeders — ${theme}`, async ({ page }) => {
    await openView(page, "/receiver/feeders", theme, VIEWPORT_HEIGHT);

    await expect(
      page.getByRole("heading", { level: 1, name: "Feeders" }),
    ).toBeVisible();
    await expect(
      page.getByRole("group", { name: "Receiver uplink" }),
    ).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Local pages" }),
    ).toBeVisible();
    await expect(page.getByText(/^Loading/)).toHaveCount(0);

    await expectNoLoadFailures(page);
    await expectFitsWithoutScrolling(page);

    await expect(page).toHaveScreenshot(`feeders-${theme}.png`);
  });
}
