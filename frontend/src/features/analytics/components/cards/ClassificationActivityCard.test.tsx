import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ClassificationActivityCard } from "@/features/analytics/components/cards/ClassificationActivityCard";
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
    military: 2,
    government: 1,
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

describe("ClassificationActivityCard", () => {
  it("renders the empty state with no days", () => {
    render(<ClassificationActivityCard series={[]} isLoading={false} />);
    expect(screen.getByText("No data for this window.")).toBeInTheDocument();
  });

  it("renders a summary with totals across the series", () => {
    const series = [
      dailyRow({
        day: "2026-08-30",
        military: 1,
        government: 0,
        law_enforcement: 0,
      }),
      dailyRow({
        day: "2026-08-31",
        military: 2,
        government: 1,
        law_enforcement: 1,
      }),
    ];
    render(<ClassificationActivityCard series={series} isLoading={false} />);

    expect(
      screen.getByRole("img", {
        name: /military, government and law-enforcement activity over time/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText(/3 military/)).toBeInTheDocument();
    expect(screen.getByText(/1 government/)).toBeInTheDocument();
    expect(screen.getByText(/1 law-enforcement/)).toBeInTheDocument();
  });

  it("shows a loading state", () => {
    render(<ClassificationActivityCard series={[]} isLoading />);
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });
});
