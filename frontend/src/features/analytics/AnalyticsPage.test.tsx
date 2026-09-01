import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AnalyticsPage } from "@/features/analytics/AnalyticsPage";
import type { AnalyticsAircraftRow } from "@/lib/api/analytics";
import {
  analyticsWindow,
  installAnalyticsApiMock,
} from "@/test/analyticsApiMock";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderAnalyticsPage(initialPath = "/analytics") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const router = createMemoryRouter(
    [{ path: "/analytics", element: <AnalyticsPage /> }],
    { initialEntries: [initialPath] },
  );
  return {
    ...render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    ),
    router,
  };
}

const topAircraftRow: AnalyticsAircraftRow = {
  icao: "ae1463",
  registration: "05-8153",
  type: "C17",
  model: "Boeing C-17A Globemaster III",
  operator: "United States Air Force",
  operator_group: "US Military",
  classification: "military_transport",
  military: true,
  government: false,
  law_enforcement: false,
  sightings: 12,
  first_seen_at: "2026-04-02T18:11:09.000Z",
  last_seen_at: "2026-08-30T22:41:55.000Z",
  max_range_nm: 141.8,
};

describe("AnalyticsPage", () => {
  it("renders every card empty when the window has no data", async () => {
    installAnalyticsApiMock();
    renderAnalyticsPage();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Analytics" }),
    ).toBeInTheDocument();

    const emptyStates = await screen.findAllByText("No data for this window.");
    // top aircraft, top types, top operators, classification, daily counts,
    // max distance, receiver activity, never seen before — every chart card.
    expect(emptyStates.length).toBe(8);
    expect(
      screen.getByText("No rare aircraft in this window."),
    ).toBeInTheDocument();
  });

  it("renders populated cards from mocked API data", async () => {
    installAnalyticsApiMock({
      topAircraft: { window: analyticsWindow(), items: [topAircraftRow] },
    });
    renderAnalyticsPage();

    expect(
      await screen.findByRole("img", { name: /top aircraft by sightings/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/05-8153 \(12\)/)).toBeInTheDocument();
  });

  it("defaults to the today preset and persists a change to the URL", async () => {
    installAnalyticsApiMock();
    const user = userEvent.setup();
    const { router } = renderAnalyticsPage();

    await screen.findByRole("heading", { level: 1, name: "Analytics" });
    expect(router.state.location.search).toBe("");

    await user.click(screen.getByRole("radio", { name: "30 days" }));

    await waitFor(() => {
      expect(router.state.location.search).toBe("?preset=30d");
    });
    expect(screen.getByRole("radio", { name: "30 days" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("reads the initial preset back out of the URL", async () => {
    installAnalyticsApiMock();
    renderAnalyticsPage("/analytics?preset=ytd");

    await screen.findByRole("heading", { level: 1, name: "Analytics" });
    expect(screen.getByRole("radio", { name: "This year" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("shows a per-card error message when a query fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(String(input), "http://localhost");
        if (url.pathname === "/api/v1/analytics/top-aircraft") {
          return new Response(
            JSON.stringify({
              error: { code: "internal_error", message: "boom" },
            }),
            { status: 500 },
          );
        }
        if (url.pathname === "/api/v1/receiver") {
          return new Response(
            JSON.stringify({
              site_name: "Test",
              latitude: 0,
              longitude: 0,
              antenna_height_ft: 10,
              timezone: "UTC",
              units: "aviation",
              display_radius_nm: 250,
              alert_radius_nm: null,
              demo_mode: false,
              t0: null,
            }),
            { status: 200 },
          );
        }
        return new Response(
          JSON.stringify({ window: analyticsWindow(), items: [] }),
          { status: 200 },
        );
      }),
    );
    renderAnalyticsPage();

    expect(await screen.findByText("boom")).toBeInTheDocument();
  });
});
