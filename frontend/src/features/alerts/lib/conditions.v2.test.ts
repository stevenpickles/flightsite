/**
 * The version 2 condition kinds (roadmap slice 089): validation messages in
 * canonical units (R4-13), and the documents they compose — which must be
 * exactly the shapes `backend/tests/api/test_alert_rules_v2_api.py` proves
 * the API accepts and echoes unchanged.
 */
import { describe, expect, it } from "vitest";

import {
  conditionsToDocument,
  emptyCondition,
  validateCondition,
  validateEmitterCategory,
  validateSquawkCode,
  MAX_SQUAWK_CODES,
  type ConditionDraft,
} from "@/features/alerts/lib/conditions";

describe("v2 validation", () => {
  it.each([
    ["7000", null],
    ["0020", null],
    ["7800", /four digits, each 0–7/],
    ["700", /four digits/],
    ["70000", /four digits/],
  ])("squawk code %s", (code, expected) => {
    const message = validateSquawkCode(code);
    if (expected === null) {
      expect(message).toBeNull();
    } else {
      expect(message).toMatch(expected);
    }
  });

  it.each([
    ["A7", null],
    ["b1", null],
    ["E1", /A–D and a digit 0–7/],
    ["A8", /A–D/],
  ])("emitter category %s", (code, expected) => {
    const message = validateEmitterCategory(code);
    if (expected === null) {
      expect(message).toBeNull();
    } else {
      expect(message).toMatch(expected);
    }
  });

  it.each<[ConditionDraft, RegExp | null]>([
    [{ kind: "squawk", values: [] }, /at least one squawk/],
    [
      {
        kind: "squawk",
        values: Array.from({ length: MAX_SQUAWK_CODES + 1 }, (_, n) =>
          n.toString(8).padStart(4, "0"),
        ),
      },
      /at most 16 squawk codes/,
    ],
    [{ kind: "squawk", values: ["1200", "7000"] }, null],
    [{ kind: "emitter_category", values: [] }, /at least one emitter/],
    [{ kind: "emitter_category", values: ["A7"] }, null],
    [{ kind: "callsign_glob", text: "" }, /Enter a pattern/],
    [{ kind: "callsign_glob", text: "RCH 1" }, /cannot contain spaces/],
    [{ kind: "callsign_glob", text: "X".repeat(33) }, /at most 32 characters/],
    [{ kind: "registration_glob", text: " N?23AB " }, null],
    [{ kind: "ground_speed", min: "", max: "" }, /a minimum, a maximum/],
    [{ kind: "ground_speed", min: "fast", max: "" }, /in knots/],
    [{ kind: "ground_speed", min: "-1", max: "" }, /between 0 and 2000 kt/],
    [{ kind: "ground_speed", min: "", max: "2500" }, /at most 2000 kt/],
    [{ kind: "ground_speed", min: "300", max: "200" }, /can never match/],
    [{ kind: "ground_speed", min: "80", max: "250" }, null],
    [{ kind: "vertical_rate", min: "", max: "x" }, /in feet per minute/],
    [
      { kind: "vertical_rate", min: "-25000", max: "" },
      /between -20000 and 20000 ft\/min \(negative is descending\)/,
    ],
    [{ kind: "vertical_rate", min: "500", max: "-500" }, /can never match/],
    [{ kind: "vertical_rate", min: "", max: "-1000" }, null],
    [{ kind: "within_area", text: "" }, /Draw an area on the map/],
    [{ kind: "within_area", text: "-2, 50\n-1, 50" }, /between 3 and 64/],
    [{ kind: "within_area", text: "-2, 50\nnope" }, /Line 2/],
    [{ kind: "within_area", text: "-2, 50\n-1, 50\n-1, 51" }, null],
  ])("%j → %s", (draft, expected) => {
    const message = validateCondition(draft);
    if (expected === null) {
      expect(message).toBeNull();
    } else {
      expect(message).toMatch(expected);
    }
  });

  it("starts every v2 kind blank and invalid", () => {
    for (const kind of [
      "squawk",
      "callsign_glob",
      "registration_glob",
      "emitter_category",
      "ground_speed",
      "vertical_rate",
      "within_area",
    ] as const) {
      expect(validateCondition(emptyCondition(kind))).not.toBeNull();
    }
  });
});

describe("v2 documents", () => {
  it("writes version 2 and each new field in the API's shape", () => {
    const document = conditionsToDocument(
      [
        { kind: "squawk", values: ["7000", "1200", "7000"] },
        { kind: "callsign_glob", text: " RCH* " },
        { kind: "registration_glob", text: "N?23AB" },
        { kind: "emitter_category", values: ["a7", "A1"] },
        { kind: "ground_speed", min: "", max: "120" },
        { kind: "vertical_rate", min: "-3000", max: "-1000" },
        { kind: "within_area", text: "-2, 50\n-1, 50\n-1, 51" },
      ],
      false,
    );

    expect(document).toEqual({
      version: 2,
      squawk_in: ["1200", "7000"],
      callsign_glob: "RCH*",
      registration_glob: "N?23AB",
      emitter_category_in: ["A1", "A7"],
      max_ground_speed_kt: 120,
      min_vertical_rate_fpm: -3000,
      max_vertical_rate_fpm: -1000,
      within_area: {
        type: "Polygon",
        coordinates: [
          [
            [-2, 50],
            [-1, 50],
            [-1, 51],
            [-2, 50],
          ],
        ],
      },
    });
  });
});
