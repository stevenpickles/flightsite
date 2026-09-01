import { beforeEach, describe, expect, it } from "vitest";

import {
  DEFAULT_RING_RADII_NM,
  DEV_PLACEHOLDER_MAP_CONFIG,
} from "@/features/map/mapConfig";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import {
  applyServerConfigToMapStore,
  deriveMapConfig,
} from "@/features/setup/lib/mapConfigSync";
import { defaultFlightSiteConfig } from "@/test/configApiMock";

beforeEach(() => {
  useMapConfigStore.setState({ config: DEV_PLACEHOLDER_MAP_CONFIG });
});

describe("deriveMapConfig", () => {
  it("returns null when no receiver location is configured", () => {
    expect(deriveMapConfig(defaultFlightSiteConfig())).toBeNull();
  });

  it("derives a MapConfig from a configured location", () => {
    const derived = deriveMapConfig(
      defaultFlightSiteConfig({
        location: {
          latitude: 51.5,
          longitude: -0.12,
          site_name: "Home Roof",
          antenna_height_ft: null,
        },
      }),
    );
    expect(derived).toEqual({
      receiver: { lat: 51.5, lon: -0.12, label: "Home Roof" },
      ringRadiiNm: [50, 100, 150, 200],
      unit: "nm",
      displayRadiusNm: 250,
    });
  });

  it("falls back to a generic label when site_name is blank", () => {
    const derived = deriveMapConfig(
      defaultFlightSiteConfig({
        location: {
          latitude: 1,
          longitude: 2,
          site_name: "  ",
          antenna_height_ft: null,
        },
      }),
    );
    expect(derived?.receiver.label).toBe("Receiver");
  });

  it("falls back to the default ring radii when the server list is empty", () => {
    const derived = deriveMapConfig(
      defaultFlightSiteConfig({
        location: {
          latitude: 1,
          longitude: 2,
          site_name: "Home",
          antenna_height_ft: null,
        },
        map: {
          basemap: "dark-aviation",
          range_rings_enabled: true,
          range_ring_radii_nm: [],
        },
      }),
    );
    expect(derived?.ringRadiiNm).toEqual(DEFAULT_RING_RADII_NM);
  });

  it("maps metric units to the km display unit", () => {
    const derived = deriveMapConfig(
      defaultFlightSiteConfig({
        units: "metric",
        location: {
          latitude: 1,
          longitude: 2,
          site_name: "Home",
          antenna_height_ft: null,
        },
      }),
    );
    expect(derived?.unit).toBe("km");
  });

  it("carries the server's display radius through as displayRadiusNm", () => {
    const derived = deriveMapConfig(
      defaultFlightSiteConfig({
        display_radius_nm: 100,
        location: {
          latitude: 1,
          longitude: 2,
          site_name: "Home",
          antenna_height_ft: null,
        },
      }),
    );
    expect(derived?.displayRadiusNm).toBe(100);
  });
});

describe("applyServerConfigToMapStore", () => {
  it("updates the map store when a location is configured", () => {
    applyServerConfigToMapStore(
      defaultFlightSiteConfig({
        location: {
          latitude: 51.5,
          longitude: -0.12,
          site_name: "Home Roof",
          antenna_height_ft: null,
        },
      }),
    );
    expect(useMapConfigStore.getState().config.receiver).toEqual({
      lat: 51.5,
      lon: -0.12,
      label: "Home Roof",
    });
  });

  it("leaves the store untouched when no location is configured", () => {
    applyServerConfigToMapStore(defaultFlightSiteConfig());
    expect(useMapConfigStore.getState().config).toBe(
      DEV_PLACEHOLDER_MAP_CONFIG,
    );
  });
});
