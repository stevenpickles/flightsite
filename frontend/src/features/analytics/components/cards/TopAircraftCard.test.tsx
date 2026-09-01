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

  it("renders a chart with an accessible summary listing every row", () => {
    const rows = [
      aircraftRow({ sightings: 12 }),
      aircraftRow({ icao: "a9c2f0", registration: "N302DN", sightings: 8 }),
    ];
    render(
      <MemoryRouter>
        <TopAircraftCard rows={rows} isLoading={false} />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("img", { name: /top aircraft by sightings/i }),
    ).toBeInTheDocument();
    expect(screen.getByText(/05-8153 \(12\)/)).toBeInTheDocument();
    expect(screen.getByText(/N302DN \(8\)/)).toBeInTheDocument();
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
