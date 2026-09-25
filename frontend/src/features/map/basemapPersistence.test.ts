import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BASEMAP_STORAGE_KEY,
  readStoredBasemapId,
  writeStoredBasemapId,
} from "@/features/map/basemapPersistence";

afterEach(() => {
  window.localStorage.clear();
});

describe("basemap persistence", () => {
  it("reports no explicit choice when nothing is stored", () => {
    // Not the registry default (issue R1-14): substituting one here made
    // "chose dark aviation" and "chose nothing" the same value, and the
    // theme could then never pick for a user who had not picked.
    expect(readStoredBasemapId()).toBeNull();
  });

  it("round-trips a valid selection", () => {
    writeStoredBasemapId("osm-raster");
    expect(readStoredBasemapId()).toBe("osm-raster");
    expect(window.localStorage.getItem(BASEMAP_STORAGE_KEY)).toBe("osm-raster");
  });

  it("reports no choice for an unrecognized stored id", () => {
    window.localStorage.setItem(BASEMAP_STORAGE_KEY, "some-removed-basemap");
    expect(readStoredBasemapId()).toBeNull();
  });

  it("reports no choice when localStorage.getItem throws", () => {
    const spy = vi
      .spyOn(window.localStorage, "getItem")
      .mockImplementation(() => {
        throw new Error("storage disabled");
      });
    expect(readStoredBasemapId()).toBeNull();
    spy.mockRestore();
  });

  it("silently no-ops when localStorage.setItem throws", () => {
    const spy = vi
      .spyOn(window.localStorage, "setItem")
      .mockImplementation(() => {
        throw new Error("storage disabled");
      });
    expect(() => writeStoredBasemapId("osm-raster")).not.toThrow();
    spy.mockRestore();
  });
});
