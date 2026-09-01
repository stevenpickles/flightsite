/**
 * Flow — Sightings page (roadmap slice 046, `docs/TEST_STRATEGY.md` §4).
 *
 * The second history-backed page: a chronological log of observation periods,
 * again read from SQLite rather than the live registry, so it shares
 * `07`'s polled precondition (`support/history.ts`).
 *
 * Unlike the Aircraft page, this one has real filtering, which is where its
 * interesting behaviour lives — so the bulk of this file exercises the filter
 * bar rather than the table. The two assertions that matter:
 *
 * - **The ICAO filter actually narrows the query**, checked by requiring every
 *   surviving row to belong to the requested aircraft rather than by counting
 *   rows (a count would be a moving target while demo traffic keeps arriving).
 * - **"Open now" means open**, checked against the one cell that distinguishes
 *   an ongoing observation from a closed one.
 *
 * Both read `data-icao` / `data-sighting-id`, test affordances added for this
 * slice (`SightingsTable.tsx`). They earn their place here more than on the
 * Aircraft page: a sightings row contains no anchor at all, so before this
 * slice neither the sighting's id nor the aircraft's ICAO existed anywhere in
 * the page's DOM, and a filter assertion had nothing to bite on.
 */

import type { Page } from "@playwright/test";

import {
  pickBusiestAircraft,
  waitForPersistedAircraft,
  waitForPersistedSightings,
} from "./support/history";
import { expect, test } from "./support/fixtures";

/** The ICAO of every row currently rendered, in display order. */
async function renderedIcaos(page: Page): Promise<string[]> {
  return page
    .getByTestId("sighting-row")
    .evaluateAll((rows) =>
      rows.map((row) => (row as HTMLElement).dataset["icao"] ?? ""),
    );
}

test.describe("Sightings page", () => {
  test("lists persisted sightings, reached from the sidebar", async ({
    page,
    request,
  }) => {
    await waitForPersistedSightings(request);

    await page.goto("/");
    await page
      .getByRole("navigation", { name: "Primary" })
      .getByRole("link", { name: "Sightings" })
      .click();

    await expect(page).toHaveURL(/\/sightings$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "Sightings" }),
    ).toBeVisible();

    const rows = page.getByTestId("sighting-row");
    await expect(rows.first()).toBeVisible();

    // Ground truth: a sighting the page is displaying resolves through the
    // detail endpoint, so the log is showing real persisted records.
    const id = await rows.first().getAttribute("data-sighting-id");
    expect(id, "a rendered row carried no data-sighting-id").toBeTruthy();
    const detail = await request.get(`/api/v1/sightings/${id}`);
    expect(
      detail.ok(),
      `the log listed sighting ${id}, which /api/v1/sightings/{id} does not know`,
    ).toBeTruthy();

    // `/sightings` deliberately returns no exact count (`docs/API.md` §2.4),
    // so the footer commits only to a page number.
    await expect(page.getByText(/^Page 1\b/)).toBeVisible();
  });

  test("the ICAO filter narrows the log to one aircraft, and Clear filters restores it", async ({
    page,
    request,
  }) => {
    const aircraft = await waitForPersistedAircraft(request);
    // The busiest airframe is the one whose filtered log is least likely to
    // be a single row, which makes "narrowed to exactly this aircraft" a
    // meaningful assertion rather than a coincidence.
    const subject = pickBusiestAircraft(aircraft);

    await page.goto("/sightings");
    await expect(page.getByTestId("sighting-row").first()).toBeVisible();

    // Before filtering there is no reason for the log to be single-aircraft,
    // so record what it looked like: this is what "Clear filters" has to
    // bring back.
    const unfiltered = await renderedIcaos(page);
    expect(unfiltered.length).toBeGreaterThan(0);

    // The filter commits on submit, not on keystroke (`SightingsFilters.tsx`).
    await page.getByLabel("Aircraft (ICAO)").fill(subject.icao);
    await page.getByLabel("Aircraft (ICAO)").press("Enter");

    await expect(page).toHaveURL(new RegExp(`[?&]icao=${subject.icao}`, "i"));
    const rows = page.getByTestId("sighting-row");
    await expect(rows.first()).toBeVisible();

    // Every surviving row belongs to the requested aircraft. Asserted over
    // the whole set rather than the first row, so a filter that narrowed
    // partially — or not at all — fails here.
    //
    // Polled, because the table deliberately keeps the *unfiltered* rows on
    // screen while the filtered query is in flight (`keepPreviousData`, so
    // filtering never flashes an empty log). Reading once immediately after
    // submitting reads the pre-filter rows and reports a filter that let
    // everything through, which is a race in the test rather than a bug in
    // the app.
    await expect
      .poll(
        async () => {
          const icaos = await renderedIcaos(page);
          return (
            icaos.length > 0 && icaos.every((icao) => icao === subject.icao)
          );
        },
        {
          message: `the log never narrowed to ${subject.icao} alone — the ICAO filter let other aircraft through`,
        },
      )
      .toBe(true);

    // "Clear filters" appears only while a filter is set, so its presence is
    // itself part of the contract.
    const clear = page.getByRole("button", { name: "Clear filters" });
    await expect(clear).toBeVisible();
    await clear.click();

    await expect(page).not.toHaveURL(/[?&]icao=/);
    await expect(clear).toHaveCount(0);
    await expect(page.getByLabel("Aircraft (ICAO)")).toHaveValue("");
  });

  test("a malformed ICAO is rejected without touching the query", async ({
    page,
  }) => {
    await page.goto("/sightings");
    const field = page.getByLabel("Aircraft (ICAO)");
    await field.fill("nothex");
    await field.press("Enter");

    // Rejected in the field rather than sent to the API as an unsatisfiable
    // query that would render as an empty log.
    await expect(field).toHaveAttribute("aria-invalid", "true");
    await expect(
      page.getByText("Enter a 6-character hex ICAO address."),
    ).toBeVisible();
    await expect(page).not.toHaveURL(/[?&]icao=/);
  });

  test('"Open now" restricts the log to observations still in progress', async ({
    page,
  }) => {
    await page.goto("/sightings");
    await expect(page.getByTestId("sighting-row").first()).toBeVisible();

    const toggle = page.getByRole("button", { name: "Open now" });
    await expect(toggle).toHaveAttribute("aria-pressed", "false");
    await toggle.click();

    await expect(page).toHaveURL(/[?&]open=true/);
    await expect(toggle).toHaveAttribute("aria-pressed", "true");

    // Demo traffic is live throughout the suite, so there is always at least
    // one observation in progress.
    const rows = page.getByTestId("sighting-row");
    await expect(rows.first()).toBeVisible();

    // An open sighting has no end time, which the End column renders as
    // "Ongoing" (`SightingsTable.tsx`). Every row must say so — a closed
    // sighting surviving an open-only filter is the bug this catches.
    const count = await rows.count();
    for (let index = 0; index < count; index += 1) {
      await expect(rows.nth(index).locator("td").nth(1)).toHaveText("Ongoing");
    }
  });

  test("a row opens that sighting's detail page", async ({ page, request }) => {
    await waitForPersistedSightings(request);

    await page.goto("/sightings");
    const row = page.getByTestId("sighting-row").first();
    await expect(row).toBeVisible();
    const id = await row.getAttribute("data-sighting-id");
    expect(id).toBeTruthy();

    await row.click();

    await expect(page).toHaveURL(new RegExp(`/sightings/${id}(\\?|$)`));
    // The detail page's heading is the aircraft's identity; the page having
    // resolved a real sighting is what the "not found" branch would deny.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("Sighting not found")).toHaveCount(0);
  });
});
