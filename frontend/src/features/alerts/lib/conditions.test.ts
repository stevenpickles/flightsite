import { describe, expect, it } from "vitest";

import {
  availableKinds,
  conditionsToDocument,
  documentToConditions,
  emptyCondition,
  isRuleDraftValid,
  validateCondition,
  validateConditionList,
  validateRuleDescription,
  validateRuleName,
  CONDITION_KINDS,
  MAX_ALTITUDE_FT,
  MAX_DISTANCE_NM,
  MAX_NAME_LENGTH,
  MAX_RARITY_THRESHOLD,
  type ConditionDraft,
} from "@/features/alerts/lib/conditions";
import type { AlertRuleConditions } from "@/lib/api/alertRules";

describe("conditionsToDocument", () => {
  it("writes only the conditions that were added", () => {
    const document = conditionsToDocument(
      [{ kind: "type_code", text: " c17 " }],
      false,
    );

    // An unset condition is an absent key, never a null or a zero — adding a
    // condition kind in a later document version must not be able to change
    // what an existing rule means.
    expect(document).toEqual({ version: 1, type_code: "c17" });
  });

  it("splits a distance window into its two document fields", () => {
    const document = conditionsToDocument(
      [{ kind: "distance", min: "5", max: "40" }],
      false,
    );

    expect(document.min_distance_nm).toBe(5);
    expect(document.max_distance_nm).toBe(40);
  });

  it("leaves an open end of a window absent", () => {
    const document = conditionsToDocument(
      [{ kind: "altitude", min: "", max: "10000" }],
      false,
    );

    expect(document.min_alt_ft).toBeUndefined();
    expect(document.max_alt_ft).toBe(10000);
  });

  it("omits a classification's mission when none is required", () => {
    const document = conditionsToDocument(
      [
        {
          kind: "classification",
          military: true,
          government: false,
          lawEnforcement: false,
          mission: "",
        },
      ],
      false,
    );

    expect(document.classification).toEqual({
      military: true,
      government: false,
      law_enforcement: false,
    });
  });

  it("writes applies_on_ground only when it is asked for", () => {
    const drafts: ConditionDraft[] = [{ kind: "watchlist_any" }];

    expect(
      conditionsToDocument(drafts, false).applies_on_ground,
    ).toBeUndefined();
    expect(conditionsToDocument(drafts, true).applies_on_ground).toBe(true);
  });
});

describe("documentToConditions", () => {
  it("round-trips every condition kind this build can write", () => {
    // The property the rule builder rests on: a rule can be opened, changed
    // in one place and saved without the untouched conditions being reworded
    // on the way through.
    const document: AlertRuleConditions = {
      version: 1,
      classification: {
        military: true,
        government: false,
        law_enforcement: true,
        mission: "medical",
      },
      type_code: "C17",
      model: "Globemaster",
      watchlist_id: 3,
      watchlist_any: true,
      rare_aircraft: { max_sightings: 2 },
      rare_type: { max_sightings: 4 },
      min_distance_nm: 5,
      max_distance_nm: 40,
      min_alt_ft: 500,
      max_alt_ft: 10000,
      applies_on_ground: true,
    };

    const { drafts, appliesOnGround } = documentToConditions(document);

    expect(appliesOnGround).toBe(true);
    expect(conditionsToDocument(drafts, appliesOnGround)).toEqual(document);
  });

  it("covers every kind the builder offers", () => {
    const document: AlertRuleConditions = {
      version: 1,
      classification: {
        military: true,
        government: false,
        law_enforcement: false,
      },
      type_code: "C17",
      model: "Globemaster",
      watchlist_id: 3,
      watchlist_any: true,
      rare_aircraft: { max_sightings: 2 },
      rare_type: { max_sightings: 4 },
      max_distance_nm: 40,
      max_alt_ft: 10000,
    };

    const kinds = documentToConditions(document).drafts.map(
      (draft) => draft.kind,
    );

    expect(new Set(kinds)).toEqual(
      new Set(CONDITION_KINDS.map((meta) => meta.kind)),
    );
  });

  it("returns drafts in catalogue order whatever order the document lists", () => {
    const { drafts } = documentToConditions({
      version: 1,
      max_alt_ft: 10000,
      type_code: "C17",
    });

    expect(drafts.map((draft) => draft.kind)).toEqual([
      "type_code",
      "altitude",
    ]);
  });

  it("reads an absent watchlist_any as no condition", () => {
    const { drafts } = documentToConditions({ version: 1, type_code: "C17" });

    expect(drafts.map((draft) => draft.kind)).toEqual(["type_code"]);
  });
});

describe("availableKinds", () => {
  it("offers every kind for an empty rule", () => {
    expect(availableKinds([])).toHaveLength(CONDITION_KINDS.length);
  });

  it("stops offering a kind already in use", () => {
    // The document is flat, so a second `type_code` would have nowhere to go.
    const remaining = availableKinds([{ kind: "type_code", text: "C17" }]);

    expect(remaining.map((meta) => meta.kind)).not.toContain("type_code");
  });
});

describe("validateCondition", () => {
  it("refuses a classification that requires nothing", () => {
    expect(validateCondition(emptyCondition("classification"))).toMatch(
      /at least one/i,
    );
  });

  it("accepts a classification asking only for a mission", () => {
    expect(
      validateCondition({
        kind: "classification",
        military: false,
        government: false,
        lawEnforcement: false,
        mission: "firefighting",
      }),
    ).toBeNull();
  });

  it("refuses blank text conditions", () => {
    expect(validateCondition({ kind: "type_code", text: "  " })).not.toBeNull();
    expect(validateCondition({ kind: "model", text: "" })).not.toBeNull();
  });

  it("refuses a watchlist condition with nothing chosen", () => {
    expect(validateCondition(emptyCondition("watchlist"))).toMatch(/choose/i);
  });

  it("accepts 'on any watchlist', which has nothing to fill in", () => {
    expect(validateCondition({ kind: "watchlist_any" })).toBeNull();
  });

  it.each([
    ["", /enter a threshold/i],
    ["0", /between 1 and/i],
    ["1.5", /whole number/i],
    ["abc", /whole number/i],
    [String(MAX_RARITY_THRESHOLD + 1), /between 1 and/i],
  ])("refuses the rarity threshold %j", (raw, expected) => {
    expect(
      validateCondition({ kind: "rare_aircraft", maxSightings: raw }),
    ).toMatch(expected);
  });

  it("accepts a rarity threshold of 1 — never seen here before", () => {
    expect(
      validateCondition({ kind: "rare_type", maxSightings: "1" }),
    ).toBeNull();
  });

  it("refuses a distance window with neither end", () => {
    expect(validateCondition(emptyCondition("distance"))).toMatch(
      /minimum, a maximum, or both/i,
    );
  });

  it("refuses an inverted distance window, which can never match", () => {
    expect(
      validateCondition({ kind: "distance", min: "40", max: "10" }),
    ).toMatch(/below the maximum/i);
  });

  it("refuses a distance beyond the bound the backend enforces", () => {
    expect(
      validateCondition({
        kind: "distance",
        min: "",
        max: String(MAX_DISTANCE_NM + 1),
      }),
    ).toMatch(/at most/i);
  });

  it("refuses a zero maximum distance, which can never match", () => {
    expect(validateCondition({ kind: "distance", min: "", max: "0" })).toMatch(
      /above 0/i,
    );
  });

  it("accepts an open-ended distance window", () => {
    expect(
      validateCondition({ kind: "distance", min: "", max: "40" }),
    ).toBeNull();
    expect(
      validateCondition({ kind: "distance", min: "5", max: "" }),
    ).toBeNull();
  });

  it("refuses an inverted altitude window", () => {
    expect(
      validateCondition({ kind: "altitude", min: "10000", max: "500" }),
    ).toMatch(/below the ceiling/i);
  });

  it("refuses an altitude outside the bounds the backend enforces", () => {
    expect(
      validateCondition({
        kind: "altitude",
        min: "",
        max: String(MAX_ALTITUDE_FT + 1),
      }),
    ).toMatch(/between/i);
  });

  it("accepts a negative floor, the Dead Sea being below sea level", () => {
    expect(
      validateCondition({ kind: "altitude", min: "-500", max: "1000" }),
    ).toBeNull();
  });
});

describe("rule-level validation", () => {
  it("refuses a blank name", () => {
    expect(validateRuleName("   ")).toMatch(/enter a name/i);
  });

  it("refuses an over-long name", () => {
    expect(validateRuleName("x".repeat(MAX_NAME_LENGTH + 1))).toMatch(
      /at most/i,
    );
  });

  it("accepts an empty description", () => {
    expect(validateRuleDescription("")).toBeNull();
  });

  it("refuses an empty condition list", () => {
    // An empty condition set would match every aircraft in the sky at
    // whatever severity it declared.
    expect(validateConditionList([])).toMatch(/at least one condition/i);
  });

  it("is invalid while any single condition is", () => {
    expect(
      isRuleDraftValid("Rule", "", [{ kind: "type_code", text: "" }]),
    ).toBe(false);
  });

  it("is valid once the name and every condition are", () => {
    expect(
      isRuleDraftValid("Rule", "", [{ kind: "type_code", text: "C17" }]),
    ).toBe(true);
  });
});
