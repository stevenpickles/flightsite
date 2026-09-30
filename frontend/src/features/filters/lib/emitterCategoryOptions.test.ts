import { describe, expect, it } from "vitest";

import {
  emitterCategoryOptions,
  presentEmitterCategoriesKey,
} from "@/features/filters/lib/emitterCategoryOptions";
import { makeRecord } from "@/test/liveAircraftFixtures";

describe("presentEmitterCategoriesKey", () => {
  it("is the sorted distinct categories in the live picture", () => {
    const aircraft = {
      aaaaaa: makeRecord({ icao: "aaaaaa", emitter_category: "A7" }),
      bbbbbb: makeRecord({ icao: "bbbbbb", emitter_category: "A3" }),
      cccccc: makeRecord({ icao: "cccccc", emitter_category: "A3" }),
      dddddd: makeRecord({ icao: "dddddd", emitter_category: null }),
    };
    expect(presentEmitterCategoriesKey(aircraft)).toBe("A3,A7");
  });

  it("is an empty string for an empty sky", () => {
    expect(presentEmitterCategoriesKey({})).toBe("");
  });
});

describe("emitterCategoryOptions", () => {
  it("offers what is present plus what is selected, sorted", () => {
    expect(emitterCategoryOptions("A3,A7", ["B1", "A7"])).toEqual([
      "A3",
      "A7",
      "B1",
    ]);
  });

  it("offers nothing when nothing is present or selected", () => {
    expect(emitterCategoryOptions("", [])).toEqual([]);
  });
});
