import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getBasemapById, getDefaultBasemap } from "@/features/map/basemaps";
import { MapLibreMap } from "@/features/map/MapLibreMap";
import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
import {
  RANGE_RING_LINE_LAYER_ID,
  RANGE_RINGS_SOURCE_ID,
  RECEIVER_DOT_LAYER_ID,
  RECEIVER_SOURCE_ID,
} from "@/features/map/overlayLayers";
import type { MapConfig } from "@/features/map/types";
import {
  AttributionControlMock,
  getLastMockMap,
  MapLibreMockMap,
  resetMapLibreMock,
} from "@/test/maplibreGlMock";

// The `maplibre-gl` mock itself is registered globally in
// src/test/setup.ts (jsdom has no WebGL context to construct a real map).

beforeEach(() => {
  resetMapLibreMock();
});

afterEach(() => {
  vi.restoreAllMocks();
});

const basemap = getDefaultBasemap();
const otherBasemap = getBasemapById("osm-raster")!;
const config = DEV_PLACEHOLDER_MAP_CONFIG;

/** Whatever the receiver-marker source currently holds. */
function receiverFeatures(map: MapLibreMockMap): unknown[] {
  const data = map.getSource(RECEIVER_SOURCE_ID)?.data as
    { features: unknown[] } | undefined;
  return data?.features ?? [];
}

describe("MapLibreMap", () => {
  it("renders a map container centered on the receiver", () => {
    render(<MapLibreMap config={config} basemap={basemap} />);
    expect(screen.getByTestId("maplibre-container")).toBeInTheDocument();
    expect(MapLibreMockMap.instances).toHaveLength(1);
    expect(getLastMockMap().options.center).toEqual([
      config.receiver.lon,
      config.receiver.lat,
    ]);
  });

  it("leaves the symbol fade duration at MapLibre's default", () => {
    // `fadeDuration` is also the minimum interval between label placement
    // passes (`Placement.stillRecent`), so it is the one knob that would
    // damp the anchor movement issue #147 measured — and the one that
    // decision declined, because raising it slows every symbol's fade and
    // delays a collided label's return in exchange. Pinned so a future
    // change to it is a deliberate revisit of that reasoning.
    render(<MapLibreMap config={config} basemap={basemap} />);
    expect(getLastMockMap().options.fadeDuration).toBeUndefined();
  });

  it("adds an always-visible attribution control", () => {
    render(<MapLibreMap config={config} basemap={basemap} />);
    const map = getLastMockMap();
    expect(map.addControl).toHaveBeenCalledTimes(1);
    expect(map.addControl.mock.calls[0]?.[0]).toBeInstanceOf(
      AttributionControlMock,
    );
  });

  it("adds range-ring and receiver layers once the map fires 'load'", () => {
    render(<MapLibreMap config={config} basemap={basemap} />);
    const map = getLastMockMap();

    expect(map.layers.size).toBe(0);
    act(() => {
      map.emit("load");
    });
    expect(map.layers.size).toBeGreaterThan(0);
  });

  it("recenters the camera once the real receiver location replaces the mount-time config", () => {
    // The map is constructed with whatever `config` the first render held
    // — for the Live Map that's always `DEV_PLACEHOLDER_MAP_CONFIG`, since
    // React Query never resolves synchronously — until `mapConfigSync.ts`
    // replaces it with the real receiver location. This must not depend on
    // the map's own 'load' event: that races the config fetch
    // unpredictably (tile/style network conditions vary), so the recenter
    // reacts to the `config` prop itself instead (see MapLibreMap.tsx's
    // `isInitialConfigRef` comment).
    const { rerender } = render(
      <MapLibreMap config={config} basemap={basemap} />,
    );
    const map = getLastMockMap();
    expect(map.jumpTo).not.toHaveBeenCalled();

    const realConfig = {
      ...config,
      receiver: { lat: 47.6205, lon: -122.3493, label: "Rooftop Pi" },
    };
    act(() => {
      rerender(<MapLibreMap config={realConfig} basemap={basemap} />);
    });

    expect(map.jumpTo).toHaveBeenCalledTimes(1);
    expect(map.jumpTo).toHaveBeenCalledWith({
      center: [realConfig.receiver.lon, realConfig.receiver.lat],
    });
  });

  it("never recenters a second time (a later config edit must not fight the user's pan/zoom)", () => {
    const { rerender } = render(
      <MapLibreMap config={config} basemap={basemap} />,
    );
    const map = getLastMockMap();

    const firstConfig = {
      ...config,
      receiver: { lat: 47.6205, lon: -122.3493, label: "Rooftop Pi" },
    };
    act(() => {
      rerender(<MapLibreMap config={firstConfig} basemap={basemap} />);
    });
    expect(map.jumpTo).toHaveBeenCalledTimes(1);

    const secondConfig = {
      ...config,
      receiver: { lat: 51.5, lon: -0.1, label: "Another site" },
    };
    act(() => {
      rerender(<MapLibreMap config={secondConfig} basemap={basemap} />);
    });
    expect(map.jumpTo).toHaveBeenCalledTimes(1);
  });

  it("shows no degraded indicator before any tile error", () => {
    render(<MapLibreMap config={config} basemap={basemap} />);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("shows a non-blocking 'basemap unavailable' indicator on a tile error", () => {
    render(<MapLibreMap config={config} basemap={basemap} />);
    const map = getLastMockMap();

    act(() => {
      map.emit("error", { error: new Error("network error") });
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      /basemap unavailable/i,
    );
    // The map container (and, by extension, the client-drawn rings and
    // receiver marker layered on the canvas) must remain in the document.
    expect(screen.getByTestId("maplibre-container")).toBeInTheDocument();
  });

  it("places the degraded notice clear of the corners the panels claim", () => {
    // Issue R1-16: at `bottom-3 left-3 z-10` the notice shared a slot, and a
    // z-index, with the Live Map's interesting/non-positioned column, and
    // lost — one word of it was legible in the review's screenshot.
    render(<MapLibreMap config={config} basemap={basemap} />);
    act(() => {
      getLastMockMap().emit("error", { error: new Error("network error") });
    });

    const slot = screen.getByTestId("map-degraded-notice");
    // Above every floating panel (they are z-10/z-20), and in the one edge
    // of the map none of them occupies.
    expect(slot).toHaveClass("z-30");
    expect(slot).toHaveClass("justify-center");
    expect(slot.className).not.toMatch(/\bleft-3\b|\bright-3\b/);
  });

  it("keeps the degraded indicator up while only the tiles are down", () => {
    // Issue R1-05: `load` fires on a map whose tile requests have already
    // failed — that *is* the degraded case, a working renderer with no
    // imagery — so clearing the flag there cancelled the notice the error
    // listener had just raised and the outage went unannounced.
    render(<MapLibreMap config={config} basemap={basemap} />);
    const map = getLastMockMap();

    act(() => {
      map.emit("error", { error: new Error("network error") });
      map.emit("load");
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      /basemap unavailable/i,
    );
  });

  it("clears the degraded indicator when a basemap source actually loads", () => {
    render(<MapLibreMap config={config} basemap={basemap} />);
    const map = getLastMockMap();

    act(() => {
      map.emit("error", { error: new Error("network error") });
    });
    expect(screen.getByRole("status")).toBeInTheDocument();

    act(() => {
      // FlightSite's own client-drawn GeoJSON loads without a network and
      // must not be read as evidence that the basemap came back.
      map.emit("sourcedata", {
        isSourceLoaded: true,
        sourceId: RANGE_RINGS_SOURCE_ID,
      });
    });
    expect(screen.getByRole("status")).toBeInTheDocument();

    act(() => {
      map.emit("sourcedata", {
        isSourceLoaded: true,
        sourceId: "openmaptiles",
      });
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("corrects the overlays when the real config arrives after the style load", () => {
    // Issue R1-05: with the tile host blocked, `isStyleLoaded()` never
    // becomes true, so the old config effect bailed on every run and the
    // rings and receiver marker kept whichever config won the race against
    // `GET /api/internal/config` — the placeholder, 1,400 nm away.
    const { rerender } = render(
      <MapLibreMap config={config} basemap={basemap} />,
    );
    const map = getLastMockMap();
    act(() => {
      map.emit("error", { error: new Error("tiles blocked") });
      map.emit("load");
    });
    // `isStyleLoaded()` is `_loaded && every source loaded`, so a style
    // whose vector tiles are erroring reports false for as long as the
    // outage lasts — while its layers stay perfectly editable. That gap is
    // what the old guard tripped over.
    map.styleLoaded = false;
    // Nothing is drawn from the placeholder at all.
    expect(receiverFeatures(map)).toEqual([]);

    const realConfig: MapConfig = {
      ...config,
      receiver: { lat: 39.8283, lon: -98.5795, label: "Review Site" },
      receiverConfigured: true,
    };
    act(() => {
      rerender(<MapLibreMap config={realConfig} basemap={basemap} />);
    });

    expect(receiverFeatures(map)).toHaveLength(1);
    expect(
      (receiverFeatures(map)[0] as { geometry: { coordinates: number[] } })
        .geometry.coordinates,
    ).toEqual([-98.5795, 39.8283]);
  });

  it("names no placeholder site while the receiver location is unknown", () => {
    render(<MapLibreMap config={config} basemap={basemap} />);
    expect(screen.getByTestId("maplibre-container")).toHaveAttribute(
      "aria-label",
      "Live map — receiver location not configured",
    );
  });

  it("does not call setStyle on initial mount (the map is already constructed with that style)", () => {
    render(<MapLibreMap config={config} basemap={basemap} />);
    const map = getLastMockMap();
    expect(map.setStyle).not.toHaveBeenCalled();
  });

  it("swaps the style and re-adds overlay layers on a basemap change", () => {
    // Issue R1-01: `setStyle` clears the style's custom layers and fires
    // `style.load` synchronously for an inline style object, so nothing is
    // emitted by hand here. A handler registered after the swap would miss
    // that event and leave the map empty, which is precisely what shipped.
    const { rerender } = render(
      <MapLibreMap config={config} basemap={basemap} />,
    );
    const map = getLastMockMap();
    act(() => {
      map.emit("load");
    });
    expect(map.layers.has(RANGE_RING_LINE_LAYER_ID)).toBe(true);

    act(() => {
      rerender(<MapLibreMap config={config} basemap={otherBasemap} />);
    });

    expect(map.setStyle).toHaveBeenCalledWith(otherBasemap.style);
    expect(map.layers.has(RANGE_RING_LINE_LAYER_ID)).toBe(true);
    expect(map.layers.has(RECEIVER_DOT_LAYER_ID)).toBe(true);
  });

  it("re-adds the overlay layers even if the style swap fires no event", () => {
    // The self-healing branch: `Style.setState` fires `style.load` only when
    // its diff produced an operation, and falls back to a full style reload
    // when the diff cannot be applied. Asking the map — style loaded, our
    // layers gone — covers every path without assuming which one ran.
    const { rerender } = render(
      <MapLibreMap config={config} basemap={basemap} />,
    );
    const map = getLastMockMap();
    act(() => {
      map.emit("load");
    });

    map.setStyle = vi.fn(() => {
      map.layers.clear();
      map.sources.clear();
      map.styleLoaded = true;
    });
    act(() => {
      rerender(<MapLibreMap config={config} basemap={otherBasemap} />);
    });

    expect(map.layers.has(RANGE_RING_LINE_LAYER_ID)).toBe(true);
    expect(map.layers.has(RECEIVER_DOT_LAYER_ID)).toBe(true);
  });

  it("removes the map instance on unmount", () => {
    const { unmount } = render(
      <MapLibreMap config={config} basemap={basemap} />,
    );
    const map = getLastMockMap();
    unmount();
    expect(map.removed).toBe(true);
  });
});

describe("WebGL-unavailable degradation", () => {
  const renderMap = () =>
    render(<MapLibreMap config={config} basemap={basemap} />);

  it("renders the unsupported notice instead of crashing when the map cannot construct", () => {
    MapLibreMockMap.throwOnNextConstruct = true;
    const { unmount } = renderMap();

    expect(screen.getByTestId("map-unsupported")).toBeInTheDocument();
    expect(
      screen.getByText(/cannot render in this browser/i),
    ).toBeInTheDocument();
    // No half-constructed instance was recorded, and unmounting the failed
    // map must not throw either.
    expect(MapLibreMockMap.instances).toHaveLength(0);
    expect(() => unmount()).not.toThrow();
  });

  it("survives a map whose teardown throws (dead GL context)", () => {
    const { unmount } = renderMap();
    const map = getLastMockMap();
    map.remove = vi.fn(() => {
      throw new Error(
        'can\'t access property "destroy", this.painter is undefined',
      );
    });

    expect(() => unmount()).not.toThrow();
    expect(map.remove).toHaveBeenCalled();
  });
});
