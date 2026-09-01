import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NeverSeenBeforeCard } from "@/features/analytics/components/cards/NeverSeenBeforeCard";
import type { AnalyticsDailyRow } from "@/lib/api/analytics";

function dailyRow(
  overrides: Partial<AnalyticsDailyRow> = {},
): AnalyticsDailyRow {
  return {
    day: "2026-08-31",
    unique_aircraft: 10,
    new_aircraft: 2,
    sightings: 15,
    interesting: 2,
    military: 0,
    government: 0,
    law_enforcement: 0,
    max_range_nm: 141.8,
    busiest_hour: 14,
    receiver_messages: 100000,
    receiver_positions: 5000,
    receiver_aircraft_max: 12,
    receiver_max_range_nm: 150.2,
    ...overrides,
  };
}

describe("NeverSeenBeforeCard", () => {
  it("renders the empty state with no days", () => {
    render(<NeverSeenBeforeCard items={[]} isLoading={false} />);
    expect(screen.getByText("No data for this window.")).toBeInTheDocument();
  });

  it("sums the daily new-aircraft counts in the summary", () => {
    const items = [
      dailyRow({ day: "2026-08-30", new_aircraft: 1 }),
      dailyRow({ day: "2026-08-31", new_aircraft: 2 }),
    ];
    render(<NeverSeenBeforeCard items={items} isLoading={false} />);

    expect(
      screen.getByRole("img", { name: /new aircraft never seen before/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/3 total/)).toBeInTheDocument();
  });
});
