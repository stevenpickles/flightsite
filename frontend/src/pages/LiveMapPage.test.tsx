import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AIRCRAFT_SOURCE_ID,
  AIRCRAFT_SYMBOL_LAYER_ID,
  AIRCRAFT_TRACK_SOURCE_ID,
} from "@/features/map/aircraft/aircraftLayers";
import type { AircraftFeatureProperties } from "@/features/map/aircraft/geojson";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { DEFAULT_BASEMAP_ID } from "@/features/map/basemaps";
import { useBasemapStore } from "@/features/map/store/useBasemapStore";
import { LiveMapPage } from "@/pages/LiveMapPage";
import { makeAircraft } from "@/test/liveAircraftFixtures";
import {
  getLastMockMap,
  MapLibreMockMap,
  resetMapLibreMock,
} from "@/test/maplibreGlMock";
import { getLastWebSocket, resetWebSocketMock } from "@/test/webSocketMock";

// The `maplibre-gl` and `WebSocket` mocks are registered globally in
// src/test/setup.ts (jsdom has neither a WebGL context nor a socket server).

beforeEach(() => {
  resetMapLibreMock();
  resetWebSocketMock();
  useLiveAircraftStore.getState().reset();
});

afterEach(() => {
  window.localStorage.clear();
  useBasemapStore.setState({ basemapId: DEFAULT_BASEMAP_ID });
  vi.restoreAllMocks();
});

/** Renders the page and drives the map through its first style load, which is
 * what registers the icons and attaches the aircraft layers. */
async function renderLoadedMap() {
  render(<LiveMapPage />);
  const map = getLastMockMap();
  await act(async () => {
    map.emit("load");
  });
  // The icons are decoded asynchronously, and the layers are attached only
  // once every one of them is registered.
  await act(async () => {
    await Promise.resolve();
  });
  return map;
}

function snapshotFrame(
  seq: number,
  aircraft: ReturnType<typeof makeAircraft>[],
) {
  return {
    type: "snapshot",
    seq,
    data: { aircraft, receiver: null },
  };
}

function aircraftFeatures(map: MapLibreMockMap) {
  const data = map.getSource(AIRCRAFT_SOURCE_ID)?.data as
    { features: { properties: AircraftFeatureProperties }[] } | undefined;
  return data?.features ?? [];
}

describe("LiveMapPage", () => {
  it("renders a heading and a full-viewport map container", () => {
    render(<LiveMapPage />);
    expect(
      screen.getByRole("heading", { level: 1, name: "Live Map" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("maplibre-container")).toBeInTheDocument();
  });

  it("initializes MapLibre with the default dark-aviation basemap", () => {
    render(<LiveMapPage />);
    expect(MapLibreMockMap.instances).toHaveLength(1);
    expect(getLastMockMap().options.style).toBeTruthy();
  });

  it("renders the basemap switcher control", () => {
    render(<LiveMapPage />);
    expect(
      screen.getByRole("radiogroup", { name: /basemap/i }),
    ).toBeInTheDocument();
  });

  it("opens the live socket against the documented path", () => {
    render(<LiveMapPage />);
    expect(getLastWebSocket().url).toMatch(/\/api\/v1\/ws\/live$/);
  });

  it("attaches the aircraft layers once the style has loaded", async () => {
    const map = await renderLoadedMap();
    expect(map.layers.has(AIRCRAFT_SYMBOL_LAYER_ID)).toBe(true);
    expect(map.getSource(AIRCRAFT_SOURCE_ID)).toBeDefined();
    expect(map.images.size).toBeGreaterThan(0);
  });

  it("renders aircraft from a snapshot frame", async () => {
    const map = await renderLoadedMap();
    await act(async () => {
      getLastWebSocket().emitFrame(
        snapshotFrame(1, [
          makeAircraft({ icao: "aaaaaa", position: { lat: 47, lon: -122 } }),
        ]),
      );
    });

    const features = aircraftFeatures(map);
    expect(features).toHaveLength(1);
    expect(features[0]?.properties.icao).toBe("aaaaaa");
  });

  it("reports the connection as live once the snapshot lands", async () => {
    await renderLoadedMap();
    await act(async () => {
      getLastWebSocket().emitFrame(snapshotFrame(1, []));
    });
    expect(screen.getByText("Live")).toBeInTheDocument();
  });

  it("applies a delta's removals, staleness and updates", async () => {
    const map = await renderLoadedMap();
    await act(async () => {
      getLastWebSocket().emitFrame(
        snapshotFrame(1, [
          makeAircraft({ icao: "aaaaaa" }),
          makeAircraft({ icao: "bbbbbb" }),
        ]),
      );
    });
    await act(async () => {
      getLastWebSocket().emitFrame({
        type: "delta",
        seq: 2,
        data: {
          updated: [makeAircraft({ icao: "cccccc" })],
          stale: ["bbbbbb"],
          removed: ["aaaaaa"],
        },
      });
    });

    const properties = aircraftFeatures(map).map(
      (feature) => feature.properties,
    );
    const byIcao = Object.fromEntries(
      properties.map((entry) => [entry.icao, entry]),
    );
    // `aaaaaa` is mid removal-fade rather than gone outright.
    expect(byIcao.aaaaaa?.opacity).toBeGreaterThan(0);
    expect(byIcao.bbbbbb?.stale).toBe(true);
    expect(byIcao.cccccc?.stale).toBe(false);
  });

  it("selects the aircraft under a click and draws its track", async () => {
    const map = await renderLoadedMap();
    await act(async () => {
      getLastWebSocket().emitFrame(
        snapshotFrame(1, [
          makeAircraft({ icao: "aaaaaa", position: { lat: 47, lon: -122 } }),
        ]),
      );
      getLastWebSocket().emitFrame({
        type: "delta",
        seq: 2,
        data: {
          updated: [
            makeAircraft({
              icao: "aaaaaa",
              position: { lat: 47.2, lon: -122 },
            }),
          ],
          stale: [],
          removed: [],
        },
      });
    });

    map.renderedFeatures = [{ properties: { icao: "aaaaaa" } }];
    await act(async () => {
      map.emit("click", { point: { x: 10, y: 10 } });
    });

    expect(useLiveAircraftStore.getState().selectedIcao).toBe("aaaaaa");
    expect(aircraftFeatures(map)[0]?.properties.selected).toBe(true);

    await act(async () => {
      getLastWebSocket().emitFrame({
        type: "delta",
        seq: 3,
        data: {
          updated: [
            makeAircraft({
              icao: "aaaaaa",
              position: { lat: 47.4, lon: -122 },
            }),
          ],
          stale: [],
          removed: [],
        },
      });
    });

    const track = map.getSource(AIRCRAFT_TRACK_SOURCE_ID)?.data as {
      features: { geometry: { coordinates: number[][] } }[];
    };
    expect(track.features[0]?.geometry.coordinates).toHaveLength(2);
  });

  it("clears the selection when the click lands on empty map", async () => {
    const map = await renderLoadedMap();
    await act(async () => {
      getLastWebSocket().emitFrame(
        snapshotFrame(1, [makeAircraft({ icao: "aaaaaa" })]),
      );
    });
    map.renderedFeatures = [{ properties: { icao: "aaaaaa" } }];
    await act(async () => {
      map.emit("click", { point: { x: 1, y: 1 } });
    });
    expect(useLiveAircraftStore.getState().selectedIcao).toBe("aaaaaa");

    map.renderedFeatures = [];
    await act(async () => {
      map.emit("click", { point: { x: 500, y: 500 } });
    });
    expect(useLiveAircraftStore.getState().selectedIcao).toBeNull();
    expect(useLiveAircraftStore.getState().track).toBeNull();
  });

  it("answers the server's keepalive so the connection survives", async () => {
    await renderLoadedMap();
    const socket = getLastWebSocket();
    await act(async () => {
      socket.emitFrame(snapshotFrame(1, []));
      socket.emitFrame({ type: "ping", seq: 2 });
    });
    expect(socket.sent).toEqual([JSON.stringify({ type: "pong" })]);
  });

  it("re-attaches the aircraft layers after a basemap switch", async () => {
    // setStyle discards custom sources, layers and registered images.
    const map = await renderLoadedMap();
    await act(async () => {
      await userEvent.click(
        screen.getByRole("radio", { name: /openstreetmap/i }),
      );
    });
    map.layers.clear();
    map.sources.clear();
    map.images.clear();

    await act(async () => {
      map.emit("style.load");
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(map.layers.has(AIRCRAFT_SYMBOL_LAYER_ID)).toBe(true);
    expect(map.images.size).toBeGreaterThan(0);
  });

  it("closes the socket and clears the picture on unmount", async () => {
    const { unmount } = render(<LiveMapPage />);
    const socket = getLastWebSocket();
    await act(async () => {
      socket.emitFrame(snapshotFrame(1, [makeAircraft()]));
    });
    expect(Object.keys(useLiveAircraftStore.getState().aircraft)).toHaveLength(
      1,
    );

    unmount();

    expect(socket.closed).toBe(true);
    expect(useLiveAircraftStore.getState().aircraft).toEqual({});
  });
});
