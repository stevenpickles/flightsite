import { describe, expect, it } from "vitest";

import {
  columnClasses,
  columnVisibilityClass,
} from "@/features/history/lib/columnPriority";

describe("columnVisibilityClass", () => {
  it("leaves an essential column visible at every width", () => {
    expect(columnVisibilityClass({})).toBe("");
  });

  it("hides a secondary column below its breakpoint", () => {
    expect(columnVisibilityClass({ showFrom: "lg" })).toBe(
      "hidden lg:table-cell",
    );
  });

  it("keeps the alignment a column asked for", () => {
    expect(columnVisibilityClass({ align: "right", showFrom: "2xl" })).toBe(
      "text-right hidden 2xl:table-cell",
    );
  });
});

describe("columnClasses", () => {
  it("gives a header and its body cells the same classes", () => {
    // The point of the lookup: a `<th>` that hides at `lg` and a `<td>` that
    // does not would leave the table a column out of step with its own
    // header, which is worse than either choice made consistently.
    const columns = [
      { key: "tail" as const },
      { key: "operator" as const, showFrom: "lg" as const },
    ];
    const classes = columnClasses(columns);

    expect(classes.tail).toBe(columnVisibilityClass(columns[0]));
    expect(classes.operator).toBe(columnVisibilityClass(columns[1]));
    expect(classes.operator).toContain("lg:table-cell");
  });
});
