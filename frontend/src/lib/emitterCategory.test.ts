import { describe, expect, it } from "vitest";

import {
  EMITTER_CATEGORY_LABELS,
  emitterCategoryLabel,
  formatEmitterCategory,
} from "@/lib/emitterCategory";

describe("emitter categories", () => {
  it("names every one of the 32 codes, A0 through D7", () => {
    const expected = ["A", "B", "C", "D"].flatMap((set) =>
      Array.from({ length: 8 }, (_, digit) => `${set}${digit}`),
    );
    expect(Object.keys(EMITTER_CATEGORY_LABELS).sort()).toEqual(expected);
  });

  it.each([
    ["A1", "A1 · Light aircraft"],
    ["A3", "A3 · Large aircraft"],
    ["A5", "A5 · Heavy aircraft"],
    ["A7", "A7 · Rotorcraft"],
    ["B1", "B1 · Glider / sailplane"],
    ["C1", "C1 · Surface emergency vehicle"],
  ])("formats %s as %s", (code, expected) => {
    expect(formatEmitterCategory(code)).toBe(expected);
  });

  it("is null for an absent or malformed code rather than a guess", () => {
    expect(formatEmitterCategory(null)).toBeNull();
    expect(formatEmitterCategory(undefined)).toBeNull();
    expect(formatEmitterCategory("E1")).toBeNull();
    expect(emitterCategoryLabel("a3")).toBeNull();
    expect(emitterCategoryLabel("constructor")).toBeNull();
  });
});
