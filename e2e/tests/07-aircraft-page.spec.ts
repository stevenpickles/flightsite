/**
 * Flow — Aircraft page (roadmap slice 046, `docs/TEST_STRATEGY.md` §4).
 *
 * The first of the two history-backed pages: everything the receiver has ever
 * seen, read from SQLite rather than from the live registry the Live Map
 * flows exercise. Setup was completed by `01`, and the demo scenario has been
 * running for every spec since, so by the time this file runs the persistence
 * worker has had ample opportunity to flush — `waitForPersistedAircraft`
 * makes that a polled precondition rather than an assumption (see
 * `support/history.ts`).
 *
 * What is asserted, and why it is not a race
 * ------------------------------------------
 * Demo traffic keeps arriving while the test runs, so the row *set* is a
 * moving target and any assertion comparing two fetches of it would flake.
 * Each test here instead asserts a property that holds regardless of what
 * arrived in between:
 *
 * - the rows on screen are real persisted aircraft (verified by fetching one
 *   of them back from `/api/v1/aircraft/{icao}`), rather than a count the UI
 *   invented;
 * - a sort produces a sequence that is *internally* ordered, checked against
 *   itself rather than against a separately-fetched expected order;
 * - a row click opens the detail page for the ICAO that row carried.
 *
 * The `data-icao` attribute those assertions read is a test affordance added
 * for this slice (`AircraftTable.tsx`): the whole row navigates on click but
 * only its first cell holds an anchor, so without it a specific aircraft's
 * row is addressable only through rendered text — and every absent field on
 * this page renders the same "Unknown".
 */

import {
  pickBusiestAircraft,
  waitForPersistedAircraft,
} from "./support/history";
import { expect, test } from "./support/fixtures";

/** Reads the ICAO of every row currently rendered, in display order. */
async function renderedIcaos(page: import("@playwright/test").Page) {
  return page
    .getByTestId("aircraft-row")
    .evaluateAll((rows) =>
      rows.map((row) => (row as HTMLElement).dataset["icao"] ?? ""),
    );
}

/**
 * Waits until the rendered rows are actually in `direction` ICAO order.
 *
 * Polled rather than read once because the table keeps the previous page's
 * rows on screen while the re-sorted query is in flight
 * (`placeholderData: keepPreviousData`, so sorting never flashes an empty
 * table). Reading immediately after the click would therefore assert against
 * the *old* order and fail for a reason that has nothing to do with sorting.
 */
async function expectSortedIcaos(
  page: import("@playwright/test").Page,
  direction: "ascending" | "descending",
): Promise<void> {
  await expect
    .poll(
      async () => {
        const icaos = await renderedIcaos(page);
        if (icaos.length === 0) {
          return false;
        }
        const expected = [...icaos].sort();
        if (direction === "descending") {
          expected.reverse();
        }
        return expected.every((icao, index) => icao === icaos[index]);
      },
      { message: `rows never settled into ${direction} ICAO order` },
    )
    .toBe(true);
}

test.describe("Aircraft page", () => {
  test("lists persisted aircraft, reached from the sidebar", async ({
    page,
    request,
  }) => {
    const persisted = await waitForPersistedAircraft(request);

    await page.goto("/");
    // The real user path into the page, which also proves the section is
    // reachable from the primary nav rather than only by URL.
    await page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Aircraft" })
      .click();

    await expect(page).toHaveURL(/\/aircraft$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "Aircraft" }),
    ).toBeVisible();

    const rows = page.getByTestId("aircraft-row");
    await expect(rows.first()).toBeVisible();
    expect(await rows.count()).toBeGreaterThan(0);

    // Ground truth: an ICAO the page is displaying resolves to a real
    // persisted airframe through the detail endpoint. History only ever
    // grows, so an aircraft the list showed cannot have vanished by the time
    // this asks about it.
    const icaos = await renderedIcaos(page);
    const first = icaos[0];
    expect(first, "a rendered row carried no data-icao").toBeTruthy();
    const detail = await request.get(`/api/v1/aircraft/${first}`);
    expect(
      detail.ok(),
      `the page listed ${first}, which /api/v1/aircraft/{icao} does not know`,
    ).toBeTruthy();

    // The ICAO column renders the hex in upper case (`AircraftTable.tsx`).
    await expect(
      rows.first().getByText(first!.toUpperCase(), { exact: true }),
    ).toBeVisible();

    // This endpoint returns an exact count, so the footer commits to one
    // (`AircraftPaginationControls.tsx`).
    await expect(page.getByText(/^Page 1 of \d+ · \d+ aircraft$/)).toBeVisible();
    expect(persisted.length).toBeGreaterThan(0);
  });

  test("sorting by a column re-orders the table and is reflected in the URL", async ({
    page,
  }) => {
    await page.goto("/aircraft");
    await expect(page.getByTestId("aircraft-row").first()).toBeVisible();

    // ICAO is the one column whose ordering the test can verify without
    // reimplementing the app's formatting: it is a plain hex string, present
    // on every row, and never null.
    const header = page.getByRole("columnheader", { name: "ICAO" });
    await page.getByRole("button", { name: "ICAO", exact: true }).click();

    // A first click on a new column sorts descending
    // (`useAircraftTableState.ts`). `order` is *absent* from the URL here
    // rather than spelled out: descending is the default, and `urlState.ts`
    // omits any parameter equal to its default so a shared link carries only
    // what the user actually changed.
    await expect(page).toHaveURL(/[?&]sort=icao/);
    await expect(page).not.toHaveURL(/[?&]order=/);
    await expect(header).toHaveAttribute("aria-sort", "descending");

    await expectSortedIcaos(page, "descending");

    // Clicking the active column toggles direction rather than re-sorting.
    await page.getByRole("button", { name: "ICAO", exact: true }).click();
    await expect(page).toHaveURL(/[?&]order=asc/);
    await expect(header).toHaveAttribute("aria-sort", "ascending");

    await expectSortedIcaos(page, "ascending");
  });

  test("a row opens that aircraft's detail page", async ({ page, request }) => {
    const persisted = await waitForPersistedAircraft(request);
    // The busiest airframe has the most history behind it, so its detail page
    // renders the fullest version of itself.
    const subject = pickBusiestAircraft(persisted);

    await page.goto("/aircraft?sort=sighting_count&order=desc");
    const row = page.locator(
      `[data-testid="aircraft-row"][data-icao="${subject.icao}"]`,
    );
    await expect(row).toBeVisible();
    await row.click();

    await expect(page).toHaveURL(
      new RegExp(`/aircraft/${subject.icao}(\\?|$)`, "i"),
    );
    // The detail page identifies the airframe it opened; the ICAO hex is the
    // one identifier every aircraft has (`docs/API.md` §2.7 lets the rest be
    // absent).
    await expect(
      page.getByText(new RegExp(subject.icao, "i")).first(),
    ).toBeVisible();
  });
});
