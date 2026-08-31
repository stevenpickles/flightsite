import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_BASEMAP_ID } from "@/features/map/basemaps";
import { useBasemapStore } from "@/features/map/store/useBasemapStore";
import { LiveMapPage } from "@/pages/LiveMapPage";
import {
  getLastMockMap,
  MapLibreMockMap,
  resetMapLibreMock,
} from "@/test/maplibreGlMock";

// The `maplibre-gl` mock itself is registered globally in
// src/test/setup.ts (jsdom has no WebGL context to construct a real map).

beforeEach(() => {
  resetMapLibreMock();
});

afterEach(() => {
  window.localStorage.clear();
  useBasemapStore.setState({ basemapId: DEFAULT_BASEMAP_ID });
  vi.restoreAllMocks();
});

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
});
