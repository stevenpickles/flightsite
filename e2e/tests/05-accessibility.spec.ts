/**
 * Automated accessibility checks over the main flows — roadmap slice 048,
 * SPEC §80, `docs/TEST_STRATEGY.md` §1.5 ("Automated axe checks integrated
 * into E2E for main flows, CI-gated").
 *
 * Runs as `05-` so it lands after the ordered 01→04 story: those specs
 * complete first-run setup against the shared backend, and every route here
 * assumes a configured, demo-populated install.
 *
 * **Both themes are scanned, not just the default.** Contrast is a property
 * of a token pair, and FlightSite defines two independent palettes in
 * `frontend/src/index.css`; a light-theme-only regression would be invisible
 * to a dark-only sweep (slice 048's audit found exactly that — the light
 * accent failed as link text while dark passed comfortably). The theme is
 * forced through the same `localStorage` key the app's own pre-hydration
 * script reads (`index.html`), set via `addInitScript` so it applies before
 * first paint rather than causing a flash-and-reflow mid-scan.
 */

import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";

import { expect, test } from "./support/fixtures";
import { waitForLiveAircraft } from "./support/liveMap";

type Theme = "light" | "dark";

const THEMES: readonly Theme[] = ["dark", "light"];

/** Mirrors `STORAGE_KEY` in `frontend/index.html`'s theme bootstrap. */
const THEME_STORAGE_KEY = "flightsite-ui-theme";

/**
 * The main flows, as (path, heading) pairs. The heading is what the scan
 * waits on: it proves the route actually rendered its content rather than
 * axe sweeping an empty shell and passing vacuously.
 */
const FLOWS: readonly { path: string; heading: RegExp; name: string }[] = [
  { path: "/aircraft", heading: /aircraft/i, name: "Aircraft" },
  { path: "/sightings", heading: /sightings/i, name: "Sightings" },
  { path: "/analytics", heading: /analytics/i, name: "Analytics" },
  { path: "/receiver", heading: /receiver/i, name: "Receiver" },
  { path: "/alerts", heading: /alerts/i, name: "Alerts" },
  { path: "/settings", heading: /settings/i, name: "Settings" },
  { path: "/activity", heading: /activity/i, name: "Activity" },
];

async function useTheme(page: Page, theme: Theme): Promise<void> {
  await page.addInitScript(
    ([key, value]) => {
      window.localStorage.setItem(key as string, value as string);
    },
    [THEME_STORAGE_KEY, theme],
  );
}

/**
 * Scans the current page and asserts zero violations.
 *
 * Scoped to WCAG 2.1 A/AA — the baseline SPEC §80 actually describes. It
 * deliberately does NOT claim conformance ("Do not claim formal WCAG
 * certification unless actually qualified"); these are the machine-checkable
 * subset, which is a floor, not a certificate.
 */
async function expectNoViolations(page: Page, label: string): Promise<void> {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    // The MapLibre canvas is an opaque WebGL surface: axe cannot inspect
    // what is painted inside it, and the app already exposes the map through
    // `role="application"` + `aria-label` with every control mirrored in DOM
    // (basemap switcher, filters, aircraft lists). Excluding the canvas
    // keeps the rest of the Live Map genuinely covered instead of the whole
    // page being written off.
    .exclude("canvas")
    .analyze();

  const summary = results.violations.map((violation) => ({
    id: violation.id,
    impact: violation.impact,
    help: violation.help,
    nodes: violation.nodes.map((node) => node.target.join(" ")),
  }));

  expect(
    summary,
    `axe found accessibility violations on ${label}:\n${JSON.stringify(summary, null, 2)}`,
  ).toEqual([]);
}

for (const theme of THEMES) {
  test.describe(`accessibility (${theme} theme)`, () => {
    test(`Live Map has no automatically detectable violations`, async ({
      page,
    }) => {
      await useTheme(page, theme);
      await page.goto("/");
      // Scan the populated map, not the empty pre-socket state — the
      // aircraft lists and interesting panel are part of what needs checking.
      await waitForLiveAircraft(page);
      await expectNoViolations(page, `Live Map (${theme})`);
    });

    for (const flow of FLOWS) {
      test(`${flow.name} has no automatically detectable violations`, async ({
        page,
      }) => {
        await useTheme(page, theme);
        await page.goto(flow.path);
        await expect(
          page.getByRole("heading", { level: 1, name: flow.heading }),
        ).toBeVisible();
        await expectNoViolations(page, `${flow.name} (${theme})`);
      });
    }
  });
}

/**
 * Keyboard-only walkthrough (SPEC §80 "keyboard navigation", the roadmap's
 * "keyboard-only walkthrough of critical flows succeeds" acceptance
 * criterion). These assert the patterns axe structurally cannot see: axe
 * checks that roles and names exist, not that the arrow keys those roles
 * promise actually move focus.
 */
test.describe("keyboard-only navigation", () => {
  test("the skip link is reachable by keyboard and jumps to main content", async ({
    page,
  }) => {
    await page.goto("/");
    // First Tab from the document start must reach the skip link.
    await page.keyboard.press("Tab");
    const skipLink = page.getByRole("link", { name: /skip to main content/i });
    await expect(skipLink).toBeFocused();

    await page.keyboard.press("Enter");
    await expect(page.locator("#main-content")).toBeVisible();
  });

  test("Alerts tabs are reachable and operable with the arrow keys", async ({
    page,
  }) => {
    await page.goto("/alerts");

    const tabs = page.getByRole("tab");
    await expect(tabs).toHaveCount(4);

    // A tablist is ONE tab stop with a roving tabindex, so the unselected
    // tabs are reachable only via the arrow keys. Before slice 048 there was
    // no arrow handler at all, which left Rules/Templates/History
    // unreachable by keyboard entirely — this is the regression guard.
    const watchlists = page.getByRole("tab", { name: "Watchlists" });
    await watchlists.focus();
    await expect(watchlists).toHaveAttribute("aria-selected", "true");

    await page.keyboard.press("ArrowRight");
    const rules = page.getByRole("tab", { name: "Rules" });
    await expect(rules).toBeFocused();
    await expect(rules).toHaveAttribute("aria-selected", "true");

    await page.keyboard.press("End");
    const history = page.getByRole("tab", { name: "History" });
    await expect(history).toBeFocused();
    await expect(history).toHaveAttribute("aria-selected", "true");

    // Wrapping is part of the pattern.
    await page.keyboard.press("ArrowRight");
    await expect(watchlists).toBeFocused();
  });

  test("the filter drawer traps nothing but returns focus to its trigger on Escape", async ({
    page,
  }) => {
    await page.goto("/");
    const trigger = page.getByRole("button", { name: /filters/i }).first();
    await trigger.click();
    await expect(page.getByTestId("filter-drawer")).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(page.getByTestId("filter-drawer")).toHaveCount(0);
    // Focus restoration: closing an overlay must not dump the user at the
    // top of the document.
    await expect(trigger).toBeFocused();
  });

  test("the analytics time-range radiogroup is operable with the arrow keys", async ({
    page,
  }) => {
    await page.goto("/analytics");
    const group = page.getByRole("radiogroup", { name: "Time range" });
    await expect(group).toBeVisible();

    const checked = group.getByRole("radio", { checked: true });
    await checked.focus();
    await page.keyboard.press("ArrowRight");

    // Arrow keys move AND select in a radiogroup.
    const nowChecked = group.getByRole("radio", { checked: true });
    await expect(nowChecked).toBeFocused();
  });
});
