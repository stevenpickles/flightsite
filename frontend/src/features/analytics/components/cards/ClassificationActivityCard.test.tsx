import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ClassificationActivityCard } from "@/features/analytics/components/cards/ClassificationActivityCard";
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

  it("names the value axis and formats the tooltip value with a unit (R3-12)", () => {
    render(
      <ClassificationActivityCard series={[dailyRow()]} isLoading={false} />,
    );

    const option = getLastMockChart().optionCalls.at(-1) as {
      yAxis: { name: string };
      tooltip: { valueFormatter: (value: unknown) => string };
    };
    expect(option.yAxis.name).toBe("sightings");
    expect(option.tooltip.valueFormatter(1)).toBe("1 sighting");
    expect(option.tooltip.valueFormatter(3)).toBe("3 sightings");
  });

  it("sums null (not-computed-yet) days as 0 rather than throwing off the total, and notes the window may undercount (R3-02)", () => {
    const series = [
      dailyRow({ day: "2026-09-19", military: 2, government: 1 }),
      dailyRow({
        day: "2026-09-20",
        complete: false,
        military: null,
        government: null,
        law_enforcement: null,
      }),
    ];
    render(
      <ClassificationActivityCard
        series={series}
        complete={false}
        isLoading={false}
      />,
    );

    expect(screen.getByText(/2 military/)).toBeInTheDocument();
    expect(screen.getByText(/1 government/)).toBeInTheDocument();
    expect(
      screen.getByText(/today not computed yet, so this may undercount/),
    ).toBeInTheDocument();
  });
});
