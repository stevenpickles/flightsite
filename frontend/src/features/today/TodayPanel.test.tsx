import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { TodayPanel } from "@/features/today/TodayPanel";
import {
  analyticsSummaryResponse,
  installAnalyticsApiMock,
} from "@/test/analyticsApiMock";
import { defaultReceiverInfo } from "@/test/aircraftApiMock";

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <TodayPanel />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function expand(): Promise<void> {
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /today/i }));
}

describe("TodayPanel", () => {
  it("is collapsed by default, with a sightings badge visible in the header", async () => {
    installAnalyticsApiMock({
      summary: analyticsSummaryResponse({ sightings: 18 }),
    });
    renderPanel();

    await waitFor(() =>
      expect(screen.getByTestId("today-sightings-badge")).toHaveTextContent(
        "18 sightings",
      ),
    );
    const header = screen.getByRole("button", { name: /today/i });
    expect(header).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Unique aircraft")).not.toBeInTheDocument();
  });

  it("renders every §59 stat tile once expanded", async () => {
    installAnalyticsApiMock({
      summary: analyticsSummaryResponse({
        unique_aircraft: 12,
        sightings: 18,
        interesting: 2,
        military: 1,
        government: 2,
        law_enforcement: 3,
        max_range_nm: 187.44,
        busiest_hour: 14,
        new_aircraft: 3,
        new_milestones: 5,
      }),
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("today-sightings-badge")).toBeInTheDocument(),
    );

    await expand();

    expect(screen.getByText("Unique aircraft")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.getByText("Sightings")).toBeInTheDocument();
    expect(screen.getByText("Interesting")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("Mil / gov / police")).toBeInTheDocument();
    expect(screen.getByText("1 / 2 / 3")).toBeInTheDocument();
    expect(screen.getByText("Max range")).toBeInTheDocument();
    expect(screen.getByText("187.4 nm")).toBeInTheDocument();
    expect(screen.getByText("Busiest hour")).toBeInTheDocument();
    // Receiver-local hour, rendered as the clock range it covers.
    expect(screen.getByText("14:00–15:00")).toBeInTheDocument();
    expect(screen.getByText("New aircraft")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("New milestones")).toBeInTheDocument();
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("renders null figures as placeholders rather than blanks or errors", async () => {
    installAnalyticsApiMock({
      summary: analyticsSummaryResponse({
        max_range_nm: null,
        busiest_hour: null,
        busiest_hour_source: null,
        interesting: 0,
      }),
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("today-sightings-badge")).toBeInTheDocument(),
    );

    await expand();

    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText("No data yet")).toBeInTheDocument();
  });

  it("converts the max-range tile to kilometers when the receiver prefers metric units", async () => {
    installAnalyticsApiMock({
      receiver: defaultReceiverInfo({ units: "metric" }),
      summary: analyticsSummaryResponse({ max_range_nm: 187.44 }),
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("today-sightings-badge")).toBeInTheDocument(),
    );

    await expand();

    expect(screen.getByText("347.1 km")).toBeInTheDocument();
  });

  it("links the new-milestones tile to the activity page", async () => {
    installAnalyticsApiMock({
      summary: analyticsSummaryResponse({ new_milestones: 4 }),
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("today-sightings-badge")).toBeInTheDocument(),
    );

    await expand();

    expect(screen.getByTestId("today-milestones-link")).toHaveAttribute(
      "href",
      "/activity",
    );
  });

  it("collapses and expands from the header button", async () => {
    installAnalyticsApiMock({ summary: analyticsSummaryResponse() });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByTestId("today-sightings-badge")).toBeInTheDocument(),
    );

    await expand();
    expect(screen.getByText("Unique aircraft")).toBeInTheDocument();

    await expand();
    expect(screen.queryByText("Unique aircraft")).not.toBeInTheDocument();
  });

  it("reports a failed fetch rather than rendering an empty grid", async () => {
    installAnalyticsApiMock({ summaryStatus: 500 });
    renderPanel();

    await expand();

    await waitFor(() =>
      expect(
        screen.getByText(/could not load today's summary/i),
      ).toBeInTheDocument(),
    );
  });
});
