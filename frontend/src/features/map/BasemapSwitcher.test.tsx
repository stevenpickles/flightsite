import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { BasemapSwitcher } from "@/features/map/BasemapSwitcher";
import { BASEMAPS, DEFAULT_BASEMAP_ID } from "@/features/map/basemaps";
import { BASEMAP_STORAGE_KEY } from "@/features/map/basemapPersistence";
import { useBasemapStore } from "@/features/map/store/useBasemapStore";
import { useUiStore } from "@/store/useUiStore";

afterEach(() => {
  window.localStorage.clear();
  useBasemapStore.setState({ explicitBasemapId: null });
  useUiStore.setState({ theme: "dark" });
});

describe("BasemapSwitcher", () => {
  it("lists every registered basemap as a radio option", () => {
    render(<BasemapSwitcher />);
    const group = screen.getByRole("radiogroup", { name: /basemap/i });
    for (const basemap of BASEMAPS) {
      expect(
        within(group).getByRole("radio", { name: new RegExp(basemap.label) }),
      ).toBeInTheDocument();
    }
  });

  it("marks the default basemap as checked initially", () => {
    render(<BasemapSwitcher />);
    const defaultBasemap = BASEMAPS.find((b) => b.id === DEFAULT_BASEMAP_ID)!;
    expect(
      screen.getByRole("radio", { name: new RegExp(defaultBasemap.label) }),
    ).toHaveAttribute("aria-checked", "true");
  });

  it("selecting a basemap updates the store and persists the choice", async () => {
    const user = userEvent.setup();
    render(<BasemapSwitcher />);

    const osmOption = screen.getByRole("radio", { name: /openstreetmap/i });
    await user.click(osmOption);

    expect(osmOption).toHaveAttribute("aria-checked", "true");
    expect(useBasemapStore.getState().explicitBasemapId).toBe("osm-raster");
    expect(window.localStorage.getItem(BASEMAP_STORAGE_KEY)).toBe("osm-raster");
  });

  it("checks the theme's basemap while the user has chosen none", () => {
    // Issue R1-14: the switcher must show the map that is actually on
    // screen, which after a theme toggle is no longer the registry default.
    useUiStore.setState({ theme: "light" });
    render(<BasemapSwitcher />);

    expect(
      screen.getByRole("radio", { name: /light aviation/i }),
    ).toHaveAttribute("aria-checked", "true");
    expect(
      screen.getByRole("radio", { name: /dark aviation/i }),
    ).toHaveAttribute("aria-checked", "false");
  });

  it("keeps an explicit choice checked across a theme change", async () => {
    const user = userEvent.setup();
    render(<BasemapSwitcher />);
    await user.click(screen.getByRole("radio", { name: /openstreetmap/i }));

    useUiStore.setState({ theme: "light" });
    expect(
      screen.getByRole("radio", { name: /openstreetmap/i }),
    ).toHaveAttribute("aria-checked", "true");
  });
});
