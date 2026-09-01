import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  installReceiverStatsApiMock,
  metricSeries,
  rangeByBearing,
  scorecard,
  signalDistribution,
} from "@/test/receiverStatsApiMock";
import { renderApp } from "@/test/test-utils";

afterEach(() => {
  vi.unstubAllGlobals();
});

function metricsCalls(fetchMock: ReturnType<typeof vi.fn>): URL[] {
  return (fetchMock.mock.calls as [string][])
    .map(([url]) => new URL(url, "http://localhost"))
    .filter((url) => url.pathname === "/api/v1/receiver/metrics");
}

describe("ReceiverPage", () => {
  it("renders the scorecard's documented fields", async () => {
    installReceiverStatsApiMock({
      scorecard: scorecard({
        current_visible: 17,
        current_positioned: 11,
        health: "ok",
      }),
    });

    renderApp("/receiver");

    expect(await screen.findByText("17")).toBeInTheDocument();
    expect(screen.getByText("11 positioned")).toBeInTheDocument();
    expect(screen.getByText("OK")).toBeInTheDocument();
  });

  it("shows a non-color health cue (icon + text) for each health state", async () => {
    installReceiverStatsApiMock({
      scorecard: scorecard({ health: "no_stats" }),
    });

    renderApp("/receiver");

    expect(await screen.findByText("No decoder stats")).toBeInTheDocument();
  });

  it("shows an unavailable-scorecard message when the request fails", async () => {
    const { fetchMock: baseline } = installReceiverStatsApiMock();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), "http://localhost");
        if (url.pathname === "/api/v1/receiver/scorecard") {
          return Promise.resolve(new Response("", { status: 500 }));
        }
        return baseline(input, init);
      }),
    );

    renderApp("/receiver");

    expect(
      await screen.findByText(/could not load the scorecard/i),
    ).toBeInTheDocument();
  });

  it("requests hourly resolution by default and switches to high/daily via the window selector", async () => {
    const { fetchMock } = installReceiverStatsApiMock();
    const user = userEvent.setup();

    renderApp("/receiver");
    await screen.findByText("Messages per second");

    await waitFor(() => {
      const calls = metricsCalls(fetchMock);
      const messages = calls.find(
        (url) => url.searchParams.get("metric") === "messages_per_sec",
      );
      expect(messages?.searchParams.get("resolution")).toBe("hourly");
    });

    // The always-daily charts request resolution=daily regardless of the
    // window selector's default (7 days -> hourly for the windowed charts).
    const dailyOnly = metricsCalls(fetchMock).find(
      (url) => url.searchParams.get("metric") === "unique_aircraft",
    );
    expect(dailyOnly?.searchParams.get("resolution")).toBe("daily");

    await user.click(screen.getByRole("button", { name: "24 hours" }));

    await waitFor(() => {
      const calls = metricsCalls(fetchMock);
      const messages = calls.find(
        (url) =>
          url.searchParams.get("metric") === "messages_per_sec" &&
          url.searchParams.get("resolution") === "high",
      );
      expect(messages).toBeDefined();
    });
  });

  it("shows an empty-state summary for a chart with no points", async () => {
    installReceiverStatsApiMock({
      series: {
        max_range_nm: metricSeries({ metric: "max_range_nm", points: [] }),
      },
    });

    renderApp("/receiver");

    expect(await screen.findByText("Maximum range")).toBeInTheDocument();
    await waitFor(() => {
      // The shared `EChart` wrapper's own empty-state copy (roadmap slice
      // 032) — it renders this instead of an empty canvas whenever
      // `buildOption` returns `null`, regardless of this chart's own
      // (unused in that case) summary string.
      expect(screen.getByText("No data for this window.")).toBeInTheDocument();
    });
  });

  it("renders the range-by-bearing chart's summary from today/ever sectors", async () => {
    installReceiverStatsApiMock({
      rangeByBearing: rangeByBearing({ ever: { 10: 150 }, today: { 10: 40 } }),
    });

    renderApp("/receiver");

    expect(
      await screen.findByText(/Lifetime maximum range 150(\.0)? nm/),
    ).toBeInTheDocument();
  });

  it("renders the signal-distribution chart's summary", async () => {
    installReceiverStatsApiMock({
      signalDistribution: signalDistribution({ sample_count: 58 }),
    });

    renderApp("/receiver");

    expect(
      await screen.findByText(/Signal strength distribution over 58 sightings/),
    ).toBeInTheDocument();
  });

  it("renders the lifetime statistics section's documented fields", async () => {
    installReceiverStatsApiMock();

    renderApp("/receiver");

    const heading = await screen.findByText("Lifetime statistics");
    const section = heading.closest("section");
    expect(section).not.toBeNull();
    const withinSection = within(section as HTMLElement);
    expect(withinSection.getByText("40,213")).toBeInTheDocument();
    expect(withinSection.getByText(/Delta Air Lines/)).toBeInTheDocument();
  });

  it("renders 'never-data' first-run states without crashing", async () => {
    installReceiverStatsApiMock({
      scorecard: scorecard({
        current_visible: 0,
        current_positioned: 0,
        messages_per_sec: null,
        positions_per_sec: null,
        max_range_today_nm: null,
        max_range_ever_nm: null,
        unique_aircraft_today: 0,
        unique_aircraft_since_t0: 0,
        decoder_uptime_s: null,
        flightsite_uptime_s: 4,
        health: "unknown",
      }),
      lifetime: {
        since: null,
        unique_aircraft: 0,
        total_sightings: 0,
        total_positions: null,
        total_messages: null,
        max_range: null,
        peak_message_rate_per_sec: null,
        peak_position_rate_per_sec: null,
        max_simultaneous_aircraft: null,
        busiest_day: null,
        most_frequent_aircraft: null,
        common_type: null,
        common_model: null,
        common_operator: null,
      },
      rangeByBearing: rangeByBearing(),
      signalDistribution: signalDistribution({
        buckets: [],
        sample_count: 0,
        min_db: null,
        max_db: null,
        avg_db: null,
      }),
    });

    renderApp("/receiver");

    expect(await screen.findByText("Unknown")).toBeInTheDocument();
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });
});
