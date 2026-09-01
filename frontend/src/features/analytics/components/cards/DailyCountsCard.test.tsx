import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DailyCountsCard } from "@/features/analytics/components/cards/DailyCountsCard";
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
    receiver_messages: 100000,
    receiver_positions: 5000,
    receiver_aircraft_max: 12,
    receiver_max_range_nm: 150.2,
    ...overrides,
  };
}

describe("DailyCountsCard", () => {
  it("renders the empty state with no days", () => {
    render(<DailyCountsCard items={[]} isLoading={false} />);
    expect(screen.getByText("No data for this window.")).toBeInTheDocument();
  });

  it("renders a chart with a per-day accessible summary", () => {
    const items = [
      dailyRow({ day: "2026-08-30", unique_aircraft: 8, sightings: 11 }),
      dailyRow({ day: "2026-08-31", unique_aircraft: 10, sightings: 15 }),
    ];
    render(<DailyCountsCard items={items} isLoading={false} />);

    expect(
      screen.getByRole("img", { name: /daily aircraft and sighting counts/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/2026-08-30 — 8 aircraft, 11 sightings/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/2026-08-31 — 10 aircraft, 15 sightings/),
    ).toBeInTheDocument();
  });
});
