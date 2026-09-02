import { describe, expect, it } from "vitest";

import {
  DENSITY_CALLSIGN_ENTER,
  DENSITY_CALLSIGN_EXIT,
  deriveLabelSortKey,
  deriveLabelTier,
  nextDensityLatched,
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
        densityLatched: false,
        priority: false,
      }),
    ).toBe("none");
  });

  it("shows callsign only from the minimum zoom up to (not including) the full-label zoom", () => {
    expect(
      deriveLabelTier({
        zoom: ZOOM_LABELS_MIN,
        densityLatched: false,
        priority: false,
      }),
    ).toBe("callsign");
    expect(
      deriveLabelTier({
        zoom: ZOOM_LABELS_FULL - 0.1,
        densityLatched: false,
        priority: false,
      }),
    ).toBe("callsign");
  });

  it("shows the full stack at and above the full-label zoom, for a sparse picture", () => {
    expect(
      deriveLabelTier({
        zoom: ZOOM_LABELS_FULL,
        densityLatched: false,
        priority: false,
      }),
    ).toBe("full");
  });

  it("drops to callsign-only while the density latch is on, even above the full-label zoom", () => {
    expect(
      deriveLabelTier({
        zoom: ZOOM_LABELS_FULL,
        densityLatched: true,
        priority: false,
      }),
    ).toBe("callsign");
  });

  it("still hides a latched label below the minimum zoom — zoom wins over density", () => {
    expect(
      deriveLabelTier({
        zoom: ZOOM_LABELS_MIN - 0.1,
        densityLatched: true,
        priority: false,
      }),
    ).toBe("none");
  });

  it("always returns full for a priority aircraft, regardless of zoom or density", () => {
    expect(
      deriveLabelTier({ zoom: 0, densityLatched: true, priority: true }),
    ).toBe("full");
    expect(
      deriveLabelTier({
        zoom: ZOOM_LABELS_MIN - 1,
        densityLatched: false,
        priority: true,
      }),
    ).toBe("full");
  });
});

describe("nextDensityLatched", () => {
  it("keeps the band's edges apart, entering above the exit count", () => {
    // A single threshold is the bug (issue #143) — pin that there are two,
    // and which way round they go.
    expect(DENSITY_CALLSIGN_EXIT).toBeLessThan(DENSITY_CALLSIGN_ENTER);
  });

  it("latches on only once the count rises above the upper edge", () => {
    expect(nextDensityLatched(false, DENSITY_CALLSIGN_ENTER - 1)).toBe(false);
    expect(nextDensityLatched(false, DENSITY_CALLSIGN_ENTER)).toBe(false);
    expect(nextDensityLatched(false, DENSITY_CALLSIGN_ENTER + 1)).toBe(true);
  });

  it("stays latched while the count falls back through the band", () => {
    // The blink itself: 61 -> 55 -> 61 must not change the label content.
    let latched = nextDensityLatched(false, DENSITY_CALLSIGN_ENTER + 1);
    expect(latched).toBe(true);
    latched = nextDensityLatched(latched, DENSITY_CALLSIGN_EXIT + 5);
    expect(latched).toBe(true);
    latched = nextDensityLatched(latched, DENSITY_CALLSIGN_ENTER - 1);
    expect(latched).toBe(true);
  });

  it("unlatches only once the count falls below the lower edge", () => {
    expect(nextDensityLatched(true, DENSITY_CALLSIGN_EXIT + 1)).toBe(true);
    expect(nextDensityLatched(true, DENSITY_CALLSIGN_EXIT)).toBe(true);
    expect(nextDensityLatched(true, DENSITY_CALLSIGN_EXIT - 1)).toBe(false);
  });

  it("holds whatever the previous frame decided while inside the band", () => {
    for (
      let count = DENSITY_CALLSIGN_EXIT;
      count <= DENSITY_CALLSIGN_ENTER;
      count += 1
    ) {
      expect(nextDensityLatched(true, count)).toBe(true);
      expect(nextDensityLatched(false, count)).toBe(false);
    }
  });

  it("unlatches on an empty picture whatever the previous frame said", () => {
    // What makes a store reset or a dropped connection settle on its own.
    expect(nextDensityLatched(true, 0)).toBe(false);
  });

  it("does not oscillate for a count churning across the upper edge", () => {
    // The reported symptom: a receiver gaining and losing a contact around
    // 60 produced a new tier every frame. Walk that sequence and assert the
    // latch never moves after the first crossing.
    let latched = false;
    const seen: boolean[] = [];
    for (const count of [59, 61, 60, 59, 61, 58, 60, 61]) {
      latched = nextDensityLatched(latched, count);
      seen.push(latched);
    }
    expect(seen).toEqual([false, true, true, true, true, true, true, true]);
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
