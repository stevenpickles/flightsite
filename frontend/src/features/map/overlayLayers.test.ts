import type { Map as MapLibreGlMap } from "maplibre-gl";
import { describe, expect, it, vi } from "vitest";

import {
  ensureOverlayLayers,
  RANGE_RING_LABEL_LAYER_ID,
  RANGE_RING_LINE_LAYER_ID,
  RANGE_RINGS_SOURCE_ID,
  RECEIVER_DOT_LAYER_ID,
  RECEIVER_HALO_LAYER_ID,
  RECEIVER_SOURCE_ID,
} from "@/features/map/overlayLayers";
import type { MapConfig } from "@/features/map/types";

const config: MapConfig = {
  receiver: { lat: 47.6, lon: -122.3, label: "Test Receiver" },
  ringRadiiNm: [50, 100, 250],
  unit: "nm",
  displayRadiusNm: 250,
};

/** Lightweight fake of the subset of the MapLibre Map API these helpers
 * use — enough to verify idempotent add/update behavior without pulling
 * in a real (WebGL-requiring) map instance. */
function createFakeMap() {
  const sources = new Map<string, { setData: ReturnType<typeof vi.fn> }>();
  const layers = new Set<string>();

  return {
    addSource: vi.fn((id: string) => {
      sources.set(id, { setData: vi.fn() });
    }),
    getSource: vi.fn((id: string) => sources.get(id)),
    addLayer: vi.fn((layer: { id: string }) => {
      layers.add(layer.id);
    }),
    getLayer: vi.fn((id: string) => (layers.has(id) ? {} : undefined)),
    _sources: sources,
    _layers: layers,
  };
}

describe("ensureOverlayLayers", () => {
  it("adds the range-ring and receiver sources and layers on first call", () => {
    const fakeMap = createFakeMap();
    ensureOverlayLayers(fakeMap as unknown as MapLibreGlMap, config);

    expect(fakeMap._sources.has(RANGE_RINGS_SOURCE_ID)).toBe(true);
    expect(fakeMap._sources.has(RECEIVER_SOURCE_ID)).toBe(true);
    expect(fakeMap._layers.has(RANGE_RING_LINE_LAYER_ID)).toBe(true);
    expect(fakeMap._layers.has(RANGE_RING_LABEL_LAYER_ID)).toBe(true);
    expect(fakeMap._layers.has(RECEIVER_HALO_LAYER_ID)).toBe(true);
    expect(fakeMap._layers.has(RECEIVER_DOT_LAYER_ID)).toBe(true);
  });

  it("is idempotent: a second call updates data instead of re-adding sources/layers", () => {
    const fakeMap = createFakeMap();
    ensureOverlayLayers(fakeMap as unknown as MapLibreGlMap, config);
    const addSourceCalls = fakeMap.addSource.mock.calls.length;
    const addLayerCalls = fakeMap.addLayer.mock.calls.length;

    ensureOverlayLayers(fakeMap as unknown as MapLibreGlMap, config);

    expect(fakeMap.addSource).toHaveBeenCalledTimes(addSourceCalls);
    expect(fakeMap.addLayer).toHaveBeenCalledTimes(addLayerCalls);
    expect(
      fakeMap._sources.get(RANGE_RINGS_SOURCE_ID)?.setData,
    ).toHaveBeenCalled();
    expect(
      fakeMap._sources.get(RECEIVER_SOURCE_ID)?.setData,
    ).toHaveBeenCalled();
  });

  it("updates the receiver source with the new position on a config change", () => {
    const fakeMap = createFakeMap();
    ensureOverlayLayers(fakeMap as unknown as MapLibreGlMap, config);

    const nextConfig: MapConfig = {
      ...config,
      receiver: { ...config.receiver, lat: 40, lon: -74 },
    };
    ensureOverlayLayers(fakeMap as unknown as MapLibreGlMap, nextConfig);

    const receiverSetData = fakeMap._sources.get(RECEIVER_SOURCE_ID)?.setData;
    const lastCallArg = receiverSetData?.mock.calls.at(-1)?.[0];
    expect(lastCallArg.features[0].geometry.coordinates).toEqual([-74, 40]);
  });
});
