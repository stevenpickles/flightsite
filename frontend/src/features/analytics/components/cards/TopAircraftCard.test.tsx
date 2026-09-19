import { act, render, screen } from "@testing-library/react";
import {
  createMemoryRouter,
  MemoryRouter,
  RouterProvider,
  useParams,
} from "react-router-dom";
import { describe, expect, it } from "vitest";

import { TopAircraftCard } from "@/features/analytics/components/cards/TopAircraftCard";
import type { AnalyticsAircraftRow } from "@/lib/api/analytics";
import { getLastMockChart } from "@/test/echartsMock";

function aircraftRow(
  overrides: Partial<AnalyticsAircraftRow> = {},
): AnalyticsAircraftRow {
  return {
    icao: "ae1463",
    registration: "05-8153",
    type: "C17",
    model: "Boeing C-17A Globemaster III",
    operator: "United States Air Force",
    operator_group: "US Military",
    classification: "military_transport",
    military: true,
    government: false,
    law_enforcement: false,
    sightings: 12,
    first_seen_at: "2026-04-02T18:11:09.000Z",
    last_seen_at: "2026-08-30T22:41:55.000Z",
    max_range_nm: 141.8,
    ...overrides,
  };
}

/** The last option the (mocked) chart was given, narrowed to the parts
 * these tests read: the category-axis label formatter and the tooltip
 * formatter. Both are functions, so the option object is the only way to
 * observe what a bar is labelled with. */
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

describe("TopAircraftCard", () => {
  it("renders a loading state", () => {
    render(
      <MemoryRouter>
        <TopAircraftCard rows={[]} isLoading />
      </MemoryRouter>,
    );
    expect(screen.getByText("Loading…")).toBeInTheDocument();
  });

  it("renders an error state", () => {
    render(
      <MemoryRouter>
        <TopAircraftCard rows={[]} isLoading={false} error="Could not load." />
      </MemoryRouter>,
    );
    expect(screen.getByText("Could not load.")).toBeInTheDocument();
  });

  it("renders the empty state when there are no rows", () => {
    render(
      <MemoryRouter>
        <TopAircraftCard rows={[]} isLoading={false} />
      </MemoryRouter>,
    );
    expect(screen.getByText("No data for this window.")).toBeInTheDocument();
  });

  it("renders a chart with an accessible summary naming every row's identity and type", () => {
    const rows = [
      aircraftRow({ sightings: 12 }),
      aircraftRow({
        icao: "a9c2f0",
        registration: "N302DN",
        type: "B738",
        model: "Boeing 737-800",
        sightings: 8,
      }),
    ];
    render(
      <MemoryRouter>
        <TopAircraftCard rows={rows} isLoading={false} />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("img", { name: /top aircraft by sightings/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/05-8153, C17 Boeing C-17A Globemaster III \(12\)/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/N302DN, B738 Boeing 737-800 \(8\)/),
    ).toBeInTheDocument();
  });

  it("labels each bar with the tail number and the type designator", () => {
    const rows = [
      aircraftRow({ sightings: 12 }),
      aircraftRow({
        icao: "a9c2f0",
        registration: "N302DN",
        type: "B738",
        sightings: 8,
      }),
    ];
    render(
      <MemoryRouter>
        <TopAircraftCard rows={rows} isLoading={false} />
      </MemoryRouter>,
    );

    const { yAxis } = lastOption();
    // The axis is drawn bottom-up, so the runner-up comes first.
    expect(yAxis.data).toEqual(["N302DN", "05-8153"]);
    expect(yAxis.axisLabel.formatter("N302DN", 0)).toBe(
      "{ident|N302DN}  {type|B738}",
    );
    expect(yAxis.axisLabel.formatter("05-8153", 1)).toBe(
      "{ident|05-8153}  {type|C17}",
    );
  });

  it("falls back to the hex, with no type segment, when the metadata knows nothing", () => {
    const rows = [
      aircraftRow({
        icao: "a9c2f0",
        registration: null,
        type: null,
        model: null,
        operator: null,
        operator_group: null,
        sightings: 3,
      }),
    ];
    render(
      <MemoryRouter>
        <TopAircraftCard rows={rows} isLoading={false} />
      </MemoryRouter>,
    );

    const { yAxis, tooltip } = lastOption();
    expect(yAxis.axisLabel.formatter("A9C2F0", 0)).toBe("{ident|A9C2F0}");
    expect(tooltip.formatter([{ dataIndex: 0 }])).toBe(
      "<strong>A9C2F0</strong><br/>3 sightings",
    );
    expect(screen.getByText(/A9C2F0 \(3\)/)).toBeInTheDocument();
  });

  it("puts the hex, model, operator and count in the tooltip", () => {
    const rows = [
      aircraftRow({
        icao: "a9c2f0",
        registration: "N302DN",
        type: "B738",
        model: "Boeing 737-800",
        operator: "Delta Air Lines",
        sightings: 8,
      }),
    ];
    render(
      <MemoryRouter>
        <TopAircraftCard rows={rows} isLoading={false} />
      </MemoryRouter>,
    );

    const { tooltip } = lastOption();
    expect(tooltip.formatter([{ dataIndex: 0 }])).toBe(
      [
        "<strong>N302DN · A9C2F0</strong>",
        "B738 Boeing 737-800",
        "Delta Air Lines",
        "8 sightings",
      ].join("<br/>"),
    );
    // A hover ECharts cannot map to a row draws nothing rather than crashing.
    expect(tooltip.formatter([{ dataIndex: 7 }])).toBe("");
    expect(tooltip.formatter(undefined)).toBe("");
  });

  it("escapes metadata strings in the tooltip rather than rendering them as markup", () => {
    const rows = [
      aircraftRow({
        registration: "N1<b>",
        operator: "Ma & Pa's Air",
        sightings: 1,
      }),
    ];
    render(
      <MemoryRouter>
        <TopAircraftCard rows={rows} isLoading={false} />
      </MemoryRouter>,
    );

    const html = lastOption().tooltip.formatter([{ dataIndex: 0 }]);
    expect(html).toContain("N1&lt;b&gt;");
    expect(html).toContain("Ma &amp; Pa&#39;s Air");
    expect(html).toMatch(/<br\/>1 sighting$/);
  });

  it("navigates to the aircraft detail route on a bar click", () => {
    function AircraftDetailStub() {
      const { icao } = useParams();
      return <p>Detail for {icao}</p>;
    }

    const rows = [aircraftRow({ icao: "ae1463", registration: "05-8153" })];
    const router = createMemoryRouter(
      [
        {
          path: "/analytics",
          element: <TopAircraftCard rows={rows} isLoading={false} />,
        },
        { path: "/aircraft/:icao", element: <AircraftDetailStub /> },
      ],
      { initialEntries: ["/analytics"] },
    );
    render(<RouterProvider router={router} />);

    const instance = getLastMockChart();
    act(() => {
      instance.emit("click", { dataIndex: 0, name: "05-8153", value: 12 });
    });

    expect(screen.getByText("Detail for ae1463")).toBeInTheDocument();
  });
});
