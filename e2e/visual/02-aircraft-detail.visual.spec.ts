/**
 * Aircraft detail baselines (roadmap slice 047, SPEC §83).
 *
 * The full-page detail view at `/aircraft/:icao` — identity and metadata
 * with its provenance markers, manufacture/ownership, the SPEC §53 lifetime
 * records, recent sightings, and the external tracker links.
 *
 * The ICAO is not hard-coded here: it is whichever aircraft the capture
 * chose (lowest ICAO with both a callsign and a position), recorded in the
 * fixture manifest. Reading it from the manifest means a re-capture that
 * lands on a different aircraft updates the fixture and the baseline
 * together, instead of leaving a spec pointing at an ICAO the HAR no longer
 * contains.
 */

import {
  FIXTURE_MANIFEST,
  expect,
  expectFitsWithoutScrolling,
  expectNoLoadFailures,
  openView,
  test,
} from "./support/replay";
import { VISUAL_THEMES } from "./support/stabilize";

/** Tall enough to hold the whole detail column without scrolling — see
 * `expectFitsWithoutScrolling`, which fails the run if it stops being. */
const VIEWPORT_HEIGHT = 1050;

for (const theme of VISUAL_THEMES) {
  test(`aircraft detail — ${theme}`, async ({ page }) => {
    await openView(
      page,
      `/aircraft/${FIXTURE_MANIFEST.detailIcao}`,
      theme,
      VIEWPORT_HEIGHT,
    );

    // `AircraftDetailPage` renders this exact heading for both "not found"
    // and "could not load", so asserting the section headings — which only
    // exist on the success path — is what proves the fixture served real
    // detail data rather than an error card.
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByRole("heading", { name: "History" })).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Recent sightings" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "External trackers" }),
    ).toBeVisible();
    await expect(page.getByText(/^Loading/)).toHaveCount(0);

    await expectNoLoadFailures(page);
    await expectFitsWithoutScrolling(page);

    await expect(page).toHaveScreenshot(`aircraft-detail-${theme}.png`);
  });
}
