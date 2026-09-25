import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReceiverActivityCard } from "@/features/analytics/components/cards/ReceiverActivityCard";
import type { AnalyticsDailyRow } from "@/lib/api/analytics";
import { getLastMockChart } from "@/test/echartsMock";

function dailyRow(
  overrides: Partial<AnalyticsDailyRow> = {},
): AnalyticsDailyRow {
  return {
    day: "2026-08-31",
    complete: true,
    unique_aircraft: 10,
    new_aircraft: 1,
    sightings: 15,
    interesting: 2,
    military: 0,
    government: 0,
    law_enforcement: 0,
    max_range_nm: 141.8,
    busiest_hour: 14,
    receiver_messages: 120000,
    receiver_positions: 6000,
    receiver_aircraft_max: 12,
    receiver_max_range_nm: 150.2,
    ...overrides,
  };
}

describe("ReceiverActivityCard", () => {
  it("renders the empty state when no day has receiver activity", () => {
    render(
      <ReceiverActivityCard
        items={[
          dailyRow({ receiver_messages: null, receiver_positions: null }),
        ]}
        isLoading={false}
      />,
    );
    expect(screen.getByText("No data for this window.")).toBeInTheDocument();
  });

  it("renders a summary with compact message/position counts", () => {
    render(
      <ReceiverActivityCard
        items={[
          dailyRow({
            day: "2026-08-31",
            receiver_messages: 120000,
            receiver_positions: 6000,
          }),
        ]}
        isLoading={false}
      />,
    );

    expect(
      screen.getByRole("img", { name: /receiver messages and positions/i }),
    ).toBeInTheDocument();
    // R3-11: the day key is rendered through formatCalendarDay, not as the
    // raw "2026-08-31" string.
    expect(
      screen.getByText(/Aug 31, 2026 — 120K messages, 6K positions/),
    ).toBeInTheDocument();
  });

  it("treats a partially-recorded window (some days null) as having data", () => {
    const items = [
      dailyRow({
        day: "2026-08-30",
        receiver_messages: null,
        receiver_positions: null,
      }),
      dailyRow({
        day: "2026-08-31",
        receiver_messages: 500,
        receiver_positions: 50,
      }),
    ];
    render(<ReceiverActivityCard items={items} isLoading={false} />);

    expect(
      screen.queryByText("No data for this window."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Aug 30, 2026/)).not.toBeInTheDocument();
  });

  it("names the value axis (R3-12)", () => {
    render(
      <ReceiverActivityCard
        items={[dailyRow({ receiver_messages: 500, receiver_positions: 50 })]}
        isLoading={false}
      />,
    );

    const option = getLastMockChart().optionCalls.at(-1) as {
      yAxis: { name: string };
    };
    expect(option.yAxis.name).toBe("count");
  });

  it("renders a day not computed yet as 'not computed yet', not a fabricated zero (R3-02)", () => {
    const items = [
      dailyRow({
        day: "2026-09-20",
        complete: false,
        receiver_messages: null,
        receiver_positions: null,
      }),
    ];
    render(<ReceiverActivityCard items={items} isLoading={false} />);

    expect(
      screen.queryByText("No data for this window."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Sep 20, 2026 — not computed yet/),
    ).toBeInTheDocument();
  });
});
