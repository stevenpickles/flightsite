import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getBasemapById, getDefaultBasemap } from "@/features/map/basemaps";
import { MapLibreMap } from "@/features/map/MapLibreMap";
import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
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

  it("clears the degraded indicator once the map loads successfully", () => {
    render(<MapLibreMap config={config} basemap={basemap} />);
    const map = getLastMockMap();

    act(() => {
      map.emit("error", { error: new Error("network error") });
    });
    expect(screen.getByRole("status")).toBeInTheDocument();

    act(() => {
      map.emit("load");
    });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("does not call setStyle on initial mount (the map is already constructed with that style)", () => {
    render(<MapLibreMap config={config} basemap={basemap} />);
    const map = getLastMockMap();
    expect(map.setStyle).not.toHaveBeenCalled();
  });

  it("swaps the style and re-adds overlay layers on a basemap change", () => {
    const { rerender } = render(
      <MapLibreMap config={config} basemap={basemap} />,
    );
    const map = getLastMockMap();
    act(() => {
      map.emit("load");
    });

    rerender(<MapLibreMap config={config} basemap={otherBasemap} />);
    expect(map.setStyle).toHaveBeenCalledWith(otherBasemap.style);

    map.layers.clear();
    act(() => {
      map.emit("style.load");
    });
    expect(map.layers.size).toBeGreaterThan(0);
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
