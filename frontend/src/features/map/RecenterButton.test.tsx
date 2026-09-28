import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { Map as MapLibreGlMap } from "maplibre-gl";
import { afterEach, describe, expect, it, vi } from "vitest";

import { MapInstanceContext } from "@/features/map/MapInstanceContext";
import { RecenterButton } from "@/features/map/RecenterButton";
import { useMapCenterRequestStore } from "@/features/map/store/useMapCenterRequestStore";

const RECEIVER = { lat: 47.6, lon: -122.3, label: "Home" };

afterEach(() => {
  useMapCenterRequestStore.setState({ nonce: 0 });
});

function renderButton(map: Pick<MapLibreGlMap, "easeTo"> | null) {
  return render(
    <MapInstanceContext.Provider
      value={{ map: map as MapLibreGlMap | null, styleEpoch: 0 }}
    >
      <RecenterButton receiver={RECEIVER} />
    </MapInstanceContext.Provider>,
  );
}

describe("RecenterButton", () => {
  it("recentres the map on the receiver when clicked", async () => {
    const easeTo = vi.fn();
    const user = userEvent.setup();
    renderButton({ easeTo });

    await user.click(
      screen.getByRole("button", { name: /recentre the map on the receiver/i }),
    );

    expect(easeTo).toHaveBeenCalledWith({
      center: [RECEIVER.lon, RECEIVER.lat],
    });
  });

  it("does nothing on mount — only an actual request recentres", () => {
    const easeTo = vi.fn();
    renderButton({ easeTo });
    expect(easeTo).not.toHaveBeenCalled();
  });

  it("recentres in response to an external request (the H shortcut), not only its own click", async () => {
    const easeTo = vi.fn();
    renderButton({ easeTo });

    act(() => {
      useMapCenterRequestStore.getState().requestRecenter();
    });

    expect(easeTo).toHaveBeenCalledWith({
      center: [RECEIVER.lon, RECEIVER.lat],
    });
  });

  it("does not throw when clicked before the map instance exists", async () => {
    const user = userEvent.setup();
    renderButton(null);
    await expect(
      user.click(screen.getByRole("button", { name: /recentre/i })),
    ).resolves.not.toThrow();
  });
});
