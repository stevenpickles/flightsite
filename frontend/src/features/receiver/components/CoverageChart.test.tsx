import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CoverageChart } from "@/features/receiver/components/CoverageChart";
import type { UnitSystem } from "@/lib/api/config";
import type { ReceiverCoverageFinding } from "@/lib/api/receiverStats";
import {
  coverage,
  installReceiverStatsApiMock,
} from "@/test/receiverStatsApiMock";

afterEach(() => {
  vi.unstubAllGlobals();
});

function renderChart(units: UnitSystem = "aviation") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <CoverageChart units={units} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function card(): HTMLElement {
  return screen.getByRole("region", { name: "Coverage by altitude" });
}

const NE_FINDING: ReceiverCoverageFinding = {
  band: "above_25k",
  start_deg: 40,
  end_deg: 60,
  compass: "NE",
  max_range_nm: 116.3,
  horizon_nm: 200.6,
  share_of_horizon: 0.58,
  samples: 480,
  days: 5,
  message: "NE 40–60° reaches 58 % of the radio horizon above 25,000 ft",
};

const LOW_FINDING: ReceiverCoverageFinding = {
  ...NE_FINDING,
  band: "below_10k",
  start_deg: 180,
  end_deg: 190,
  compass: "S",
  share_of_horizon: 0.31,
};

describe("CoverageChart", () => {
  it("draws the selected band with its horizon and lists its findings", async () => {
    installReceiverStatsApiMock({
      coverage: coverage({
        antennaHeightFt: 25,
        horizons: { above_25k: 200.6, below_10k: 73.5 },
        ranges: { above_25k: { 8: 116.3, 20: 190 } },
        findings: [NE_FINDING, LOW_FINDING],
      }),
    });

    renderChart();

    expect(
      await screen.findByRole("img", {
        name: "Coverage by altitude, Above 25,000 ft, polar chart",
      }),
    ).toBeInTheDocument();
    expect(
      within(card()).getByText(
        "NE 40–60° reaches 58 % of the radio horizon above 25,000 ft — likely obstruction",
      ),
    ).toBeInTheDocument();
    expect(within(card()).getByText(/Radio horizon 200\.6 nm/)).toBeVisible();
    // Only this band's findings are listed.
    expect(within(card()).queryByText(/^S 180–190°/)).not.toBeInTheDocument();
    expect(
      within(card()).queryByText(/Set the antenna height/),
    ).not.toBeInTheDocument();
  });

  it("switches band with the band selector", async () => {
    const user = userEvent.setup();
    installReceiverStatsApiMock({
      coverage: coverage({
        antennaHeightFt: 25,
        horizons: { above_25k: 200.6, below_10k: 73.5 },
        ranges: { above_25k: { 8: 116.3 }, below_10k: { 36: 22.8 } },
        findings: [NE_FINDING, LOW_FINDING],
      }),
    });

    renderChart();
    const below = await screen.findByRole("button", {
      name: "Below 10,000 ft",
    });
    expect(below).toHaveAttribute("aria-pressed", "false");

    await user.click(below);

    expect(below).toHaveAttribute("aria-pressed", "true");
    expect(
      within(card()).getByText(
        "S 180–190° reaches 31 % of the radio horizon below 10,000 ft — likely obstruction",
      ),
    ).toBeInTheDocument();
    expect(within(card()).queryByText(/^NE 40–60°/)).not.toBeInTheDocument();
  });

  it("asks for the antenna height when it is unset, and still draws what was heard", async () => {
    installReceiverStatsApiMock({
      coverage: coverage({
        antennaHeightFt: null,
        ranges: { above_25k: { 8: 116.3 } },
      }),
    });

    renderChart();

    const link = await screen.findByRole("link", {
      name: "Set the antenna height in Settings",
    });
    expect(link).toHaveAttribute("href", "/settings#settings-receiver");
    expect(within(card()).getByText(/to see the radio horizon/)).toBeVisible();
    expect(
      screen.getByRole("img", { name: /Above 25,000 ft, polar chart/ }),
    ).toBeInTheDocument();
    // No horizon, so no findings section at all — not an empty "none found".
    expect(
      within(card()).queryByText(/Likely obstructions/),
    ).not.toBeInTheDocument();
  });

  it("shows the learning state on an install with no banded data yet", async () => {
    installReceiverStatsApiMock({
      coverage: coverage({ antennaHeightFt: 25, horizons: { above_25k: 200 } }),
    });

    renderChart();

    expect(await screen.findByText(/No coverage data yet\./)).toHaveTextContent(
      "30 samples on 3 different days",
    );
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("says when a band with a known horizon has no likely obstructions", async () => {
    installReceiverStatsApiMock({
      coverage: coverage({
        antennaHeightFt: 25,
        horizons: { above_25k: 200.6 },
        ranges: { above_25k: { 8: 180 } },
      }),
    });

    renderChart();

    expect(
      await screen.findByText(/^None found\. A direction is listed when/),
    ).toHaveTextContent("under 60 % of the radio horizon");
  });

  it("states heights and distances in metric for a metric install", async () => {
    installReceiverStatsApiMock({
      coverage: coverage({
        antennaHeightFt: 25,
        horizons: { above_25k: 200.6 },
        ranges: { above_25k: { 8: 116.3 } },
        findings: [NE_FINDING],
      }),
    });

    renderChart("metric");

    expect(
      await screen.findByRole("button", { name: "Above 7,620 m" }),
    ).toBeInTheDocument();
    expect(
      within(card()).getByText(
        /reaches 58 % of the radio horizon above 7,620 m/,
      ),
    ).toBeInTheDocument();
    expect(within(card()).getByText(/Radio horizon 371\.5 km/)).toBeVisible();
  });

  it("degrades to an honest error with a retry when the endpoint is missing", async () => {
    const { fetchMock } = installReceiverStatsApiMock({ coverage: "error" });

    renderChart();

    expect(
      await screen.findByText(
        /Coverage analysis is unavailable right now/,
        {},
        {
          timeout: 4000,
        },
      ),
    ).toBeInTheDocument();
    expect(within(card()).getByRole("button", { name: "Retry" })).toBeVisible();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalled();
    });
  });
});
