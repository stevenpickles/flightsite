/**
 * Flow (b) — decoder connection test (roadmap slice 020, `docs/
 * TEST_STRATEGY.md` §4). Runs after flow (a) has completed setup, so `/setup`
 * now opens in edit mode (SPEC: re-running the wizard from Settings).
 *
 * Demo mode has no real decoder to probe (`docs/DEVELOPMENT.md` "demo mode
 * ... no decoder and no internet"), so there is no honest success path to
 * exercise end to end here — the connection test always targets something
 * genuinely unreachable in this environment. This flow instead covers what
 * IS honestly testable: a clear, actionable failure message for an
 * unreachable endpoint, and the separate skip affordance that lets setup
 * proceed anyway (`DecoderStep.tsx`). The success rendering path
 * (`describeConnectionSuccess`) has direct unit coverage in
 * `frontend/src/features/setup/lib/decoderTestMessage.test.ts`.
 */

import { expect, test } from "./support/fixtures";

test.describe.configure({ mode: "serial" });

test.describe("decoder connection test", () => {
  test("an unreachable endpoint fails clearly, and the skip affordance unblocks setup", async ({
    page,
  }) => {
    await page.goto("/setup");
    // Confirms this really is the edit-mode re-run (SPEC: prefilled from the
    // already-saved config from flow (a)), not a fresh-install redirect.
    await expect(
      page.getByRole("heading", { name: "Update your setup" }),
    ).toBeVisible();

    // Welcome and location are already valid (prefilled from saved config).
    await page.getByRole("button", { name: "Next" }).click();
    await expect(
      page.getByRole("heading", { name: "Receiver location" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Next" }).click();

    await expect(
      page.getByRole("heading", { name: "Decoder endpoint" }),
    ).toBeVisible();

    // Port 9 on the backend container's own loopback has nothing listening
    // — a fast, deterministic "connection refused" rather than a slow
    // timeout, and an honest test of the failure path (no decoder exists
    // in demo mode to succeed against).
    await page.getByLabel("Port").fill("9");
    await page.getByRole("button", { name: "Test connection" }).click();

    const testStatus = page.getByRole("status");
    await expect(testStatus).toContainText("Unreachable", { timeout: 15_000 });
    await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();

    // The skip affordance is the documented escape hatch: the decoder may
    // legitimately be offline during setup (SPEC §11).
    await page
      .getByRole("button", { name: "Skip test — decoder may be offline" })
      .click();
    await expect(testStatus).toContainText("Test skipped");
    await expect(page.getByRole("button", { name: "Next" })).toBeEnabled();

    // Deliberately never finished — this only probes the connection test
    // and skip affordance, not a config change, so leaving the wizard
    // without saving keeps the config flow (a) already persisted untouched
    // for the remaining flows.
  });
});
