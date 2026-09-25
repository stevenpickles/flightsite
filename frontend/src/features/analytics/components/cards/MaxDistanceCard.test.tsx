import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MaxDistanceCard } from "@/features/analytics/components/cards/MaxDistanceCard";
import type { AnalyticsDailyRow } from "@/lib/api/analytics";

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
    max_range_nm: 100,
    busiest_hour: 14,
    receiver_messages: 100000,
    receiver_positions: 5000,
    receiver_aircraft_max: 12,
    receiver_max_range_nm: 150.2,
    ...overrides,
  };
}

describe("MaxDistanceCard", () => {
  it("renders the empty state when every day has no distance", () => {
    render(
      <MaxDistanceCard
        items={[dailyRow({ max_range_nm: null })]}
        units="aviation"
        isLoading={false}
      />,
    );
    expect(screen.getByText("No data for this window.")).toBeInTheDocument();
  });

  it("renders in nautical miles for aviation units", () => {
    render(
      <MaxDistanceCard
        items={[dailyRow({ day: "2026-08-31", max_range_nm: 100 })]}
        units="aviation"
        isLoading={false}
      />,
    );

    // R3-11: the day key is rendered through formatCalendarDay, not as the
    // raw "2026-08-31" string.
    expect(screen.getByText(/Aug 31, 2026 — 100 nm/)).toBeInTheDocument();
  });

  it("converts to kilometers for metric units", () => {
    render(
      <MaxDistanceCard
        items={[dailyRow({ day: "2026-08-31", max_range_nm: 100 })]}
        units="metric"
        isLoading={false}
      />,
    );

    expect(screen.getByText(/Aug 31, 2026 — 185.2 km/)).toBeInTheDocument();
  });

  it("skips days with no distance in the summary", () => {
    const items = [
      dailyRow({ day: "2026-08-30", max_range_nm: null }),
      dailyRow({ day: "2026-08-31", max_range_nm: 50 }),
    ];
    render(
      <MaxDistanceCard items={items} units="aviation" isLoading={false} />,
    );

    expect(screen.queryByText(/Aug 30, 2026/)).not.toBeInTheDocument();
    expect(screen.getByText(/Aug 31, 2026 — 50 nm/)).toBeInTheDocument();
  });

  it("renders a day not computed yet as 'not computed yet' rather than treating it as no data (R3-02)", () => {
    const items = [
      dailyRow({ day: "2026-09-20", complete: false, max_range_nm: null }),
    ];
    render(
      <MaxDistanceCard items={items} units="aviation" isLoading={false} />,
    );

    // Not the flat empty state: a pending day is still worth drawing.
    expect(
      screen.queryByText("No data for this window."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Sep 20, 2026 — not computed yet/),
    ).toBeInTheDocument();
  });

  it("still shows the empty state when every day is complete with no distance recorded", () => {
    const items = [
      dailyRow({ day: "2026-08-30", complete: true, max_range_nm: null }),
    ];
    render(
      <MaxDistanceCard items={items} units="aviation" isLoading={false} />,
    );

    expect(screen.getByText("No data for this window.")).toBeInTheDocument();
  });
});
