import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetFilteredLiveAircraftCache } from "@/features/filters/lib/filteredLiveAircraftCache";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { DEFAULT_FILTERS } from "@/features/filters/types";
import {
  AIRCRAFT_SOURCE_ID,
  AIRCRAFT_SYMBOL_LAYER_ID,
  AIRCRAFT_TRACK_SOURCE_ID,
} from "@/features/map/aircraft/aircraftLayers";
import type { AircraftFeatureProperties } from "@/features/map/aircraft/geojson";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { DEFAULT_BASEMAP_ID } from "@/features/map/basemaps";
import {
  AIRPORT_LAYER_IDS,
  AIRPORTS_SOURCE_ID,
} from "@/features/map/overlays/airportLayers";
import {
  AIRSPACE_FILL_LAYER_ID,
  AIRSPACE_LINE_LAYER_ID,
  AIRSPACE_SOURCE_ID,
} from "@/features/map/overlays/airspaceLayers";
import {
  DEFAULT_OVERLAY_VISIBILITY,
  OVERLAY_VISIBILITY_STORAGE_KEY,
} from "@/features/map/overlayVisibilityPersistence";
import { useBasemapStore } from "@/features/map/store/useBasemapStore";
import { useOverlayVisibilityStore } from "@/features/map/store/useOverlayVisibilityStore";
import { LiveMapPage } from "@/pages/LiveMapPage";
import { makeAircraft } from "@/test/liveAircraftFixtures";
import {
  getLastMockMap,
  MapLibreMockMap,
  resetMapLibreMock,
} from "@/test/maplibreGlMock";
import {
  EMPTY_FEATURE_COLLECTION,
  installOverlaysApiMock,
} from "@/test/overlaysApiMock";
import { sightingDetail, sightingRow } from "@/test/sightingsApiMock";
import { getLastWebSocket, resetWebSocketMock } from "@/test/webSocketMock";

// The `maplibre-gl` and `WebSocket` mocks are registered globally in
// src/test/setup.ts (jsdom has neither a WebGL context nor a socket server).

/** `LiveMapPage` uses `react-router`'s `useSearchParams` for filter URL sync
 * (`features/filters/hooks/useFilterUrlSync`), so every render needs a
 * router in the tree — a plain `MemoryRouter` here, distinct from
 * `test/test-utils.tsx`'s full route tree, since this file exercises the
 * page in isolation. A `QueryClientProvider` is needed too, as of roadmap
 * slice 028: the aviation overlays (`features/map/overlays/`) fetch through
 * TanStack Query, which every other child of this page still avoids (the
 * live picture is websocket/zustand-driven, not queried). */
function renderPage(initialPath = "/") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialPath]}>
        <LiveMapPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  resetMapLibreMock();
  resetWebSocketMock();
  resetFilteredLiveAircraftCache();
  useLiveAircraftStore.getState().reset();
  useFilterStore.setState({ filters: DEFAULT_FILTERS });
  useOverlayVisibilityStore.setState({ ...DEFAULT_OVERLAY_VISIBILITY });
  installOverlaysApiMock();
});

afterEach(() => {
  window.localStorage.clear();
  useBasemapStore.setState({ basemapId: DEFAULT_BASEMAP_ID });
  vi.restoreAllMocks();
});

/** Renders the page and drives the map through its first style load, which is
 * what registers the icons and attaches the aircraft layers. */
async function renderLoadedMap() {
  renderPage();
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
    renderPage();
    expect(
      screen.getByRole("heading", { level: 1, name: "Live Map" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("maplibre-container")).toBeInTheDocument();
  });

  it("initializes MapLibre with the default dark-aviation basemap", () => {
    renderPage();
    expect(MapLibreMockMap.instances).toHaveLength(1);
    expect(getLastMockMap().options.style).toBeTruthy();
  });

  it("renders the basemap switcher control", () => {
    renderPage();
    expect(
      screen.getByRole("radiogroup", { name: /basemap/i }),
    ).toBeInTheDocument();
  });

  it("opens the live socket against the documented path", () => {
    renderPage();
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

  /** Serves `aaaaaa` an open sighting whose checkpointed path runs from 46.5 to
   * 46.8 — well before any live position this file feeds in. */
  function installOpenSightingMock() {
    installOverlaysApiMock({
      sightings: {
        items: [
          sightingRow({
            id: 91_001,
            icao: "aaaaaa",
            ended_at: null,
            duration_s: null,
            closure_reason: null,
          }),
        ],
        total: null,
        limit: 1,
        offset: 0,
      },
      sightingDetail: {
        91_001: sightingDetail({
          id: 91_001,
          icao: "aaaaaa",
          ended_at: null,
          duration_s: null,
          closure_reason: null,
          path: [
            {
              t: "2020-01-01T00:00:00.000Z",
              lat: 46.5,
              lon: -122,
              altitude_ft: 20000,
              source: "adsb",
            },
            {
              t: "2020-01-01T00:05:00.000Z",
              lat: 46.8,
              lon: -122,
              altitude_ft: 21000,
              source: "adsb",
            },
          ],
        }),
      },
    });
  }

  it("backfills the clicked aircraft's track from its open sighting", async () => {
    // Issue #133: before slice 061 the trail started at the click, so an
    // aircraft that had been airborne for an hour drew a single point.
    installOpenSightingMock();

    const map = await renderLoadedMap();
    await act(async () => {
      getLastWebSocket().emitFrame(
        snapshotFrame(1, [
          makeAircraft({ icao: "aaaaaa", position: { lat: 47, lon: -122 } }),
        ]),
      );
    });

    map.renderedFeatures = [{ properties: { icao: "aaaaaa" } }];
    await act(async () => {
      map.emit("click", { point: { x: 10, y: 10 } });
    });

    await waitFor(() => {
      expect(useLiveAircraftStore.getState().track?.points).toHaveLength(3);
    });

    const track = map.getSource(AIRCRAFT_TRACK_SOURCE_ID)?.data as {
      features: { geometry: { coordinates: number[][] } }[];
    };
    // Oldest first, ending at the position the click selected.
    expect(track.features[0]?.geometry.coordinates).toEqual([
      [-122, 46.5],
      [-122, 46.8],
      [-122, 47],
    ]);
  });

  it("keeps the backfilled trail when the same aircraft is clicked again", async () => {
    // A second click (or the second half of a double-click) used to restart
    // accumulation while leaving the backfill's inputs unchanged, so nothing
    // re-fetched and the trail collapsed to a dot for the rest of the
    // selection.
    installOpenSightingMock();

    const map = await renderLoadedMap();
    await act(async () => {
      getLastWebSocket().emitFrame(
        snapshotFrame(1, [
          makeAircraft({ icao: "aaaaaa", position: { lat: 47, lon: -122 } }),
        ]),
      );
    });

    map.renderedFeatures = [{ properties: { icao: "aaaaaa" } }];
    await act(async () => {
      map.emit("click", { point: { x: 10, y: 10 } });
    });
    await waitFor(() => {
      expect(useLiveAircraftStore.getState().track?.points).toHaveLength(3);
    });

    await act(async () => {
      map.emit("click", { point: { x: 11, y: 11 } });
    });
    await act(async () => {
      map.emit("click", { point: { x: 12, y: 12 } });
    });

    expect(useLiveAircraftStore.getState().selectedIcao).toBe("aaaaaa");
    const track = map.getSource(AIRCRAFT_TRACK_SOURCE_ID)?.data as {
      features: { geometry: { coordinates: number[][] } }[];
    };
    expect(track.features[0]?.geometry.coordinates).toEqual([
      [-122, 46.5],
      [-122, 46.8],
      [-122, 47],
    ]);
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
    const { unmount } = renderPage();
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

describe("aviation overlays (roadmap slice 028)", () => {
  it("attaches the airport and airspace overlays once the style has loaded", async () => {
    const map = await renderLoadedMap();

    expect([...AIRPORT_LAYER_IDS].every((id) => map.layers.has(id))).toBe(true);
    expect(map.layers.has(AIRSPACE_FILL_LAYER_ID)).toBe(true);
    expect(map.layers.has(AIRSPACE_LINE_LAYER_ID)).toBe(true);
    expect(map.getSource(AIRPORTS_SOURCE_ID)).toBeDefined();
    expect(map.getSource(AIRSPACE_SOURCE_ID)).toBeDefined();
  });

  it("re-attaches both overlays after a basemap switch", async () => {
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

    expect([...AIRPORT_LAYER_IDS].every((id) => map.layers.has(id))).toBe(true);
    expect(map.layers.has(AIRSPACE_FILL_LAYER_ID)).toBe(true);
    expect(map.layers.has(AIRSPACE_LINE_LAYER_ID)).toBe(true);
  });

  it("renders gracefully with no airspace data supplied — an empty source, no error", async () => {
    // installOverlaysApiMock() with no options answers an empty
    // FeatureCollection for GET /api/v1/airspace, the same shape a stock
    // install with no airspace.geojson gets (ADR-0012).
    const consoleError = vi
      .spyOn(console, "error")
      .mockImplementation(() => {});
    const map = await renderLoadedMap();

    expect(map.getSource(AIRSPACE_SOURCE_ID)?.data).toEqual(
      EMPTY_FEATURE_COLLECTION,
    );
    expect(consoleError).not.toHaveBeenCalled();
  });

  it("fetches airports scoped to the current viewport and zoom-appropriate min_size", async () => {
    const { fetchMock } = installOverlaysApiMock();
    renderPage();
    const map = getLastMockMap();
    fetchMock.mockClear();
    // The viewport hook only re-reads on a "move" event (debounced) — the
    // initial read already happened at mount with the mock's defaults, so
    // changing zoom/bounds needs a move to pick them up, same as a real pan.
    map.bounds = { west: -123, south: 47, east: -121.9, north: 47.8 };
    map.zoom = 7; // Inside the "large only" band (AIRPORT_MIN_ZOOM.large=6, .medium=8).
    await act(async () => {
      map.emit("move");
    });

    const airportsCall = await vi.waitUntil(() =>
      fetchMock.mock.calls.find(([input]) =>
        String(input).startsWith("/api/v1/airports"),
      ),
    );
    const url = new URL(String(airportsCall?.[0]), "http://localhost");
    expect(url.searchParams.get("bbox")).toBe("-123,47,-121.9,47.8");
    expect(url.searchParams.get("min_size")).toBe("large");
  });

  it("shows the layers control with both toggles on by default", async () => {
    renderPage();
    const group = screen.getByRole("group", { name: /map layers/i });
    expect(within(group).getByLabelText(/airports/i)).toBeChecked();
    expect(within(group).getByLabelText(/airspace/i)).toBeChecked();
  });

  it("toggles airport layer visibility and persists the choice", async () => {
    const map = await renderLoadedMap();
    const checkbox = screen.getByLabelText(/airports/i);

    await act(async () => {
      await userEvent.click(checkbox);
    });

    for (const layerId of AIRPORT_LAYER_IDS) {
      expect(
        (map.getLayer(layerId)?.layout as Record<string, unknown>)[
          "visibility"
        ],
      ).toBe("none");
    }
    expect(useOverlayVisibilityStore.getState().airports).toBe(false);
    expect(
      JSON.parse(
        window.localStorage.getItem(OVERLAY_VISIBILITY_STORAGE_KEY) ?? "{}",
      ),
    ).toMatchObject({ airports: false });
  });

  it("toggles airspace layer visibility and persists the choice", async () => {
    const map = await renderLoadedMap();
    const checkbox = screen.getByLabelText(/airspace/i);

    await act(async () => {
      await userEvent.click(checkbox);
    });

    expect(
      (map.getLayer(AIRSPACE_FILL_LAYER_ID)?.layout as Record<string, unknown>)[
        "visibility"
      ],
    ).toBe("none");
    expect(
      (map.getLayer(AIRSPACE_LINE_LAYER_ID)?.layout as Record<string, unknown>)[
        "visibility"
      ],
    ).toBe("none");
    expect(useOverlayVisibilityStore.getState().airspace).toBe(false);
    expect(
      JSON.parse(
        window.localStorage.getItem(OVERLAY_VISIBILITY_STORAGE_KEY) ?? "{}",
      ),
    ).toMatchObject({ airspace: false });
  });

  it("marks the Airspace toggle '(no data)' when the file is absent/empty", async () => {
    renderPage();
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText(/no data/i)).toBeInTheDocument();
  });

  it("drops the '(no data)' hint once the airspace endpoint returns features", async () => {
    installOverlaysApiMock({
      airspace: {
        type: "FeatureCollection",
        features: [
          {
            type: "Feature",
            properties: { class: "B" },
            geometry: { type: "Point", coordinates: [-122.3, 47.5] },
          },
        ],
      },
    });
    renderPage();

    await waitFor(() => {
      expect(screen.queryByText(/no data/i)).not.toBeInTheDocument();
    });
  });
});
