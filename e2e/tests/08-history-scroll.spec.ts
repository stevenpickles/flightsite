/**
 * The long list pages can be scrolled to their end — with the mouse wheel,
 * the way a person scrolls.
 *
 * `<main>` is the app's scroll container. The Aircraft, Sightings and
 * Activity pages were each a column pinned to its height, and their table
 * sat in an `overflow: hidden` wrapper — which made the wrapper shrinkable,
 * so it was squeezed to the space left over instead of overflowing. The
 * table was cut off after about ten rows, the pagination below it was never
 * on screen, and nothing on the page could scroll. It shipped (v0.12.0 and
 * earlier) because every other spec reaches rows through Playwright's own
 * `scrollIntoView`, which scrolls a clipped box happily; a wheel does not.
 *
 * So this spec asserts the two things that were false: no box inside
 * `<main>` hides a meaningful part of its own content, and wheeling down
 * `<main>` brings the end of the page into view.
 */

import type { Page } from "@playwright/test";

import { waitForPersistedSightings } from "./support/history";
import { expect, test } from "./support/fixtures";

/** Boxes inside `<main>` that hide more than a sliver of their own height.
 * Single-line truncation and screen-reader-only nodes are far below the
 * thresholds; a table cut off mid-page is far above them. */
async function clippedBoxes(page: Page): Promise<string[]> {
  return page.evaluate(() =>
    [...document.querySelectorAll("main *")]
      .filter((element) => {
        const style = getComputedStyle(element);
        return (
          style.overflowY === "hidden" &&
          element.clientHeight > 20 &&
          element.scrollHeight > element.clientHeight + 40
        );
      })
      .map(
        (element) =>
          `${element.tagName.toLowerCase()}.${String(element.className).slice(0, 60)} ` +
          `shows ${element.clientHeight}px of ${element.scrollHeight}px`,
      ),
  );
}

/** Wheels `<main>` to its end and reports how far short of it the view is. */
async function wheelToEnd(page: Page): Promise<number> {
  const main = page.locator("main#main-content");
  await main.hover();
  // Several notches rather than one enormous delta: closer to a real wheel,
  // and immune to a browser clamping a single event.
  for (let notch = 0; notch < 40; notch += 1) {
    await page.mouse.wheel(0, 1200);
  }
  return main.evaluate((element) =>
    Math.round(element.scrollHeight - element.clientHeight - element.scrollTop),
  );
}

const PAGES = [
  { name: "Aircraft", path: "/aircraft" },
  { name: "Sightings (log)", path: "/sightings?preset=t0" },
  {
    name: "Sightings (by aircraft)",
    path: "/sightings?preset=t0&group=aircraft",
  },
  { name: "Sightings (by type)", path: "/sightings?preset=t0&group=types" },
  { name: "Activity", path: "/activity" },
] as const;

test.describe("long pages scroll to their end", () => {
  for (const { name, path } of PAGES) {
    test(`${name} hides nothing and wheels to its end`, async ({
      page,
      request,
    }) => {
      await waitForPersistedSightings(request);
      // A short window on a 13-inch laptop: the size at which a clipped
      // table shows only a handful of rows.
      await page.setViewportSize({ width: 1280, height: 600 });

      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
      await expect(page.locator("main").getByText(/^Loading/)).toHaveCount(0);

      expect(
        await clippedBoxes(page),
        `${name}: content is hidden inside a box that cannot scroll`,
      ).toEqual([]);
      expect(
        await wheelToEnd(page),
        `${name}: the mouse wheel did not reach the end of the page`,
      ).toBeLessThanOrEqual(1);
    });
  }

  test("the sightings log is long enough for this to mean something", async ({
    page,
    request,
  }) => {
    // Run on its own against a stack seconds old, the log needs a minute or
    // two to fill; in the suite it has had several.
    test.setTimeout(180_000);
    await waitForPersistedSightings(request);
    await page.setViewportSize({ width: 1280, height: 600 });
    await page.goto("/sightings?preset=t0");

    // Enough rows that the table cannot fit a 600px window...
    const rows = page.getByTestId("sighting-row");
    await expect
      .poll(() => rows.count(), {
        message: "the demo stack never recorded a screenful of sightings",
        timeout: 150_000,
        intervals: [3_000],
      })
      .toBeGreaterThanOrEqual(15);
    // ...so `<main>` really does have somewhere to scroll to,
    const main = page.locator("main#main-content");
    expect(
      await main.evaluate(
        (element) => element.scrollHeight > element.clientHeight + 100,
      ),
    ).toBe(true);
    // and the last row, off screen at first, is reached by the wheel alone.
    await expect(rows.last()).not.toBeInViewport();
    await wheelToEnd(page);
    await expect(rows.last()).toBeInViewport();
    await expect(page.getByText(/^Page 1\b/)).toBeInViewport();
  });
});
