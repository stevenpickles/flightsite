import { validateStyleMin } from "@maplibre/maplibre-gl-style-spec";
import type { StyleSpecification } from "@maplibre/maplibre-gl-style-spec";
import type { Map as MapLibreGlMap } from "maplibre-gl";
import { describe, expect, it } from "vitest";

import { OPENFREEMAP_GLYPHS_URL } from "@/features/map/basemaps/paletteStyleFactory";
import {
  buildMeasureFeatureCollection,
  ensureMeasureLayers,
  MEASURE_LABEL_LAYER_ID,
  MEASURE_LINE_LAYER_ID,
  MEASURE_POINT_LAYER_ID,
  MEASURE_SOURCE_ID,
  setMeasureData,
} from "@/features/map/measure/measureLayers";
import {
  describeMeasurement,
  measure,
  MEASURE_LINE_SEGMENTS,
} from "@/features/map/measure/measureMath";
import { MapLibreMockMap } from "@/test/maplibreGlMock";

const A = { lat: 47.6, lon: -122.3 };
const B = { lat: 47.6, lon: -121.3 };

describe("buildMeasureFeatureCollection", () => {
  it("is empty with nothing placed", () => {
    expect(buildMeasureFeatureCollection([], "aviation").features).toEqual([]);
  });

  it("draws only point A while waiting for B", () => {
    const { features } = buildMeasureFeatureCollection([A], "aviation");
    expect(features).toHaveLength(1);
    expect(features[0]?.properties.kind).toBe("point");
    expect(features[0]?.geometry).toEqual({
      type: "Point",
      coordinates: [A.lon, A.lat],
    });
  });

  it("draws the line, both endpoints and a midpoint label once B is placed", () => {
    const { features } = buildMeasureFeatureCollection([A, B], "aviation");
    expect(features.map((feature) => feature.properties.kind)).toEqual([
      "line",
      "point",
      "point",
      "label",
    ]);
    const line = features[0]?.geometry;
    expect(line?.type).toBe("LineString");
    expect(
      (line as { coordinates: unknown[] } | undefined)?.coordinates,
    ).toHaveLength(MEASURE_LINE_SEGMENTS + 1);
    expect(features[3]?.properties.label).toBe(
      describeMeasurement(measure(A, B), "aviation"),
    );
    // Due east along a parallel: ~40.5 nm at this latitude, setting off
    // just north of 090°, which still reads as 090°.
    expect(features[3]?.properties.label).toMatch(/^40\.\d nm · 090° E$/);
  });

  it("labels in the receiver's units", () => {
    const { features } = buildMeasureFeatureCollection([A, B], "metric");
    expect(features.at(-1)?.properties.label).toBe(
      describeMeasurement(measure(A, B), "metric"),
    );
    expect(features.at(-1)?.properties.label).toContain(" km · ");
  });
});

describe("ensureMeasureLayers", () => {
  it("adds one source and the line, point and label layers, idempotently", () => {
    const mock = new MapLibreMockMap({});
    const map = mock as unknown as MapLibreGlMap;
    ensureMeasureLayers(map);
    ensureMeasureLayers(map);
    expect([...mock.sources.keys()]).toEqual([MEASURE_SOURCE_ID]);
    expect([...mock.layers.keys()]).toEqual([
      MEASURE_LINE_LAYER_ID,
      MEASURE_POINT_LAYER_ID,
      MEASURE_LABEL_LAYER_ID,
    ]);
  });

  it("never blanks a measurement in progress when re-run", () => {
    const mock = new MapLibreMockMap({});
    const map = mock as unknown as MapLibreGlMap;
    ensureMeasureLayers(map);
    const data = buildMeasureFeatureCollection([A, B], "aviation");
    setMeasureData(map, data);
    ensureMeasureLayers(map);
    expect(mock.getSource(MEASURE_SOURCE_ID)?.data).toBe(data);
  });

  it("setMeasureData is a no-op before attach", () => {
    const mock = new MapLibreMockMap({});
    expect(() =>
      setMeasureData(
        mock as unknown as MapLibreGlMap,
        buildMeasureFeatureCollection([], "aviation"),
      ),
    ).not.toThrow();
  });

  it("passes the MapLibre style spec", () => {
    // An invalid layer fails silently in MapLibre (issue #96); validate the
    // real layers the way `aircraftLayers.test.ts` does.
    const mock = new MapLibreMockMap({});
    ensureMeasureLayers(mock as unknown as MapLibreGlMap);
    const style = {
      version: 8,
      glyphs: OPENFREEMAP_GLYPHS_URL,
      sources: {
        [MEASURE_SOURCE_ID]: {
          type: "geojson",
          data: { type: "FeatureCollection", features: [] },
        },
      },
      layers: [...mock.layers.values()],
    } as unknown as StyleSpecification;
    expect(validateStyleMin(style)).toEqual([]);
  });
});
