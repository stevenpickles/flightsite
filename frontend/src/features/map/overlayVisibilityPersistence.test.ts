import { afterEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_OVERLAY_VISIBILITY,
  OVERLAY_VISIBILITY_STORAGE_KEY,
  readStoredOverlayVisibility,
  writeStoredOverlayVisibility,
} from "@/features/map/overlayVisibilityPersistence";

afterEach(() => {
  window.localStorage.clear();
});

describe("overlay visibility persistence", () => {
  it("returns the default when nothing is stored", () => {
    expect(readStoredOverlayVisibility()).toEqual(DEFAULT_OVERLAY_VISIBILITY);
  });

  it("round-trips a stored choice", () => {
    writeStoredOverlayVisibility({ airports: false, airspace: true });
    expect(readStoredOverlayVisibility()).toEqual({
      airports: false,
      airspace: true,
    });
    expect(window.localStorage.getItem(OVERLAY_VISIBILITY_STORAGE_KEY)).toBe(
      JSON.stringify({ airports: false, airspace: true }),
    );
  });

  it("falls back member-by-member for a partially-valid stored value", () => {
    window.localStorage.setItem(
      OVERLAY_VISIBILITY_STORAGE_KEY,
      JSON.stringify({ airports: false, airspace: "not-a-boolean" }),
    );
    expect(readStoredOverlayVisibility()).toEqual({
      airports: false,
      airspace: DEFAULT_OVERLAY_VISIBILITY.airspace,
    });
  });

  it("falls back to the default for malformed JSON", () => {
    window.localStorage.setItem(OVERLAY_VISIBILITY_STORAGE_KEY, "{not json");
    expect(readStoredOverlayVisibility()).toEqual(DEFAULT_OVERLAY_VISIBILITY);
  });

  it("falls back to the default for a non-object stored value", () => {
    window.localStorage.setItem(
      OVERLAY_VISIBILITY_STORAGE_KEY,
      JSON.stringify([1, 2, 3]),
    );
    expect(readStoredOverlayVisibility()).toEqual(DEFAULT_OVERLAY_VISIBILITY);
  });

  it("falls back to the default when localStorage.getItem throws", () => {
    const spy = vi
      .spyOn(window.localStorage, "getItem")
      .mockImplementation(() => {
        throw new Error("storage disabled");
      });
    expect(readStoredOverlayVisibility()).toEqual(DEFAULT_OVERLAY_VISIBILITY);
    spy.mockRestore();
  });

  it("silently no-ops when localStorage.setItem throws", () => {
    const spy = vi
      .spyOn(window.localStorage, "setItem")
      .mockImplementation(() => {
        throw new Error("storage disabled");
      });
    expect(() =>
      writeStoredOverlayVisibility({ airports: false, airspace: false }),
    ).not.toThrow();
    spy.mockRestore();
  });
});
