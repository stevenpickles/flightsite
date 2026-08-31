import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { BasemapSwitcher } from "@/features/map/BasemapSwitcher";
import { BASEMAPS, DEFAULT_BASEMAP_ID } from "@/features/map/basemaps";
import { BASEMAP_STORAGE_KEY } from "@/features/map/basemapPersistence";
import { useBasemapStore } from "@/features/map/store/useBasemapStore";

afterEach(() => {
  window.localStorage.clear();
  useBasemapStore.setState({ basemapId: DEFAULT_BASEMAP_ID });
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
    expect(useBasemapStore.getState().basemapId).toBe("osm-raster");
    expect(window.localStorage.getItem(BASEMAP_STORAGE_KEY)).toBe("osm-raster");
  });
});
