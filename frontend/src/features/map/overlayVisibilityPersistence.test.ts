import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_OVERLAY_VISIBILITY,
  OVERLAY_VISIBILITY_STORAGE_KEY,
  readStoredOverlayVisibility,
  writeStoredOverlayVisibility,
  type OverlayVisibility,
} from "@/features/map/overlayVisibilityPersistence";

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

const EVERYTHING_OFF: OverlayVisibility = {
  airports: false,
  airspace: false,
  rangeRings: false,
  receiver: false,
  labels: false,
};

describe("overlay visibility persistence", () => {
  it("returns the default when nothing is stored", () => {
    expect(readStoredOverlayVisibility()).toEqual(DEFAULT_OVERLAY_VISIBILITY);
  });

  it("defaults every slice 085 toggle on, matching the map as it was", () => {
    expect(DEFAULT_OVERLAY_VISIBILITY).toMatchObject({
      rangeRings: true,
      receiver: true,
      labels: true,
    });
  });

  it("round-trips a stored choice", () => {
    const choice: OverlayVisibility = {
      ...DEFAULT_OVERLAY_VISIBILITY,
      airports: false,
    };
    writeStoredOverlayVisibility(choice);
    expect(readStoredOverlayVisibility()).toEqual(choice);
    expect(window.localStorage.getItem(OVERLAY_VISIBILITY_STORAGE_KEY)).toBe(
      JSON.stringify(choice),
    );
  });

  it("round-trips the range-ring, receiver and label toggles", () => {
    writeStoredOverlayVisibility(EVERYTHING_OFF);
    expect(readStoredOverlayVisibility()).toEqual(EVERYTHING_OFF);
  });

  it("keeps a pre-085 stored value's choices and defaults the new members", () => {
    // Every browser that used the Layers card before slice 085 has exactly
    // this shape stored; it must not reset their Airports/Airspace choice.
    window.localStorage.setItem(
      OVERLAY_VISIBILITY_STORAGE_KEY,
      JSON.stringify({ airports: false, airspace: false }),
    );
    expect(readStoredOverlayVisibility()).toEqual({
      ...DEFAULT_OVERLAY_VISIBILITY,
      airports: false,
      airspace: false,
    });
  });

  it("falls back member-by-member for a partially-valid stored value", () => {
    window.localStorage.setItem(
      OVERLAY_VISIBILITY_STORAGE_KEY,
      JSON.stringify({
        airports: false,
        airspace: "not-a-boolean",
        rangeRings: false,
        receiver: 0,
        labels: null,
      }),
    );
    expect(readStoredOverlayVisibility()).toEqual({
      airports: false,
      airspace: DEFAULT_OVERLAY_VISIBILITY.airspace,
      rangeRings: false,
      receiver: DEFAULT_OVERLAY_VISIBILITY.receiver,
      labels: DEFAULT_OVERLAY_VISIBILITY.labels,
    });
  });

  it("falls back to the default for malformed JSON", () => {
    window.localStorage.setItem(OVERLAY_VISIBILITY_STORAGE_KEY, "{not json");
    expect(readStoredOverlayVisibility()).toEqual(DEFAULT_OVERLAY_VISIBILITY);
  });

  it("falls back to the default for a non-object stored value", () => {
    window.localStorage.setItem(
      OVERLAY_VISIBILITY_STORAGE_KEY,
      JSON.stringify(null),
    );
    expect(readStoredOverlayVisibility()).toEqual(DEFAULT_OVERLAY_VISIBILITY);
  });

  it("falls back to the defaults for an array stored value", () => {
    window.localStorage.setItem(
      OVERLAY_VISIBILITY_STORAGE_KEY,
      JSON.stringify([1, 2, 3]),
    );
    expect(readStoredOverlayVisibility()).toEqual(DEFAULT_OVERLAY_VISIBILITY);
  });

  it("falls back to the default when localStorage.getItem throws", () => {
    vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });
    expect(readStoredOverlayVisibility()).toEqual(DEFAULT_OVERLAY_VISIBILITY);
  });

  it("falls back to the default when localStorage itself is unreachable", () => {
    // Some privacy modes throw on the `localStorage` property access itself,
    // before any method is called.
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(readStoredOverlayVisibility()).toEqual(DEFAULT_OVERLAY_VISIBILITY);
    expect(() => writeStoredOverlayVisibility(EVERYTHING_OFF)).not.toThrow();
  });

  it("silently no-ops when localStorage.setItem throws", () => {
    vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });
    expect(() => writeStoredOverlayVisibility(EVERYTHING_OFF)).not.toThrow();
  });
});
