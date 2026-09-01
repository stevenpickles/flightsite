/**
 * Flow — browser notification permission (roadmap slice 040, `docs/
 * TEST_STRATEGY.md` §4). Runs after 01 has completed first-run setup, so the
 * Settings page is reachable and the notification preferences it shows are
 * the ones the wizard wrote.
 *
 * What only a real browser can prove, and therefore what this covers:
 *
 * - **Loading FlightSite does not ask.** `docs/SECURITY.md` §5 allows the
 *   permission to be requested only after the user opts in. jsdom can assert
 *   that no *mock* was called; only a real engine can confirm the real
 *   `Notification.permission` is untouched after the app has fully loaded,
 *   fetched its config (which says notifications are enabled) and connected
 *   its socket.
 * - **The status the user sees matches what the browser actually thinks**, in
 *   both the granted and the not-yet-asked states.
 * - **The ask is re-promptable from Settings**, and answering it moves the
 *   status off "Not requested" whichever way the browser answers.
 *
 * Chromium only. Playwright can grant and clear the notifications permission
 * in Chromium; Firefox and WebKit do not support it, and there is no way to
 * drive a native permission prompt in any of the three — so the other two
 * projects skip, the same capability escape hatch spec 04 uses for WebGL.
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

import { waitForLiveAircraft } from "./support/liveMap";
import { expect, test } from "./support/fixtures";

const STATUS = "notification-permission-status";

test.describe("browser notification permission", () => {
  test.skip(
    ({ browserName }) => browserName !== "chromium",
    "only Chromium lets Playwright grant or clear the notifications permission",
  );

  test("is never requested by loading FlightSite", async ({
    page,
    context,
  }) => {
    await context.clearPermissions();

    // The Live Map is the page that holds the socket alerts arrive on — the
    // one place an implementation might be tempted to ask from. Waiting for
    // live aircraft means the config load, the socket and the first frames
    // have all happened before the assertion.
    await page.goto("/");
    await waitForLiveAircraft(page);

    expect(await page.evaluate(() => Notification.permission)).toBe("default");
  });

  test("shows the not-yet-asked state in Settings, with the ask on offer", async ({
    page,
    context,
  }) => {
    await context.clearPermissions();
    await page.goto("/settings");

    const status = page.getByTestId(STATUS);
    await expect(status).toBeVisible();
    await expect(status).toContainText(/browser permission: not requested/i);
    await expect(
      status.getByRole("button", { name: /allow notifications/i }),
    ).toBeVisible();
  });

  test("asking the browser moves the status off 'not requested'", async ({
    page,
    context,
  }) => {
    await context.clearPermissions();
    await page.goto("/settings");

    const status = page.getByTestId(STATUS);
    await status.getByRole("button", { name: /allow notifications/i }).click();

    // Headless Chromium answers the request itself rather than showing a
    // prompt, and which way it answers is the browser's business — what
    // matters is that FlightSite asked and then reported the real answer.
    await expect(status).not.toContainText(/not requested/i);
    await expect(status).toContainText(/browser permission: (allowed|blocked)/i);
  });

  test("reports a granted permission, and stops offering to ask", async ({
    page,
    context,
  }) => {
    await context.grantPermissions(["notifications"]);
    await page.goto("/settings");

    const status = page.getByTestId(STATUS);
    await expect(status).toContainText(/browser permission: allowed/i);
    await expect(
      status.getByRole("button", { name: /allow notifications/i }),
    ).toHaveCount(0);
  });
});
