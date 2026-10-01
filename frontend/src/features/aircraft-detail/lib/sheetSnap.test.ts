import { describe, expect, it } from "vitest";

import {
  clampSheetHeight,
  collapseSnap,
  expandSnap,
  nearestSnap,
  PEEK_HEIGHT_PX,
  snapHeightPx,
} from "@/features/aircraft-detail/lib/sheetSnap";

describe("sheetSnap", () => {
  it("expands one snap at a time and stops at full", () => {
    expect(expandSnap("peek")).toBe("half");
    expect(expandSnap("half")).toBe("full");
    expect(expandSnap("full")).toBe("full");
  });

  it("collapses one snap at a time and stops at peek", () => {
    expect(collapseSnap("full")).toBe("half");
    expect(collapseSnap("half")).toBe("peek");
    expect(collapseSnap("peek")).toBe("peek");
  });

  it("resolves each snap against the container height", () => {
    expect(snapHeightPx("peek", 700)).toBe(PEEK_HEIGHT_PX);
    expect(snapHeightPx("half", 700)).toBe(350);
    expect(snapHeightPx("full", 700)).toBe(700);
  });

  it("never lets peek outgrow a very short container", () => {
    expect(snapHeightPx("peek", 120)).toBe(120);
    expect(snapHeightPx("full", -5)).toBe(0);
  });

  it("clamps a drag between peek and the container", () => {
    expect(clampSheetHeight(10, 700)).toBe(PEEK_HEIGHT_PX);
    expect(clampSheetHeight(400, 700)).toBe(400);
    expect(clampSheetHeight(9000, 700)).toBe(700);
  });

  it("settles a released drag on the nearest snap", () => {
    expect(nearestSnap(190, 700)).toBe("peek");
    expect(nearestSnap(330, 700)).toBe("half");
    expect(nearestSnap(640, 700)).toBe("full");
  });

  it("breaks a tie toward the lower snap", () => {
    // Exactly between half (350) and full (700).
    expect(nearestSnap(525, 700)).toBe("half");
  });
});
