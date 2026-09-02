/**
 * The contract shared by fixture capture and fixture replay (roadmap slice
 * 047).
 *
 * Both halves of the visual suite have to agree on where the fixtures live,
 * what is in them, and which view state they describe — and they run in
 * different processes against different configs, so the agreement has to be
 * written down somewhere neither owns. This is that place. It deliberately
 * imports nothing from Playwright so either side can use it freely.
 */

import { STACK_BASE_URL } from "../../stackContract";

/** Directory (relative to `visual/`) holding the committed fixture set. */
export const FIXTURE_DIR_NAME = "fixtures";

/**
 * Origin the fixtures are RECORDED against — the compose stack's published
 * port (`compose.yaml`), which is what the demo stack serves on.
 *
 * Derived from `stackContract.ts` rather than repeated, so moving the
 * published host port cannot leave capture aimed at an origin nothing is
 * listening on. That particular mismatch fails quietly: `rewriteHar.ts` only
 * `console.warn`s when it rewrites no entries, so the result is a committed
 * fixture set full of "Failed to fetch" states rather than an error.
 */
export const CAPTURE_BASE_URL = STACK_BASE_URL;

/**
 * Origin the fixtures are REPLAYED against — `vite preview` over
 * `frontend/dist`, started by the visual config's `webServer`.
 *
 * These two differ, and that difference is load-bearing enough to be worth
 * spelling out: Playwright's HAR router matches a request against recorded
 * entries by full URL, origin included, so a recording made on the compose
 * stack's port matches nothing when replayed on :4173 — every API call aborts
 * and every view quietly renders its error state, which a screenshot will
 * happily baseline.
 * `visual/capture/rewriteHar.ts` rewrites the recorded origin to this one as
 * the last step of a capture, which is why the committed HAR names :4173.
 *
 * Fixed rather than configurable on purpose. Making the port an environment
 * override would let a run replay against an origin the fixtures were never
 * rewritten to, reintroducing exactly the silent failure the rewrite exists
 * to prevent.
 */
export const VISUAL_PORT = 4173;
export const VISUAL_BASE_URL = `http://127.0.0.1:${VISUAL_PORT}`;

export const HAR_FILE_NAME = "api.har";
export const LIVE_SNAPSHOT_FILE_NAME = "live-snapshot.json";
export const MANIFEST_FILE_NAME = "manifest.json";

/**
 * Receiver coordinates written during capture.
 *
 * These are not arbitrary: they are `DEFAULT_CENTER` from
 * `backend/src/flightsite/demo/adapter.py`. The demo roster is built once at
 * backend startup around that point and never recenters when the config is
 * later saved with a different location, so configuring any other
 * coordinates would leave the map looking at empty sky. The flow suite's
 * first-run spec types these same numbers into the wizard for the same
 * reason.
 */
export const RECEIVER_LAT = 39.8283;
export const RECEIVER_LON = -98.5795;
export const SITE_NAME = "FlightSite Demo";

/**
 * Analytics preset the fixtures (and therefore the baselines) are captured
 * at.
 *
 * `t0` — "since the first sighting" — rather than the page's default
 * `today`.
 *
 * Originally that was forced: demo sightings were stamped from a fixed
 * scenario epoch (2026-01-01) while the backend resolved `today` against the
 * real wall clock, so `today` was genuinely empty on a demo stack and every
 * card rendered "No data for this window." Slice 058 fixed that (issue #107)
 * — the demo scenario now anchors to the wall clock, so `today` is populated
 * and would make a perfectly good baseline.
 *
 * It stays `t0` because changing it means re-capturing the HAR and every
 * analytics baseline, which needs a live demo stack (`npm run visual:capture`)
 * and is not something to do as a side effect. `t0` spans the whole scenario
 * either way, so the charts and tables have real content — which is the thing
 * worth having a baseline of.
 */
export const ANALYTICS_PRESET = "t0";

/**
 * Every Alerts tab, visited during capture so each tab's queries land in the
 * HAR. Only {@link ALERT_SCREENSHOT_TABS} are actually photographed;
 * recording the other two costs nothing and means adding a screenshot later
 * needs no re-capture.
 */
export const ALERT_TAB_IDS = ["watchlists", "rules", "templates", "history"] as const;

/**
 * The Alerts tabs the suite takes baselines of.
 *
 * `watchlists` is the tab the page opens on — what "the Alerts page" looks
 * like to a user — and on a fresh install it is the empty state, which is a
 * real and worth-locking appearance. `history` is the only tab with
 * populated rows on demo data, and it carries the severity styling (SPEC
 * §80's non-color severity signaling) that a contrast or focus change is
 * most likely to disturb. `rules` and `templates` are skipped on purpose:
 * the roadmap's out-of-scope line is "pixel-perfect coverage of every
 * state".
 */
export const ALERT_SCREENSHOT_TABS = ["watchlists", "history"] as const;
export type AlertScreenshotTab = (typeof ALERT_SCREENSHOT_TABS)[number];

/** Written by capture, read by replay. */
export interface FixtureManifest {
  /**
   * ISO instant the replayed browser clock is frozen at — the wall-clock
   * moment of capture, which is also the moment the backend used to resolve
   * every analytics window now recorded in the HAR. Freezing anywhere else
   * would render a UI whose idea of "now" contradicts its own data.
   */
  frozenClock: string;
  /** ICAO the aircraft-detail baseline is taken for (lowercase hex). */
  detailIcao: string;
  /** Analytics preset captured — see {@link ANALYTICS_PRESET}. */
  analyticsPreset: string;
  /** Aircraft count in the captured live snapshot; a sanity signal only. */
  aircraftInSnapshot: number;
  note: string;
}
