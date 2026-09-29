import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AircraftLayer } from "@/features/map/aircraft/AircraftLayer";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { getBasemapById, getDefaultBasemap } from "@/features/map/basemaps";
import { destinationPoint } from "@/features/map/geo/rings";
import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
import { MapLibreMap } from "@/features/map/MapLibreMap";
import { MeasureControl } from "@/features/map/measure/MeasureControl";
import {
  MEASURE_LINE_LAYER_ID,
  MEASURE_SOURCE_ID,
} from "@/features/map/measure/measureLayers";
import { useMeasureStore } from "@/features/map/measure/useMeasureStore";
import type { ReceiverPosition } from "@/features/map/types";
import type { ReceiverInfo } from "@/lib/api/live";
import { makeAircraft } from "@/test/liveAircraftFixtures";
import {
  getLastMockMap,
  resetMapLibreMock,
  type MapLibreMockMap,
} from "@/test/maplibreGlMock";
import { installOverlaysApiMock } from "@/test/overlaysApiMock";

const RECEIVER: ReceiverPosition = { lat: 47.6, lon: -122.3, label: "Home" };

beforeEach(() => {
  resetMapLibreMock();
  useLiveAircraftStore.getState().reset();
  installOverlaysApiMock();
});

afterEach(() => {
  useMeasureStore.getState().exit();
  vi.unstubAllGlobals();
});

function tree(
  receiver: ReceiverPosition | null,
  basemapId = getDefaultBasemap().id,
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      <MapLibreMap
        config={DEV_PLACEHOLDER_MAP_CONFIG}
        basemap={getBasemapById(basemapId) ?? getDefaultBasemap()}
      >
        <AircraftLayer />
        <MeasureControl receiver={receiver} />
      </MapLibreMap>
    </QueryClientProvider>
  );
}

async function renderLoaded(
  receiver: ReceiverPosition | null = RECEIVER,
): Promise<{
  map: MapLibreMockMap;
  rerender: ReturnType<typeof render>["rerender"];
  unmount: () => void;
}> {
  const { rerender, unmount } = render(tree(receiver));
  const map = getLastMockMap();
  await act(async () => {
    map.emit("load");
  });
  await act(async () => {
    await Promise.resolve();
  });
  return { map, rerender, unmount };
}

function clickMap(
  map: MapLibreMockMap,
  point: { lat: number; lon: number },
): void {
  act(() => {
    map.emit("click", {
      lngLat: { lat: point.lat, lng: point.lon },
      point: { x: 10, y: 10 },
    });
  });
}

function measureFeatureKinds(map: MapLibreMockMap): string[] {
  const data = map.getSource(MEASURE_SOURCE_ID)?.data as
    { features: { properties: { kind: string } }[] } | undefined;
  return data?.features.map((feature) => feature.properties.kind) ?? [];
}

function toggleButton(): HTMLElement {
  return screen.getByRole("button", { name: "Measure distance and bearing" });
}

describe("MeasureControl", () => {
  it("is a pressed/unpressed toggle, off by default", async () => {
    const user = userEvent.setup();
    await renderLoaded();
    expect(toggleButton()).toHaveAttribute("aria-pressed", "false");

    await user.click(toggleButton());
    expect(toggleButton()).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("measure-readout")).toHaveTextContent(
      "Click the map to set point A",
    );

    await user.click(toggleButton());
    expect(toggleButton()).toHaveAttribute("aria-pressed", "false");
  });

  it("is keyboard operable", async () => {
    const user = userEvent.setup();
    await renderLoaded();
    toggleButton().focus();
    await user.keyboard("{Enter}");
    expect(useMeasureStore.getState().active).toBe(true);
    await user.keyboard(" ");
    expect(useMeasureStore.getState().active).toBe(false);
  });

  it("places A, then B with distance and bearing, then starts over", async () => {
    const user = userEvent.setup();
    const { map } = await renderLoaded();
    await user.click(toggleButton());

    const a = { lat: 47.6, lon: -122.3 };
    const b = destinationPoint(a, 45, 42.7);
    clickMap(map, a);
    expect(screen.getByTestId("measure-readout")).toHaveTextContent(
      "Click the map to set point B",
    );
    expect(measureFeatureKinds(map)).toEqual(["point"]);

    clickMap(map, b);
    expect(screen.getByTestId("measure-readout")).toHaveTextContent(
      "42.7 nm · 045° NE",
    );
    expect(measureFeatureKinds(map)).toEqual([
      "line",
      "point",
      "point",
      "label",
    ]);

    clickMap(map, b);
    expect(measureFeatureKinds(map)).toEqual(["point"]);
    expect(screen.getByTestId("measure-readout")).toHaveTextContent(
      "Click the map to set point B",
    );
  });

  it("reads the distance in the receiver's metric units", async () => {
    const user = userEvent.setup();
    const { map } = await renderLoaded();
    act(() => {
      useLiveAircraftStore.setState({
        receiver: { units: "metric" } as ReceiverInfo,
      });
    });
    await user.click(toggleButton());
    const a = { lat: 47.6, lon: -122.3 };
    clickMap(map, a);
    clickMap(map, destinationPoint(a, 45, 42.7));
    expect(screen.getByTestId("measure-readout")).toHaveTextContent(
      "79.1 km · 045° NE",
    );
  });

  it("measures from the receiver with one click", async () => {
    const user = userEvent.setup();
    const { map } = await renderLoaded();
    await user.click(toggleButton());
    await user.click(screen.getByRole("button", { name: "From receiver" }));
    expect(useMeasureStore.getState().points).toEqual([
      { lat: RECEIVER.lat, lon: RECEIVER.lon },
    ]);

    clickMap(map, destinationPoint(RECEIVER, 270, 12));
    expect(screen.getByTestId("measure-readout")).toHaveTextContent(
      "12.0 nm · 270° W",
    );
  });

  it("offers no 'From receiver' when no real receiver location is configured", async () => {
    const user = userEvent.setup();
    await renderLoaded(null);
    await user.click(toggleButton());
    expect(
      screen.queryByRole("button", { name: "From receiver" }),
    ).not.toBeInTheDocument();
  });

  it("ignores map clicks while off", async () => {
    const { map } = await renderLoaded();
    clickMap(map, RECEIVER);
    expect(useMeasureStore.getState().points).toEqual([]);
    expect(measureFeatureKinds(map)).toEqual([]);
  });

  it("does not select an aircraft clicked while measuring", async () => {
    const user = userEvent.setup();
    const { map } = await renderLoaded();
    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [makeAircraft({ icao: "aaaaaa" })],
        receiver: null,
      });
    });
    map.renderedFeatures = [{ properties: { icao: "aaaaaa" } }];

    await user.click(toggleButton());
    clickMap(map, RECEIVER);
    expect(useLiveAircraftStore.getState().selectedIcao).toBeNull();
    expect(useMeasureStore.getState().points).toHaveLength(1);

    // …and selection works again the moment measuring stops.
    await user.click(toggleButton());
    clickMap(map, RECEIVER);
    expect(useLiveAircraftStore.getState().selectedIcao).toBe("aaaaaa");
  });

  it("does not clear an existing selection with a measuring click on empty map", async () => {
    const user = userEvent.setup();
    const { map } = await renderLoaded();
    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [makeAircraft({ icao: "aaaaaa" })],
        receiver: null,
      });
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });
    map.renderedFeatures = [];

    await user.click(toggleButton());
    clickMap(map, RECEIVER);
    expect(useLiveAircraftStore.getState().selectedIcao).toBe("aaaaaa");
  });

  it("exits on Escape, clearing the line, without the key reaching other handlers", async () => {
    const user = userEvent.setup();
    const { map } = await renderLoaded();
    await user.click(toggleButton());
    clickMap(map, RECEIVER);

    // Stands in for AircraftDetailPanel's and FilterDrawer's own window
    // listeners, which must not also act on this Escape.
    const other = vi.fn();
    window.addEventListener("keydown", other);
    fireEvent.keyDown(document.body, { key: "Escape" });
    window.removeEventListener("keydown", other);

    expect(useMeasureStore.getState().active).toBe(false);
    expect(other).not.toHaveBeenCalled();
    expect(measureFeatureKinds(map)).toEqual([]);
    expect(toggleButton()).toHaveAttribute("aria-pressed", "false");
  });

  it("leaves Escape alone while not measuring", async () => {
    await renderLoaded();
    const other = vi.fn();
    window.addEventListener("keydown", other);
    fireEvent.keyDown(document.body, { key: "Escape" });
    window.removeEventListener("keydown", other);
    expect(other).toHaveBeenCalledTimes(1);
  });

  it("shows a crosshair cursor while measuring, and restores it after", async () => {
    const user = userEvent.setup();
    const { map } = await renderLoaded();
    await user.click(toggleButton());
    expect(map.getCanvas().style.cursor).toBe("crosshair");
    await user.click(toggleButton());
    expect(map.getCanvas().style.cursor).toBe("");
  });

  it("re-draws a measurement after a basemap switch", async () => {
    const user = userEvent.setup();
    const { map, rerender } = await renderLoaded();
    await user.click(toggleButton());
    clickMap(map, RECEIVER);
    clickMap(map, destinationPoint(RECEIVER, 90, 10));

    await act(async () => {
      rerender(tree(RECEIVER, "osm-raster"));
    });
    expect(map.layers.has(MEASURE_LINE_LAYER_ID)).toBe(true);
    expect(measureFeatureKinds(map)).toContain("line");
  });

  it("leaves measure mode when the map unmounts", async () => {
    const user = userEvent.setup();
    const { unmount } = await renderLoaded();
    await user.click(toggleButton());
    unmount();
    expect(useMeasureStore.getState().active).toBe(false);
  });
});
