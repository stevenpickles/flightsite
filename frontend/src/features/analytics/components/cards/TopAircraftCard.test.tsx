import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { TopAircraftCard } from "@/features/analytics/components/cards/TopAircraftCard";
import type { AnalyticsAircraftRow } from "@/lib/api/analytics";

function aircraftRow(
  overrides: Partial<AnalyticsAircraftRow> = {},
): AnalyticsAircraftRow {
  return {
    icao: "ae1463",
    registration: "05-8153",
    type: "C17",
    model: "Boeing C-17A Globemaster III",
    operator: "United States Air Force",
    owner: null,
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

function renderCard(rows: AnalyticsAircraftRow[]) {
  return render(
    <MemoryRouter>
      <TopAircraftCard rows={rows} isLoading={false} />
    </MemoryRouter>,
  );
}

/** The cells of the ranking's body rows, as text, one array per row. */
function bodyRows(): string[][] {
  const table = screen.getByRole("table", {
    name: "Top aircraft by sightings",
  });
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent ?? ""),
    );
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
    renderCard([]);
    expect(
      screen.getByText("No aircraft sighted in this window."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders a table, not a chart: aircraft, type in words, operator and count", () => {
    renderCard([
      aircraftRow(),
      aircraftRow({
        icao: "a1b2c3",
        registration: "N302DN",
        type: "B738",
        model: "Boeing 737-800",
        operator: "Delta Air Lines",
        operator_group: "Delta",
        military: false,
        classification: "commercial_passenger",
        sightings: 9,
      }),
    ]);

    const table = screen.getByRole("table", {
      name: "Top aircraft by sightings",
    });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Aircraft", "Type", "Operator", "Sightings"]);

    expect(bodyRows()).toEqual([
      [
        "05-8153",
        "Boeing C-17A Globemaster IIIC17",
        "United States Air Force",
        "12",
      ],
      ["N302DN", "Boeing 737-800B738", "Delta Air Lines", "9"],
    ]);
    // The backend's order is the ranking; nothing is re-sorted or reversed.
    expect(bodyRows().map((cells) => cells[0])).toEqual(["05-8153", "N302DN"]);
  });

  it("links each aircraft to its history detail route, with the hex on hover", () => {
    renderCard([aircraftRow()]);
    const link = screen.getByRole("link", { name: "05-8153" });
    expect(link).toHaveAttribute("href", "/aircraft/ae1463");
    expect(link).toHaveAttribute("title", "05-8153 · AE1463");
  });

  it("falls back to the hex, and says Unknown, when the metadata knows nothing", () => {
    renderCard([
      aircraftRow({
        registration: null,
        type: null,
        model: null,
        operator: null,
        owner: null,
        operator_group: null,
        sightings: 2,
      }),
    ]);
    expect(bodyRows()).toEqual([["AE1463", "Unknown", "—", "2"]]);
    expect(screen.getByRole("link", { name: "AE1463" })).toHaveAttribute(
      "title",
      "AE1463",
    );
  });

  it("shows the designator alone when there is no model", () => {
    renderCard([aircraftRow({ model: null })]);
    expect(bodyRows()[0]?.[1]).toBe("C17");
  });

  it("falls back to the registered owner, labelled as such, when no operator is known", () => {
    renderCard([
      aircraftRow({
        operator: null,
        owner: "Wells Fargo Trust Co",
        operator_group: "Delta",
      }),
    ]);
    expect(bodyRows()[0]?.[2]).toBe("Wells Fargo Trust Coregistered owner");
    expect(screen.getByText("registered owner")).toBeInTheDocument();
  });

  it("falls back to the operator group when neither operator nor owner is known", () => {
    renderCard([
      aircraftRow({
        operator: null,
        owner: null,
        operator_group: "US Military",
      }),
    ]);
    expect(bodyRows()[0]?.[2]).toBe("US Military");
    expect(screen.queryByText("registered owner")).not.toBeInTheDocument();
  });

  it("tolerates a payload with no owner field (recorded before slice 095)", () => {
    const row = aircraftRow({ operator: null, operator_group: "Delta" });
    delete (row as Partial<AnalyticsAircraftRow>).owner;
    renderCard([row]);
    expect(bodyRows()[0]?.[2]).toBe("Delta");
  });

  it("puts the full text of a truncating cell on its title", () => {
    renderCard([aircraftRow()]);
    expect(
      screen.getByTitle("Boeing C-17A Globemaster III"),
    ).toBeInTheDocument();
    expect(screen.getByTitle("United States Air Force")).toBeInTheDocument();
  });
});
