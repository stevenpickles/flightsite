import { act, renderHook } from "@testing-library/react";
import type { Map as MapLibreGlMap } from "maplibre-gl";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  VIEWPORT_DEBOUNCE_MS,
  useMapViewport,
} from "@/features/map/overlays/useMapViewport";
import { MapLibreMockMap } from "@/test/maplibreGlMock";

let mock: MapLibreMockMap;
let map: MapLibreGlMap;

beforeEach(() => {
  vi.useFakeTimers();
  mock = new MapLibreMockMap({});
  mock.bounds = { west: -123, south: 47, east: -121.9, north: 47.8 };
  mock.zoom = 8;
  map = mock as unknown as MapLibreGlMap;
});

afterEach(() => {
  vi.useRealTimers();
});

describe("useMapViewport", () => {
  it("is null before the map exists", () => {
    const { result } = renderHook(() => useMapViewport(null));
    expect(result.current).toBeNull();
  });

  it("reports the initial viewport immediately, without waiting for the debounce", () => {
    const { result } = renderHook(() => useMapViewport(map));
    expect(result.current).toEqual({ bbox: "-123,47,-121.9,47.8", zoom: 8 });
  });

  it("does not update on a move until the debounce elapses", () => {
    const { result } = renderHook(() => useMapViewport(map));
    mock.bounds = { west: -100, south: 40, east: -99, north: 41 };
    mock.emit("move");

    vi.advanceTimersByTime(VIEWPORT_DEBOUNCE_MS - 1);
    expect(result.current?.bbox).toBe("-123,47,-121.9,47.8");
  });

  it("updates once the debounce elapses after the last move", () => {
    const { result } = renderHook(() => useMapViewport(map));
    mock.bounds = { west: -100, south: 40, east: -99, north: 41 };
    mock.zoom = 9;
    mock.emit("move");

    act(() => {
      vi.advanceTimersByTime(VIEWPORT_DEBOUNCE_MS);
    });
    expect(result.current).toEqual({ bbox: "-100,40,-99,41", zoom: 9 });
  });

  it("coalesces a burst of moves into a single update", () => {
    const { result } = renderHook(() => useMapViewport(map));
    for (let i = 0; i < 5; i += 1) {
      mock.bounds = { west: -123 - i, south: 47, east: -121.9, north: 47.8 };
      mock.emit("move");
      act(() => {
        vi.advanceTimersByTime(VIEWPORT_DEBOUNCE_MS / 2);
      });
    }
    // Only the last move's debounce should ever complete during that loop
    // (each new move re-schedules), so the viewport is still the initial one.
    expect(result.current?.bbox).toBe("-123,47,-121.9,47.8");

    act(() => {
      vi.advanceTimersByTime(VIEWPORT_DEBOUNCE_MS);
    });
    expect(result.current?.bbox).toBe("-127,47,-121.9,47.8");
  });

  it("stops listening on unmount", () => {
    const { unmount } = renderHook(() => useMapViewport(map));
    unmount();
    expect(mock.handlers.get("move")?.size ?? 0).toBe(0);
  });
});

describe("dead-GL degradation", () => {
  it("reports null instead of crashing when getBounds throws", () => {
    (mock as unknown as { getBounds: () => never }).getBounds = () => {
      throw new TypeError("can't access property 0, n is undefined");
    };
    const { result } = renderHook(() => useMapViewport(map));
    expect(result.current).toBeNull();
  });
});
