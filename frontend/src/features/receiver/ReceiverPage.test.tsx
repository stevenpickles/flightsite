import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  installReceiverStatsApiMock,
  lifetimeStats,
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

  it("recovers a failed chart without a reload when Retry is clicked (R3-05)", async () => {
    const { fetchMock: baseline } = installReceiverStatsApiMock();
    let failSignalDistribution = true;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), "http://localhost");
        if (
          url.pathname === "/api/v1/receiver/signal-distribution" &&
          failSignalDistribution
        ) {
          return Promise.resolve(new Response("", { status: 500 }));
        }
        return baseline(input, init);
      }),
    );
    const user = userEvent.setup();

    renderApp("/receiver");

    expect(
      await screen.findByText("Could not load this chart."),
    ).toBeInTheDocument();

    failSignalDistribution = false;
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => {
      expect(
        screen.queryByText("Could not load this chart."),
      ).not.toBeInTheDocument();
    });
    expect(
      await screen.findByText(/Signal strength distribution over/),
    ).toBeInTheDocument();
  });

  it("shows a page-level 'Data as of ... refreshes every 30 s' caption once loaded (R3-06)", async () => {
    installReceiverStatsApiMock();

    renderApp("/receiver");

    expect(
      await screen.findByText(
        /Data as of \d{2}:\d{2}:\d{2} UTC · refreshes every 30 s/,
      ),
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

  it("falls back to 'high' resolution when the default 'hourly' series is empty (R3-02)", async () => {
    const { fetchMock: baseline } = installReceiverStatsApiMock();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const url = new URL(String(input), "http://localhost");
        if (
          url.pathname === "/api/v1/receiver/metrics" &&
          url.searchParams.get("metric") === "max_range_nm"
        ) {
          if (url.searchParams.get("resolution") === "hourly") {
            return Promise.resolve(
              new Response(
                JSON.stringify(
                  metricSeries({ metric: "max_range_nm", points: [] }),
                ),
                {
                  status: 200,
                  headers: { "Content-Type": "application/json" },
                },
              ),
            );
          }
          if (url.searchParams.get("resolution") === "high") {
            return Promise.resolve(
              new Response(
                JSON.stringify(
                  metricSeries({
                    metric: "max_range_nm",
                    resolution: "high",
                    points: [{ t: "2026-09-20T21:00:00.000Z", value: 42 }],
                  }),
                ),
                {
                  status: 200,
                  headers: { "Content-Type": "application/json" },
                },
              ),
            );
          }
        }
        return baseline(input, init);
      }),
    );

    renderApp("/receiver");

    const heading = await screen.findByText("Maximum range");
    const section = heading.closest("section");
    expect(section).not.toBeNull();
    await waitFor(() => {
      // The young-install-on-hourly-only case (R3-02, A1 deferred): the
      // default window opens on "hourly" and this metric's hourly series is
      // empty, but "high" (raw) samples exist, so the chart draws those
      // instead of the flat "No data for this window."
      expect(
        within(section as HTMLElement).queryByText("No data for this window."),
      ).not.toBeInTheDocument();
    });
  });

  it("shows an empty-state summary for a chart with no points", async () => {
    installReceiverStatsApiMock({
      series: {
        max_range_nm: metricSeries({ metric: "max_range_nm", points: [] }),
      },
    });

    renderApp("/receiver");

    const heading = await screen.findByText("Maximum range");
    const section = heading.closest("section");
    expect(section).not.toBeNull();
    await waitFor(() => {
      // The shared `EChart` wrapper's own empty-state copy (roadmap slice
      // 032) — it renders this instead of an empty canvas whenever
      // `buildOption` returns `null`, regardless of this chart's own
      // (unused in that case) summary string. Scoped to this chart's own
      // section: the default (all-null) range-by-bearing fixture this test
      // does not override also renders the empty state (R3-09), so an
      // unscoped query would match more than one element.
      expect(
        within(section as HTMLElement).getByText("No data for this window."),
      ).toBeInTheDocument();
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

  it("formats the busiest day as a locale date, not the raw day key (R3-10)", async () => {
    installReceiverStatsApiMock({
      lifetime: lifetimeStats({
        busiest_day: { day: "2026-07-04", message_count: 5_100_000 },
      }),
    });

    renderApp("/receiver");

    expect(await screen.findByText(/Jul 4, 2026/)).toBeInTheDocument();
    expect(screen.queryByText(/2026-07-04/)).not.toBeInTheDocument();
  });

  it("pluralizes 'sighting' correctly for the most frequently seen aircraft", async () => {
    installReceiverStatsApiMock({
      lifetime: lifetimeStats({
        most_frequent_aircraft: {
          icao: "0a4fce",
          registration: null,
          sighting_count: 1,
        },
        // Not every aircraft tied at 1 — a genuine (if small) record.
        unique_aircraft: 95,
        total_sightings: 200,
      }),
    });

    renderApp("/receiver");

    expect(
      await screen.findByText(/0A4FCE \(1 sighting\)/),
    ).toBeInTheDocument();
  });

  it("shows a tie-aware caption instead of a fabricated record when every aircraft has exactly 1 sighting (R3-10)", async () => {
    installReceiverStatsApiMock({
      lifetime: lifetimeStats({
        most_frequent_aircraft: {
          icao: "0a4fce",
          registration: null,
          sighting_count: 1,
        },
        unique_aircraft: 95,
        total_sightings: 95,
      }),
    });

    renderApp("/receiver");

    expect(
      await screen.findByText("95 aircraft tied at 1 sighting"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/0A4FCE/)).not.toBeInTheDocument();
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

  it("renders a null 'max range today' as 'Not computed yet', never a dash or a zero (R3-02)", async () => {
    installReceiverStatsApiMock({
      scorecard: scorecard({ max_range_today_nm: null }),
    });

    renderApp("/receiver");

    expect(await screen.findByText("Not computed yet")).toBeInTheDocument();
  });
});
