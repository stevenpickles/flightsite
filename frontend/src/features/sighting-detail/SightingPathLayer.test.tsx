import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { getDefaultBasemap } from "@/features/map/basemaps";
import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
import { MapLibreMap } from "@/features/map/MapLibreMap";
import {
  PATH_ENDPOINTS_SOURCE_ID,
  PATH_LINE_LAYER_ID,
  PATH_LINE_SOURCE_ID,
  SightingPathLayer,
} from "@/features/sighting-detail/SightingPathLayer";
import type { SightingPathPoint } from "@/lib/api/sightings";
import { getLastMockMap, resetMapLibreMock } from "@/test/maplibreGlMock";

beforeEach(() => {
  resetMapLibreMock();
});

const PATH: SightingPathPoint[] = [
  {
    t: "2026-08-30T22:02:10.000Z",
    lat: 47.11,
    lon: -121.8,
    altitude_ft: 21000,
    source: "adsb",
  },
  {
    t: "2026-08-30T22:03:42.000Z",
    lat: 47.19,
    lon: -121.88,
    altitude_ft: 21850,
    source: "adsb",
  },
];

function renderLoaded(path: SightingPathPoint[]) {
  const view = render(
    <MapLibreMap
      config={DEV_PLACEHOLDER_MAP_CONFIG}
      basemap={getDefaultBasemap()}
    >
      <SightingPathLayer path={path} />
    </MapLibreMap>,
  );
  const map = getLastMockMap();
  act(() => {
    map.emit("load");
  });
  return { map, ...view };
}

describe("SightingPathLayer", () => {
  it("adds the path line and endpoints sources once the map has loaded", () => {
    const { map } = renderLoaded(PATH);

    expect(map.getSource(PATH_LINE_SOURCE_ID)).toBeDefined();
    expect(map.getSource(PATH_ENDPOINTS_SOURCE_ID)).toBeDefined();
    expect(map.getLayer(PATH_LINE_LAYER_ID)).toBeDefined();
  });

  it("fits the camera to the path's bounds", () => {
    const { map } = renderLoaded(PATH);

    expect(map.fitBounds).toHaveBeenCalledTimes(1);
    expect(map.fitBounds).toHaveBeenCalledWith(
      [
        [-121.88, 47.11],
        [-121.8, 47.19],
      ],
      expect.objectContaining({ maxZoom: expect.any(Number) as number }),
    );
  });

  it("colors the line by altitude when the path carries altitude data", () => {
    const { map } = renderLoaded(PATH);

    const layer = map.getLayer(PATH_LINE_LAYER_ID) as {
      paint: { "line-color": unknown };
    };
    expect(Array.isArray(layer.paint["line-color"])).toBe(true);
  });

  it("falls back to a plain accent color when no point carries an altitude", () => {
    const noAltitude = PATH.map((point) => ({ ...point, altitude_ft: null }));

    const { map } = renderLoaded(noAltitude);

    const layer = map.getLayer(PATH_LINE_LAYER_ID) as {
      paint: { "line-color": unknown };
    };
    expect(layer.paint["line-color"]).toBe("#4dd8cf");
  });

  it("does not fit bounds a second time for the same path on a re-render", () => {
    const { map, rerender } = renderLoaded(PATH);
    expect(map.fitBounds).toHaveBeenCalledTimes(1);

    rerender(
      <MapLibreMap
        config={DEV_PLACEHOLDER_MAP_CONFIG}
        basemap={getDefaultBasemap()}
      >
        <SightingPathLayer path={PATH} />
      </MapLibreMap>,
    );

    expect(map.fitBounds).toHaveBeenCalledTimes(1);
  });

  it("re-fits when navigating to a sighting with a different path", () => {
    const { map, rerender } = renderLoaded(PATH);
    expect(map.fitBounds).toHaveBeenCalledTimes(1);

    const otherPath: SightingPathPoint[] = [
      {
        t: "2026-08-31T10:00:00.000Z",
        lat: 40.0,
        lon: -100.0,
        altitude_ft: 30000,
        source: "adsb",
      },
      {
        t: "2026-08-31T10:05:00.000Z",
        lat: 40.5,
        lon: -100.5,
        altitude_ft: 31000,
        source: "adsb",
      },
    ];
    rerender(
      <MapLibreMap
        config={DEV_PLACEHOLDER_MAP_CONFIG}
        basemap={getDefaultBasemap()}
      >
        <SightingPathLayer path={otherPath} />
      </MapLibreMap>,
    );

    expect(map.fitBounds).toHaveBeenCalledTimes(2);
  });

  it("does nothing before the map has loaded", () => {
    render(
      <MapLibreMap
        config={DEV_PLACEHOLDER_MAP_CONFIG}
        basemap={getDefaultBasemap()}
      >
        <SightingPathLayer path={PATH} />
      </MapLibreMap>,
    );
    const map = getLastMockMap();

    expect(map.getSource(PATH_LINE_SOURCE_ID)).toBeUndefined();
  });

  it("renders no path visuals for an empty path, without error", () => {
    const { map } = renderLoaded([]);

    const source = map.getSource(PATH_LINE_SOURCE_ID);
    expect(source?.data).toMatchObject({ features: [] });
    expect(map.fitBounds).not.toHaveBeenCalled();
  });
});
