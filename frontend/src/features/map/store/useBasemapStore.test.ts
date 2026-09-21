import { afterEach, describe, expect, it } from "vitest";

import { BASEMAP_STORAGE_KEY } from "@/features/map/basemapPersistence";
import { useBasemapStore } from "@/features/map/store/useBasemapStore";

afterEach(() => {
  window.localStorage.clear();
  useBasemapStore.setState({ explicitBasemapId: null });
});

describe("useBasemapStore", () => {
  it("starts with no explicit choice when nothing is persisted", () => {
    // `null`, not the registry default: "picked dark aviation" and "picked
    // nothing" have to stay distinguishable or the theme can never decide
    // (issue R1-14).
    expect(useBasemapStore.getState().explicitBasemapId).toBeNull();
  });

  it("setBasemapId updates state and persists the choice", () => {
    useBasemapStore.getState().setBasemapId("osm-raster");
    expect(useBasemapStore.getState().explicitBasemapId).toBe("osm-raster");
    expect(window.localStorage.getItem(BASEMAP_STORAGE_KEY)).toBe("osm-raster");
  });

  it("ignores an unknown basemap id", () => {
    useBasemapStore.getState().setBasemapId("osm-raster");
    useBasemapStore.getState().setBasemapId("not-a-real-basemap");
    expect(useBasemapStore.getState().explicitBasemapId).toBe("osm-raster");
  });
});
