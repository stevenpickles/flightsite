/**
 * Flow — browser notification permission (roadmap slice 040, `docs/
 * TEST_STRATEGY.md` §4). Runs after 01 has completed first-run setup, so the
 * Settings page is reachable and the notification preferences it shows are
 * the ones the wizard wrote.
 *
 * **What a headless browser will and will not do.** An automated engine does
 * not present the interactive permission model a person sees: headless
 * Chromium has no notification centre to deliver to, so it reports a standing
 * `denied` and a CDP grant does not move it, and Playwright cannot drive a
 * native permission prompt in any of the three engines. An earlier version of
 * this spec assumed the not-yet-asked state existed and every assertion in it
 * failed on CI for that one reason. So nothing here assumes a state: each test
 * asks the page what the browser actually reports and then asserts against
 * *that*, skipping with a reason where a state is unreachable — the same
 * capability escape hatch spec 04 uses for WebGL.
 *
 * That leaves two assertions that hold in every engine and are the two worth
 * having:
 *
 * - **Loading FlightSite never asks.** `docs/SECURITY.md` §5 allows the
 *   permission to be requested only after the user opts in. This is checked by
 *   counting real calls to `Notification.requestPermission` rather than by
 *   inspecting the resulting permission — which is both stronger and immune to
 *   whatever standing answer the engine happens to give.
 * - **The status the user sees is the status the browser reports.** Whichever
 *   of the five states this engine is in, Settings names that one, offers the
 *   ask only where asking could still work, and — in the `denied` state CI
 *   actually runs in — shows the remedy. That is the slice's "denied
 *   permission degrades cleanly with status surfaced" criterion, exercised in
 *   a real browser.
 *
 * Delivery itself (an alert becoming exactly one notification) is not here.
 * A demo alert fires at a fixed phase of the scenario's 30-minute rotation
 * (`flightsite.demo.roster.PERIOD_S`), so waiting for one from an arbitrary
 * start time is a coin toss, not a test. Dispatch, dedupe and the
 * severity-upgrade case are covered against the real protocol client in
 * `frontend/src/features/map/aircraft/useLiveConnection.test.tsx` and
 * `frontend/src/features/notifications/lib/dispatch.test.ts`; making a demo
 * alert observable end-to-end belongs with the "Interesting-aircraft alert"
 * flow that `docs/TEST_STRATEGY.md` §4 assigns to slice 046.
 */

import type { Page } from "@playwright/test";

import { waitForLiveAircraft } from "./support/liveMap";
import { expect, test } from "./support/fixtures";

const STATUS = "notification-permission-status";

/** Where the init script records what it saw, on `window`. */
const PROBE = "__flightsiteNotificationProbe";

interface AskProbe {
  /** Whether `requestPermission` was successfully wrapped. Asserted so a
   * failure to instrument shows up as a failure rather than as a test that
   * passes by never having watched anything. */
  patched: boolean;
  /** How many times the app asked the browser for permission. */
  calls: number;
}

/** What this engine can actually do, read from inside the page. */
interface Capability {
  /** Whether the Notification API exists here at all. */
  api: boolean;
  /** Whether the origin is one the engine considers trustworthy. */
  secure: boolean;
  /** The standing answer, or `null` where there is no API to ask. */
  permission: "default" | "granted" | "denied" | null;
}

async function capability(page: Page): Promise<Capability> {
  return page.evaluate(() => {
    const api = typeof Notification !== "undefined";
    return {
      api,
      secure: window.isSecureContext,
      permission: api ? (Notification.permission as Capability["permission"]) : null,
    };
  }) as Promise<Capability>;
}

/**
 * Counts real `Notification.requestPermission` calls for the life of the
 * page's JS context.
 *
 * Installed before any navigation so it is in place while the app boots. The
 * counter lives in the page context, so it survives client-side route changes
 * (which is how the Settings page is reached below) but resets on a full
 * reload — every assertion here is therefore made within one `goto`.
 */
async function watchForAsks(page: Page): Promise<void> {
  await page.addInitScript((key: string) => {
    const store = { patched: false, calls: 0 };
    (window as unknown as Record<string, unknown>)[key] = store;
    if (typeof Notification === "undefined") {
      return;
    }
    try {
      const original = Notification.requestPermission.bind(Notification);
      Notification.requestPermission = ((...args: unknown[]) => {
        store.calls += 1;
        return (original as (...rest: unknown[]) => unknown)(...args);
      }) as typeof Notification.requestPermission;
      store.patched = true;
    } catch {
      // Left unpatched; the test asserts `patched` and will say so.
    }
  }, PROBE);
}

async function askProbe(page: Page): Promise<AskProbe> {
  return page.evaluate(
    (key: string) =>
      ((window as unknown as Record<string, unknown>)[key] as AskProbe) ?? {
        patched: false,
        calls: 0,
      },
    PROBE,
  ) as Promise<AskProbe>;
}

/**
 * The state `NotificationPermissionStatus` must be reporting, derived from
 * what the browser says — mirroring `features/notifications/lib/permission.ts`
 * from the outside. The component publishes its own answer as
 * `data-permission`, so comparing the two is a direct check that FlightSite
 * and the browser agree.
 */
type PermissionState =
  | "granted"
  | "denied"
  | "default"
  | "unsupported"
  | "insecure-context";

function expectedState(state: Capability): PermissionState {
  if (!state.api) {
    return state.secure ? "unsupported" : "insecure-context";
  }
  return state.permission === "granted" || state.permission === "denied"
    ? state.permission
    : "default";
}

/** The label the user should see for that state. Asserted alongside the
 * attribute so the prose cannot go missing or contradict it. */
const LABELS: Record<PermissionState, RegExp> = {
  granted: /browser permission: allowed/i,
  denied: /browser permission: blocked/i,
  default: /browser permission: not requested/i,
  unsupported: /browser permission: unavailable in this browser/i,
  "insecure-context": /browser permission: unavailable on this address/i,
};

test.describe("browser notification permission", () => {
  test("is never requested by loading FlightSite or opening Settings", async ({
    page,
  }) => {
    await watchForAsks(page);

    // The Live Map holds the socket alerts arrive on — the one place an
    // implementation might be tempted to ask from. Waiting for live aircraft
    // means the config load (which says notifications are enabled), the
    // socket and the first frames have all happened before the assertion.
    await page.goto("/");
    await waitForLiveAircraft(page);

    const afterLoad = await askProbe(page);
    const state = await capability(page);
    if (state.api) {
      expect(
        afterLoad.patched,
        "requestPermission could not be instrumented, so this test watched nothing",
      ).toBe(true);
    }
    expect(afterLoad.calls, "loading the Live Map asked for permission").toBe(0);

    // Client-side navigation, so the counter above stays in scope: opening
    // the page that *owns* the ask must still not perform it.
    await page.getByRole("link", { name: "Settings" }).click();
    await expect(page.getByTestId(STATUS)).toBeVisible();

    expect(
      (await askProbe(page)).calls,
      "opening Settings asked for permission without being asked to",
    ).toBe(0);
  });

  test("Settings reports the state the browser actually reports", async ({
    page,
  }) => {
    await page.goto("/settings");
    const status = page.getByTestId(STATUS);
    await expect(status).toBeVisible();

    const state = await capability(page);
    const expected = expectedState(state);
    await expect(status).toHaveAttribute("data-permission", expected);
    await expect(status).toContainText(LABELS[expected]);

    // The ask is offered exactly where asking could still change the answer.
    const ask = status.getByRole("button", { name: /allow notifications/i });
    if (state.api && state.permission === "default") {
      await expect(ask).toBeVisible();
    } else {
      await expect(ask).toHaveCount(0);
    }

    // The state CI actually runs in: a standing denial, which must carry its
    // remedy rather than a dead end.
    if (state.api && state.permission === "denied") {
      await expect(status).toContainText(/site settings/i);
    }
  });

  test("asking the browser moves the status off 'not requested'", async ({
    page,
    context,
  }) => {
    await context.clearPermissions();
    await page.goto("/settings");

    const state = await capability(page);
    test.skip(
      !state.api || state.permission !== "default",
      `this engine reports "${state.permission ?? "no Notification API"}" rather than an askable state, and no automation can drive a native permission prompt`,
    );

    const status = page.getByTestId(STATUS);
    await status.getByRole("button", { name: /allow notifications/i }).click();

    // Which way the browser answers is its business; that FlightSite asked
    // and then reported the real answer is not.
    await expect(status).not.toContainText(/not requested/i);
    await expect(status).toContainText(/browser permission: (allowed|blocked)/i);
  });

  test("reports a granted permission, and stops offering to ask", async ({
    page,
    context,
    browserName,
  }) => {
    test.skip(
      browserName !== "chromium",
      "only Chromium lets Playwright grant the notifications permission",
    );
    await context.grantPermissions(["notifications"]);
    await page.goto("/settings");

    const state = await capability(page);
    test.skip(
      state.permission !== "granted",
      `granting had no effect — this engine still reports "${state.permission ?? "no Notification API"}"; headless Chromium has no notification centre to deliver to`,
    );

    const status = page.getByTestId(STATUS);
    await expect(status).toContainText(/browser permission: allowed/i);
    await expect(
      status.getByRole("button", { name: /allow notifications/i }),
    ).toHaveCount(0);
  });
});
