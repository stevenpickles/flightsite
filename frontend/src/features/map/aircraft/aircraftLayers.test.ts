import type { Map as MapLibreGlMap } from "maplibre-gl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AIRCRAFT_LABEL_LAYER_ID,
  AIRCRAFT_MLAT_RING_LAYER_ID,
  AIRCRAFT_SELECTED_LABEL_LAYER_ID,
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
import {
  SORT_KEY_DEFAULT,
  SORT_KEY_INTERESTING,
} from "@/features/map/labels/priority";
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
  it("adds both sources and all six layers", () => {
    ensureAircraftLayers(map);
    expect([...mock.sources.keys()].sort()).toEqual(
      [AIRCRAFT_SOURCE_ID, AIRCRAFT_TRACK_SOURCE_ID].sort(),
    );
    expect([...mock.layers.keys()]).toEqual([
      AIRCRAFT_TRACK_LAYER_ID,
      AIRCRAFT_SELECTION_LAYER_ID,
      AIRCRAFT_MLAT_RING_LAYER_ID,
      AIRCRAFT_SYMBOL_LAYER_ID,
      AIRCRAFT_LABEL_LAYER_ID,
      AIRCRAFT_SELECTED_LABEL_LAYER_ID,
    ]);
  });

  it("draws the track under the icons, the rings under the symbols, and the labels above everything", () => {
    // Layer order is paint order: the selection halo and the MLAT ring are
    // decoration behind the silhouette, not on top of it, and labels must
    // paint over the silhouettes they annotate.
    ensureAircraftLayers(map);
    const order = [...mock.layers.keys()];
    expect(order.indexOf(AIRCRAFT_TRACK_LAYER_ID)).toBeLessThan(
      order.indexOf(AIRCRAFT_SELECTION_LAYER_ID),
    );
    expect(order.indexOf(AIRCRAFT_MLAT_RING_LAYER_ID)).toBeLessThan(
      order.indexOf(AIRCRAFT_SYMBOL_LAYER_ID),
    );
    expect(order.indexOf(AIRCRAFT_SYMBOL_LAYER_ID)).toBeLessThan(
      order.indexOf(AIRCRAFT_LABEL_LAYER_ID),
    );
    expect(order.indexOf(AIRCRAFT_LABEL_LAYER_ID)).toBeLessThan(
      order.indexOf(AIRCRAFT_SELECTED_LABEL_LAYER_ID),
    );
  });

  it("is idempotent and never re-adds a layer", () => {
    ensureAircraftLayers(map);
    const first = mock.layers.get(AIRCRAFT_SYMBOL_LAYER_ID);
    ensureAircraftLayers(map);
    expect(mock.layers.size).toBe(6);
    expect(mock.layers.get(AIRCRAFT_SYMBOL_LAYER_ID)).toBe(first);
  });

  it("never introduces a clustered GeoJSON source", () => {
    // Roadmap slice 015 explicitly rules out marker clustering as a
    // decluttering mechanism — this guards against one creeping in later.
    const addSource = vi.spyOn(mock, "addSource");
    ensureAircraftLayers(map);
    expect(addSource).toHaveBeenCalled();
    for (const call of addSource.mock.calls) {
      const options = call[1] as Record<string, unknown> | undefined;
      expect(options?.cluster).toBeUndefined();
    }
  });

  it("filters the non-selected label layer to non-empty, non-selected labels", () => {
    ensureAircraftLayers(map);
    expect(mock.layers.get(AIRCRAFT_LABEL_LAYER_ID)?.filter).toEqual([
      "all",
      ["!=", ["get", "label"], ""],
      ["==", ["get", "selected"], false],
    ]);
  });

  it("filters the selected label layer to the selected feature", () => {
    ensureAircraftLayers(map);
    expect(mock.layers.get(AIRCRAFT_SELECTED_LABEL_LAYER_ID)?.filter).toEqual([
      "==",
      ["get", "selected"],
      true,
    ]);
  });

  it("disables collision overlap for ordinary labels but not for the selected one", () => {
    // The whole point of the split: MapLibre's collision system can hide an
    // ordinary label, but the selected aircraft's label must never be the
    // one that loses that contest.
    ensureAircraftLayers(map);
    const ordinary = mock.layers.get(AIRCRAFT_LABEL_LAYER_ID)?.layout as Record<
      string,
      unknown
    >;
    const selected = mock.layers.get(AIRCRAFT_SELECTED_LABEL_LAYER_ID)
      ?.layout as Record<string, unknown>;
    expect(ordinary["text-allow-overlap"]).toBe(false);
    expect(selected["text-allow-overlap"]).toBe(true);
    expect(selected["text-ignore-placement"]).toBe(true);
  });

  it("prioritizes interesting aircraft over ordinary ones in the label collision order", () => {
    ensureAircraftLayers(map);
    const layout = mock.layers.get(AIRCRAFT_LABEL_LAYER_ID)?.layout as Record<
      string,
      unknown
    >;
    expect(layout["symbol-sort-key"]).toEqual([
      "case",
      ["get", "interesting"],
      SORT_KEY_INTERESTING,
      SORT_KEY_DEFAULT,
    ]);
  });

  it("reads label text from the precomputed feature property, never composing it in the style", () => {
    ensureAircraftLayers(map);
    for (const id of [
      AIRCRAFT_LABEL_LAYER_ID,
      AIRCRAFT_SELECTED_LABEL_LAYER_ID,
    ]) {
      const layout = mock.layers.get(id)?.layout as Record<string, unknown>;
      expect(layout["text-field"]).toEqual(["get", "label"]);
    }
  });

  it("fades label opacity with the same staleness signal as the icon", () => {
    ensureAircraftLayers(map);
    for (const id of [
      AIRCRAFT_LABEL_LAYER_ID,
      AIRCRAFT_SELECTED_LABEL_LAYER_ID,
    ]) {
      const paint = mock.layers.get(id)?.paint as Record<string, unknown>;
      expect(paint["text-opacity"]).toEqual(["get", "opacity"]);
    }
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

  it("fully labels the selected aircraft at the mock map's default zoom", () => {
    // The mock defaults `getZoom()` into the full-label band precisely so a
    // test like this one exercises the real `frame.ts` -> `geojson.ts` path
    // end to end instead of stubbing zoom away.
    drawAircraftFrame(map, state, NOW);
    const data = mock.getSource(AIRCRAFT_SOURCE_ID)?.data as {
      features: { properties: { label: string } }[];
    };
    expect(data.features[0]?.properties.label).toBe("RCH471\nFL310");
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
