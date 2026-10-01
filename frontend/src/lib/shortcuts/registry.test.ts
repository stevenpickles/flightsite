import { describe, expect, it } from "vitest";

import { NAVIGATION_LETTERS, SHORTCUTS } from "./registry";

describe("shortcut registry", () => {
  it("gives every shortcut a unique id", () => {
    const ids = SHORTCUTS.map((shortcut) => shortcut.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("declares exactly the ten documented g-sequence letters", () => {
    expect(Object.keys(NAVIGATION_LETTERS).sort()).toEqual(
      ["a", "f", "h", "l", "m", "n", "r", "s", "t", "v"].sort(),
    );
  });

  it("routes every g-sequence letter to an absolute app path", () => {
    for (const path of Object.values(NAVIGATION_LETTERS)) {
      expect(path.startsWith("/")).toBe(true);
    }
  });

  it("lists the slice 085 Live Map shortcuts, clear of the navigation letters' own sequence", () => {
    const liveMapKeys = SHORTCUTS.filter(
      (shortcut) => shortcut.group === "Live Map",
    ).map((shortcut) => shortcut.keys);
    expect(liveMapKeys).toContain("M");
    expect(liveMapKeys).toContain("T");
    // Slice 090's "What was that?".
    expect(liveMapKeys).toContain("W");
    // Every single-key Live Map binding is distinct.
    expect(new Set(liveMapKeys).size).toBe(liveMapKeys.length);
  });

  it("has one 'Go to…' row per navigation letter", () => {
    const goToRows = SHORTCUTS.filter(
      (shortcut) => shortcut.group === "Go to…",
    );
    expect(goToRows).toHaveLength(Object.keys(NAVIGATION_LETTERS).length);
  });
});
