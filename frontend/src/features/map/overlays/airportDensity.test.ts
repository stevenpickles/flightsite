import { describe, expect, it } from "vitest";

import {
  AIRPORT_MIN_ZOOM,
  AIRPORT_SIZE_CLASSES_LARGEST_FIRST,
  minSizeForZoom,
} from "@/features/map/overlays/airportDensity";

describe("AIRPORT_SIZE_CLASSES_LARGEST_FIRST", () => {
  it("is exactly the four imported size classes, largest first", () => {
    expect(AIRPORT_SIZE_CLASSES_LARGEST_FIRST).toEqual([
      "large",
      "medium",
      "small",
      "heliport",
    ]);
  });

  it("is strictly increasing in AIRPORT_MIN_ZOOM order", () => {
    const zooms = AIRPORT_SIZE_CLASSES_LARGEST_FIRST.map(
      (sizeClass) => AIRPORT_MIN_ZOOM[sizeClass],
    );
    for (let index = 1; index < zooms.length; index += 1) {
      expect(zooms[index]).toBeGreaterThan(zooms[index - 1] as number);
    }
  });
});

describe("minSizeForZoom", () => {
  it("is null below the lowest threshold (large's own minzoom)", () => {
    expect(minSizeForZoom(AIRPORT_MIN_ZOOM.large - 0.1)).toBeNull();
    expect(minSizeForZoom(0)).toBeNull();
  });

  it("is 'large' exactly at large's threshold and up to medium's", () => {
    expect(minSizeForZoom(AIRPORT_MIN_ZOOM.large)).toBe("large");
    expect(minSizeForZoom(AIRPORT_MIN_ZOOM.medium - 0.1)).toBe("large");
  });

  it("is 'medium' exactly at medium's threshold and up to small's", () => {
    expect(minSizeForZoom(AIRPORT_MIN_ZOOM.medium)).toBe("medium");
    expect(minSizeForZoom(AIRPORT_MIN_ZOOM.small - 0.1)).toBe("medium");
  });

  it("is 'small' exactly at small's threshold and up to heliport's", () => {
    expect(minSizeForZoom(AIRPORT_MIN_ZOOM.small)).toBe("small");
    expect(minSizeForZoom(AIRPORT_MIN_ZOOM.heliport - 0.1)).toBe("small");
  });

  it("is 'heliport' at and above heliport's threshold — everything included", () => {
    expect(minSizeForZoom(AIRPORT_MIN_ZOOM.heliport)).toBe("heliport");
    expect(minSizeForZoom(20)).toBe("heliport");
  });
});
