import { afterEach, describe, expect, it } from "vitest";

import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import type { MapConfig } from "@/features/map/types";

afterEach(() => {
  useMapConfigStore.setState({ config: DEV_PLACEHOLDER_MAP_CONFIG });
});

describe("useMapConfigStore", () => {
  it("initializes with the development placeholder config", () => {
    expect(useMapConfigStore.getState().config).toBe(
      DEV_PLACEHOLDER_MAP_CONFIG,
    );
  });

  it("setConfig replaces the active config — the seam future slices (004/010) call into", () => {
    const realConfig: MapConfig = {
      receiver: { lat: 51.5, lon: -0.1, label: "A real receiver" },
      ringRadiiNm: [25, 75],
      unit: "km",
      displayRadiusNm: 150,
    };

    useMapConfigStore.getState().setConfig(realConfig);

    expect(useMapConfigStore.getState().config).toEqual(realConfig);
  });
});
