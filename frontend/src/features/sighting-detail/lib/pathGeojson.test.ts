import { describe, expect, it } from "vitest";

import { buildPathGeojson } from "@/features/sighting-detail/lib/pathGeojson";
import type { SightingPathPoint } from "@/lib/api/sightings";

function point(overrides: Partial<SightingPathPoint> = {}): SightingPathPoint {
  return {
    t: "2026-08-30T22:02:10.000Z",
    lat: 47.11,
    lon: -121.8,
    altitude_ft: 21000,
    source: "adsb",
    ...overrides,
  };
}

describe("buildPathGeojson", () => {
  it("returns empty collections and null bounds for an empty path", () => {
    const result = buildPathGeojson([]);

    expect(result.line.features).toHaveLength(0);
    expect(result.endpoints.features).toHaveLength(0);
    expect(result.altitudeRangeFt).toBeNull();
    expect(result.bounds).toBeNull();
  });

  it("marks the first and last points as start/end, in timestamp order", () => {
    const path = [
      point({ t: "2026-08-30T22:02:10.000Z", lat: 47.11, lon: -121.8 }),
      point({ t: "2026-08-30T22:03:42.000Z", lat: 47.19, lon: -121.88 }),
      point({ t: "2026-08-30T22:05:00.000Z", lat: 47.25, lon: -121.95 }),
    ];

    const result = buildPathGeojson(path);

    const [start, end] = result.endpoints.features;
    expect(start?.properties.kind).toBe("start");
    expect(start?.geometry.coordinates).toEqual([-121.8, 47.11]);
    expect(end?.properties.kind).toBe("end");
    expect(end?.geometry.coordinates).toEqual([-121.95, 47.25]);
  });

  it("builds one whole-path line feature with no altitude coloring when fewer than two points carry an altitude", () => {
    const path = [
      point({ altitude_ft: null }),
      point({ lat: 47.2, lon: -121.9, altitude_ft: null }),
    ];

    const result = buildPathGeojson(path);

    expect(result.altitudeRangeFt).toBeNull();
    expect(result.line.features).toHaveLength(1);
    expect(result.line.features[0]?.geometry.type).toBe("LineString");
    expect(result.line.features[0]?.geometry.coordinates).toEqual([
      [-121.8, 47.11],
      [-121.9, 47.2],
    ]);
  });

  it("segments the line and computes an altitude range when altitude data is present", () => {
    const path = [
      point({ lat: 47.0, lon: -122.0, altitude_ft: 5000 }),
      point({ lat: 47.1, lon: -122.1, altitude_ft: 15000 }),
      point({ lat: 47.2, lon: -122.2, altitude_ft: 25000 }),
    ];

    const result = buildPathGeojson(path);

    expect(result.altitudeRangeFt).toEqual([5000, 25000]);
    // Two segments for three points.
    expect(result.line.features).toHaveLength(2);
    expect(result.line.features[0]?.properties.altitude_ft).toBe(10000);
    expect(result.line.features[1]?.properties.altitude_ft).toBe(20000);
  });

  it("computes bounds spanning every point", () => {
    const path = [
      point({ lat: 47.0, lon: -122.0 }),
      point({ lat: 48.0, lon: -121.0 }),
    ];

    const result = buildPathGeojson(path);

    expect(result.bounds).toEqual([
      [-122.0, 47.0],
      [-121.0, 48.0],
    ]);
  });

  it("draws no line for a single-point path but still places coincident markers", () => {
    const result = buildPathGeojson([point()]);

    expect(result.line.features).toHaveLength(0);
    expect(result.endpoints.features).toHaveLength(2);
    expect(result.endpoints.features[0]?.geometry.coordinates).toEqual(
      result.endpoints.features[1]?.geometry.coordinates,
    );
  });
});
