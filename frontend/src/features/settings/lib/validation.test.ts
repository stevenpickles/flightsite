import { describe, expect, it } from "vitest";

import {
  parseRangeRingRadii,
  validateAlertRadius,
  validateDisplayRadius,
  validateHighResMetricDays,
  validateRangeRingRadii,
  validateTimezone,
} from "@/features/settings/lib/validation";

describe("validateDisplayRadius", () => {
  it("rejects blank, zero, negative, and over-max values", () => {
    expect(validateDisplayRadius("")).not.toBeNull();
    expect(validateDisplayRadius("0")).not.toBeNull();
    expect(validateDisplayRadius("-5")).not.toBeNull();
    expect(validateDisplayRadius("10001")).not.toBeNull();
  });

  it("accepts an in-range value", () => {
    expect(validateDisplayRadius("250")).toBeNull();
    expect(validateDisplayRadius("10000")).toBeNull();
  });
});

describe("validateAlertRadius", () => {
  it("treats blank as valid (unlimited)", () => {
    expect(validateAlertRadius("")).toBeNull();
    expect(validateAlertRadius("   ")).toBeNull();
  });

  it("rejects zero, negative, and over-max values", () => {
    expect(validateAlertRadius("0")).not.toBeNull();
    expect(validateAlertRadius("-1")).not.toBeNull();
    expect(validateAlertRadius("10001")).not.toBeNull();
  });

  it("accepts an in-range value", () => {
    expect(validateAlertRadius("100")).toBeNull();
  });
});

describe("validateHighResMetricDays", () => {
  it("rejects out-of-range and non-integer values", () => {
    expect(validateHighResMetricDays("6")).not.toBeNull();
    expect(validateHighResMetricDays("31")).not.toBeNull();
    expect(validateHighResMetricDays("14.5")).not.toBeNull();
    expect(validateHighResMetricDays("")).not.toBeNull();
  });

  it("accepts the documented bounds", () => {
    expect(validateHighResMetricDays("7")).toBeNull();
    expect(validateHighResMetricDays("30")).toBeNull();
    expect(validateHighResMetricDays("14")).toBeNull();
  });
});

describe("validateTimezone", () => {
  it("requires a non-blank value", () => {
    expect(validateTimezone("")).not.toBeNull();
    expect(validateTimezone("  ")).not.toBeNull();
    expect(validateTimezone("UTC")).toBeNull();
  });
});

describe("parseRangeRingRadii", () => {
  it("parses a comma-separated list, ignoring blank segments", () => {
    expect(parseRangeRingRadii("50, 100, 150,")).toEqual([50, 100, 150]);
  });
});

describe("validateRangeRingRadii", () => {
  it("requires at least one entry", () => {
    expect(validateRangeRingRadii("")).not.toBeNull();
  });

  it("rejects non-numeric entries", () => {
    expect(validateRangeRingRadii("50, abc")).not.toBeNull();
  });

  it("rejects more than 10 entries", () => {
    const many = Array.from({ length: 11 }, (_, i) => i + 1).join(", ");
    expect(validateRangeRingRadii(many)).not.toBeNull();
  });

  it("rejects zero or negative radii", () => {
    expect(validateRangeRingRadii("50, 0")).not.toBeNull();
    expect(validateRangeRingRadii("50, -10")).not.toBeNull();
  });

  it("rejects duplicate radii", () => {
    expect(validateRangeRingRadii("50, 50")).not.toBeNull();
  });

  it("accepts a valid list", () => {
    expect(validateRangeRingRadii("50, 100, 150, 200")).toBeNull();
  });
});
