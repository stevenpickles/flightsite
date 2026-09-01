import { describe, expect, it } from "vitest";

import {
  DENSITY_CALLSIGN_THRESHOLD,
  deriveLabelSortKey,
  deriveLabelTier,
  SORT_KEY_DEFAULT,
  SORT_KEY_INTERESTING,
  SORT_KEY_SELECTED,
  ZOOM_LABELS_FULL,
  ZOOM_LABELS_MIN,
} from "@/features/map/labels/priority";

describe("deriveLabelTier", () => {
  it("hides the label below the minimum zoom for a non-priority aircraft", () => {
    expect(
      deriveLabelTier({
        zoom: ZOOM_LABELS_MIN - 0.1,
        liveCount: 1,
        priority: false,
      }),
    ).toBe("none");
  });

  it("shows callsign only from the minimum zoom up to (not including) the full-label zoom", () => {
    expect(
      deriveLabelTier({ zoom: ZOOM_LABELS_MIN, liveCount: 1, priority: false }),
    ).toBe("callsign");
    expect(
      deriveLabelTier({
        zoom: ZOOM_LABELS_FULL - 0.1,
        liveCount: 1,
        priority: false,
      }),
    ).toBe("callsign");
  });

  it("shows the full stack at and above the full-label zoom, for a sparse picture", () => {
    expect(
      deriveLabelTier({
        zoom: ZOOM_LABELS_FULL,
        liveCount: 1,
        priority: false,
      }),
    ).toBe("full");
  });

  it("drops to callsign-only once the live count exceeds the density threshold, even above the full-label zoom", () => {
    expect(
      deriveLabelTier({
        zoom: ZOOM_LABELS_FULL,
        liveCount: DENSITY_CALLSIGN_THRESHOLD,
        priority: false,
      }),
    ).toBe("full");
    expect(
      deriveLabelTier({
        zoom: ZOOM_LABELS_FULL,
        liveCount: DENSITY_CALLSIGN_THRESHOLD + 1,
        priority: false,
      }),
    ).toBe("callsign");
  });

  it("never lets density push a label all the way to none", () => {
    expect(
      deriveLabelTier({
        zoom: ZOOM_LABELS_FULL,
        liveCount: 100_000,
        priority: false,
      }),
    ).toBe("callsign");
  });

  it("always returns full for a priority aircraft, regardless of zoom or density", () => {
    expect(
      deriveLabelTier({ zoom: 0, liveCount: 100_000, priority: true }),
    ).toBe("full");
    expect(
      deriveLabelTier({
        zoom: ZOOM_LABELS_MIN - 1,
        liveCount: 0,
        priority: true,
      }),
    ).toBe("full");
  });
});

describe("deriveLabelSortKey", () => {
  it("gives the selected aircraft the top priority regardless of interesting", () => {
    expect(deriveLabelSortKey(true, false)).toBe(SORT_KEY_SELECTED);
    expect(deriveLabelSortKey(true, true)).toBe(SORT_KEY_SELECTED);
  });

  it("gives an interesting, non-selected aircraft the middle priority", () => {
    expect(deriveLabelSortKey(false, true)).toBe(SORT_KEY_INTERESTING);
  });

  it("gives an ordinary aircraft the lowest priority", () => {
    expect(deriveLabelSortKey(false, false)).toBe(SORT_KEY_DEFAULT);
  });

  it("orders the three priorities from most to least important", () => {
    // Lower is higher priority per MapLibre's own symbol-sort-key
    // convention (see the module doc comment) — pin the ordering itself,
    // not just the individual values.
    expect(SORT_KEY_SELECTED).toBeLessThan(SORT_KEY_INTERESTING);
    expect(SORT_KEY_INTERESTING).toBeLessThan(SORT_KEY_DEFAULT);
  });
});
