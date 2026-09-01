import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { NearestAirportSection } from "@/features/aircraft-detail/components/NearestAirportSection";
import { TooltipProvider } from "@/components/ui/tooltip";
import type { NearestAirportInfo } from "@/lib/api/live";

function renderSection(
  airport: NearestAirportInfo | null,
  provenanceSource: string | undefined = airport === null
    ? undefined
    : "heuristic",
) {
  return render(
    <TooltipProvider>
      <NearestAirportSection
        airport={airport}
        provenanceSource={provenanceSource}
        units="aviation"
      />
    </TooltipProvider>,
  );
}

function section(): HTMLElement {
  const heading = screen.getByText("Nearest airport").closest("section");
  expect(heading).not.toBeNull();
  return heading as HTMLElement;
}

describe("NearestAirportSection", () => {
  it("renders the field, its range and the inferred phase", () => {
    renderSection({
      ident: "KBFI",
      name: "Boeing Field",
      distance_nm: 4.12,
      phase: "arriving",
    });

    expect(
      within(section()).getByText("KBFI — Boeing Field"),
    ).toBeInTheDocument();
    expect(within(section()).getByText("4.1 nm")).toBeInTheDocument();
    expect(
      within(section()).getByText("Likely arriving · inferred"),
    ).toBeInTheDocument();
  });

  it("labels a departure as inferred too", () => {
    renderSection({
      ident: "EGLL",
      name: "London Heathrow",
      distance_nm: 2.0,
      phase: "departing",
    });

    expect(
      within(section()).getByText("Likely departing · inferred"),
    ).toBeInTheDocument();
  });

  it("states in words, not only in colour, that the section is inferred", () => {
    // SPEC §80: signalling is never colour-only, and SPEC §41 requires the
    // inference to be *clearly labeled*. The caption stands whether or not a
    // phase was inferred, so it describes the section rather than appearing
    // only when there is a guess to excuse.
    renderSection(null);

    expect(
      within(section()).getByText(/Inferred by FlightSite/i),
    ).toBeVisible();
    expect(within(section()).getByText(/not a reported route/i)).toBeVisible();
  });

  it("renders Unknown for an aircraft with no nearby field", () => {
    renderSection(null);

    // Airport, distance and phase: at cruise there is no nearest field, and
    // `docs/API.md` §2.7 renders that the same way as every other unknown.
    expect(within(section()).getAllByText("Unknown").length).toBe(3);
  });

  it("reports the field but no phase when the kinematics were ambiguous", () => {
    renderSection({
      ident: "KSEA",
      name: "Seattle-Tacoma International",
      distance_nm: 1.2,
      phase: null,
    });

    expect(
      within(section()).getByText("KSEA — Seattle-Tacoma International"),
    ).toBeInTheDocument();
    expect(within(section()).getAllByText("Unknown").length).toBe(1);
    expect(within(section()).queryByText(/Likely/)).not.toBeInTheDocument();
  });

  it("attributes every value it shows to the heuristic", () => {
    renderSection({
      ident: "KBFI",
      name: "Boeing Field",
      distance_nm: 4.1,
      phase: "arriving",
    });

    expect(
      within(section()).getAllByRole("button", {
        name: /Source: Heuristic\. Inferred using a best-effort heuristic/i,
      }).length,
    ).toBe(3);
  });

  it("shows no provenance dot for values that do not exist", () => {
    renderSection(null);

    expect(
      within(section()).queryByRole("button", { name: /Source:/i }),
    ).not.toBeInTheDocument();
  });

  it("converts the range for a metric install", () => {
    render(
      <TooltipProvider>
        <NearestAirportSection
          airport={{
            ident: "LFPG",
            name: "Charles de Gaulle",
            distance_nm: 10,
            phase: null,
          }}
          provenanceSource="heuristic"
          units="metric"
        />
      </TooltipProvider>,
    );

    expect(within(section()).getByText("18.5 km")).toBeInTheDocument();
  });
});
