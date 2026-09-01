import type { FeatureCollection, Point } from "geojson";
import type { Map as MapLibreGlMap } from "maplibre-gl";
import { beforeEach, describe, expect, it } from "vitest";

import { AIRPORT_MIN_ZOOM } from "@/features/map/overlays/airportDensity";
import { airportIconImageId } from "@/features/map/overlays/airportIcons";
import {
  AIRPORT_LAYER_IDS,
  AIRPORTS_SOURCE_ID,
  EMPTY_AIRPORT_FEATURE_COLLECTION,
  airportLayerId,
  ensureAirportLayers,
  setAirportFeatures,
  setAirportLayersVisible,
} from "@/features/map/overlays/airportLayers";
import { MapLibreMockMap } from "@/test/maplibreGlMock";

let mock: MapLibreMockMap;
let map: MapLibreGlMap;

beforeEach(() => {
  mock = new MapLibreMockMap({});
  map = mock as unknown as MapLibreGlMap;
});

function collection(
  features: FeatureCollection<Point>["features"],
): FeatureCollection<Point> {
  return { type: "FeatureCollection", features };
}

describe("ensureAirportLayers", () => {
  it("adds the source and one layer per size class", () => {
    ensureAirportLayers(map);

    expect([...mock.sources.keys()]).toEqual([AIRPORTS_SOURCE_ID]);
    expect([...mock.layers.keys()].sort()).toEqual(
      [...AIRPORT_LAYER_IDS].sort(),
    );
  });

  it("starts the source with an empty collection", () => {
    ensureAirportLayers(map);
    expect(mock.getSource(AIRPORTS_SOURCE_ID)?.data).toEqual(
      EMPTY_AIRPORT_FEATURE_COLLECTION,
    );
  });

  it("gives each size class's layer its own glyph and MapLibre minzoom", () => {
    ensureAirportLayers(map);

    for (const sizeClass of ["large", "medium", "small", "heliport"] as const) {
      const layer = mock.getLayer(airportLayerId(sizeClass));
      expect(layer?.minzoom).toBe(AIRPORT_MIN_ZOOM[sizeClass]);
      const layout = layer?.layout as Record<string, unknown>;
      expect(layout["icon-image"]).toBe(airportIconImageId(sizeClass));
      expect(layout["text-field"]).toEqual(["get", "ident"]);
    }
  });

  it("filters each layer to exactly its own size class", () => {
    ensureAirportLayers(map);
    for (const sizeClass of ["large", "medium", "small", "heliport"] as const) {
      const layer = mock.getLayer(airportLayerId(sizeClass));
      expect(layer?.filter).toEqual(["==", ["get", "size_class"], sizeClass]);
    }
  });

  it("is idempotent: a second call adds nothing new", () => {
    ensureAirportLayers(map);
    ensureAirportLayers(map);
    expect(mock.sources.size).toBe(1);
    expect(mock.layers.size).toBe(AIRPORT_LAYER_IDS.length);
  });
});

describe("setAirportFeatures", () => {
  it("replaces the source's data", () => {
    ensureAirportLayers(map);
    const data = collection([
      {
        type: "Feature",
        geometry: { type: "Point", coordinates: [-122.3, 47.5] },
        properties: {
          ident: "KBFI",
          name: "Boeing Field",
          size_class: "large",
        },
      },
    ]);

    setAirportFeatures(map, data);

    expect(mock.getSource(AIRPORTS_SOURCE_ID)?.data).toEqual(data);
  });

  it("falls back to an empty collection for undefined", () => {
    ensureAirportLayers(map);
    setAirportFeatures(map, collection([]));

    setAirportFeatures(map, undefined);

    expect(mock.getSource(AIRPORTS_SOURCE_ID)?.data).toEqual(
      EMPTY_AIRPORT_FEATURE_COLLECTION,
    );
  });

  it("no-ops gracefully when the source does not exist yet", () => {
    expect(() => setAirportFeatures(map, collection([]))).not.toThrow();
  });
});

describe("setAirportLayersVisible", () => {
  it("sets every layer's visibility layout property", () => {
    ensureAirportLayers(map);

    setAirportLayersVisible(map, false);
    for (const layerId of AIRPORT_LAYER_IDS) {
      expect(
        (mock.getLayer(layerId)?.layout as Record<string, unknown>)[
          "visibility"
        ],
      ).toBe("none");
    }

    setAirportLayersVisible(map, true);
    for (const layerId of AIRPORT_LAYER_IDS) {
      expect(
        (mock.getLayer(layerId)?.layout as Record<string, unknown>)[
          "visibility"
        ],
      ).toBe("visible");
    }
  });

  it("no-ops gracefully when the layers do not exist yet", () => {
    expect(() => setAirportLayersVisible(map, false)).not.toThrow();
  });
});
