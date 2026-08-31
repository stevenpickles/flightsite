import { describe, expect, it } from "vitest";

import { cn } from "./utils";

describe("cn", () => {
  it("joins class names and drops falsy values", () => {
    const showB = false;
    expect(cn("a", showB && "b", undefined, "c")).toBe("a c");
  });

  it("merges conflicting tailwind utilities, keeping the last", () => {
    expect(cn("px-2", "px-4")).toBe("px-4");
  });
});
