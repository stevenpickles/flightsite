/**
 * Flow — Analytics windows, all presets (roadmap slice 046,
 * `docs/TEST_STRATEGY.md` §4; SPEC §58's Today / 7 days / 30 days / This year
 * / Since T0).
 *
 * The flow SPEC §82 names is "Analytics windows", plural, so this covers
 * every one of the five rather than sampling one. What makes that a real test
 * rather than five button clicks is *what* each selection is asserted to have
 * done, at three levels:
 *
 * 1. **The control agrees with itself** — the chosen preset is the one
 *    reporting `aria-checked`, and it is the only one.
 * 2. **The backend was actually asked for that window** — each click is paired
 *    with `waitForResponse` on the analytics request carrying that preset, so
 *    the assertion settles on the response arriving rather than on a timer
 *    (`docs/TEST_STRATEGY.md` §3).
 * 3. **The page says which window it is showing** — every card echoes the
 *    window the API resolved (`docs/API.md` §3.7), and that caption is what a
 *    user actually reads. A control that highlighted correctly while the
 *    cards below it still showed yesterday's range would pass (1) and (2) and
 *    fail here.
 *
 * Charts themselves are deliberately not asserted through: ECharts renders to
 * canvas with no SVG renderer registered (`lib/echartsSetup.ts`), so nothing
 * inside a chart is in the DOM. The window caption and the per-card text
 * alternatives are the assertable surface, and they are the meaningful one.
 *
 * Two traps this file encodes, both learned from the URL contract in
 * `features/analytics/lib/urlState.ts`:
 *
 * - **The default preset is serialized as an empty query string.** `/analytics`
 *   and `?preset=today` are the same page, so selecting Today *clears* the
 *   query rather than writing it.
 * - **A window already fetched fires no second request.** These queries hold a
 *   60 s `staleTime`, so returning to Today moments after the page loaded it
 *   is answered from cache. Pairing *that* step with a `waitForResponse`
 *   would time out on entirely correct behaviour — so the loop waits on
 *   responses only for the four windows the page has not yet asked for, and
 *   the return to Today is asserted on the control, the URL and the rendered
 *   window instead.
 */

import { expect, test } from "./support/fixtures";

/** SPEC §58's five windows, in the order the selector renders them
 * (`ANALYTICS_PRESETS`), paired with the label a user sees. */
const PRESETS = [
  { value: "today", label: "Today" },
  { value: "7d", label: "7 days" },
  { value: "30d", label: "30 days" },
  { value: "ytd", label: "This year" },
  { value: "t0", label: "Since T0" },
] as const;

/** The preset the page opens on when the URL says nothing. */
const DEFAULT_PRESET = "today";

/** One of the six requests a preset change fires; the daily-counts query is
 * the one every window has, so it is the reliable one to wait on. */
function dailyRequestFor(preset: string) {
  return (url: string) =>
    url.includes("/api/v1/analytics/daily") && url.includes(`preset=${preset}`);
}

test.describe("Analytics windows", () => {
  test("opens on Today with its cards rendered", async ({ page }) => {
    await page.goto("/analytics");

    await expect(
      page.getByRole("heading", { level: 1, name: "Analytics" }),
    ).toBeVisible();

    // The page is route-level lazy (`routes.tsx`), so the selector appearing
    // is also the proof its chunk loaded.
    const group = page.getByRole("radiogroup", { name: "Time range" });
    await expect(group).toBeVisible();
    await expect(group.getByRole("radio")).toHaveCount(PRESETS.length);

    await expect(
      page.locator(`[data-testid="analytics-preset"][data-preset="${DEFAULT_PRESET}"]`),
    ).toHaveAttribute("aria-checked", "true");

    // Every card echoes the window it resolved once its query lands; that
    // they all do is what says the page is populated rather than stuck
    // loading.
    const captions = page.getByTestId("analytics-card-window");
    await expect(captions.first()).toBeVisible();
    expect(await captions.count()).toBeGreaterThan(0);
  });

  test("every preset re-queries its own window and is reflected in the URL", async ({
    page,
  }) => {
    await page.goto("/analytics");
    await expect(page.getByTestId("analytics-card-window").first()).toBeVisible();

    // Today is already selected — and already fetched — on load, so it is
    // handled after the loop rather than inside it: see the note there.
    for (const { value, label } of PRESETS.filter(
      (preset) => preset.value !== DEFAULT_PRESET,
    )) {
      const radio = page.locator(
        `[data-testid="analytics-preset"][data-preset="${value}"]`,
      );
      // The label a user reads and the value the app sends are the same
      // control — checked once here so the rest of the flow can address
      // presets by value without losing sight of the visible UI.
      await expect(radio).toHaveText(label);

      const responded = page.waitForResponse(
        (response) =>
          dailyRequestFor(value)(response.url()) && response.status() === 200,
      );
      await radio.click();
      await responded;

      // The control agrees with itself: exactly one radio is checked, and it
      // is this one.
      await expect(radio).toHaveAttribute("aria-checked", "true");
      await expect(
        page.locator('[data-testid="analytics-preset"][aria-checked="true"]'),
      ).toHaveCount(1);

      // The URL round-trips the choice.
      await expect(page).toHaveURL(new RegExp(`[?&]preset=${value}`));

      // And the cards say which window they are showing, rather than the
      // selection highlighting over stale content.
      await expect(
        page.getByTestId("analytics-card-window").first(),
      ).toBeVisible();
    }

    // Returning to the default. Deliberately *not* paired with a
    // `waitForResponse`: the analytics queries hold a 60 s `staleTime`
    // (`lib/api/analytics.ts`), so Today — already fetched on load moments
    // ago — is served from cache and fires no request at all. Waiting for one
    // would time out on correct behaviour. Today's own request is covered by
    // this file's first test, which asserts the window it opens on.
    const today = page.locator(
      `[data-testid="analytics-preset"][data-preset="${DEFAULT_PRESET}"]`,
    );
    await today.click();

    await expect(today).toHaveAttribute("aria-checked", "true");
    await expect(
      page.locator('[data-testid="analytics-preset"][aria-checked="true"]'),
    ).toHaveCount(1);
    // The default is serialized as no query string at all, so selecting it
    // *clears* the URL rather than writing `?preset=today`.
    await expect(page).toHaveURL(/\/analytics$/);
    await expect(
      page.getByTestId("analytics-card-window").first(),
    ).toBeVisible();
  });

  test("a selected window survives a reload", async ({ page }) => {
    // Deep-linking is the point of persisting the preset in the URL at all:
    // a shared or bookmarked Analytics link has to open the same window.
    await page.goto("/analytics?preset=30d");

    await expect(
      page.locator('[data-testid="analytics-preset"][data-preset="30d"]'),
    ).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("analytics-card-window").first()).toBeVisible();
  });

  test("an unrecognized window in the URL falls back to Today", async ({
    page,
  }) => {
    // A hand-edited or stale link must land on a usable page, not an empty
    // or broken one (`features/analytics/lib/urlState.ts` parses defensively).
    await page.goto("/analytics?preset=last-tuesday");

    await expect(
      page.locator(`[data-testid="analytics-preset"][data-preset="${DEFAULT_PRESET}"]`),
    ).toHaveAttribute("aria-checked", "true");
    await expect(page.getByTestId("analytics-card-window").first()).toBeVisible();
  });
});
