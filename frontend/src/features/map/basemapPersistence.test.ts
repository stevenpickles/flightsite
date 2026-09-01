import { afterEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_BASEMAP_ID } from "@/features/map/basemaps";
import {
  BASEMAP_STORAGE_KEY,
  readStoredBasemapId,
  writeStoredBasemapId,
} from "@/features/map/basemapPersistence";

afterEach(() => {
  window.localStorage.clear();
});

describe("basemap persistence", () => {
  it("returns the default when nothing is stored", () => {
    expect(readStoredBasemapId()).toBe(DEFAULT_BASEMAP_ID);
  });

  it("round-trips a valid selection", () => {
    writeStoredBasemapId("osm-raster");
    expect(readStoredBasemapId()).toBe("osm-raster");
    expect(window.localStorage.getItem(BASEMAP_STORAGE_KEY)).toBe("osm-raster");
  });

  it("falls back to the default for an unrecognized stored id", () => {
    window.localStorage.setItem(BASEMAP_STORAGE_KEY, "some-removed-basemap");
    expect(readStoredBasemapId()).toBe(DEFAULT_BASEMAP_ID);
  });

  it("falls back to the default when localStorage.getItem throws", () => {
    const spy = vi
      .spyOn(window.localStorage, "getItem")
      .mockImplementation(() => {
        throw new Error("storage disabled");
      });
    expect(readStoredBasemapId()).toBe(DEFAULT_BASEMAP_ID);
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
