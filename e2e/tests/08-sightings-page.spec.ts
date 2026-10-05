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
 * - **The aircraft filter actually narrows the query**, checked by requiring every
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

    // The subject is chosen from every aircraft ever persisted, so the log
    // is asked for the same span: the default window is the receiver's
    // local today (slice 098), which a subject last heard before midnight
    // would be absent from.
    await page.goto("/sightings?preset=t0");
    await expect(page.getByTestId("sighting-row").first()).toBeVisible();

    // Before filtering there is no reason for the log to be single-aircraft,
    // so record what it looked like: this is what "Clear filters" has to
    // bring back.
    const unfiltered = await renderedIcaos(page);
    expect(unfiltered.length).toBeGreaterThan(0);

    // The filter commits on submit, not on keystroke (`SightingsFilters.tsx`),
    // and since slice 083 sends an ICAO-or-callsign prefix as `q`.
    await page.getByLabel("Aircraft or callsign").fill(subject.icao);
    await page.getByLabel("Aircraft or callsign").press("Enter");

    await expect(page).toHaveURL(new RegExp(`[?&]q=${subject.icao}`, "i"));
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

    await expect(page).not.toHaveURL(/[?&]q=/);
    await expect(clear).toHaveCount(0);
    await expect(page.getByLabel("Aircraft or callsign")).toHaveValue("");
  });

  test("the start of an address narrows the log (slice 083)", async ({
    page,
    request,
  }) => {
    const aircraft = await waitForPersistedAircraft(request);
    // Five of six digits: a real prefix, and long enough that no demo
    // callsign (three letters and a flight number) can start with it too.
    const prefix = pickBusiestAircraft(aircraft).icao.slice(0, 5).toLowerCase();

    // The subject is chosen from every aircraft ever persisted, so the log
    // is asked for the same span: the default window is the receiver's
    // local today (slice 098), which a subject last heard before midnight
    // would be absent from.
    await page.goto("/sightings?preset=t0");
    await expect(page.getByTestId("sighting-row").first()).toBeVisible();
    const field = page.getByLabel("Aircraft or callsign");
    await field.fill(prefix.toUpperCase());
    await field.press("Enter");

    // A prefix is a search, not a malformed address: it reaches the URL and
    // narrows the log to aircraft whose address starts with it, whatever the
    // case it was typed in.
    await expect(page).toHaveURL(new RegExp(`[?&]q=${prefix}`, "i"));
    await expect
      .poll(async () => {
        const icaos = await renderedIcaos(page);
        return (
          icaos.length > 0 &&
          icaos.every((icao) => icao.toLowerCase().startsWith(prefix))
        );
      })
      .toBe(true);
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

  test("every row carries a link into its sighting, reachable by keyboard", async ({
    page,
  }) => {
    // Review R2-07: the log's rows navigated through a bare `onClick` on the
    // `<tr>`, so a keyboard-only or screen-reader user had no route into any
    // `/sightings/:id` page at all. The Start cell is now an anchor, as Tail
    // already was on `/aircraft`.
    await page.goto("/sightings");
    const rows = page.getByTestId("sighting-row");
    await expect(rows.first()).toBeVisible();

    const hrefs = await rows.evaluateAll((elements) =>
      elements.map((row) => ({
        id: (row as HTMLElement).dataset["sightingId"] ?? "",
        href: row.querySelector("a")?.getAttribute("href") ?? null,
      })),
    );
    expect(hrefs.length).toBeGreaterThan(0);
    for (const { id, href } of hrefs) {
      expect(href, `row for sighting ${id} contains no link`).toBe(
        `/sightings/${id}`,
      );
    }

    // And the link is genuinely focusable, not an anchor without an href.
    const first = rows.first().getByRole("link").first();
    await first.focus();
    await expect(first).toBeFocused();
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

  test("opens on today and states what the window held (slice 098)", async ({
    page,
    request,
  }) => {
    await waitForPersistedSightings(request);

    await page.goto("/sightings");
    await expect(page.getByRole("radio", { name: "Today" })).toBeChecked();

    // The summary line is the live `counts` for the same window, so its
    // aircraft figure is the API's — not something the page added up.
    const counts = (await (
      await request.get("/api/v1/analytics/counts?preset=t0")
    ).json()) as { unique_aircraft: number; unique_types: number };
    expect(counts.unique_aircraft).toBeGreaterThan(0);

    await page.getByRole("radio", { name: "Since T0" }).click();
    await expect(page).toHaveURL(/[?&]preset=t0/);
    const summary = page.getByRole("group", { name: "In this window" });
    await expect(summary).toContainText("sightings");
    await expect(summary).toContainText("aircraft");
    await expect(summary).toContainText("types");
    // Over the whole history "never seen before" would only repeat the
    // aircraft count, so it is left out.
    await expect(summary).not.toContainText("never seen before");
  });

  test("groups the window by aircraft and by type (slice 098)", async ({
    page,
    request,
  }) => {
    await waitForPersistedSightings(request);

    await page.goto("/sightings?preset=t0");
    await expect(page.getByTestId("sighting-row").first()).toBeVisible();

    await page.getByRole("radio", { name: "Aircraft" }).click();
    await expect(page).toHaveURL(/[?&]group=aircraft/);
    const aircraftRows = page.getByTestId("seen-aircraft-row");
    await expect(aircraftRows.first()).toBeVisible();
    // One row per distinct airframe: no address appears twice.
    const icaos = await aircraftRows.evaluateAll((rows) =>
      rows.map((row) => (row as HTMLElement).dataset["icao"] ?? ""),
    );
    expect(new Set(icaos).size).toBe(icaos.length);
    // And each is an airframe the API knows.
    const known = await request.get(`/api/v1/aircraft/${icaos[0]}`);
    expect(
      known.ok(),
      `the grouping listed unknown aircraft ${icaos[0]}`,
    ).toBeTruthy();

    await page.getByRole("radio", { name: "Types" }).click();
    await expect(page).toHaveURL(/[?&]group=types/);
    const typeRows = page.getByTestId("seen-type-row");
    await expect(typeRows.first()).toBeVisible();
    const types = await typeRows.evaluateAll((rows) =>
      rows.map((row) => (row as HTMLElement).dataset["type"] ?? ""),
    );
    expect(new Set(types).size).toBe(types.length);

    // A type row opens the aircraft of that type.
    const chosen = types[0] as string;
    await typeRows.first().getByRole("button").first().click();
    await expect(page).toHaveURL(new RegExp(`[?&]type=${chosen}(&|$)`));
    await expect(page.getByText("Showing only")).toBeVisible();
    await expect(page.getByTestId("seen-aircraft-row").first()).toBeVisible();
  });

  test("a header sorts its list, and a second click reverses it (slice 100)", async ({
    page,
    request,
  }) => {
    await waitForPersistedSightings(request);
    const sortButton = (name: RegExp) =>
      page.getByRole("columnheader", { name }).getByRole("button");

    // The type list, by name: what each row leads with, A to Z first.
    await page.goto("/sightings?preset=t0&group=types");
    const typeRows = page.getByTestId("seen-type-row");
    await expect(typeRows.first()).toBeVisible();
    const typeNames = () =>
      typeRows.evaluateAll((rows) =>
        rows.map((row) =>
          (row.querySelector("button")?.textContent ?? "").toLowerCase(),
        ),
      );
    const ascending = <T extends string | number>(values: T[]) =>
      values.slice(1).every((value, index) => (values[index] as T) <= value);
    const descending = <T extends string | number>(values: T[]) =>
      values.slice(1).every((value, index) => (values[index] as T) >= value);

    await sortButton(/^Type/).click();
    await expect(page).toHaveURL(/[?&]sort=type&order=asc/);
    await expect(
      page.getByRole("columnheader", { name: /^Type/ }),
    ).toHaveAttribute("aria-sort", "ascending");
    await expect
      .poll(async () => ascending(await typeNames()), {
        message: "the type list is not in A-to-Z order",
      })
      .toBe(true);
    // Demo traffic has more than one type, or neither order proves anything.
    expect(new Set(await typeNames()).size).toBeGreaterThan(1);

    await sortButton(/^Type/).click();
    await expect(
      page.getByRole("columnheader", { name: /^Type/ }),
    ).toHaveAttribute("aria-sort", "descending");
    await expect
      .poll(async () => descending(await typeNames()), {
        message: "the type list is not in Z-to-A order",
      })
      .toBe(true);

    // The aircraft list, by a number: busiest first is the default, so one
    // click on Sightings turns it round.
    await page.getByRole("radio", { name: "Aircraft" }).click();
    const aircraftRows = page.getByTestId("seen-aircraft-row");
    await expect(aircraftRows.first()).toBeVisible();
    // The type list's sort did not follow it here.
    await expect(page).not.toHaveURL(/[?&]sort=/);
    const sightingCounts = () =>
      aircraftRows.evaluateAll((rows) =>
        rows.map((row) => Number(row.children[3]?.textContent ?? "NaN")),
      );
    await expect(
      page.getByRole("columnheader", { name: /^Sightings/ }),
    ).toHaveAttribute("aria-sort", "descending");

    await sortButton(/^Sightings/).click();
    await expect(page).toHaveURL(/[?&]order=asc/);
    await expect
      .poll(async () => ascending(await sightingCounts()), {
        message: "the aircraft list is not least-sighted first",
      })
      .toBe(true);

    // The log, by a column it could not be sorted by before this slice.
    await page.getByRole("radio", { name: "Sightings", exact: true }).click();
    await expect(page.getByTestId("sighting-row").first()).toBeVisible();
    await sortButton(/^Tail/).click();
    await expect(page).toHaveURL(/[?&]sort=tail&order=asc/);
    await expect(
      page.getByRole("columnheader", { name: /^Tail/ }),
    ).toHaveAttribute("aria-sort", "ascending");
    await expect(page.getByTestId("sighting-row").first()).toBeVisible();
    await expect(page.getByText(/could not be loaded/i)).toHaveCount(0);
  });
});
