import { afterEach, describe, expect, it } from "vitest";

import {
  resetDensityLatch,
  updateDensityLatch,
} from "@/features/map/labels/densityLatch";
import {
  DENSITY_CALLSIGN_ENTER,
  DENSITY_CALLSIGN_EXIT,
} from "@/features/map/labels/priority";

afterEach(() => {
  resetDensityLatch();
});

describe("updateDensityLatch", () => {
  it("starts unlatched", () => {
    expect(updateDensityLatch(DENSITY_CALLSIGN_ENTER)).toBe(false);
  });

  it("carries the latch across calls, which is the whole point of it", () => {
    expect(updateDensityLatch(DENSITY_CALLSIGN_ENTER + 1)).toBe(true);
    expect(updateDensityLatch(DENSITY_CALLSIGN_EXIT + 1)).toBe(true);
    expect(updateDensityLatch(DENSITY_CALLSIGN_EXIT - 1)).toBe(false);
    expect(updateDensityLatch(DENSITY_CALLSIGN_EXIT + 1)).toBe(false);
  });
});

describe("resetDensityLatch", () => {
  it("drops a held latch so the next frame is judged with no history", () => {
    expect(updateDensityLatch(DENSITY_CALLSIGN_ENTER + 1)).toBe(true);
    resetDensityLatch();
    expect(updateDensityLatch(DENSITY_CALLSIGN_ENTER)).toBe(false);
  });
});
