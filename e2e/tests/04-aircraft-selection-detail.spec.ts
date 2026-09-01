/**
 * Flow (d) — aircraft selection + detail panel (roadmap slice 020, `docs/
 * TEST_STRATEGY.md` §4). Clicks a real, currently-live aircraft on the map
 * canvas — there is no non-canvas selection affordance yet (`useAircraftLayer.ts`:
 * one map-level click handler resolves the feature under the cursor) — and
 * confirms the detail panel opens with identifying fields, then closes on
 * Escape.
 *
 * The click target is computed by asking the live MapLibre instance itself
 * to project the aircraft's real lat/lon (see `support/liveMap.ts`'s
 * `clickAircraftOnMap`), not by reimplementing Web Mercator math in the
 * test. Demo aircraft keep moving between the API fetch and the click
 * landing, so this retries against a freshly-fetched, preferably-stationary
 * candidate a few times before failing.
 */

import {
  clickAircraftOnMap,
  fetchPositionedAircraft,
  mapIsAvailable,
  pickStableAircraft,
  waitForAircraftLayer,
  waitForLiveAircraft,
} from "./support/liveMap";
import { expect, test } from "./support/fixtures";

test.describe("aircraft selection + detail panel", () => {
  test("clicking a live aircraft opens its detail panel; Escape closes it", async ({
    page,
    request,
  }) => {
    await page.goto("/");
    test.skip(
      !(await mapIsAvailable(page)),
      "browser has no WebGL — canvas selection cannot render; degradation is unit-tested",
    );
    await waitForLiveAircraft(page);
    await waitForAircraftLayer(page);

    const panel = page.getByTestId("aircraft-detail-panel");
    await expect(panel).toHaveCount(0);

    const attempts = 5;
    let matched = false;
    let lastIcao = "";
    // Ruled out on a prior attempt (opened the wrong aircraft's panel, or
    // never opened one at all) — excluded so `pickStableAircraft` moves on
    // to its next-best candidate instead of retrying the same ambiguous
    // spot forever.
    const excluded = new Set<string>();
    for (let attempt = 0; attempt < attempts && !matched; attempt += 1) {
      const candidates = await fetchPositionedAircraft(request);
      const aircraft = pickStableAircraft(candidates, excluded);
      lastIcao = aircraft.icao;
      excluded.add(aircraft.icao);

      await clickAircraftOnMap(page, aircraft);

      const opened = await panel
        .waitFor({ state: "visible", timeout: 3_000 })
        .then(() => true)
        .catch(() => false);
      if (!opened) {
        continue;
      }

      // A click can in principle land on a neighbouring icon (overlapping
      // traffic, or the target having moved) — confirm the panel shows the
      // aircraft actually clicked before accepting this attempt, retrying
      // otherwise rather than asserting against the wrong aircraft.
      matched = await panel
        .getByText(new RegExp(`ICAO ${lastIcao.toUpperCase()}`))
        .isVisible()
        .catch(() => false);
      if (!matched) {
        await page.keyboard.press("Escape");
        await expect(panel).not.toBeVisible();
      }
    }

    expect(
      matched,
      `detail panel never showed the clicked aircraft (last tried ${lastIcao}) after ${attempts} attempts`,
    ).toBe(true);

    // Identifying fields: the panel's top-level heading is the callsign
    // (or the ICAO hex fallback) — `level: 2` distinguishes it from the
    // per-section `<h3>`s ("Live", "Identity & metadata", ...) also inside
    // the panel (`AircraftDetailPanel.tsx` / `DetailSection.tsx`).
    await expect(panel.getByRole("heading", { level: 2 })).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(panel).not.toBeVisible();
  });
});
