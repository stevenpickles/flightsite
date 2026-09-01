import type { Feature, FeatureCollection, Geometry } from "geojson";
import type { Map as MapLibreGlMap } from "maplibre-gl";
import { beforeEach, describe, expect, it } from "vitest";

import {
  AIRSPACE_FILL_LAYER_ID,
  AIRSPACE_LAYER_IDS,
  AIRSPACE_LINE_LAYER_ID,
  AIRSPACE_SOURCE_ID,
  EMPTY_AIRSPACE_FEATURE_COLLECTION,
  ensureAirspaceLayers,
  setAirspaceFeatures,
  setAirspaceLayersVisible,
} from "@/features/map/overlays/airspaceLayers";
import { MapLibreMockMap } from "@/test/maplibreGlMock";

let mock: MapLibreMockMap;
let map: MapLibreGlMap;

beforeEach(() => {
  mock = new MapLibreMockMap({});
  map = mock as unknown as MapLibreGlMap;
});

const POLYGON: Feature<Geometry> = {
  type: "Feature",
  properties: { class: "B" },
  geometry: {
    type: "Polygon",
    coordinates: [
      [
        [-1, 50],
        [-1, 51],
        [1, 51],
        [1, 50],
        [-1, 50],
      ],
    ],
  },
};

function collection(
  features: Feature<Geometry>[],
): FeatureCollection<Geometry> {
  return { type: "FeatureCollection", features };
}

describe("ensureAirspaceLayers", () => {
  it("adds the source and both the fill and line layers", () => {
    ensureAirspaceLayers(map);

    expect([...mock.sources.keys()]).toEqual([AIRSPACE_SOURCE_ID]);
    expect([...mock.layers.keys()]).toEqual([
      AIRSPACE_FILL_LAYER_ID,
      AIRSPACE_LINE_LAYER_ID,
    ]);
  });

  it("starts the source with an empty collection — no data present, no file supplied", () => {
    ensureAirspaceLayers(map);
    expect(mock.getSource(AIRSPACE_SOURCE_ID)?.data).toEqual(
      EMPTY_AIRSPACE_FEATURE_COLLECTION,
    );
  });

  it("restricts the fill layer to polygon geometry", () => {
    ensureAirspaceLayers(map);
    const fill = mock.getLayer(AIRSPACE_FILL_LAYER_ID);
    expect(fill?.filter).toEqual(["==", ["geometry-type"], "Polygon"]);
  });

  it("uses a restrained default opacity for the fill", () => {
    ensureAirspaceLayers(map);
    const paint = mock.getLayer(AIRSPACE_FILL_LAYER_ID)?.paint as Record<
      string,
      unknown
    >;
    expect(paint["fill-opacity"]).toBeLessThanOrEqual(0.15);
  });

  it("is idempotent: a second call adds nothing new", () => {
    ensureAirspaceLayers(map);
    ensureAirspaceLayers(map);
    expect(mock.sources.size).toBe(1);
    expect(mock.layers.size).toBe(2);
  });
});

describe("setAirspaceFeatures", () => {
  it("replaces the source's data", () => {
    ensureAirspaceLayers(map);
    const data = collection([POLYGON]);

    setAirspaceFeatures(map, data);

    expect(mock.getSource(AIRSPACE_SOURCE_ID)?.data).toEqual(data);
  });

  it("renders an empty collection without error — the graceful-degradation case", () => {
    ensureAirspaceLayers(map);
    expect(() => setAirspaceFeatures(map, collection([]))).not.toThrow();
    expect(mock.getSource(AIRSPACE_SOURCE_ID)?.data).toEqual({
      type: "FeatureCollection",
      features: [],
    });
  });

  it("falls back to an empty collection for undefined", () => {
    ensureAirspaceLayers(map);
    setAirspaceFeatures(map, undefined);
    expect(mock.getSource(AIRSPACE_SOURCE_ID)?.data).toEqual(
      EMPTY_AIRSPACE_FEATURE_COLLECTION,
    );
  });

  it("no-ops gracefully when the source does not exist yet", () => {
    expect(() => setAirspaceFeatures(map, collection([]))).not.toThrow();
  });
});

describe("setAirspaceLayersVisible", () => {
  it("sets both layers' visibility layout property", () => {
    ensureAirspaceLayers(map);

    setAirspaceLayersVisible(map, false);
    for (const layerId of AIRSPACE_LAYER_IDS) {
      expect(
        (mock.getLayer(layerId)?.layout as Record<string, unknown>)[
          "visibility"
        ],
      ).toBe("none");
    }

    setAirspaceLayersVisible(map, true);
    for (const layerId of AIRSPACE_LAYER_IDS) {
      expect(
        (mock.getLayer(layerId)?.layout as Record<string, unknown>)[
          "visibility"
        ],
      ).toBe("visible");
    }
  });

  it("no-ops gracefully when the layers do not exist yet", () => {
    expect(() => setAirspaceLayersVisible(map, false)).not.toThrow();
  });
});
