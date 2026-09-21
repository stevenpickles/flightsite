import { describe, expect, it } from "vitest";

import {
  parseSelectedIcaoFromSearchParams,
  SELECTED_ICAO_PARAM,
  withSelectedIcaoInSearchParams,
} from "@/features/filters/lib/selectionUrlSync";

describe("parseSelectedIcaoFromSearchParams", () => {
  it("returns null when the param is absent", () => {
    expect(
      parseSelectedIcaoFromSearchParams(new URLSearchParams()),
    ).toBeNull();
  });

  it("returns null for a blank value", () => {
    expect(
      parseSelectedIcaoFromSearchParams(new URLSearchParams("selected=")),
    ).toBeNull();
  });

  it("lower-cases the ICAO to match the store's keys", () => {
    expect(
      parseSelectedIcaoFromSearchParams(new URLSearchParams("selected=A1B2C3")),
    ).toBe("a1b2c3");
  });

  it("trims surrounding whitespace", () => {
    expect(
      parseSelectedIcaoFromSearchParams(
        new URLSearchParams("selected=%20aaaaaa%20"),
      ),
    ).toBe("aaaaaa");
  });
});

describe("withSelectedIcaoInSearchParams", () => {
  it("sets the param for a non-null icao", () => {
    const next = withSelectedIcaoInSearchParams(
      new URLSearchParams(),
      "aaaaaa",
    );
    expect(next.get(SELECTED_ICAO_PARAM)).toBe("aaaaaa");
  });

  it("removes the param for null", () => {
    const next = withSelectedIcaoInSearchParams(
      new URLSearchParams("selected=aaaaaa"),
      null,
    );
    expect(next.has(SELECTED_ICAO_PARAM)).toBe(false);
  });

  it("leaves other params untouched either way", () => {
    const set = withSelectedIcaoInSearchParams(
      new URLSearchParams("hide_stale=1"),
      "aaaaaa",
    );
    expect(set.get("hide_stale")).toBe("1");

    const cleared = withSelectedIcaoInSearchParams(
      new URLSearchParams("hide_stale=1&selected=aaaaaa"),
      null,
    );
    expect(cleared.get("hide_stale")).toBe("1");
  });

  it("does not mutate the params it was given", () => {
    const original = new URLSearchParams();
    withSelectedIcaoInSearchParams(original, "aaaaaa");
    expect(original.has(SELECTED_ICAO_PARAM)).toBe(false);
  });
});
