import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AlertsPage } from "@/pages/AlertsPage";
import { renderWithProviders } from "@/test/test-utils";
import { installWatchlistsApiMock, watchlist } from "@/test/watchlistsApiMock";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("AlertsPage", () => {
  it("renders the page heading and the Watchlists area", async () => {
    installWatchlistsApiMock({
      watchlists: [watchlist({ name: "Police Helicopters" })],
    });

    renderWithProviders(<AlertsPage />);

    expect(
      screen.getByRole("heading", { level: 1, name: "Alerts" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("Police Helicopters")).toBeInTheDocument();
  });

  it("renders a single-tab page without a visible tab bar", async () => {
    // With only the Watchlists area implemented (roadmap slice 037), a tab
    // bar with nothing to switch between would just be visual noise —
    // slice 041 adding a sibling tab is what makes it appear.
    installWatchlistsApiMock();

    renderWithProviders(<AlertsPage />);
    await screen.findByText(/no watchlists yet/i);

    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.getByRole("tabpanel")).toBeInTheDocument();
  });
});
