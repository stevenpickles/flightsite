import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DEV_PLACEHOLDER_MAP_CONFIG } from "@/features/map/mapConfig";
import { useMapConfigStore } from "@/features/map/store/useMapConfigStore";
import { NAV_ITEMS } from "@/components/shell/nav-items";
import {
  defaultFlightSiteConfig,
  installConfigApiMock,
} from "@/test/configApiMock";
import { renderApp } from "@/test/test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
  useMapConfigStore.setState({ config: DEV_PLACEHOLDER_MAP_CONFIG });
});

describe("RootLayout", () => {
  it("redirects to /setup when the config reports first_run", async () => {
    installConfigApiMock({ firstRun: true });
    renderApp("/");

    expect(
      await screen.findByText(/welcome to flightsite/i),
    ).toBeInTheDocument();
  });

  it("does not redirect once setup is complete (first_run: false)", async () => {
    installConfigApiMock({ firstRun: false });
    renderApp("/");

    const liveMap = NAV_ITEMS.find((item) => item.to === "/")!;
    await waitFor(() => {
      expect(
        screen.getByRole("heading", { level: 1, name: liveMap.label }),
      ).toBeInTheDocument();
    });
    expect(
      screen.queryByText(/welcome to flightsite/i),
    ).not.toBeInTheDocument();
  });

  it("allows visiting /setup directly even when not first-run (re-run from Settings)", async () => {
    installConfigApiMock({
      firstRun: false,
      config: defaultFlightSiteConfig({
        location: {
          latitude: 1,
          longitude: 2,
          site_name: "Home",
          antenna_height_ft: null,
        },
      }),
    });
    renderApp("/setup");

    expect(await screen.findByText(/update your setup/i)).toBeInTheDocument();
  });

  it("syncs the Live Map's receiver position from a configured location on load", async () => {
    installConfigApiMock({
      firstRun: false,
      config: defaultFlightSiteConfig({
        location: {
          latitude: 51.5,
          longitude: -0.12,
          site_name: "Home Roof",
          antenna_height_ft: null,
        },
      }),
    });
    renderApp("/");

    await waitFor(() => {
      expect(useMapConfigStore.getState().config.receiver).toEqual({
        lat: 51.5,
        lon: -0.12,
        label: "Home Roof",
      });
    });
  });

  it("leaves the map on its fallback config when the config fetch fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("network error")),
    );
    renderApp("/");

    const liveMap = NAV_ITEMS.find((item) => item.to === "/")!;
    expect(
      await screen.findByRole("heading", { level: 1, name: liveMap.label }),
    ).toBeInTheDocument();
    expect(useMapConfigStore.getState().config).toBe(
      DEV_PLACEHOLDER_MAP_CONFIG,
    );
  });

  it("navigates to the Live Map once the wizard finishes from a first-run redirect", async () => {
    installConfigApiMock({ firstRun: true });
    const user = userEvent.setup();
    renderApp("/");

    await screen.findByText(/welcome to flightsite/i);
    await user.type(screen.getByLabelText(/site name/i), "Home");
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    await screen.findByText(/receiver location/i);
    await user.type(screen.getByLabelText(/latitude/i), "1");
    await user.type(screen.getByLabelText(/longitude/i), "2");
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    await screen.findByText(/decoder endpoint/i);
    await user.click(screen.getByRole("button", { name: /skip test/i }));
    await user.click(screen.getByRole("button", { name: /^next$/i }));

    for (let i = 0; i < 4; i += 1) {
      await user.click(screen.getByRole("button", { name: /^next$/i }));
    }

    await screen.findByRole("heading", { name: /^review$/i });
    await user.click(screen.getByRole("button", { name: /finish setup/i }));

    const liveMap = NAV_ITEMS.find((item) => item.to === "/")!;
    expect(
      await screen.findByRole("heading", { level: 1, name: liveMap.label }),
    ).toBeInTheDocument();
    // The wizard never reappears once complete.
    expect(
      screen.queryByText(/welcome to flightsite/i),
    ).not.toBeInTheDocument();
  });
});
