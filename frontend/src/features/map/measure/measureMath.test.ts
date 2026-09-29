import { describe, expect, it } from "vitest";

import {
  destinationPoint,
  greatCircleDistanceNm,
} from "@/features/map/geo/rings";
import {
  describeMeasurement,
  formatBearing,
  greatCircleLine,
  greatCircleMidpoint,
  initialBearingDeg,
  measure,
  MEASURE_LINE_SEGMENTS,
} from "@/features/map/measure/measureMath";

const ORIGIN = { lat: 0, lon: 0 };

describe("initialBearingDeg", () => {
  it.each([
    ["north", { lat: 1, lon: 0 }, 0],
    ["east", { lat: 0, lon: 1 }, 90],
    ["south", { lat: -1, lon: 0 }, 180],
    ["west", { lat: 0, lon: -1 }, 270],
  ])("points %s along the axes", (_name, to, expected) => {
    expect(initialBearingDeg(ORIGIN, to)).toBeCloseTo(expected, 6);
  });

  it("stays in [0, 360) — north-west is 315, not -45", () => {
    expect(initialBearingDeg(ORIGIN, { lat: 1, lon: -1 })).toBeCloseTo(315, 0);
  });

  it("is the *initial* great-circle bearing, not the rhumb line", () => {
    // Seattle to London sets off far north of the rhumb line's ~80°: the
    // great circle climbs over Greenland.
    const bearing = initialBearingDeg(
      { lat: 47.45, lon: -122.31 },
      { lat: 51.47, lon: -0.45 },
    );
    expect(bearing).toBeGreaterThan(20);
    expect(bearing).toBeLessThan(40);
  });

  it("round-trips with the ring geometry's destinationPoint", () => {
    const from = { lat: 47.6, lon: -122.3 };
    for (const bearing of [10, 95, 181, 300]) {
      const to = destinationPoint(from, bearing, 80);
      expect(initialBearingDeg(from, to)).toBeCloseTo(bearing, 6);
    }
  });

  it("is 0 for coincident points", () => {
    expect(initialBearingDeg(ORIGIN, ORIGIN)).toBe(0);
  });
});

describe("measure", () => {
  it("measures one degree of latitude as ~60 nm", () => {
    const result = measure(ORIGIN, { lat: 1, lon: 0 });
    expect(result.distanceNm).toBeCloseTo(60.04, 1);
    expect(result.bearingDeg).toBeCloseTo(0, 6);
  });

  it("uses the same distance the range rings are drawn with", () => {
    const from = { lat: 47.6, lon: -122.3 };
    const to = destinationPoint(from, 45, 100);
    expect(measure(from, to).distanceNm).toBeCloseTo(100, 6);
  });
});

describe("greatCircleLine / greatCircleMidpoint", () => {
  const from = { lat: 47.6, lon: -122.3 };
  const to = destinationPoint(from, 60, 200);
  const measurement = measure(from, to);

  it("runs exactly from A to B in MEASURE_LINE_SEGMENTS segments", () => {
    const line = greatCircleLine(measurement);
    expect(line).toHaveLength(MEASURE_LINE_SEGMENTS + 1);
    expect(line[0]).toEqual([from.lon, from.lat]);
    expect(line.at(-1)).toEqual([to.lon, to.lat]);
  });

  it("places every vertex on the great circle, evenly spaced", () => {
    const line = greatCircleLine(measurement, 4);
    for (let index = 1; index < line.length; index += 1) {
      const [lon, lat] = line[index] as [number, number];
      expect(greatCircleDistanceNm(from, { lat, lon })).toBeCloseTo(
        (200 * index) / 4,
        4,
      );
    }
  });

  it("puts the midpoint halfway along", () => {
    const midpoint = greatCircleMidpoint(measurement);
    expect(greatCircleDistanceNm(from, midpoint)).toBeCloseTo(100, 4);
    expect(greatCircleDistanceNm(midpoint, to)).toBeCloseTo(100, 4);
  });
});

describe("formatBearing", () => {
  it.each([
    [0, "000°"],
    [5.4, "005°"],
    [45, "045°"],
    [270.5, "271°"],
    [359.6, "000°"],
  ])("formats %s as %s", (bearing, expected) => {
    expect(formatBearing(bearing)).toBe(expected);
  });
});

describe("describeMeasurement", () => {
  const from = { lat: 47.6, lon: -122.3 };
  const to = destinationPoint(from, 45, 42.7);

  it("reads nautical miles, three-digit bearing and cardinal in aviation units", () => {
    expect(describeMeasurement(measure(from, to), "aviation")).toBe(
      "42.7 nm · 045° NE",
    );
  });

  it("converts the distance to kilometres for a metric receiver", () => {
    // 42.7 nm x 1.852 = 79.08 km; the bearing is unit-free.
    expect(describeMeasurement(measure(from, to), "metric")).toBe(
      "79.1 km · 045° NE",
    );
  });

  it("names the 16-point cardinal", () => {
    const south = destinationPoint(from, 190, 10);
    expect(describeMeasurement(measure(from, south), "aviation")).toBe(
      "10.0 nm · 190° S",
    );
  });
});
