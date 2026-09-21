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
    expect(
      screen.getByText(/05-8153, C17 Boeing C-17A Globemaster III \(12\)/),
    ).toBeInTheDocument();
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

  it("shows a page-level 'Data as of ... refreshes every 60 s' caption once loaded (R3-06)", async () => {
    installAnalyticsApiMock();
    renderAnalyticsPage();

    await screen.findByRole("heading", { level: 1, name: "Analytics" });

    expect(
      await screen.findByText(
        /Data as of \d{2}:\d{2}:\d{2} · refreshes every 60 s/,
      ),
    ).toBeInTheDocument();
  });

  /** A `global.fetch` stub answering every analytics/receiver endpoint with
   * an empty-but-successful body except the ones named in `failing`, which
   * answer with the given status and a raw `{"error":{"message":...}}` body
   * — the shape a real backend 500 carries. */
  function stubAnalyticsFetch(failing: Record<string, string>) {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = new URL(String(input), "http://localhost");
        const rawMessage = failing[url.pathname];
        if (rawMessage !== undefined) {
          return new Response(
            JSON.stringify({
              error: { code: "internal_error", message: rawMessage },
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
        if (url.pathname === "/api/v1/analytics/rarity") {
          return new Response(
            JSON.stringify({
              window: analyticsWindow(),
              never_seen_before: 0,
              rare_max_sightings: 0,
              rare_max_type_aircraft: 0,
              rare_aircraft: [],
              rare_types: [],
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
  }

  it("shows the human fallback, never the backend's raw error text, with a Retry button (R3-08)", async () => {
    stubAnalyticsFetch({ "/api/v1/analytics/top-aircraft": "boom" });
    renderAnalyticsPage();

    expect(
      await screen.findByText("Could not load top aircraft."),
    ).toBeInTheDocument();
    expect(screen.queryByText("boom")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("dedupes a shared /analytics/daily failure into one page banner instead of four card errors (R3-08)", async () => {
    stubAnalyticsFetch({ "/api/v1/analytics/daily": "daily exploded" });
    renderAnalyticsPage();

    // One banner, not four repetitions of the raw string.
    expect(
      await screen.findByText("Could not load daily activity data."),
    ).toBeInTheDocument();
    expect(screen.queryByText("daily exploded")).not.toBeInTheDocument();

    const pointers = await screen.findAllByText(
      "Could not load — see notice above.",
    );
    // Daily counts, max distance, receiver activity, never seen before.
    expect(pointers.length).toBe(4);
  });

  it("shows one 'can't reach the API' banner when every analytics query fails (R3-08)", async () => {
    stubAnalyticsFetch({
      "/api/v1/analytics/daily": "boom",
      "/api/v1/analytics/classification-activity": "boom",
      "/api/v1/analytics/top-aircraft": "boom",
      "/api/v1/analytics/top-types": "boom",
      "/api/v1/analytics/top-operators": "boom",
      "/api/v1/analytics/rarity": "boom",
    });
    renderAnalyticsPage();

    expect(
      await screen.findByText("FlightSite can't reach the API."),
    ).toBeInTheDocument();
    expect(screen.queryByText("boom")).not.toBeInTheDocument();
    // Only the banner's Retry — no per-card Retry buttons duplicating it.
    expect(screen.getAllByRole("button", { name: "Retry" }).length).toBe(1);
  });
});
