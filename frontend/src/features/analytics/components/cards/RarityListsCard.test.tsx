import { render, screen } from "@testing-library/react";
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
    type: "military_transport",
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

  it("renders rare type rows with a humanized label, no link", () => {
    render(
      <MemoryRouter>
        <RarityListsCard
          neverSeenBefore={0}
          rareMaxSightings={2}
          rareAircraft={[]}
          rareTypes={[rareType({ type: "military_transport" })]}
          isLoading={false}
        />
      </MemoryRouter>,
    );

    expect(screen.getByText("Military transport")).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
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
