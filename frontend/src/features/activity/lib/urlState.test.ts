import { describe, expect, it } from "vitest";

import {
  DEFAULT_ACTIVITY_STATE,
  parseActivityPageState,
  serializeActivityPageState,
} from "@/features/activity/lib/urlState";

function parse(search: string) {
  return parseActivityPageState(new URLSearchParams(search));
}

describe("parseActivityPageState", () => {
  it("defaults an empty query string", () => {
    expect(parse("")).toEqual(DEFAULT_ACTIVITY_STATE);
  });

  it("reads a repeated type parameter", () => {
    expect(parse("type=new_type&type=milestone").types).toEqual([
      "new_type",
      "milestone",
    ]);
  });

  it("orders types canonically so two links share one query key", () => {
    // The chips write in click order; the URL may name them in any order.
    // Normalising here is what keeps `?type=a&type=b` and `?type=b&type=a`
    // one TanStack Query cache entry rather than two.
    expect(parse("type=milestone&type=new_type").types).toEqual(
      parse("type=new_type&type=milestone").types,
    );
  });

  it("drops a type this build does not know rather than failing the URL", () => {
    // A link from a newer build degrades to a narrower filter, never an error.
    expect(parse("type=new_type&type=warp_drive").types).toEqual(["new_type"]);
  });

  it("collapses a repeated type to one", () => {
    expect(parse("type=new_type&type=new_type").types).toEqual(["new_type"]);
  });

  it.each(["page=0", "page=-2", "page=abc", "page="])(
    "falls back to page 1 for %s",
    (search) => {
      expect(parse(search).page).toBe(1);
    },
  );

  it("reads a valid page", () => {
    expect(parse("page=4").page).toBe(4);
  });
});

describe("serializeActivityPageState", () => {
  it("writes nothing for the default state", () => {
    expect(serializeActivityPageState(DEFAULT_ACTIVITY_STATE).toString()).toBe(
      "",
    );
  });

  it("round-trips page and types", () => {
    const state = { page: 3, types: ["new_type", "milestone"] as const };
    expect(parseActivityPageState(serializeActivityPageState(state))).toEqual(
      state,
    );
  });

  it("repeats the type key rather than joining values", () => {
    const search = serializeActivityPageState({
      page: 1,
      types: ["new_type", "milestone"],
    }).toString();
    expect(search).toBe("type=new_type&type=milestone");
  });
});
