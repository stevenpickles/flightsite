import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import { RarityListsCard } from "@/features/analytics/components/cards/RarityListsCard";
import type {
  AnalyticsAircraftRow,
  AnalyticsRareType,
} from "@/lib/api/analytics";

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
    sightings: 1,
    first_seen_at: "2026-08-30T22:02:10.000Z",
    last_seen_at: "2026-08-30T22:41:55.000Z",
    max_range_nm: 96,
    ...overrides,
  };
}

function rareType(
  overrides: Partial<AnalyticsRareType> = {},
): AnalyticsRareType {
  return {
    type: "C17",
    description: "Boeing C-17A Globemaster III",
    unique_aircraft: 1,
    total_sightings: 1,
    first_seen_at: "2026-08-30T22:02:10.000Z",
    last_seen_at: "2026-08-30T22:41:55.000Z",
    ...overrides,
  };
}

describe("RarityListsCard", () => {
  it("shows the never-seen-before total and empty-list messages when both lists are empty", () => {
    render(
      <MemoryRouter>
        <RarityListsCard
          neverSeenBefore={3}
          rareMaxSightings={2}
          rareAircraft={[]}
          rareTypes={[]}
          isLoading={false}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("3")).toBeInTheDocument();
    expect(
      screen.getByText(/never seen before this window/),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No rare aircraft in this window."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("No rare types in this window."),
    ).toBeInTheDocument();
  });

  it("renders rare aircraft rows linking to the aircraft detail route", () => {
    render(
      <MemoryRouter>
        <RarityListsCard
          neverSeenBefore={1}
          rareMaxSightings={2}
          rareAircraft={[aircraftRow()]}
          rareTypes={[]}
          isLoading={false}
        />
      </MemoryRouter>,
    );

    const link = screen.getByRole("link", { name: "05-8153" });
    expect(link).toHaveAttribute("href", "/aircraft/ae1463");
  });

  it("lists a rare aircraft the way Top aircraft does: tail, type in words, operator, count", () => {
    render(
      <MemoryRouter>
        <RarityListsCard
          neverSeenBefore={1}
          rareMaxSightings={2}
          rareAircraft={[
            aircraftRow(),
            aircraftRow({
              icao: "a1b2c3",
              registration: "N12345",
              type: "C172",
              model: "Cessna 172S Skyhawk",
              operator: null,
              owner: "Wells Fargo Trust Co",
              operator_group: null,
              military: false,
              sightings: 2,
            }),
          ]}
          rareTypes={[]}
          isLoading={false}
        />
      </MemoryRouter>,
    );

    const table = screen.getByRole("table", { name: "Rare aircraft" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Aircraft", "Type", "Operator", "Sightings"]);
    const rows = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      );
    expect(rows).toEqual([
      [
        "05-8153",
        "Boeing C-17A Globemaster IIIC17",
        "United States Air Force",
        "1",
      ],
      [
        "N12345",
        "Cessna 172S SkyhawkC172",
        "Wells Fargo Trust Coregistered owner",
        "2",
      ],
    ]);
  });

  it("leads a rare type with its long-form name over the designator, no link", () => {
    render(
      <MemoryRouter>
        <RarityListsCard
          neverSeenBefore={0}
          rareMaxSightings={2}
          rareAircraft={[]}
          rareTypes={[
            rareType(),
            rareType({
              type: "ZZZZ",
              description: null,
              unique_aircraft: 2,
              total_sightings: 3,
            }),
          ]}
          isLoading={false}
        />
      </MemoryRouter>,
    );

    const table = screen.getByRole("table", { name: "Rare types" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Type", "Aircraft", "Sightings"]);
    const rows = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((row) =>
        within(row)
          .getAllByRole("cell")
          .map((cell) => cell.textContent),
      );
    expect(rows).toEqual([
      ["Boeing C-17A Globemaster IIIC17", "1", "1"],
      ["ZZZZ", "2", "3"],
    ]);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("tolerates a rare type recorded before the description field existed", () => {
    const legacy = rareType({ type: "EC35" });
    delete (legacy as Partial<AnalyticsRareType>).description;
    render(
      <MemoryRouter>
        <RarityListsCard
          neverSeenBefore={0}
          rareMaxSightings={2}
          rareAircraft={[]}
          rareTypes={[legacy]}
          isLoading={false}
        />
      </MemoryRouter>,
    );
    expect(screen.getByText("EC35")).toBeInTheDocument();
  });

  it("shows an error message in place of the lists", () => {
    render(
      <MemoryRouter>
        <RarityListsCard
          neverSeenBefore={0}
          rareMaxSightings={2}
          rareAircraft={[]}
          rareTypes={[]}
          isLoading={false}
          error="Could not load rarity data."
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Could not load rarity data.")).toBeInTheDocument();
  });
});
