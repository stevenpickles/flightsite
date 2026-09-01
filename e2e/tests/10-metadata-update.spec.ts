/**
 * Flow — metadata update (roadmap slice 046, `docs/TEST_STRATEGY.md` §4;
 * SPEC §27's per-source import outcomes).
 *
 * Why this flow is stubbed at the internal API, and why that is the honest
 * choice here
 * ---------------------------------------------------------------------------
 * A metadata update downloads three real datasets — the Mictronics database,
 * the FAA releasable-aircraft registry, and the OurAirports table — from the
 * public internet. That download happens **server-side, inside the backend
 * container**, so the browser never sees those requests and no amount of
 * `page.route` against `raw.githubusercontent.com` or `registry.faa.gov`
 * would stop them. There is deliberately no local-source override: the
 * providers' URLs are constructor arguments used by backend unit tests, not
 * configuration a running container exposes.
 *
 * Letting the real update run is therefore not an option. It would violate
 * `docs/TEST_STRATEGY.md` §3's "no external network in tests", make the suite
 * depend on three third parties' availability from wherever CI runs, take
 * minutes (the FAA fetch alone allows 120 s), and write metadata rows and
 * activity events into the database the later specs read — a dirty stack, in
 * exchange for testing someone else's HTTP server.
 *
 * So the boundary is drawn where the interesting behaviour actually lives.
 * The two internal endpoints are intercepted and driven through a scripted
 * lifecycle, and what is under test is FlightSite's half of the exchange,
 * which is the half this project wrote:
 *
 * - the action is offered, and starts an update on one click;
 * - the UI commits to the in-flight state — the button stops accepting
 *   clicks, the source says "Running" — rather than looking idle while work
 *   happens;
 * - polling stops on its own once every source settles, and the outcome is
 *   reported per source (SPEC §27: one source failing neither hides nor
 *   delays another's success);
 * - the "last updated" line moves from "never" to a real time.
 *
 * The import machinery underneath has its own direct coverage in the backend
 * suite, against fixtures rather than the live internet.
 *
 * **The interception is installed before the first navigation**, not before
 * the first click: the status endpoint is polled as soon as Settings mounts,
 * and a single real POST would start a multi-minute download that outlives
 * the test.
 */

import type { Page, Route } from "@playwright/test";

import { expect, test } from "./support/fixtures";

/** The sources the backend registers (`app.py`'s metadata registry). */
const SOURCES = ["mictronics", "faa", "airports"] as const;

/** Where the scripted backend currently is. */
type Phase = "never-run" | "running" | "done";

interface SourceEntry {
  name: string;
  status: string;
  last_success_ms: number | null;
  dataset_version: string | null;
  row_count: number | null;
  last_error: string | null;
}

/** The moment the scripted update "finished" — fixed, so the rendered time is
 * a function of the script rather than of when the test happened to run. */
const COMPLETED_AT_MS = Date.UTC(2026, 7, 31, 12, 0, 0);

function statusBody(phase: Phase): { sources: SourceEntry[] } {
  return {
    sources: SOURCES.map((name, index) => {
      if (phase === "never-run") {
        return {
          name,
          status: "never-run",
          last_success_ms: null,
          dataset_version: null,
          row_count: null,
          last_error: null,
        };
      }
      if (phase === "running") {
        return {
          name,
          status: "running",
          last_success_ms: null,
          dataset_version: null,
          row_count: null,
          last_error: null,
        };
      }
      return {
        name,
        status: "ok",
        last_success_ms: COMPLETED_AT_MS,
        dataset_version: `2026.08.${index + 1}`,
        row_count: 100_000 + index,
        last_error: null,
      };
    }),
  };
}

/**
 * Installs the scripted metadata backend and returns a handle for advancing
 * it.
 *
 * Both endpoints are intercepted. The trigger records that it was called —
 * asserted, so a test cannot pass by never having driven anything — and the
 * status endpoint answers from whatever phase the script is in.
 */
async function installScriptedMetadataApi(page: Page) {
  const state = { phase: "never-run" as Phase, triggers: 0 };

  await page.route("**/api/internal/metadata/status", (route: Route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(statusBody(state.phase)),
    }),
  );

  await page.route("**/api/internal/metadata/update", (route: Route) => {
    if (route.request().method() !== "POST") {
      return route.fallback();
    }
    state.triggers += 1;
    state.phase = "running";
    return route.fulfill({
      status: 202,
      contentType: "application/json",
      body: JSON.stringify({
        started: true,
        already_running: false,
        started_ms: COMPLETED_AT_MS,
      }),
    });
  });

  return state;
}

/** Opens Settings and scrolls the metadata section into view — it sits far
 * down a long page. */
async function openMetadataSection(page: Page) {
  await page.goto("/settings");
  const button = page.getByTestId("metadata-update-button");
  await button.scrollIntoViewIfNeeded();
  await expect(button).toBeVisible();
  return button;
}

test.describe("metadata update", () => {
  test("runs an update from Settings and reports each source's outcome", async ({
    page,
  }) => {
    const script = await installScriptedMetadataApi(page);

    const button = await openMetadataSection(page);

    // Nothing has ever been imported on this fresh install, and the UI says
    // so plainly rather than showing an empty or ambiguous age.
    await expect(page.getByTestId("metadata-age-line")).toContainText("never");
    await expect(button).toBeEnabled();
    await expect(button).toHaveText("Update Aircraft Metadata");

    // Every registered source has a card of its own from the start — SPEC
    // §27's per-source reporting is not something that only appears on
    // failure.
    for (const name of SOURCES) {
      await expect(
        page.locator(`[data-testid="metadata-source-card"][data-source="${name}"]`),
      ).toBeVisible();
    }

    await button.click();

    // In flight: the action withdraws itself so a second click cannot start a
    // second run, and each source says it is working.
    await expect(button).toBeDisabled();
    await expect(button).toHaveText("Updating…");
    const statuses = page.getByTestId("metadata-source-status");
    await expect(statuses.first()).toHaveAttribute("data-status", "running");
    await expect(page.getByText("Running").first()).toBeVisible();

    expect(
      script.triggers,
      "one click should have started exactly one update",
    ).toBe(1);

    // Let the scripted run finish. The page is polling while anything is
    // running, so it picks this up on its own next poll — no reload.
    script.phase = "done";

    // Settled: the outcome is reported per source, with the dataset actually
    // installed.
    for (const name of SOURCES) {
      const card = page.locator(
        `[data-testid="metadata-source-card"][data-source="${name}"]`,
      );
      await expect(card.getByTestId("metadata-source-status")).toHaveAttribute(
        "data-status",
        "ok",
      );
      await expect(card).toContainText("Up to date");
      await expect(card).toContainText("Version 2026.08.");
    }

    // The action is offered again, and the age line has moved off "never".
    await expect(button).toBeEnabled();
    await expect(button).toHaveText("Update Aircraft Metadata");
    await expect(page.getByTestId("metadata-age-line")).not.toContainText(
      "never",
    );

    // Polling stops once everything has settled (`useMetadataStatusQuery`
    // returns `false` for its interval), so no further run was started behind
    // the assertions above.
    expect(
      script.triggers,
      "the update was triggered more than once",
    ).toBe(1);
  });

  test("a failing source reports itself without hiding the others", async ({
    page,
  }) => {
    // SPEC §27: a failed import leaves the previous dataset intact and must
    // not delay or mask a sibling source's success. Driven here because a
    // real failure would need one of three third parties to be down.
    await page.route("**/api/internal/metadata/status", (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          sources: [
            {
              name: "mictronics",
              status: "ok",
              last_success_ms: COMPLETED_AT_MS,
              dataset_version: "2026.08.1",
              row_count: 123_456,
              last_error: null,
            },
            {
              name: "faa",
              status: "failed",
              last_success_ms: COMPLETED_AT_MS,
              dataset_version: "2026.07.9",
              row_count: 99_000,
              last_error: "download timed out after 120s",
            },
          ],
        }),
      }),
    );

    await openMetadataSection(page);

    const ok = page.locator(
      '[data-testid="metadata-source-card"][data-source="mictronics"]',
    );
    await expect(ok.getByTestId("metadata-source-status")).toHaveAttribute(
      "data-status",
      "ok",
    );

    const failed = page.locator(
      '[data-testid="metadata-source-card"][data-source="faa"]',
    );
    await expect(failed.getByTestId("metadata-source-status")).toHaveAttribute(
      "data-status",
      "failed",
    );
    // The reason, and the reassurance that the previous dataset survived.
    await expect(failed.getByRole("alert")).toContainText(
      "download timed out after 120s",
    );
    await expect(failed).toContainText("did not lose what it had");
    // Which it demonstrably did — the older version is still on the card.
    await expect(failed).toContainText("Version 2026.07.9");
  });

  test("a refused trigger surfaces the error instead of pretending to work", async ({
    page,
  }) => {
    await page.route("**/api/internal/metadata/status", (route: Route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(statusBody("never-run")),
      }),
    );
    await page.route("**/api/internal/metadata/update", (route: Route) =>
      route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "metadata importer is unavailable" }),
      }),
    );

    const button = await openMetadataSection(page);
    await button.click();

    await expect(page.getByRole("alert").first()).toContainText(
      /metadata importer is unavailable|Could not start the update/,
    );
    // And the action stays available, rather than being left stuck in a
    // busy state that no poll will ever clear.
    await expect(button).toBeEnabled();
  });
});
