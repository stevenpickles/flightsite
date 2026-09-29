import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { getBasemapById, getDefaultBasemap } from "@/features/map/basemaps";
import { MapLibreMap } from "@/features/map/MapLibreMap";
import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
import {
  RANGE_RING_LABEL_LAYER_ID,
  RANGE_RING_LINE_LAYER_ID,
  RECEIVER_DOT_LAYER_ID,
  RECEIVER_HALO_LAYER_ID,
} from "@/features/map/overlayLayers";
import { useDisplayLayerVisibility } from "@/features/map/overlays/useDisplayLayerVisibility";
import { DEFAULT_OVERLAY_VISIBILITY } from "@/features/map/overlayVisibilityPersistence";
import { useOverlayVisibilityStore } from "@/features/map/store/useOverlayVisibilityStore";
import {
  getLastMockMap,
  resetMapLibreMock,
  type MapLibreMockMap,
} from "@/test/maplibreGlMock";

const basemap = getDefaultBasemap();
const otherBasemap = getBasemapById("osm-raster")!;
const config = DEV_PLACEHOLDER_MAP_CONFIG;

function Probe() {
  useDisplayLayerVisibility();
  return null;
}

function visibility(map: MapLibreMockMap, layerId: string): unknown {
  const layout = map.layers.get(layerId)?.layout as
    Record<string, unknown> | undefined;
  return layout?.visibility;
}

beforeEach(() => {
  resetMapLibreMock();
});

afterEach(() => {
  window.localStorage.clear();
  useOverlayVisibilityStore.setState({ ...DEFAULT_OVERLAY_VISIBILITY });
});

describe("useDisplayLayerVisibility", () => {
  it("applies the stored range-ring and receiver choices once the style loads", () => {
    useOverlayVisibilityStore.setState({ rangeRings: false, receiver: false });
    render(
      <MapLibreMap config={config} basemap={basemap}>
        <Probe />
      </MapLibreMap>,
    );
    const map = getLastMockMap();
    act(() => {
      map.emit("load");
    });

    for (const id of [RANGE_RING_LINE_LAYER_ID, RANGE_RING_LABEL_LAYER_ID]) {
      expect(visibility(map, id)).toBe("none");
    }
    for (const id of [RECEIVER_HALO_LAYER_ID, RECEIVER_DOT_LAYER_ID]) {
      expect(visibility(map, id)).toBe("none");
    }
  });

  it("follows a toggle without touching the other overlay", () => {
    render(
      <MapLibreMap config={config} basemap={basemap}>
        <Probe />
      </MapLibreMap>,
    );
    const map = getLastMockMap();
    act(() => {
      map.emit("load");
    });
    expect(visibility(map, RANGE_RING_LINE_LAYER_ID)).toBe("visible");

    act(() => {
      useOverlayVisibilityStore.getState().setRangeRingsVisible(false);
    });
    expect(visibility(map, RANGE_RING_LINE_LAYER_ID)).toBe("none");
    expect(visibility(map, RECEIVER_DOT_LAYER_ID)).toBe("visible");

    act(() => {
      useOverlayVisibilityStore.getState().setRangeRingsVisible(true);
    });
    expect(visibility(map, RANGE_RING_LINE_LAYER_ID)).toBe("visible");
  });

  it("re-applies a hidden overlay after a basemap switch re-adds the layers", () => {
    // `setStyle` drops every custom layer (and the visibility it carried);
    // `MapLibreMap` re-adds them visible and bumps `styleEpoch`, and the hook
    // must hide them again — issue #228's "toggles survive basemap switch".
    useOverlayVisibilityStore.setState({ rangeRings: false, receiver: false });
    const { rerender } = render(
      <MapLibreMap config={config} basemap={basemap}>
        <Probe />
      </MapLibreMap>,
    );
    const map = getLastMockMap();
    act(() => {
      map.emit("load");
    });
    const before = map.layers.get(RANGE_RING_LINE_LAYER_ID);

    act(() => {
      rerender(
        <MapLibreMap config={config} basemap={otherBasemap}>
          <Probe />
        </MapLibreMap>,
      );
    });

    // A genuinely new layer object — the switch really did re-add it …
    expect(map.layers.get(RANGE_RING_LINE_LAYER_ID)).not.toBe(before);
    // … and it is hidden again.
    expect(visibility(map, RANGE_RING_LINE_LAYER_ID)).toBe("none");
    expect(visibility(map, RECEIVER_DOT_LAYER_ID)).toBe("none");
  });
});
