/**
 * Project-wide fixtures for the FlightSite E2E suite.
 *
 * `page` is extended with a standing block on the external basemap tile
 * service (`docs/TEST_STRATEGY.md` §5: "No external network in tests ...
 * tiles are mocked/stubbed in all automated suites; offline behavior is
 * itself a tested path"). `MapLibreMap.tsx` already has a first-class
 * degraded mode for exactly this ("Basemap unavailable — rings and receiver
 * position still shown") — range rings, the receiver marker, and the
 * aircraft layer are all client-drawn GeoJSON with locally-generated icons
 * (SVG data URIs, no network), so blocking the live tile host exercises a
 * real, already-tested code path rather than skipping coverage, and keeps
 * every flow's timing independent of a third party's latency or
 * availability from wherever CI happens to run.
 */

import { test as base, expect } from "@playwright/test";

export const test = base.extend({
  page: async ({ page }, use) => {
    await page.route("https://tiles.openfreemap.org/**", (route) => route.abort());
    await use(page);
  },
});

export { expect };
