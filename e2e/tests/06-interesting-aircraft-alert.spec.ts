/**
 * Flow — interesting-aircraft alert (roadmap slice 046,
 * `docs/TEST_STRATEGY.md` §4; SPEC §49's interesting panel and §36's map
 * emphasis).
 *
 * This is the flow `05-browser-notifications.spec.ts` deferred to slice 046:
 * *"making a demo alert observable end-to-end belongs with the
 * interesting-aircraft alert flow"*. It is the one flow in the suite that
 * needs the application to make a judgement — that a particular aircraft is
 * worth the user's attention — and then show it in three places at once.
 *
 * How a real alert is made to happen on schedule
 * ----------------------------------------------
 * See `support/alerts.ts`. In short: the demo scenario's own alerting traffic
 * appears only during a fixed phase of a 30-minute rotation, so instead of
 * waiting for it, the test creates a genuine watchlist and rule through the
 * same internal API the Alerts page writes through, aimed at aircraft that
 * are airborne *right now*. The backend's evaluator then reaches its own
 * verdict on its ordinary once-per-second pass. Nothing about the alert is
 * faked; only its timing is made deterministic.
 *
 * The rule and watchlist are removed in `afterAll`, which also removes the
 * matches they produced — later specs in this ordered suite must not inherit
 * a standing alert this file invented.
 *
 * What is asserted
 * ----------------
 * The four surfaces an alert is supposed to reach, in the order a user would
 * meet them:
 *
 * 1. **The interesting panel** lists the aircraft, at the rule's severity,
 *    naming the rule that caught it (SPEC §49).
 * 2. **Selecting it** opens the detail panel with the same reason (§49:
 *    "clicking selects the aircraft").
 * 3. **The map emphasises it** — the attention layer's feature properties
 *    carry the severity that drives the ring's radius and stroke (§36).
 *    WebGL-gated, like every other map-paint assertion in this suite.
 * 4. **The alert history records it**, so the alert survives the aircraft
 *    leaving the air.
 */

import type { APIRequestContext } from "@playwright/test";

import {
  armAlertProbe,
  disarmAlertProbe,
  waitForAlertMatch,
  waitForInterestingIcao,
  PROBE_RULE_NAME,
  PROBE_SEVERITY,
  type AlertProbe,
} from "./support/alerts";
import {
  browserHasWebGl,
  fetchPositionedAircraft,
  waitForAircraftLayer,
  waitForLiveAircraft,
} from "./support/liveMap";
import { expect, test } from "./support/fixtures";

/** How many live aircraft the probe rule is aimed at. Enough that at least
 * one is still airborne whenever an assertion runs, few enough that the rule
 * stays a targeted watchlist rather than an alert-on-everything. */
const WATCH_COUNT = 6;

/** Mirrors `AIRCRAFT_SOURCE_ID` / `AIRCRAFT_ATTENTION_LAYER_ID` in
 * `frontend/src/features/map/aircraft/aircraftLayers.ts`. The attention layer
 * is the ring SPEC §36 requires around an alerting aircraft. */
const AIRCRAFT_SOURCE_ID = "flightsite-aircraft";
const ATTENTION_LAYER_ID = "flightsite-aircraft-attention";

let api: APIRequestContext;
let probe: AlertProbe;

test.beforeAll(async ({ playwright }, testInfo) => {
  api = await playwright.request.newContext({
    baseURL: testInfo.project.use.baseURL,
  });

  // Aim the rule at aircraft the demo scenario currently has in the air.
  // Positioned ones, so the same subjects can carry the map assertion.
  let candidates: Awaited<ReturnType<typeof fetchPositionedAircraft>> = [];
  await expect
    .poll(
      async () => {
        candidates = await fetchPositionedAircraft(api);
        return candidates.length;
      },
      {
        timeout: 60_000,
        message: "demo mode never put a positioned aircraft in the air",
      },
    )
    .toBeGreaterThan(0);

  probe = await armAlertProbe(
    api,
    candidates.slice(0, WATCH_COUNT).map((item) => item.icao),
  );
});

test.afterAll(async () => {
  if (probe !== undefined) {
    await disarmAlertProbe(api, probe);
  }
  await api.dispose();
});

test.describe("interesting-aircraft alert", () => {
  test("an aircraft matching a rule is listed in the interesting panel", async ({
    page,
  }) => {
    const icao = await waitForInterestingIcao(api, probe);

    await page.goto("/");
    await waitForLiveAircraft(page);

    const panel = page.getByTestId("interesting-panel");
    await expect(panel).toBeVisible();

    // The badge counts every interesting aircraft, filtered or not, so it
    // must have left zero the moment the rule started matching.
    await expect(page.getByTestId("interesting-count")).not.toHaveText("0");

    const row = panel.locator(
      `[data-testid="interesting-row"][data-icao="${icao}"]`,
    );
    await expect(row).toBeVisible();

    // The severity the rule declared, carried on the row so it is
    // distinguishable without relying on colour (SPEC §80).
    await expect(row).toHaveAttribute("data-severity", PROBE_SEVERITY);
    // And the row says *why*, naming the rule that caught it rather than
    // merely flagging the aircraft.
    await expect(row).toContainText(`Rule: ${PROBE_RULE_NAME}`);
  });

  test("selecting the alerting aircraft shows the match reason in its detail panel", async ({
    page,
  }) => {
    const icao = await waitForInterestingIcao(api, probe);

    await page.goto("/");
    await waitForLiveAircraft(page);

    const row = page.locator(
      `[data-testid="interesting-row"][data-icao="${icao}"]`,
    );
    await expect(row).toBeVisible();
    // SPEC §49: "clicking selects the aircraft". Unlike flow (d)'s canvas
    // click this needs no WebGL — the panel is ordinary DOM, which is why
    // this assertion runs on every engine.
    await row.click();

    const detail = page.getByTestId("aircraft-detail-panel");
    await expect(detail).toBeVisible();
    await expect(detail.getByText(new RegExp(`ICAO ${icao}`, "i"))).toBeVisible();

    // The same verdict, reached through a different component: the detail
    // panel's Interesting section (`InterestingSection.tsx`).
    await expect(detail.getByTestId("interesting-reasons")).toContainText(
      `Rule: ${PROBE_RULE_NAME}`,
    );
  });

  test("the map carries the emphasis that draws the eye to it", async ({
    page,
  }) => {
    const icao = await waitForInterestingIcao(api, probe);

    await page.goto("/");
    test.skip(
      !(await browserHasWebGl(page)),
      "browser has no WebGL — the attention ring cannot render; the app's degradation is unit-tested",
    );
    await waitForLiveAircraft(page);
    await waitForAircraftLayer(page);

    // The ring layer itself exists. SPEC §36 encodes severity in radius and
    // stroke width as well as colour, so its presence is what makes the
    // alerting aircraft findable on a crowded map.
    const hasAttentionLayer = await page.evaluate((layerId) => {
      const map = (
        window as unknown as {
          __flightsiteMap?: { getLayer: (id: string) => unknown };
        }
      ).__flightsiteMap;
      return Boolean(map?.getLayer(layerId));
    }, ATTENTION_LAYER_ID);
    expect(
      hasAttentionLayer,
      "the map has no attention layer, so no aircraft can be emphasised",
    ).toBe(true);

    // And the alerting aircraft's own feature carries the severity that layer
    // paints from. Polled: the aircraft source is refreshed on each live
    // frame, so the property lands on the next tick rather than instantly.
    await expect
      .poll(
        async () =>
          page.evaluate(
            ({ sourceId, subject }) => {
              const map = (
                window as unknown as {
                  __flightsiteMap?: {
                    querySourceFeatures: (
                      id: string,
                    ) => { properties: Record<string, unknown> }[];
                  };
                }
              ).__flightsiteMap;
              if (!map) {
                return null;
              }
              const feature = map
                .querySourceFeatures(sourceId)
                .find((item) => item.properties["icao"] === subject);
              return (feature?.properties["severity"] as string) ?? null;
            },
            { sourceId: AIRCRAFT_SOURCE_ID, subject: icao },
          ),
        {
          timeout: 20_000,
          message: `the map never published an emphasis severity for ${icao}`,
        },
      )
      .toBe(PROBE_SEVERITY);
  });

  test("the alert is recorded in the history on the Alerts page", async ({
    page,
  }) => {
    const icao = await waitForInterestingIcao(api, probe);
    // The durable record, which outlives the aircraft leaving the air. Waited
    // on through the API first so the page below is asked only for something
    // that already exists.
    const match = await waitForAlertMatch(api, probe, icao);
    expect(match.severity).toBe(PROBE_SEVERITY);

    await page.goto("/alerts");
    await expect(
      page.getByRole("heading", { level: 1, name: "Alerts" }),
    ).toBeVisible();

    // History is a tab, and the tab state is local rather than URL-persisted,
    // so it has to be clicked rather than deep-linked.
    await page.getByRole("tab", { name: "History" }).click();

    const history = page.getByRole("list", { name: "Alert history" });
    await expect(history).toBeVisible();
    await expect(history).toContainText(`Rule: ${PROBE_RULE_NAME}`);
    // The entry links back to the aircraft it fired for.
    await expect(
      history.getByRole("link", { name: icao.toUpperCase() }).first(),
    ).toBeVisible();
  });

  test("a live alert becomes a browser notification", async ({ page }) => {
    // This is the assertion `docs/TEST_STRATEGY.md` §4 defers to this flow:
    // *"making a demo alert observable end to end belongs with the
    // interesting-aircraft alert flow"*. Slice 040 could not make it, because
    // waiting for the demo scenario's own alert from an arbitrary start time
    // is a coin toss; with a rule the test arms itself, it becomes ordinary.
    //
    // The `Notification` boundary is stubbed for the same reason spec 05
    // stubs it: no headless engine implements a notification centre, and
    // Chromium answers `denied` to a permission it has nowhere to deliver.
    // Everything *upstream* of that boundary is real — a real rule, a real
    // backend verdict, a real WebSocket activity frame, and FlightSite's real
    // dispatch path deciding this one is worth showing.
    await page.addInitScript(() => {
      const delivered: { title: string; body: string }[] = [];
      (window as unknown as Record<string, unknown>)[
        "__flightsiteNotifications"
      ] = delivered;

      class StubNotification {
        static permission: NotificationPermission = "granted";
        static requestPermission(): Promise<NotificationPermission> {
          return Promise.resolve("granted");
        }
        constructor(title: string, options?: NotificationOptions) {
          delivered.push({ title, body: options?.body ?? "" });
        }
        close(): void {}
        addEventListener(): void {}
        removeEventListener(): void {}
      }

      (window as unknown as Record<string, unknown>)["Notification"] =
        StubNotification;
    });

    // The app shell owns the socket alerts arrive on (ADR-0015), so delivery
    // happens on any route; the Live Map is used here because
    // `waitForLiveAircraft` gives this test a definite "the stream is
    // flowing" signal to start from.
    await page.goto("/");
    await waitForLiveAircraft(page);

    // A *second*, independently-named rule, armed while the page is already
    // watching. The first probe's matches have long since fired, and alert
    // dedupe is per-sighting — so without a new rule there would be no new
    // alert for this page to receive, and the test would be asserting
    // against history rather than delivery.
    const notifyProbe = await armAlertProbe(
      api,
      probe.icaos,
      "E2E notification probe",
    );
    try {
      await expect
        .poll(
          async () =>
            page.evaluate(
              () =>
                (
                  (window as unknown as Record<string, unknown>)[
                    "__flightsiteNotifications"
                  ] as { title: string; body: string }[]
                ).length,
            ),
          {
            // The activity feed flushes on its own interval before the frame
            // is broadcast, so this is slower than the live `interesting`
            // surface the earlier tests read.
            timeout: 45_000,
            message: "a matching alert never became a browser notification",
          },
        )
        .toBeGreaterThan(0);

      // It is a notification about *this* alert, not an unrelated one: the
      // composed body names the rule that fired.
      const shown = await page.evaluate(
        () =>
          (window as unknown as Record<string, unknown>)[
            "__flightsiteNotifications"
          ] as { title: string; body: string }[],
      );
      const texts = shown.map((item) => `${item.title} ${item.body}`);
      expect(
        texts.some((text) => text.includes(notifyProbe.ruleName)),
        `no notification mentioned the rule that fired; saw: ${JSON.stringify(texts)}`,
      ).toBe(true);
    } finally {
      await disarmAlertProbe(api, notifyProbe);
    }
  });
});
