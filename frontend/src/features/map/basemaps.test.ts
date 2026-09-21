import { describe, expect, it } from "vitest";

import {
  BASEMAPS,
  DEFAULT_BASEMAP_ID,
  getBasemapById,
  getDefaultBasemap,
  getThemeDefaultBasemap,
  isValidBasemapId,
  resolveActiveBasemap,
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

describe("getThemeDefaultBasemap (R1-14)", () => {
  it("matches each theme to a basemap designed for it", () => {
    // `themeAffinity` has been in the registry since slice 013 and nothing
    // read it, so a light-theme user got bright panels over a near-black map
    // until they found the switcher.
    expect(getThemeDefaultBasemap("dark").themeAffinity).toBe("dark");
    expect(getThemeDefaultBasemap("light").themeAffinity).toBe("light");
  });

  it("keeps the registry default for the dark theme", () => {
    expect(getThemeDefaultBasemap("dark").id).toBe(DEFAULT_BASEMAP_ID);
  });
});

describe("resolveActiveBasemap (R1-14)", () => {
  it("follows the theme while the user has chosen nothing", () => {
    expect(resolveActiveBasemap(null, "dark").id).toBe("dark-aviation");
    expect(resolveActiveBasemap(null, "light").id).toBe("light-aviation");
  });

  it("keeps an explicit choice in either theme", () => {
    // Someone who picked OpenStreetMap wants OpenStreetMap; the theme only
    // ever decides what has not been decided.
    expect(resolveActiveBasemap("osm-raster", "dark").id).toBe("osm-raster");
    expect(resolveActiveBasemap("osm-raster", "light").id).toBe("osm-raster");
  });

  it("falls back to the theme's default for a basemap this build dropped", () => {
    expect(resolveActiveBasemap("removed-in-a-later-release", "light").id).toBe(
      "light-aviation",
    );
  });

  it("returns registry constants, so the map never re-styles on a re-render", () => {
    // `MapLibreMap`'s basemap effect keys on this object's identity.
    expect(resolveActiveBasemap(null, "light")).toBe(
      resolveActiveBasemap(null, "light"),
    );
  });
});
