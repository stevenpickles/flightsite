import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ReceiverActivityCard } from "@/features/analytics/components/cards/ReceiverActivityCard";
import type { AnalyticsDailyRow } from "@/lib/api/analytics";

function dailyRow(
  overrides: Partial<AnalyticsDailyRow> = {},
): AnalyticsDailyRow {
  return {
    day: "2026-08-31",
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
    expect(
      screen.getByText(/2026-08-31 — 120K messages, 6K positions/),
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
    expect(screen.queryByText(/2026-08-30/)).not.toBeInTheDocument();
  });
});
