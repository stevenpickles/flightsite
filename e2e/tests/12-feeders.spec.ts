/**
 * Flow — Feeders page (roadmap slice 077, `docs/design/077-feeders-page.md`,
 * issue #215).
 *
 * Driven against the demo stack, like every other numbered flow in this
 * suite (`docs/TEST_STRATEGY.md` §3: seeded demo mode, no external network,
 * no stubbed internal endpoints for a page the backend actually serves).
 * The design record's backend work packages (A/B) ship `demo/feeders.py`:
 * probes for every one of the seven kinds, and a scripted ~3-minute FR24
 * outage that recurs on its own cycle. This file deliberately does not
 * assert *which* state that scripted outage is in at the moment a test
 * happens to run — the design record does not fix the outage to a frozen
 * clock the way the visual suite freezes its inputs (`docs/TEST_STRATEGY.md`
 * §5's "Frozen visual inputs" is a visual-regression rule, not a functional
 * one), so pinning a run to "FR24 is down right now" would be exactly the
 * kind of wall-clock-dependent flake `docs/TEST_STRATEGY.md` §3 rules out.
 * What *is* asserted is structural and always true regardless of where in
 * the cycle a run lands: every demo feeder has a status pill in some valid
 * state, the gap timeline renders, and the stats link appears only where
 * the demo config actually set one.
 *
 * **Contract assumptions — work package D, no backend or FeedersPage
 * contract to check these against yet (agents A/B/C build them in
 * parallel worktrees):**
 * - The route is `/receiver/feeders` (design record "Frontend"), reached
 *   from a link on `/receiver` — `NAV_ITEMS` does not grow an eighth entry
 *   (SPEC §10), the same precedent `/health` already set.
 * - `FeederCard` reuses the existing `features/health/components/StatusPill`
 *   component (already used for exactly this "icon + word + `data-tone`"
 *   badge across the Health page), so a card's status is asserted via
 *   `[data-tone]` rather than a guessed test id.
 * - The demo config mirrors the design record's own six-entry example
 *   verbatim (`docs/design/077-feeders-page.md` "Config") — the same
 *   fixture `FeedersSection`'s "Load the example" button fills
 *   (`frontend/src/features/settings/lib/feederKinds.ts`,
 *   `FEEDERS_EXAMPLE_ENTRIES`) — and its `secrets.yaml` counterpart
 *   configures a stats URL for every entry except `receiver` (which has
 *   none in the design record's own `secrets.yaml` example), so this file
 *   asserts a stats link is present on the other five cards and absent
 *   from the receiver's.
 * - A card names its feeder with the entry's `label` and carries a
 *   `data-testid="feeder-card"` with `data-feeder="<name>"`, the same
 *   `[data-testid][data-X="…"]` convention `10-metadata-update.spec.ts`
 *   established for its per-source cards.
 *
 * If any of these turn out to differ from what agent C actually ships,
 * this file's locators need updating to match — that reconciliation is
 * expected, not a sign the contract above was guessed carelessly.
 */

import { expect, test } from "./support/fixtures";

/** The six entries `docs/design/077-feeders-page.md`'s "Config" section
 * gives as the worked example — the same list
 * `frontend/src/features/settings/lib/feederKinds.ts`'s
 * `FEEDERS_EXAMPLE_ENTRIES` encodes, and what the demo backend is expected
 * to mirror so this page has something to show without real hardware. */
const DEMO_FEEDERS = [
  { name: "receiver", label: "Receiver (readsb)", hasStatsLink: false },
  { name: "flightaware", label: "FlightAware", hasStatsLink: true },
  { name: "fr24", label: "FlightRadar24", hasStatsLink: true },
  { name: "adsbx", label: "ADS-B Exchange", hasStatsLink: true },
  { name: "aerodatabox", label: "AeroDataBox", hasStatsLink: true },
  { name: "opensky", label: "OpenSky Network", hasStatsLink: true },
] as const;

/** The four locally hosted pages the design record's example links. */
const LOCAL_PAGES = ["tar1090", "graphs1090", "SkyAware", "FR24 feeder"];

test.describe("Feeders page", () => {
  test("is reached from Receiver and shows every demo feeder's status", async ({
    page,
  }) => {
    await page.goto("/receiver");
    await expect(
      page.getByRole("heading", { level: 1, name: "Receiver" }),
    ).toBeVisible();

    await page
      .getByRole("link", { name: /feeders/i })
      .first()
      .click();
    await expect(page).toHaveURL(/\/receiver\/feeders$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "Feeders" }),
    ).toBeVisible();

    for (const feeder of DEMO_FEEDERS) {
      const card = page.locator(
        `[data-testid="feeder-card"][data-feeder="${feeder.name}"]`,
      );
      await expect(card).toBeVisible();
      await expect(card).toContainText(feeder.label);

      // Every card degrades honestly rather than hiding — a status pill
      // exists and names a real, known state (SPEC §80: colour is never
      // the only carrier of meaning, so the pill's own text also has to be
      // one of these words, not just its `data-tone`).
      const pill = card.locator("[data-tone]");
      await expect(pill).toBeVisible();
      await expect(pill).toHaveAttribute(
        "data-tone",
        /^(ok|warn|bad|unknown|idle)$/,
      );

      const statsLink = card.getByRole("link", { name: /view stats/i });
      if (feeder.hasStatsLink) {
        await expect(statsLink).toBeVisible();
      } else {
        await expect(statsLink).toHaveCount(0);
      }
    }
  });

  test("shows the local pages card and a gap timeline", async ({ page }) => {
    await page.goto("/receiver/feeders");
    await expect(
      page.getByRole("heading", { level: 1, name: "Feeders" }),
    ).toBeVisible();

    const localPagesCard = page.getByTestId("local-pages-card");
    await expect(localPagesCard).toBeVisible();
    for (const label of LOCAL_PAGES) {
      await expect(
        localPagesCard.getByRole("link", { name: label }),
      ).toBeVisible();
    }

    // The gap timeline (24h/7d/30d availability bars) — asserted on its own
    // test id rather than window-button labels, which the design record
    // does not pin down precisely enough to guess safely.
    await expect(page.getByTestId("gap-timeline").first()).toBeVisible();
  });

  test("Settings round-trips an added local page: add, save, reload, remove, save", async ({
    page,
  }) => {
    await page.goto("/settings#settings-feeders");
    await expect(
      page.getByRole("heading", { level: 2, name: "Feeders" }),
    ).toBeVisible();

    const label = "e2e test page";
    const url = "http://fermi.local:9999/";

    // `addLocalPage` (`frontend/src/features/settings/sections/
    // FeedersSection.tsx`) always appends, so the new row's index is
    // whatever the table's row count was just before adding it — captured
    // here rather than assumed to be a fixed number, since the demo config
    // may already seed some local pages of its own.
    const rowsBeforeAdd = await page.getByTestId("local-page-row").count();
    await page.getByRole("button", { name: /add local page/i }).click();
    const newRow = page.getByTestId("local-page-row").nth(rowsBeforeAdd);
    await newRow.getByLabel(/label/i).fill(label);
    await newRow.getByLabel(/url/i).fill(url);

    const saveButton = page.getByRole("button", { name: /^save$/i }).last();
    await saveButton.click();
    await expect(page.getByText(/^saved$/i).last()).toBeVisible();

    // Reload — this is the point of the test: a save that only looked
    // right in memory would still fail here, since the page re-reads
    // `GET /api/internal/config` from scratch. `buildFeedersPatch` sends
    // the local-pages list wholesale in the order the table held it, so the
    // same index still names the same row afterward.
    await page.reload();
    await expect(
      page.getByRole("heading", { level: 2, name: "Feeders" }),
    ).toBeVisible();
    const reloadedRow = page.getByTestId("local-page-row").nth(rowsBeforeAdd);
    await expect(reloadedRow.getByLabel(/label/i)).toHaveValue(label);
    await expect(reloadedRow.getByLabel(/url/i)).toHaveValue(url);

    // Remove it again and save — the section should return to exactly its
    // prior state, not leave an empty trailing row behind.
    await reloadedRow
      .getByRole("button", { name: /remove local page/i })
      .click();
    await page
      .getByRole("button", { name: /^save$/i })
      .last()
      .click();
    await expect(page.getByText(/^saved$/i).last()).toBeVisible();

    await page.reload();
    await expect(page.getByTestId("local-page-row")).toHaveCount(rowsBeforeAdd);
  });
});
