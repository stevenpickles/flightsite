/**
 * The replay environment every visual spec runs inside (roadmap slice 047).
 *
 * Extends Playwright's `page` so that, before a spec does anything, the
 * browser is sealed off from the world and from time:
 *
 *   - every `/api/v1` and `/api/internal` request is answered from the
 *     committed HAR, so responses are byte-identical on every run
 *   - `/api/v1/ws/live` is served one frozen snapshot frame and then goes
 *     quiet, so the live picture stops moving
 *   - basemap tile hosts are blocked, as in the flow suite
 *   - `Date.now()` is frozen and CSS motion is neutralized
 *
 * Nothing reaches a network. There is no backend in a visual run.
 */

import { readFileSync } from "node:fs";

import { test as base, expect, type Page } from "@playwright/test";

import { FIXTURE_MANIFEST, HAR_PATH, LIVE_SNAPSHOT } from "./fixtureStore";
import {
  disableMotion,
  freezeClock,
  pinTheme,
  type VisualTheme,
} from "./stabilize";

export { expect, FIXTURE_MANIFEST };
export type { VisualTheme };

/** Mirrors `LIVE_WS_PATH` in `frontend/src/lib/ws/protocol.ts`. */
const LIVE_WS_PATH = "/api/v1/ws/live";

export const test = base.extend({
  page: async ({ page }, use) => {
    // --- REST -----------------------------------------------------------
    // `notFound: "abort"` rather than falling through to the network: there
    // is no backend to fall through to, and a silent fallback would turn a
    // missing fixture into a mystery timeout. An abort surfaces as the
    // view's error state, which the per-spec content assertions then fail
    // on — the specs deliberately assert real captured values before
    // screenshotting, so "the fixture set no longer covers this view" fails
    // loudly instead of quietly baselining an error card.
    await page.routeFromHAR(HAR_PATH, {
      url: "**/api/**",
      notFound: "abort",
    });

    // The airports overlay is the one request whose URL the client derives
    // from rendered geometry: `bbox` comes from MapLibre's `getBounds()`,
    // formatted as full-precision floats. That is reproducible in principle
    // — same viewport, same camera — but it is reproducible across two
    // different machines' GL stacks only by luck, and a one-ULP difference
    // would miss the HAR entry and abort the overlay. Serving the recorded
    // airports response for any bbox removes the whole failure mode.
    //
    // Registered AFTER the HAR router because Playwright matches route
    // handlers in reverse registration order — last registered wins.
    const airportsEntry = findHarEntry("/api/v1/airports");
    if (airportsEntry) {
      await page.route("**/api/v1/airports*", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: airportsEntry,
        });
      });
    }

    // --- Basemap tiles ---------------------------------------------------
    // Same block the flow suite applies (`tests/support/fixtures.ts`) and
    // the same block capture applied, so the baselines lock the map's
    // documented degraded appearance ("Basemap unavailable — rings and
    // receiver position still shown") rather than a third party's tiles.
    // `docs/TEST_STRATEGY.md` §5: no live internet tiles in any test.
    await page.route("https://tiles.openfreemap.org/**", (route) => route.abort());
    await page.route("https://tile.openstreetmap.org/**", (route) => route.abort());

    // --- Live socket -----------------------------------------------------
    // One snapshot frame, then silence. The client treats a snapshot as the
    // complete live picture (§4.2) and applies no further change without a
    // delta, so the map, the aircraft count and every panel fed by the live
    // store hold exactly the captured state for as long as the page is open.
    // Serving the real socket instead would repaint at 1 Hz forever, which
    // no screenshot can be taken of twice.
    //
    // `seq` is 1 in the captured frame, which is what the protocol requires
    // of the first frame on a connection — the client's gap detection is
    // therefore satisfied and it never tries to resync.
    await page.routeWebSocket((url) => url.pathname === LIVE_WS_PATH, (ws) => {
      // Swallow anything the client sends (it only ever sends a pong, and
      // only in reply to a ping this stub never sends). Not registering a
      // message handler would be fine too; being explicit documents that
      // the silence is deliberate.
      ws.onMessage(() => {});
      ws.send(JSON.stringify(LIVE_SNAPSHOT));
    });

    // --- Time and motion -------------------------------------------------
    await freezeClock(page);
    await disableMotion(page);

    await use(page);
  },
});

/**
 * Pins the theme and navigates, in that order.
 *
 * The order is the point: `pinTheme` installs an init script, and
 * `frontend/index.html`'s blocking head script reads the value it writes
 * before the first paint. Navigating first and setting the theme afterwards
 * would render the dark default and then repaint, which is both slower and
 * a chance to photograph the wrong theme.
 */
export async function openView(
  page: Page,
  urlPath: string,
  theme: VisualTheme,
  viewportHeight?: number,
): Promise<void> {
  if (viewportHeight !== undefined) {
    // Taller viewport instead of `fullPage: true` — see
    // `expectFitsWithoutScrolling` for why full-page capture cannot reach
    // this app's content. Width stays at the configured 1440 so the
    // responsive grid keeps the same column count in every baseline.
    await page.setViewportSize({ width: 1440, height: viewportHeight });
  }
  await pinTheme(page, theme);
  await page.goto(urlPath);
}

/**
 * Asserts the view rendered real data rather than an error state.
 *
 * Every spec calls this before photographing, and it exists because of a
 * failure this suite actually had during development: the fixtures were
 * recorded on one origin and replayed on another, Playwright's HAR router
 * matched nothing, every request aborted, and each card rendered "Failed to
 * fetch". The screenshots were still perfectly deterministic — deterministic
 * pictures of a broken app — and the heading assertions all passed, because
 * headings paint whether or not their data arrives.
 *
 * Per-view content assertions catch most of that, but only where a spec
 * thought to add one. This is the blanket check: no view in this suite may
 * contain a load-failure message at the moment it is captured.
 *
 * "Failed to fetch" is what a network-level abort surfaces as through
 * `apiFetch`; "Could not load" prefixes the hand-written error strings on
 * the aircraft-detail, scorecard, chart-card and lifetime sections.
 */
export async function expectNoLoadFailures(page: Page): Promise<void> {
  await expect(
    page.getByText(/Failed to fetch|Could not load/),
    "the view rendered a load-failure message — the fixture set no longer covers it",
  ).toHaveCount(0);
}

/**
 * Asserts the whole view is inside the viewport, so nothing is cropped.
 *
 * `fullPage: true` is the obvious way to photograph a long page and it does
 * not work here. The app shell is a fixed-height layout whose `<main>` is
 * its own scroll container, so the document itself never grows — a full-page
 * screenshot returns the viewport plus empty background, silently cropping
 * every card below the fold. The fix is a viewport tall enough to hold the
 * content; this is the check that the chosen height is still tall enough.
 *
 * Without it, a view that grows past its height would quietly lose its lower
 * half from the baseline, and the suite would go on passing — a regression
 * in the part of the page nobody can see any more would be invisible.
 */
export async function expectFitsWithoutScrolling(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => {
    const scroller = document.querySelector("main");
    if (!scroller) {
      return null;
    }
    return {
      scrollHeight: scroller.scrollHeight,
      clientHeight: scroller.clientHeight,
    };
  });
  expect(overflow, "no <main> element to measure").not.toBeNull();
  expect(
    overflow!.scrollHeight,
    `view is taller than the viewport (${overflow!.scrollHeight}px of content in ` +
      `${overflow!.clientHeight}px) — the screenshot would be cropped. ` +
      "Raise this spec's viewport height and regenerate the baseline.",
  ).toBeLessThanOrEqual(overflow!.clientHeight);
}

interface HarLog {
  log: {
    entries: {
      request: { url: string };
      response: { content?: { text?: string } };
    }[];
  };
}

/** Parsed once per worker: the HAR is ~200 KB and every test would otherwise
 * re-read and re-parse it just to answer the airports override. */
let harCache: HarLog | null = null;

/**
 * Reads one recorded response body out of the HAR by URL path prefix. Used
 * only for the airports override above; every other request goes through
 * Playwright's own HAR router.
 *
 * Returns `null` rather than throwing when nothing matches — a fixture set
 * recorded before this endpoint existed simply has no entry, and the
 * override then does not install, leaving the request to abort exactly as
 * any other unmatched request would.
 */
function findHarEntry(pathPrefix: string): string | null {
  harCache ??= JSON.parse(readFileSync(HAR_PATH, "utf8")) as HarLog;
  const entry = harCache.log.entries.find((candidate) =>
    new URL(candidate.request.url).pathname.startsWith(pathPrefix),
  );
  return entry?.response?.content?.text ?? null;
}
