/**
 * Arming a real, targeted alert for the interesting-aircraft flow (roadmap
 * slice 046, `docs/TEST_STRATEGY.md` §4).
 *
 * Why the test creates the alert instead of waiting for one
 * --------------------------------------------------------
 * The demo scenario does produce alerting traffic on its own — two
 * emergency-squawk profiles — but only during a fixed slice of a 30-minute
 * rotation anchored to backend process start. `docs/TEST_STRATEGY.md` already
 * records the verdict on waiting for it from an arbitrary start time: "a coin
 * toss, not a test". So this drives the *rule* side, which is fully under the
 * test's control, against traffic the demo guarantees.
 *
 * Why that is a real end-to-end test and not a stub
 * ------------------------------------------------
 * Nothing here fakes an alert. It creates a genuine watchlist and a genuine
 * rule through the same internal API the Alerts page uses, and the backend's
 * own evaluator then decides — on its ordinary once-per-second pass over live
 * state — that a real demo aircraft matches. The UI is asserted against the
 * result of that decision.
 *
 * It is bounded because alert evaluation is *continuous*, not
 * transition-driven: every live aircraft is re-evaluated against the whole
 * rule set on each update, so a rule created against an aircraft that is
 * already airborne fires on that aircraft's very next tick rather than
 * waiting for it to change state. Both mutations recompile the engine's rule
 * set before their HTTP response returns, so by the time `armAlertProbe`
 * resolves the rule is already live.
 *
 * Several aircraft are watched rather than one. Demo profiles have finite
 * lifespans, and a test that pinned its hopes on a single airframe would
 * flake whenever that one happened to land or expire mid-run; watching a
 * handful keeps the rule narrow (it is not "alert on everything") while
 * making it near-certain that at least one subject is still in the air when
 * the assertions run.
 */

import { expect, type APIRequestContext } from "@playwright/test";

/** The rule's name, asserted verbatim in the panel and the alert history —
 * distinctive enough that it cannot be confused with a shipped template. */
export const PROBE_RULE_NAME = "E2E interesting probe";

/** The severity the probe rule declares, and therefore the one the row, the
 * detail panel and the map ring must all report. */
export const PROBE_SEVERITY = "high";

export interface AlertProbe {
  watchlistId: number;
  ruleId: number;
  /** The name the rule was created under — the string that appears as
   * `Rule: {name}` everywhere this alert surfaces. */
  ruleName: string;
  /** The ICAOs the rule was armed against, lower-case hex. */
  icaos: string[];
}

/** One entry of `GET /api/v1/aircraft/interesting` (`docs/API.md` §3.4). */
export interface InterestingAircraft {
  icao: string;
  interesting: { severity: string; reasons: string[] } | null;
}

/** One entry of `GET /api/v1/alerts/matches` (`docs/API.md` §3.8). */
export interface AlertMatch {
  id: number;
  icao: string;
  severity: string;
  reason: string;
  rule: { id: number; name: string } | null;
  builtin_key: string | null;
}

async function postJson(
  request: APIRequestContext,
  path: string,
  data: unknown,
  expectedStatus: number,
): Promise<Record<string, unknown>> {
  const response = await request.post(path, { data });
  expect(
    response.status(),
    `POST ${path} failed: ${response.status()} ${await response.text()}`,
  ).toBe(expectedStatus);
  return (await response.json()) as Record<string, unknown>;
}

/**
 * Creates a watchlist holding `icaos` and an enabled rule that matches it,
 * returning the ids so the caller can tear both down again.
 *
 * `applies_on_ground` is deliberately true: the demo roster parks aircraft at
 * airports, and a probe that silently declined to match a grounded subject
 * would look exactly like a broken alert engine.
 */
export async function armAlertProbe(
  request: APIRequestContext,
  icaos: readonly string[],
  ruleName: string = PROBE_RULE_NAME,
): Promise<AlertProbe> {
  expect(icaos.length, "armAlertProbe needs at least one ICAO").toBeGreaterThan(
    0,
  );

  const watchlist = await postJson(
    request,
    "/api/internal/watchlists",
    { name: `${ruleName} watchlist ${Date.now()}`, description: null },
    201,
  );
  const watchlistId = watchlist["id"] as number;

  for (const icao of icaos) {
    await postJson(
      request,
      `/api/internal/watchlists/${watchlistId}/entries`,
      { kind: "icao24", value: icao, note: null },
      201,
    );
  }

  const rule = await postJson(
    request,
    "/api/internal/alert-rules",
    {
      name: ruleName,
      description: null,
      severity: PROBE_SEVERITY,
      enabled: true,
      conditions: { watchlist_id: watchlistId, applies_on_ground: true },
    },
    201,
  );

  return {
    watchlistId,
    ruleId: rule["id"] as number,
    ruleName,
    icaos: [...icaos],
  };
}

/**
 * Removes the rule and the watchlist again, leaving the install as the probe
 * found it.
 *
 * Deleting the rule takes its alert matches with it (`ON DELETE CASCADE`), so
 * the later specs in this suite see neither a standing "interesting" aircraft
 * nor a history of alerts this test invented. Best-effort: a teardown failure
 * must not mask the assertion failure that is the real news.
 */
export async function disarmAlertProbe(
  request: APIRequestContext,
  probe: AlertProbe,
): Promise<void> {
  await request
    .delete(`/api/internal/alert-rules/${probe.ruleId}`)
    .catch(() => undefined);
  await request
    .delete(`/api/internal/watchlists/${probe.watchlistId}`)
    .catch(() => undefined);
}

/**
 * Waits for the backend to agree that one of the watched aircraft is now
 * interesting, and returns that aircraft's ICAO.
 *
 * Polls `/api/v1/aircraft/interesting`, which is served straight from the
 * live registry the WebSocket also feeds from — so this settles as soon as
 * the engine has decided, without waiting on a database write.
 */
export async function waitForInterestingIcao(
  request: APIRequestContext,
  probe: AlertProbe,
  timeoutMs = 30_000,
): Promise<string> {
  const watched = new Set(probe.icaos);
  let found = "";
  await expect
    .poll(
      async () => {
        const response = await request.get("/api/v1/aircraft/interesting");
        if (!response.ok()) {
          return false;
        }
        const body = (await response.json()) as {
          items: InterestingAircraft[];
        };
        const hit = body.items.find(
          (item) =>
            watched.has(item.icao) &&
            item.interesting?.severity === PROBE_SEVERITY,
        );
        found = hit?.icao ?? "";
        return found !== "";
      },
      {
        timeout: timeoutMs,
        message:
          "no watched aircraft ever became interesting — the rule was created but never matched",
      },
    )
    .toBe(true);
  return found;
}

/**
 * Waits for the durable alert history to record the probe's match for `icao`.
 *
 * Slower than the live surface above: this one waits on the engine's own
 * transaction, which in turn waits for the sighting the match belongs to.
 */
export async function waitForAlertMatch(
  request: APIRequestContext,
  probe: AlertProbe,
  icao: string,
  timeoutMs = 30_000,
): Promise<AlertMatch> {
  let match: AlertMatch | undefined;
  await expect
    .poll(
      async () => {
        const response = await request.get(
          `/api/v1/alerts/matches?icao=${icao}&limit=25&offset=0`,
        );
        if (!response.ok()) {
          return false;
        }
        const body = (await response.json()) as { items: AlertMatch[] };
        match = body.items.find((item) => item.rule?.name === probe.ruleName);
        return match !== undefined;
      },
      {
        timeout: timeoutMs,
        message: `the probe's match for ${icao} never reached the alert history`,
      },
    )
    .toBe(true);
  return match!;
}
