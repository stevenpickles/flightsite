/**
 * Flow — browser notification permission (roadmap slice 040, `docs/
 * TEST_STRATEGY.md` §4). Runs after 01 has completed first-run setup, so the
 * Settings page is reachable and the notification preferences it shows are
 * the ones the wizard wrote.
 *
 * **What a headless browser will and will not do**, learned the hard way from
 * two CI rounds. No automated engine presents the interactive permission model
 * a person sees, and no two of them decline in the same way: headless Chromium
 * has no notification centre to deliver to, so it reports a standing `denied`
 * that a CDP grant does not move, while headless Firefox reports `default` and
 * then never settles `requestPermission()` at all, because settling it is the
 * prompt's job and there is no prompt. An engine's native permission behaviour
 * is therefore not something a cross-browser spec can assert against — and
 * both rounds of failures came from trying.
 *
 * So the split here is between what the *browser* decides and what *FlightSite*
 * decides, and each is tested where it is deterministic:
 *
 * - **Loading FlightSite never asks** (test 1). `docs/SECURITY.md` §5 allows
 *   the permission to be requested only after the user opts in. Checked by
 *   counting real calls to `Notification.requestPermission` rather than by
 *   inspecting the resulting permission — stronger, and immune to whatever
 *   standing answer the engine gives.
 * - **The status the user sees is the status the browser reports** (test 2).
 *   Whichever of the five states this engine is in, Settings names that one,
 *   offers the ask only where asking could still work, and — in the `denied`
 *   state Chromium runs in — shows the remedy. That is the slice's "denied
 *   permission degrades cleanly with status surfaced" criterion, in a real
 *   browser.
 * - **Answering the prompt updates the UI** (test 3). The engine's prompt is
 *   stubbed at the `Notification` boundary, because that boundary is the only
 *   part of this flow no headless engine implements. What is under test is
 *   FlightSite's half — ask offered, ask made exactly once, answer reflected,
 *   ask withdrawn — and stubbing makes it the same assertion everywhere
 *   instead of three engine-specific ones.
 * - **A real grant, where an engine honours one** (test 4), which keeps one
 *   unstubbed path over the genuine permission machinery.
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

/** Where the prompt stub records what it did, on `window`. */
const STUB = "__flightsiteNotificationStub";

interface StubProbe {
  /** Whether the boundary was successfully replaced. */
  installed: boolean;
  /** How many times FlightSite asked. */
  calls: number;
}

/**
 * Replaces the engine's permission prompt with one that answers immediately.
 *
 * The only part of the flow no headless engine implements: Chromium refuses
 * before asking, Firefox never settles the promise because settling it is the
 * prompt's job. Both the request *and* the `permission` getter are replaced, so
 * the page is internally consistent afterwards — a component that re-reads the
 * standing permission (on a visibility change, say) must not see `default`
 * moments after being told `granted`.
 *
 * Starts at `default` regardless of what the engine would have said, so the
 * not-yet-asked state — the one Chromium never offers — is reachable and the
 * whole ask-and-answer flow can be driven in every engine.
 */
async function stubPermissionPrompt(page: Page): Promise<void> {
  await page.addInitScript((key: string) => {
    const store: { installed: boolean; calls: number } = {
      installed: false,
      calls: 0,
    };
    (window as unknown as Record<string, unknown>)[key] = store;
    if (typeof Notification === "undefined") {
      return;
    }
    let answer: NotificationPermission = "default";
    try {
      Object.defineProperty(Notification, "permission", {
        configurable: true,
        get: () => answer,
      });
      Notification.requestPermission = ((
        callback?: (permission: NotificationPermission) => void,
      ) => {
        store.calls += 1;
        answer = "granted";
        // Answer both ways the API can be consumed: the modern promise and
        // the legacy callback older Safari only supports. Resolving a
        // promise twice is a no-op, so serving both is safe.
        callback?.("granted");
        return Promise.resolve<NotificationPermission>("granted");
      }) as typeof Notification.requestPermission;
      store.installed = true;
    } catch {
      // Left uninstalled; the test asserts `installed` and will say so.
    }
  }, STUB);
}

async function stubProbe(page: Page): Promise<StubProbe> {
  return page.evaluate(
    (key: string) =>
      ((window as unknown as Record<string, unknown>)[key] as StubProbe) ?? {
        installed: false,
        calls: 0,
      },
    STUB,
  ) as Promise<StubProbe>;
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

  test("asking, and being told yes, turns the status to allowed", async ({
    page,
  }) => {
    // The prompt is stubbed (see `stubPermissionPrompt`): what is under test
    // is FlightSite's half of the exchange, which is identical in every
    // engine, rather than three engines' incompatible ways of declining to
    // show a prompt.
    await stubPermissionPrompt(page);
    await page.goto("/settings");

    const status = page.getByTestId(STATUS);
    await expect(status).toBeVisible();

    const state = await capability(page);
    test.skip(
      !state.api,
      "this engine exposes no Notification API to stub, so there is no ask to drive",
    );
    expect(
      (await stubProbe(page)).installed,
      "the permission prompt could not be stubbed, so this test drove nothing",
    ).toBe(true);

    // The not-yet-asked state, now reachable everywhere.
    await expect(status).toHaveAttribute("data-permission", "default");
    const ask = status.getByRole("button", { name: /allow notifications/i });
    await expect(ask).toBeVisible();

    await ask.click();

    await expect(status).toHaveAttribute("data-permission", "granted");
    await expect(status).toContainText(/browser permission: allowed/i);
    // The ask is withdrawn once answered — there is nothing left to ask.
    await expect(ask).toHaveCount(0);

    expect(
      (await stubProbe(page)).calls,
      "one click on the ask should ask the browser exactly once",
    ).toBe(1);
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
