import { describe, expect, it } from "vitest";

import {
  DEFAULT_RING_STEPS,
  destinationPoint,
  formatRingLabel,
  generateRangeRingLabelsGeoJSON,
  generateRangeRingsGeoJSON,
  generateReceiverPointGeoJSON,
  generateRingCoordinates,
  greatCircleDistanceNm,
  kmToNm,
  nmToKm,
} from "@/features/map/geo/rings";
import type { MapConfig } from "@/features/map/types";

describe("destinationPoint", () => {
  it("moving 60 nm due north from the equator lands ~1 degree of latitude away", () => {
    // 1 nm was historically defined as 1 minute of latitude arc, so 60 nm
    // north is ~1 degree of latitude — a well-known independent check.
    const point = destinationPoint({ lat: 0, lon: 0 }, 0, 60);
    expect(point.lat).toBeCloseTo(1.0, 1);
    expect(point.lon).toBeCloseTo(0, 6);
  });

  it("moving due east from the equator changes only longitude", () => {
    const point = destinationPoint({ lat: 0, lon: 0 }, 90, 60);
    expect(point.lat).toBeCloseTo(0, 6);
    expect(point.lon).toBeCloseTo(1.0, 1);
  });

  it("moving due south is the mirror of moving due north", () => {
    const north = destinationPoint({ lat: 10, lon: -122 }, 0, 100);
    const south = destinationPoint({ lat: 10, lon: -122 }, 180, 100);
    expect(north.lat - 10).toBeCloseTo(-(south.lat - 10), 3);
  });

  it("normalizes longitude across the antimeridian", () => {
    const point = destinationPoint({ lat: 0, lon: 179.5 }, 90, 60);
    expect(point.lon).toBeLessThan(-179);
  });
});

describe("greatCircleDistanceNm", () => {
  it("is ~0 for the same point", () => {
    expect(
      greatCircleDistanceNm(
        { lat: 47.6, lon: -122.3 },
        { lat: 47.6, lon: -122.3 },
      ),
    ).toBeCloseTo(0, 6);
  });

  it("agrees with destinationPoint's construction (round trip)", () => {
    const origin = { lat: 47.6, lon: -122.3 };
    for (const bearing of [0, 45, 90, 135, 180, 225, 270, 315]) {
      for (const distanceNm of [10, 100, 250]) {
        const point = destinationPoint(origin, bearing, distanceNm);
        expect(greatCircleDistanceNm(origin, point)).toBeCloseTo(distanceNm, 3);
      }
    }
  });
});

describe("generateRingCoordinates", () => {
  const center = { lat: 47.6, lon: -122.3 };

  it("produces a closed ring (first point equals last point)", () => {
    const coords = generateRingCoordinates(center, 100);
    expect(coords[0]).toEqual(coords[coords.length - 1]);
  });

  it("produces steps+1 points by default", () => {
    const coords = generateRingCoordinates(center, 100);
    expect(coords).toHaveLength(DEFAULT_RING_STEPS + 1);
  });

  it("every point sits radiusNm from the center at multiple test latitudes", () => {
    for (const lat of [0, 25, 47.6, 60, -33.9]) {
      const testCenter = { lat, lon: 10 };
      for (const radiusNm of [50, 150, 250]) {
        const coords = generateRingCoordinates(testCenter, radiusNm, 32);
        for (const [lon, pointLat] of coords) {
          const distance = greatCircleDistanceNm(testCenter, {
            lat: pointLat,
            lon,
          });
          expect(distance).toBeCloseTo(radiusNm, 2);
        }
      }
    }
  });

  it("respects a custom step count", () => {
    const coords = generateRingCoordinates(center, 100, 8);
    expect(coords).toHaveLength(9);
  });
});

describe("unit conversion", () => {
  it("nmToKm and kmToNm round-trip", () => {
    expect(nmToKm(100)).toBeCloseTo(185.2, 5);
    expect(kmToNm(185.2)).toBeCloseTo(100, 5);
  });
});

describe("formatRingLabel", () => {
  it("formats nm labels", () => {
    expect(formatRingLabel(100, "nm")).toBe("100 nm");
  });

  it("formats km labels, converted and rounded", () => {
    expect(formatRingLabel(100, "km")).toBe("185 km");
  });
});

const testConfig: MapConfig = {
  receiver: { lat: 47.6, lon: -122.3, label: "Test Receiver" },
  ringRadiiNm: [50, 100, 250],
  unit: "nm",
  displayRadiusNm: 250,
};

describe("generateRangeRingsGeoJSON", () => {
  it("produces one LineString feature per configured radius, in order", () => {
    const collection = generateRangeRingsGeoJSON(testConfig);
    expect(collection.type).toBe("FeatureCollection");
    expect(collection.features).toHaveLength(3);
    expect(collection.features.map((f) => f.properties.radiusNm)).toEqual([
      50, 100, 250,
    ]);
    for (const feature of collection.features) {
      expect(feature.geometry.type).toBe("LineString");
      expect(feature.geometry.coordinates.length).toBeGreaterThan(2);
    }
  });

  it("labels each feature with its unit-aware radius label", () => {
    const collection = generateRangeRingsGeoJSON(testConfig);
    expect(collection.features[0]?.properties?.label).toBe("50 nm");
  });
});

describe("generateRangeRingLabelsGeoJSON", () => {
  it("produces one point per ring, due north of the receiver", () => {
    const collection = generateRangeRingLabelsGeoJSON(testConfig);
    expect(collection.features).toHaveLength(3);
    for (const feature of collection.features) {
      const [lon] = feature.geometry.coordinates;
      expect(lon).toBeCloseTo(testConfig.receiver.lon, 6);
    }
  });
});

describe("generateReceiverPointGeoJSON", () => {
  it("places the point at the receiver's coordinates with its label", () => {
    const feature = generateReceiverPointGeoJSON(testConfig.receiver);
    expect(feature.geometry.coordinates).toEqual([
      testConfig.receiver.lon,
      testConfig.receiver.lat,
    ]);
    expect(feature.properties.label).toBe("Test Receiver");
  });
});
