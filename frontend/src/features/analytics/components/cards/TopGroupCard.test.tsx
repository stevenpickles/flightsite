import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TopGroupCard } from "@/features/analytics/components/cards/TopGroupCard";
import type { AnalyticsGroupRow } from "@/lib/api/analytics";
import { getLastMockChart } from "@/test/echartsMock";

function groupRow(
  overrides: Partial<AnalyticsGroupRow> = {},
): AnalyticsGroupRow {
  return {
    key: "C17",
    label: "C-17 Globemaster III",
    description: null,
    sightings: 9,
    unique_aircraft: 3,
    days_seen: 5,
    first_seen_at: "2026-04-02T18:11:09.000Z",
    last_seen_at: "2026-08-30T22:41:55.000Z",
    ...overrides,
  };
}

/** The last option the (mocked) chart was given, narrowed to the parts
 * these tests read. */
function lastOption(): {
  yAxis: {
    data: string[];
    axisLabel: { formatter: (value: string, index: number) => string };
  };
  tooltip: { formatter: (params: unknown) => string };
} {
  const option = getLastMockChart().optionCalls.at(-1);
  if (option === undefined) {
    throw new Error("the chart was never given an option");
  }
  return option as ReturnType<typeof lastOption>;
}

function renderTypes(rows: AnalyticsGroupRow[]) {
  return render(
    <TopGroupCard
      title="Top types"
      ariaLabel="Top types by sightings"
      emptyLabel="No types sighted in this window."
      rows={rows}
      isLoading={false}
    />,
  );
}

describe("TopGroupCard", () => {
  it("renders the empty state with the given empty label", () => {
    renderTypes([]);
    expect(screen.getByText("No data for this window.")).toBeInTheDocument();
  });

  it("renders a chart with an accessible summary, falling back to key when label is null", () => {
    renderTypes([
      groupRow({ label: "C-17 Globemaster III", sightings: 9 }),
      groupRow({ key: "B738", label: null, sightings: 4 }),
    ]);

    expect(
      screen.getByRole("img", { name: "Top types by sightings" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/C-17 Globemaster III \(9\)/)).toBeInTheDocument();
    expect(screen.getByText(/B738 \(4\)/)).toBeInTheDocument();
  });

  it("shows a type's long-form description beside its designator, and in full in the tooltip", () => {
    renderTypes([
      groupRow({
        key: "B738",
        label: "B738",
        description: "Boeing 737-800",
        sightings: 4,
        unique_aircraft: 2,
        days_seen: 3,
      }),
      groupRow({
        key: "C30J",
        label: "C30J",
        description: "Lockheed Martin C-130J Super Hercules",
        sightings: 2,
        unique_aircraft: 1,
        days_seen: 0,
      }),
    ]);

    const { yAxis, tooltip } = lastOption();
    // Drawn bottom-up, so the runner-up is index 0.
    expect(yAxis.data).toEqual(["C30J", "B738"]);
    expect(yAxis.axisLabel.formatter("B738", 1)).toBe(
      "{ident|B738}  {desc|Boeing 737-800}",
    );
    // A long description is cut on the axis but whole in the tooltip.
    expect(yAxis.axisLabel.formatter("C30J", 0)).toBe(
      "{ident|C30J}  {desc|Lockheed Martin C-130J…}",
    );
    expect(tooltip.formatter([{ dataIndex: 1 }])).toBe(
      "<strong>B738</strong><br/>Boeing 737-800<br/>4 sightings · 2 aircraft · 3 days",
    );
    // `days_seen: 0` is the since-T0 ranking's "not counted", not "zero days".
    expect(tooltip.formatter([{ dataIndex: 0 }])).toBe(
      "<strong>C30J</strong><br/>Lockheed Martin C-130J Super Hercules<br/>2 sightings · 1 aircraft",
    );
    expect(screen.getByText(/B738 Boeing 737-800 \(4\)/)).toBeInTheDocument();
  });

  it("labels a row without a description by its label alone", () => {
    renderTypes([groupRow({ key: "B738", label: null, description: null })]);

    const { yAxis, tooltip } = lastOption();
    expect(yAxis.axisLabel.formatter("B738", 0)).toBe("{ident|B738}");
    expect(tooltip.formatter([{ dataIndex: 0 }])).toBe(
      "<strong>B738</strong><br/>9 sightings · 3 aircraft · 5 days",
    );
    expect(tooltip.formatter([{ dataIndex: 4 }])).toBe("");
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
    expect(lastOption().yAxis.axisLabel.formatter("Delta Air Lines", 0)).toBe(
      "{ident|Delta Air Lines}",
    );
  });

  it("names the value axis and the bar series (R3-12)", () => {
    renderTypes([groupRow()]);

    const option = getLastMockChart().optionCalls.at(-1) as {
      xAxis: { name: string };
      series: Array<{ name: string }>;
    };
    expect(option.xAxis.name).toBe("sightings");
    expect(option.series[0]?.name).toBe("Sightings");
  });
});
