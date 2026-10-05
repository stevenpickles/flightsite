import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TopGroupCard } from "@/features/analytics/components/cards/TopGroupCard";
import type { AnalyticsGroupRow } from "@/lib/api/analytics";

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

function renderTypes(rows: AnalyticsGroupRow[]) {
  return render(
    <TopGroupCard
      title="Top types"
      ariaLabel="Top types by sightings"
      nameHeading="Type"
      emptyLabel="No types sighted in this window."
      rows={rows}
      isLoading={false}
    />,
  );
}

/** The cells of the named ranking's body rows, as text, one array per row. */
function bodyRows(name: string): string[][] {
  const table = screen.getByRole("table", { name });
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent ?? ""),
    );
}

describe("TopGroupCard", () => {
  it("renders the empty state with the given empty label", () => {
    renderTypes([]);
    expect(
      screen.getByText("No types sighted in this window."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("renders a table of name, aircraft and sightings, falling back to key when label is null", () => {
    renderTypes([
      groupRow(),
      groupRow({ key: "B738", label: null, sightings: 4, unique_aircraft: 2 }),
    ]);

    const table = screen.getByRole("table", { name: "Top types by sightings" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Type", "Aircraft", "Sightings"]);
    expect(bodyRows("Top types by sightings")).toEqual([
      ["C-17 Globemaster III", "3", "9"],
      ["B738", "2", "4"],
    ]);
  });

  it("leads a type with its long-form description, the designator muted beneath", () => {
    renderTypes([
      groupRow({ key: "B738", label: "B738", description: "Boeing 737-800" }),
    ]);
    expect(bodyRows("Top types by sightings")[0]?.[0]).toBe(
      "Boeing 737-800B738",
    );
    expect(screen.getByTitle("Boeing 737-800")).toBeInTheDocument();
    expect(screen.getByTitle("B738")).toHaveClass("text-muted-foreground");
  });

  it("shows a row without a description by its label alone", () => {
    renderTypes([groupRow({ description: null })]);
    expect(bodyRows("Top types by sightings")[0]?.[0]).toBe(
      "C-17 Globemaster III",
    );
  });

  it("reuses the same component for operators via title, heading and ariaLabel props", () => {
    render(
      <TopGroupCard
        title="Top operators"
        ariaLabel="Top operators by sightings"
        nameHeading="Operator"
        emptyLabel="No operators sighted in this window."
        rows={[
          groupRow({
            key: "3",
            label: "Delta Air Lines",
            unique_aircraft: 41,
            sightings: 118,
          }),
        ]}
        isLoading={false}
      />,
    );
    expect(screen.getByText("Top operators")).toBeInTheDocument();
    const table = screen.getByRole("table", {
      name: "Top operators by sightings",
    });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual(["Operator", "Aircraft", "Sightings"]);
    expect(bodyRows("Top operators by sightings")).toEqual([
      ["Delta Air Lines", "41", "118"],
    ]);
    // No detail route exists for a group, so the name is text, not a link.
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("keeps the backend's ranking order", () => {
    renderTypes([
      groupRow({ key: "A", label: "First", sightings: 9 }),
      groupRow({ key: "B", label: "Second", sightings: 5 }),
      groupRow({ key: "C", label: "Third", sightings: 1 }),
    ]);
    expect(bodyRows("Top types by sightings").map((cells) => cells[0])).toEqual(
      ["First", "Second", "Third"],
    );
  });
});
