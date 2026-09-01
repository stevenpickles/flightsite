/**
 * Runs once before the visual suite (roadmap slice 047).
 *
 * Its only job is to stop the run early when the environment cannot produce
 * comparable pixels. Failing here rather than inside the first test matters:
 * a `--update-snapshots` run on the wrong platform would otherwise overwrite
 * the committed Linux baselines one file at a time before anyone noticed.
 *
 * Loading the fixture store is the second half of the check — it throws a
 * pointed "run `npm run visual:capture`" error if the recording is missing,
 * and doing that here means one clear message instead of the same failure
 * repeated across every spec.
 */

import { FIXTURE_MANIFEST } from "./fixtureStore";
import { assertPinnedRenderer } from "./stabilize";

export default function globalSetup(): void {
  assertPinnedRenderer();
  console.log(
    `[visual] replaying fixtures captured at ${FIXTURE_MANIFEST.frozenClock} ` +
      `(${FIXTURE_MANIFEST.aircraftInSnapshot} aircraft, ` +
      `detail aircraft ${FIXTURE_MANIFEST.detailIcao.toUpperCase()}, ` +
      `analytics preset "${FIXTURE_MANIFEST.analyticsPreset}")`,
  );
}
