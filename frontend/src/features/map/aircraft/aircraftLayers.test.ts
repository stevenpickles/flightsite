import type { Map as MapLibreGlMap } from "maplibre-gl";
import { beforeEach, describe, expect, it } from "vitest";

import {
  AIRCRAFT_MLAT_RING_LAYER_ID,
  AIRCRAFT_SELECTION_LAYER_ID,
  AIRCRAFT_SOURCE_ID,
  AIRCRAFT_SYMBOL_LAYER_ID,
  AIRCRAFT_TRACK_LAYER_ID,
  AIRCRAFT_TRACK_SOURCE_ID,
  aircraftIcaoAtPoint,
  ensureAircraftLayers,
  setAircraftData,
  setTrackData,
} from "@/features/map/aircraft/aircraftLayers";
import { drawAircraftFrame } from "@/features/map/aircraft/frame";
import { MLAT_RING_IMAGE_ID } from "@/features/map/aircraft/icons/silhouettes";
import { makeAircraft } from "@/test/liveAircraftFixtures";
import { MapLibreMockMap } from "@/test/maplibreGlMock";

const NOW = 1_800_000_000_000;

let mock: MapLibreMockMap;
let map: MapLibreGlMap;

const EMPTY_COLLECTION = {
  type: "FeatureCollection" as const,
  features: [],
};

beforeEach(() => {
  mock = new MapLibreMockMap({});
  map = mock as unknown as MapLibreGlMap;
});

describe("ensureAircraftLayers", () => {
  it("adds both sources and all four layers", () => {
    ensureAircraftLayers(map);
    expect([...mock.sources.keys()].sort()).toEqual(
      [AIRCRAFT_SOURCE_ID, AIRCRAFT_TRACK_SOURCE_ID].sort(),
    );
    expect([...mock.layers.keys()]).toEqual([
      AIRCRAFT_TRACK_LAYER_ID,
      AIRCRAFT_SELECTION_LAYER_ID,
      AIRCRAFT_MLAT_RING_LAYER_ID,
      AIRCRAFT_SYMBOL_LAYER_ID,
    ]);
  });

  it("draws the track under the icons and the rings under the symbols", () => {
    // Layer order is paint order: the selection halo and the MLAT ring are
    // decoration behind the silhouette, not on top of it.
    ensureAircraftLayers(map);
    const order = [...mock.layers.keys()];
    expect(order.indexOf(AIRCRAFT_TRACK_LAYER_ID)).toBeLessThan(
      order.indexOf(AIRCRAFT_SELECTION_LAYER_ID),
    );
    expect(order.indexOf(AIRCRAFT_MLAT_RING_LAYER_ID)).toBeLessThan(
      order.indexOf(AIRCRAFT_SYMBOL_LAYER_ID),
    );
  });

  it("is idempotent and never re-adds a layer", () => {
    ensureAircraftLayers(map);
    const first = mock.layers.get(AIRCRAFT_SYMBOL_LAYER_ID);
    ensureAircraftLayers(map);
    expect(mock.layers.size).toBe(4);
    expect(mock.layers.get(AIRCRAFT_SYMBOL_LAYER_ID)).toBe(first);
  });

  it("updates an existing source in place rather than replacing it", () => {
    // Re-adding the source every frame would rebuild the style and defeat the
    // whole point of setData.
    ensureAircraftLayers(map);
    const source = mock.getSource(AIRCRAFT_SOURCE_ID);
    ensureAircraftLayers(map);
    expect(mock.getSource(AIRCRAFT_SOURCE_ID)).toBe(source);
    expect(source?.setData).toHaveBeenCalledTimes(1);
  });

  it("rotates the symbols by the feature's track, aligned to the map", () => {
    ensureAircraftLayers(map);
    const layer = mock.layers.get(AIRCRAFT_SYMBOL_LAYER_ID);
    const layout = layer?.layout as Record<string, unknown>;
    expect(layout["icon-rotate"]).toEqual(["get", "track"]);
    expect(layout["icon-rotation-alignment"]).toBe("map");
    expect(layout["icon-image"]).toEqual(["get", "icon"]);
  });

  it("scales the icons with zoom and enlarges the selection", () => {
    ensureAircraftLayers(map);
    const layout = mock.layers.get(AIRCRAFT_SYMBOL_LAYER_ID)?.layout as Record<
      string,
      unknown
    >;
    expect(JSON.stringify(layout["icon-size"])).toContain('["zoom"]');
    expect(JSON.stringify(layout["icon-size"])).toContain('"selected"');
  });

  it("drives icon opacity from the computed feature property", () => {
    ensureAircraftLayers(map);
    const paint = mock.layers.get(AIRCRAFT_SYMBOL_LAYER_ID)?.paint as Record<
      string,
      unknown
    >;
    expect(paint["icon-opacity"]).toEqual(["get", "opacity"]);
  });

  it("filters the MLAT ring to multilaterated positions and keeps it upright", () => {
    ensureAircraftLayers(map);
    const layer = mock.layers.get(AIRCRAFT_MLAT_RING_LAYER_ID);
    expect(layer?.filter).toEqual(["==", ["get", "mlat"], true]);
    const layout = layer?.layout as Record<string, unknown>;
    expect(layout["icon-image"]).toBe(MLAT_RING_IMAGE_ID);
    expect(layout["icon-rotation-alignment"]).toBe("viewport");
  });

  it("filters the selection halo to the selected feature", () => {
    ensureAircraftLayers(map);
    expect(mock.layers.get(AIRCRAFT_SELECTION_LAYER_ID)?.filter).toEqual([
      "==",
      ["get", "selected"],
      true,
    ]);
  });
});

describe("setAircraftData / setTrackData", () => {
  it("pushes data through the existing sources", () => {
    ensureAircraftLayers(map);
    setAircraftData(map, EMPTY_COLLECTION);
    setTrackData(map, EMPTY_COLLECTION);
    expect(mock.getSource(AIRCRAFT_SOURCE_ID)?.setData).toHaveBeenCalledWith(
      EMPTY_COLLECTION,
    );
    expect(
      mock.getSource(AIRCRAFT_TRACK_SOURCE_ID)?.setData,
    ).toHaveBeenCalledWith(EMPTY_COLLECTION);
  });

  it("is a no-op before the layers exist", () => {
    // A frame can be scheduled between a style swap and the re-attach.
    expect(() => {
      setAircraftData(map, EMPTY_COLLECTION);
      setTrackData(map, EMPTY_COLLECTION);
    }).not.toThrow();
  });
});

describe("drawAircraftFrame", () => {
  const state = {
    aircraft: {
      aaaaaa: {
        aircraft: makeAircraft({
          icao: "aaaaaa",
          position: { lat: 47, lon: -122 },
          ground_speed_kt: null,
        }),
        receivedAt: NOW,
      },
    },
    departing: {},
    selectedIcao: "aaaaaa",
    track: {
      icao: "aaaaaa",
      points: [
        { lat: 47, lon: -122, at: NOW - 1000 },
        { lat: 47.1, lon: -122, at: NOW },
      ],
    },
  };

  beforeEach(() => {
    ensureAircraftLayers(map);
  });

  it("rebuilds the aircraft source from store state", () => {
    drawAircraftFrame(map, state, NOW);
    const data = mock.getSource(AIRCRAFT_SOURCE_ID)?.data as {
      features: { properties: { icao: string; selected: boolean } }[];
    };
    expect(data.features).toHaveLength(1);
    expect(data.features[0]?.properties).toMatchObject({
      icao: "aaaaaa",
      selected: true,
    });
  });

  it("leaves the track alone on an interpolation frame", () => {
    // Re-serializing up to 900 coordinates ten times a second for an unchanged
    // line is exactly the per-frame waste a Pi cannot afford.
    const track = mock.getSource(AIRCRAFT_TRACK_SOURCE_ID);
    drawAircraftFrame(map, state, NOW);
    expect(track?.setData).not.toHaveBeenCalled();
  });

  it("rebuilds the track when asked", () => {
    drawAircraftFrame(map, state, NOW, { includeTrack: true });
    const data = mock.getSource(AIRCRAFT_TRACK_SOURCE_ID)?.data as {
      features: unknown[];
    };
    expect(data.features).toHaveLength(1);
  });
});

describe("aircraftIcaoAtPoint", () => {
  it("returns the icao of the aircraft under the cursor", () => {
    ensureAircraftLayers(map);
    mock.renderedFeatures = [{ properties: { icao: "ae1463" } }];
    expect(aircraftIcaoAtPoint(map, [10, 20])).toBe("ae1463");
  });

  it("returns null when the click hit empty map", () => {
    ensureAircraftLayers(map);
    mock.renderedFeatures = [];
    expect(aircraftIcaoAtPoint(map, [10, 20])).toBeNull();
  });

  it("returns null when the layer is not on the style yet", () => {
    mock.renderedFeatures = [{ properties: { icao: "ae1463" } }];
    expect(aircraftIcaoAtPoint(map, [10, 20])).toBeNull();
  });

  it("ignores a feature with no usable icao", () => {
    ensureAircraftLayers(map);
    mock.renderedFeatures = [{ properties: { icao: 7 } }];
    expect(aircraftIcaoAtPoint(map, [10, 20])).toBeNull();
  });
});
