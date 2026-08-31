import { afterEach, describe, expect, it } from "vitest";

import { DEFAULT_BASEMAP_ID } from "@/features/map/basemaps";
import { BASEMAP_STORAGE_KEY } from "@/features/map/basemapPersistence";
import { useBasemapStore } from "@/features/map/store/useBasemapStore";

afterEach(() => {
  window.localStorage.clear();
  useBasemapStore.setState({ basemapId: DEFAULT_BASEMAP_ID });
});

describe("useBasemapStore", () => {
  it("initializes from the persisted (or default) basemap id", () => {
    expect(useBasemapStore.getState().basemapId).toBe(DEFAULT_BASEMAP_ID);
  });

  it("setBasemapId updates state and persists the choice", () => {
    useBasemapStore.getState().setBasemapId("osm-raster");
    expect(useBasemapStore.getState().basemapId).toBe("osm-raster");
    expect(window.localStorage.getItem(BASEMAP_STORAGE_KEY)).toBe("osm-raster");
  });

  it("ignores an unknown basemap id", () => {
    useBasemapStore.getState().setBasemapId("osm-raster");
    useBasemapStore.getState().setBasemapId("not-a-real-basemap");
    expect(useBasemapStore.getState().basemapId).toBe("osm-raster");
  });
});
