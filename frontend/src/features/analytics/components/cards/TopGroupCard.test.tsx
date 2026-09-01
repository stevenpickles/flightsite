import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TopGroupCard } from "@/features/analytics/components/cards/TopGroupCard";
import type { AnalyticsGroupRow } from "@/lib/api/analytics";

function groupRow(
  overrides: Partial<AnalyticsGroupRow> = {},
): AnalyticsGroupRow {
  return {
    key: "C17",
    label: "C-17 Globemaster III",
    sightings: 9,
    unique_aircraft: 3,
    days_seen: 5,
    first_seen_at: "2026-04-02T18:11:09.000Z",
    last_seen_at: "2026-08-30T22:41:55.000Z",
    ...overrides,
  };
}

describe("TopGroupCard", () => {
  it("renders the empty state with the given empty label", () => {
    render(
      <TopGroupCard
        title="Top types"
        ariaLabel="Top types by sightings"
        emptyLabel="No types sighted in this window."
        rows={[]}
        isLoading={false}
      />,
    );
    expect(screen.getByText("No data for this window.")).toBeInTheDocument();
  });

  it("renders a chart with an accessible summary, falling back to key when label is null", () => {
    const rows = [
      groupRow({ label: "C-17 Globemaster III", sightings: 9 }),
      groupRow({ key: "B738", label: null, sightings: 4 }),
    ];
    render(
      <TopGroupCard
        title="Top types"
        ariaLabel="Top types by sightings"
        emptyLabel="No types sighted in this window."
        rows={rows}
        isLoading={false}
      />,
    );

    expect(
      screen.getByRole("img", { name: "Top types by sightings" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/C-17 Globemaster III \(9\)/)).toBeInTheDocument();
    expect(screen.getByText(/B738 \(4\)/)).toBeInTheDocument();
  });

  it("reuses the same component for operators via title/ariaLabel props", () => {
    render(
      <TopGroupCard
        title="Top operators"
        ariaLabel="Top operators by sightings"
        emptyLabel="No operators sighted in this window."
        rows={[groupRow({ key: "1", label: "Delta Air Lines", sightings: 6 })]}
        isLoading={false}
      />,
    );

    expect(screen.getByText("Top operators")).toBeInTheDocument();
    expect(
      screen.getByRole("img", { name: "Top operators by sightings" }),
    ).toBeInTheDocument();
  });
});
