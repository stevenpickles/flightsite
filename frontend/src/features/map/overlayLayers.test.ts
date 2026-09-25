import type { FeatureCollection } from "geojson";
import type { Map as MapLibreGlMap } from "maplibre-gl";
import { describe, expect, it, vi } from "vitest";

import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
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
  receiverConfigured: true,
  ringRadiiNm: [50, 100, 250],
  unit: "nm",
  displayRadiusNm: 250,
};

/** Lightweight fake of the subset of the MapLibre Map API these helpers
 * use — enough to verify idempotent add/update behavior without pulling
 * in a real (WebGL-requiring) map instance. */
function createFakeMap() {
  const sources = new Map<
    string,
    { setData: ReturnType<typeof vi.fn>; data: unknown }
  >();
  const layers = new Set<string>();

  return {
    addSource: vi.fn((id: string, source?: { data?: unknown }) => {
      const entry = {
        data: source?.data,
        setData: vi.fn((data: unknown) => {
          entry.data = data;
        }),
      };
      sources.set(id, entry);
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

  it("draws no rings and no receiver marker until the location is configured", () => {
    // Issue R1-05: the pre-configuration fallback is a camera centre, not a
    // receiver. Drawing it put a marker and five range rings 1,400 nm from
    // the actual site on an install whose config fetch lost a race with the
    // style load. The layers are still added, so a real config later is a
    // `setData` rather than a style edit.
    const fakeMap = createFakeMap();
    ensureOverlayLayers(
      fakeMap as unknown as MapLibreGlMap,
      DEV_PLACEHOLDER_MAP_CONFIG,
    );

    expect(fakeMap._layers.has(RECEIVER_DOT_LAYER_ID)).toBe(true);
    expect(fakeMap._layers.has(RANGE_RING_LINE_LAYER_ID)).toBe(true);
    expect(
      (fakeMap._sources.get(RECEIVER_SOURCE_ID)?.data as FeatureCollection)
        .features,
    ).toEqual([]);
    expect(
      (fakeMap._sources.get(RANGE_RINGS_SOURCE_ID)?.data as FeatureCollection)
        .features,
    ).toEqual([]);
  });

  it("fills both overlays as soon as a real receiver location arrives", () => {
    const fakeMap = createFakeMap();
    ensureOverlayLayers(
      fakeMap as unknown as MapLibreGlMap,
      DEV_PLACEHOLDER_MAP_CONFIG,
    );
    ensureOverlayLayers(fakeMap as unknown as MapLibreGlMap, config);

    const receiver = fakeMap._sources
      .get(RECEIVER_SOURCE_ID)
      ?.setData.mock.calls.at(-1)?.[0] as FeatureCollection;
    const rings = fakeMap._sources
      .get(RANGE_RINGS_SOURCE_ID)
      ?.setData.mock.calls.at(-1)?.[0] as FeatureCollection;
    expect(receiver.features).toHaveLength(1);
    expect(rings.features).toHaveLength(config.ringRadiiNm.length);
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
