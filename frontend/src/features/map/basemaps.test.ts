import { describe, expect, it } from "vitest";

import {
  BASEMAPS,
  DEFAULT_BASEMAP_ID,
  getBasemapById,
  getDefaultBasemap,
  isValidBasemapId,
} from "@/features/map/basemaps";

describe("basemap registry", () => {
  it("ships at least two selectable basemaps that require no API key", () => {
    const keyless = BASEMAPS.filter((basemap) => !basemap.requiresKey);
    expect(keyless.length).toBeGreaterThanOrEqual(2);
  });

  it("requires no key for any shipped entry (v1 default constraint)", () => {
    for (const basemap of BASEMAPS) {
      expect(basemap.requiresKey).toBe(false);
    }
  });

  it("has unique, non-empty ids", () => {
    const ids = BASEMAPS.map((basemap) => basemap.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(id.length).toBeGreaterThan(0);
    }
  });

  it("gives every entry a non-empty attribution string", () => {
    for (const basemap of BASEMAPS) {
      expect(basemap.attribution.length).toBeGreaterThan(0);
    }
  });

  it("gives every entry a style (inline object or URL)", () => {
    for (const basemap of BASEMAPS) {
      expect(basemap.style).toBeTruthy();
      expect(
        typeof basemap.style === "object" || typeof basemap.style === "string",
      ).toBe(true);
    }
  });

  it("includes a dark-themed default and at least one light-compatible entry", () => {
    const darkEntries = BASEMAPS.filter((b) => b.themeAffinity === "dark");
    const lightEntries = BASEMAPS.filter((b) => b.themeAffinity === "light");
    expect(darkEntries.length).toBeGreaterThanOrEqual(1);
    expect(lightEntries.length).toBeGreaterThanOrEqual(1);
  });

  it("defaults to the dark-aviation basemap", () => {
    expect(DEFAULT_BASEMAP_ID).toBe("dark-aviation");
    const basemap = getBasemapById(DEFAULT_BASEMAP_ID);
    expect(basemap?.themeAffinity).toBe("dark");
  });
});

describe("isValidBasemapId", () => {
  it("is true for every registered id", () => {
    for (const basemap of BASEMAPS) {
      expect(isValidBasemapId(basemap.id)).toBe(true);
    }
  });

  it("is false for an unknown id", () => {
    expect(isValidBasemapId("does-not-exist")).toBe(false);
  });
});

describe("getBasemapById", () => {
  it("returns the matching entry", () => {
    expect(getBasemapById("osm-raster")?.label).toBe("OpenStreetMap");
  });

  it("returns undefined for an unknown id", () => {
    expect(getBasemapById("nope")).toBeUndefined();
  });
});

describe("getDefaultBasemap", () => {
  it("returns the default registry entry", () => {
    expect(getDefaultBasemap().id).toBe(DEFAULT_BASEMAP_ID);
  });
});
