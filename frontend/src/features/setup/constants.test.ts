import { describe, expect, it } from "vitest";

import { ALERT_TEMPLATES, DEFAULT_ENABLED_TEMPLATE_IDS } from "./constants";

/**
 * The backend's shipped catalogue, from
 * `backend/src/flightsite/alerts/templates.py`. Copied deliberately: these ids
 * go out on the wire as `alerts.enabled_templates`, and the backend *skips* an
 * id it does not recognize rather than rejecting the save — so a wrong id here
 * costs the user a rule they explicitly asked for and reports nothing. That is
 * issue #111, which shipped because this list said `law_enforcement` while the
 * catalogue said `police`.
 *
 * A copy can go stale, so it is not the real guard:
 * `backend/tests/alerts/test_frontend_contract.py` reads `constants.ts` and
 * asserts it against the live catalogue, which is the one check that cannot
 * drift. This test is the fast half — it fails in the frontend suite, next to
 * the change, without needing the Python side to run.
 */
const BACKEND_TEMPLATE_KEYS = [
  "military",
  "government",
  "police",
  "emergency_squawk",
  "first_ever",
  "locally_rare",
  "locally_rare_type",
  "watchlist",
] as const;

describe("ALERT_TEMPLATES", () => {
  it("offers exactly the template keys the backend ships", () => {
    expect([...ALERT_TEMPLATES.map((template) => template.id)].sort()).toEqual(
      [...BACKEND_TEMPLATE_KEYS].sort(),
    );
  });

  it("does not send the superseded law_enforcement spelling", () => {
    // The backend still accepts it as a read-time alias so existing config
    // files keep working, but it is not a name a current client may use: while
    // the wizard sends it, every save rewrites the spelling the alias exists to
    // retire.
    expect(ALERT_TEMPLATES.map((template) => template.id)).not.toContain(
      "law_enforcement",
    );
  });

  it("offers each template exactly once", () => {
    const ids = ALERT_TEMPLATES.map((template) => template.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("gives every template a label and a description", () => {
    for (const template of ALERT_TEMPLATES) {
      expect(template.label.trim()).not.toBe("");
      expect(template.description.trim()).not.toBe("");
    }
  });

  it("ticks only real template keys by default", () => {
    // SPEC §45: "do not silently enable every possible notification" — so the
    // defaults are a strict subset, and each one has to actually name a
    // template or the most common path of all silently does nothing.
    const ids = new Set<string>(ALERT_TEMPLATES.map((template) => template.id));
    expect(DEFAULT_ENABLED_TEMPLATE_IDS.length).toBeGreaterThan(0);
    expect(DEFAULT_ENABLED_TEMPLATE_IDS.length).toBeLessThan(
      ALERT_TEMPLATES.length,
    );
    for (const id of DEFAULT_ENABLED_TEMPLATE_IDS) {
      expect(ids).toContain(id);
    }
  });
});
