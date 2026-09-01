/**
 * Flow (a) — first-run setup wizard (roadmap slice 020, `docs/TEST_STRATEGY.md`
 * §4). Runs first against a freshly-booted stack (fresh data dir, no
 * `config.yaml` yet): `GET /api/internal/config` reports `first_run: true`,
 * `RootLayout` redirects every route to `/setup`, and completing the wizard
 * lands on the Live Map and never shows the wizard again.
 *
 * Every later spec file in this suite assumes setup has already been
 * completed by this file — see playwright.config.ts's file-ordering note.
 */

import { expect, test } from "./support/fixtures";

test.describe.configure({ mode: "serial" });

test.describe("first-run setup wizard", () => {
  test("a fresh install redirects to /setup, and completing it lands on the Live Map for good", async ({
    page,
  }) => {
    await page.goto("/");
    await expect(page).toHaveURL(/\/setup$/);
    await expect(
      page.getByRole("heading", { name: "Welcome to FlightSite" }),
    ).toBeVisible();

    // Step 1: welcome / site name.
    await page.getByLabel("Site name").fill("E2E Test Site");
    await page.getByRole("button", { name: "Next" }).click();

    // Step 2: location — manual lat/lon entry (SPEC §13). Deliberately the
    // demo scenario's own traffic center (`DEFAULT_CENTER`,
    // `backend/src/flightsite/demo/adapter.py`) rather than an arbitrary
    // real-world site: the demo adapter's population is generated once at
    // process startup, centered wherever the receiver location was *then*
    // (unconfigured on a fresh install, so `DEFAULT_CENTER`), and does not
    // recenter when the wizard saves a different location afterward.
    // Matching it here is what makes the flow (d) selection/detail test's
    // map click land on visible traffic instead of off-screen aircraft.
    await expect(
      page.getByRole("heading", { name: "Receiver location" }),
    ).toBeVisible();
    await page.getByLabel("Latitude").fill("39.82830");
    await page.getByLabel("Longitude").fill("-98.57950");
    await page.getByRole("button", { name: "Next" }).click();

    // Step 3: decoder — demo mode needs no decoder, so this flow uses the
    // skip affordance (flow (b) exercises the connection test itself).
    await expect(
      page.getByRole("heading", { name: "Decoder endpoint" }),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();
    await page
      .getByRole("button", { name: "Skip test — decoder may be offline" })
      .click();
    await expect(page.getByRole("status")).toContainText("Test skipped");
    await page.getByRole("button", { name: "Next" }).click();

    // Step 4: units & timezone — schema defaults are already valid.
    await expect(page.getByRole("heading", { name: "Units" })).toBeVisible();
    await page.getByRole("button", { name: "Next" }).click();

    // Step 5: notifications — defaults are always valid.
    await expect(
      page.getByRole("heading", { name: "Browser notifications" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Next" }).click();

    // Step 6: metadata — entirely optional.
    await expect(
      page.getByRole("heading", { name: "Metadata & enrichment" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Next" }).click();

    // Step 7: alert templates — any selection, including none, is valid.
    await expect(
      page.getByRole("heading", { name: "Alert templates" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Next" }).click();

    // Step 8: review + finish.
    await expect(page.getByRole("heading", { name: "Review" })).toBeVisible();
    await expect(page.getByText("E2E Test Site")).toBeVisible();
    await expect(page.getByText("Skipped")).toBeVisible();
    await page.getByRole("button", { name: "Finish setup" }).click();

    // Lands on the Live Map.
    await expect(page).toHaveURL("http://127.0.0.1:8080/");
    await expect(page.locator('[role="status"][data-status]')).toBeVisible();

    // A reload must never show the wizard again — the wizard-redirect
    // acceptance criterion from roadmap slice 018, re-verified end to end
    // here now that setup has actually been completed against a real
    // backend.
    await page.reload();
    await expect(page).toHaveURL("http://127.0.0.1:8080/");
    await expect(
      page.getByRole("heading", { name: "Setup wizard" }),
    ).toHaveCount(0);
  });
});
