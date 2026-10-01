import { describe, expect, it } from "vitest";

import {
  buildAreaGeojson,
  closedRing,
  formatAreaText,
  MAX_AREA_VERTICES,
  parseAreaText,
  readableVertices,
  roundCoordinate,
  validateAreaVertices,
  type Vertex,
} from "@/features/alerts/lib/area";

const SQUARE: Vertex[] = [
  [-2, 50],
  [-1, 50],
  [-1, 51],
  [-2, 51],
];

function circle(count: number): Vertex[] {
  return Array.from({ length: count }, (_, k) => [
    Math.cos((2 * Math.PI * k) / count),
    Math.sin((2 * Math.PI * k) / count),
  ]);
}

describe("parseAreaText / formatAreaText", () => {
  it("round-trips a ring through its text form", () => {
    const parsed = parseAreaText(formatAreaText(SQUARE));

    expect(parsed).toEqual({ ok: true, vertices: SQUARE });
  });

  it("accepts commas, spaces, brackets and blank lines", () => {
    const parsed = parseAreaText("[-2, 50]\n\n-1 50\n-1,51\n  -2 ,  51  ");

    expect(parsed).toEqual({ ok: true, vertices: SQUARE });
  });

  it("drops a closing vertex that repeats the first", () => {
    const parsed = parseAreaText(formatAreaText(closedRing(SQUARE)));

    expect(parsed).toEqual({ ok: true, vertices: SQUARE });
  });

  it("names the first line that is not a pair", () => {
    expect(parseAreaText("-2, 50\n-1\n-1, 51")).toEqual({
      ok: false,
      error: 'Line 2 is not a "longitude, latitude" pair.',
    });
    expect(parseAreaText("-2, 50, 3")).toMatchObject({ ok: false });
    expect(parseAreaText("west, 50")).toMatchObject({ ok: false });
  });

  it("reads what it can while a line is half typed", () => {
    expect(readableVertices("-2, 50\n-1, 50\n-1,")).toEqual([
      [-2, 50],
      [-1, 50],
    ]);
  });

  it("rounds a map click to about a metre", () => {
    expect(roundCoordinate(-1.234567891)).toBe(-1.23457);
  });
});

describe("validateAreaVertices", () => {
  it("accepts a simple square", () => {
    expect(validateAreaVertices(SQUARE)).toBeNull();
  });

  it("needs 3 to 64 vertices", () => {
    expect(validateAreaVertices(SQUARE.slice(0, 2))).toMatch(
      /between 3 and 64 vertices \(it has 2\)/,
    );
    expect(validateAreaVertices(circle(MAX_AREA_VERTICES))).toBeNull();
    expect(validateAreaVertices(circle(MAX_AREA_VERTICES + 1))).toMatch(
      /it has 65/,
    );
  });

  it("explains a swapped pair by naming the axis order", () => {
    // A latitude/longitude pair typed the wrong way round near 100°E.
    expect(
      validateAreaVertices([
        [10, 100],
        [11, 100],
        [11, 101],
      ]),
    ).toMatch(/latitude 100.*longitude first/);
    expect(
      validateAreaVertices([
        [0, 0],
        [181, 0],
        [0, 1],
      ]),
    ).toMatch(/longitude 181/);
    expect(
      validateAreaVertices([
        [0, 0],
        [1, 0],
        [1, 95],
      ]),
    ).toMatch(/latitude 95/);
  });

  it("refuses a ring crossing the antimeridian", () => {
    expect(
      validateAreaVertices([
        [179, 10],
        [-179, 10],
        [-179, 12],
        [179, 12],
      ]),
    ).toMatch(/180° meridian/);
  });

  it("refuses crossing edges", () => {
    expect(
      validateAreaVertices([
        [0, 0],
        [2, 2],
        [2, 0],
        [0, 2],
      ]),
    ).toMatch(/edge 1 crosses edge 3/);
  });

  it("refuses an edge folding back on itself", () => {
    expect(
      validateAreaVertices([
        [0, 0],
        [2, 0],
        [1, 0],
        [1, 1],
      ]),
    ).toMatch(/folds back|crosses/);
  });

  it("refuses a repeated vertex", () => {
    expect(
      validateAreaVertices([
        [0, 0],
        [1, 0],
        [1, 1],
        [1, 0],
      ]),
    ).toMatch(/repeated/);
  });
});

describe("buildAreaGeojson", () => {
  it("draws a line for two vertices and a closed polygon for three or more", () => {
    expect(
      buildAreaGeojson(SQUARE.slice(0, 2)).shape.features[0]?.geometry.type,
    ).toBe("LineString");
    const polygon = buildAreaGeojson(SQUARE).shape.features[0]?.geometry;
    expect(polygon).toEqual({
      type: "Polygon",
      coordinates: [closedRing(SQUARE)],
    });
  });

  it("numbers each vertex for hit-testing", () => {
    const points = buildAreaGeojson(SQUARE).points.features;

    expect(points.map((feature) => feature.properties?.index)).toEqual([
      0, 1, 2, 3,
    ]);
  });
});
