import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AircraftLayer } from "@/features/map/aircraft/AircraftLayer";
import { AIRCRAFT_SOURCE_ID } from "@/features/map/aircraft/aircraftLayers";
import type { AircraftFeatureProperties } from "@/features/map/aircraft/geojson";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import { getDefaultBasemap } from "@/features/map/basemaps";
import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
import { MapLibreMap } from "@/features/map/MapLibreMap";
import {
  DENSITY_CALLSIGN_THRESHOLD,
  ZOOM_LABELS_FULL,
  ZOOM_LABELS_MIN,
} from "@/features/map/labels/priority";
import { makeAircraft } from "@/test/liveAircraftFixtures";
import {
  getLastMockMap,
  MapLibreMockMap,
  resetMapLibreMock,
} from "@/test/maplibreGlMock";
import { installOverlaysApiMock } from "@/test/overlaysApiMock";

/**
 * End-to-end through the real map wiring: `MapLibreMap` (which the mocked
 * `maplibre-gl` module from `src/test/setup.ts` stands in for) hosting the
 * real `AircraftLayer`, driven by writing straight into
 * `useLiveAircraftStore` the way the live socket would. This is the seam
 * roadmap slice 015's "component tests" / "integration with the page"
 * requirement targets, kept inside the aircraft feature directory rather
 * than `pages/LiveMapPage.test.tsx` so it does not collide with slice 016's
 * concurrent work on that page.
 */

beforeEach(() => {
  resetMapLibreMock();
  useLiveAircraftStore.getState().reset();
  // `AircraftLayer` reads the selected aircraft's open sighting to backfill
  // its track (slice 061); selecting one here must resolve against a stub
  // rather than the network. The default answer is "no open sighting", so
  // these label tests see exactly the track they build themselves.
  installOverlaysApiMock();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function renderLoadedLayer(): Promise<MapLibreMockMap> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={queryClient}>
      <MapLibreMap
        config={DEV_PLACEHOLDER_MAP_CONFIG}
        basemap={getDefaultBasemap()}
      >
        <AircraftLayer />
      </MapLibreMap>
    </QueryClientProvider>,
  );
  const map = getLastMockMap();
  await act(async () => {
    map.emit("load");
  });
  // Icons decode asynchronously; the layers attach only once every one of
  // them is registered.
  await act(async () => {
    await Promise.resolve();
  });
  return map;
}

function features(map: MapLibreMockMap) {
  const data = map.getSource(AIRCRAFT_SOURCE_ID)?.data as
    { features: { properties: AircraftFeatureProperties }[] } | undefined;
  return data?.features ?? [];
}

describe("AircraftLayer label integration", () => {
  it("keeps the selected aircraft's label visible even far below the labeling zoom", async () => {
    const map = await renderLoadedLayer();
    map.zoom = ZOOM_LABELS_MIN - 1;

    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [
          makeAircraft({
            icao: "aaaaaa",
            callsign: "BAW123",
            altitude_ft: 35000,
            position: { lat: 47, lon: -122 },
          }),
        ],
        receiver: null,
      });
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const selected = features(map).find(
      (entry) => entry.properties.icao === "aaaaaa",
    );
    expect(selected?.properties.selected).toBe(true);
    expect(selected?.properties.label).toBe("BAW123\nFL350");
  });

  it("hides the label for a non-priority aircraft below the labeling zoom", async () => {
    const map = await renderLoadedLayer();
    map.zoom = ZOOM_LABELS_MIN - 1;

    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [
          makeAircraft({
            icao: "bbbbbb",
            callsign: "UAL45",
            position: { lat: 47, lon: -122 },
          }),
        ],
        receiver: null,
      });
    });

    const other = features(map).find(
      (entry) => entry.properties.icao === "bbbbbb",
    );
    expect(other?.properties.label).toBe("");
  });

  it("still shows the selected aircraft's full label when the picture is dense", async () => {
    const map = await renderLoadedLayer();
    map.zoom = ZOOM_LABELS_FULL;

    const crowd = Array.from(
      { length: DENSITY_CALLSIGN_THRESHOLD + 5 },
      (_, index) =>
        makeAircraft({
          icao: (index + 1).toString(16).padStart(6, "0"),
          callsign: `AA${index}`,
          position: { lat: 47 + index / 1000, lon: -122 },
        }),
    );
    const selectedAircraft = makeAircraft({
      icao: "aaaaaa",
      callsign: "BAW123",
      altitude_ft: 35000,
      position: { lat: 47, lon: -122 },
    });

    act(() => {
      useLiveAircraftStore.getState().applySnapshot({
        aircraft: [...crowd, selectedAircraft],
        receiver: null,
      });
      useLiveAircraftStore.getState().selectAircraft("aaaaaa");
    });

    const all = features(map);
    const selected = all.find((entry) => entry.properties.icao === "aaaaaa");
    const other = all.find((entry) => entry.properties.icao === "000001");

    expect(selected?.properties.label).toBe("BAW123\nFL350");
    // A non-priority neighbour drops to callsign-only under the same
    // density that the selected aircraft is exempt from.
    expect(other?.properties.label).toBe(other?.properties.callsign);
  });
});
