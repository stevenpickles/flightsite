import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { resetFilteredLiveAircraftCache } from "@/features/filters/lib/filteredLiveAircraftCache";
import { useFilterStore } from "@/features/filters/store/useFilterStore";
import { DEFAULT_FILTERS } from "@/features/filters/types";
import { InterestingPanel } from "@/features/interesting/InterestingPanel";
import { useLiveAircraftStore } from "@/features/map/aircraft/store/useLiveAircraftStore";
import type { LiveAircraft } from "@/lib/api/live";
import { makeAircraft } from "@/test/liveAircraftFixtures";

beforeEach(() => {
  resetFilteredLiveAircraftCache();
  useLiveAircraftStore.getState().reset();
  useFilterStore.setState({ filters: DEFAULT_FILTERS });
});

function seed(aircraft: LiveAircraft[]) {
  act(() => {
    useLiveAircraftStore
      .getState()
      .applySnapshot({ aircraft, receiver: null }, Date.now());
  });
}

/** The demo emergency + military scenario the slice's acceptance criterion
 * names: a critical emergency squawk further out than a high-severity
 * military aircraft, plus an ordinary aircraft that matches nothing. */
function demoScenario(): LiveAircraft[] {
  return [
    makeAircraft({
      icao: "aaaaaa",
      callsign: "UAL45",
      position: { lat: 47, lon: -122 },
      distance_nm: 4,
      interesting: null,
    }),
    makeAircraft({
      icao: "bbbbbb",
      callsign: "RCH492",
      registration: "05-8153",
      aircraft_type: "C17",
      operator: "United States Air Force",
      position: { lat: 47.9, lon: -122 },
      distance_nm: 18.4,
      altitude_ft: 24975,
      interesting: { severity: "high", reasons: ["Rule: Military aircraft"] },
    }),
    makeAircraft({
      icao: "cccccc",
      callsign: "SWA119",
      aircraft_type: "B738",
      operator: "Southwest Airlines",
      position: { lat: 48.4, lon: -122 },
      distance_nm: 96.2,
      altitude_ft: 8000,
      squawk: "7700",
      emergency: "7700",
      interesting: {
        severity: "critical",
        reasons: ["Emergency squawk 7700 (general emergency)"],
      },
    }),
  ];
}

function rowIcaos(): string[] {
  return screen
    .getAllByTestId("interesting-row")
    .map((node) => node.getAttribute("data-icao") ?? "");
}

describe("InterestingPanel", () => {
  it("lists only aircraft with an active match", () => {
    seed(demoScenario());
    render(<InterestingPanel />);
    expect(rowIcaos()).toEqual(["cccccc", "bbbbbb"]);
    expect(screen.queryByText("UAL45")).not.toBeInTheDocument();
  });

  it("orders by severity before distance", () => {
    // The 96 nm emergency outranks the 18 nm military aircraft: severity is
    // the primary key (SPEC §49), so proximity never promotes a lesser match.
    seed(demoScenario());
    render(<InterestingPanel />);
    const rows = screen.getAllByTestId("interesting-row");
    expect(rows[0]).toHaveAttribute("data-severity", "critical");
    expect(rows[1]).toHaveAttribute("data-severity", "high");
  });

  it("orders by distance within one severity band", () => {
    seed([
      makeAircraft({
        icao: "aaaaaa",
        distance_nm: 80,
        interesting: { severity: "high", reasons: ["Rule: Military"] },
      }),
      makeAircraft({
        icao: "bbbbbb",
        distance_nm: 6,
        interesting: { severity: "high", reasons: ["Rule: Military"] },
      }),
    ]);
    render(<InterestingPanel />);
    expect(rowIcaos()).toEqual(["bbbbbb", "aaaaaa"]);
  });

  it("shows the §49 row fields: identity, type, operator, reason, distance and altitude", () => {
    seed(demoScenario());
    render(<InterestingPanel />);
    expect(screen.getByText("RCH492")).toBeInTheDocument();
    expect(
      screen.getByText(/C17 · United States Air Force/),
    ).toBeInTheDocument();
    expect(screen.getByText("Rule: Military aircraft")).toBeInTheDocument();
    expect(screen.getByText(/18\.4 nm/)).toBeInTheDocument();
    expect(screen.getByText(/FL250/)).toBeInTheDocument();
  });

  it("falls back to the tail number, then the ICAO hex, for identity", () => {
    seed([
      makeAircraft({
        icao: "bbbbbb",
        callsign: null,
        registration: "05-8153",
        interesting: { severity: "info", reasons: ["Rule: First ever"] },
      }),
      makeAircraft({
        icao: "dddddd",
        callsign: null,
        registration: null,
        distance_nm: 99,
        interesting: { severity: "info", reasons: ["Rule: First ever"] },
      }),
    ]);
    render(<InterestingPanel />);
    expect(screen.getByText("05-8153")).toBeInTheDocument();
    expect(screen.getByText("DDDDDD")).toBeInTheDocument();
  });

  it("names every reason standing against an aircraft, not just the first", () => {
    seed([
      makeAircraft({
        icao: "bbbbbb",
        interesting: {
          severity: "high",
          reasons: ["Rule: Military aircraft", "Rule: Watchlist — Tankers"],
        },
      }),
    ]);
    render(<InterestingPanel />);
    expect(
      screen.getByText("Rule: Military aircraft · Rule: Watchlist — Tankers"),
    ).toBeInTheDocument();
  });

  it("distinguishes severity by text, not by colour alone", () => {
    // SPEC §80 / the slice's own acceptance criterion. The severity word is
    // the label; the tint is decoration.
    seed(demoScenario());
    render(<InterestingPanel />);
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("High")).toBeInTheDocument();
  });

  it("selects the aircraft on click, same as a map click would", async () => {
    seed(demoScenario());
    render(<InterestingPanel />);
    expect(useLiveAircraftStore.getState().selectedIcao).toBeNull();

    await userEvent.click(screen.getAllByTestId("interesting-row")[0]!);
    expect(useLiveAircraftStore.getState().selectedIcao).toBe("cccccc");
  });

  it("marks the selected row with aria-current", async () => {
    seed(demoScenario());
    render(<InterestingPanel />);
    await userEvent.click(screen.getAllByTestId("interesting-row")[1]!);
    expect(screen.getAllByTestId("interesting-row")[1]).toHaveAttribute(
      "aria-current",
      "true",
    );
  });

  it("is expanded by default and collapses on click", async () => {
    seed(demoScenario());
    render(<InterestingPanel />);
    expect(screen.getAllByTestId("interesting-row")).toHaveLength(2);

    await userEvent.click(screen.getByRole("button", { name: /interesting/i }));
    expect(screen.queryAllByTestId("interesting-row")).toHaveLength(0);
  });

  it("counts the matching aircraft in the header badge", () => {
    seed(demoScenario());
    render(<InterestingPanel />);
    expect(screen.getByTestId("interesting-count")).toHaveTextContent("2");
  });

  it("says so plainly when nothing is matching", () => {
    seed([makeAircraft({ icao: "aaaaaa" })]);
    render(<InterestingPanel />);
    expect(
      screen.getByText("No interesting aircraft right now."),
    ).toBeInTheDocument();
    expect(screen.getByTestId("interesting-count")).toHaveTextContent("0");
  });

  it("keeps counting matches a filter has hidden, and says how many", () => {
    // A filter narrows the list, never the count: an altitude band that
    // happens to exclude a critical squawk must not make the panel look
    // like nothing is wrong.
    seed(demoScenario());
    act(() => {
      useFilterStore.setState({
        filters: { ...DEFAULT_FILTERS, altitudeMinFt: 20000 },
      });
    });
    render(<InterestingPanel />);
    expect(screen.getByTestId("interesting-count")).toHaveTextContent("2");
    expect(rowIcaos()).toEqual(["bbbbbb"]);
    expect(screen.getByTestId("interesting-hidden-note")).toHaveTextContent(
      "1 hidden by the current filters.",
    );
  });

  it("explains an empty list that the filters emptied", () => {
    seed(demoScenario());
    act(() => {
      useFilterStore.setState({
        filters: { ...DEFAULT_FILTERS, altitudeMinFt: 40000 },
      });
    });
    render(<InterestingPanel />);
    expect(
      screen.getByText(
        "Every interesting aircraft is hidden by the current filters.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("interesting-count")).toHaveTextContent("2");
  });
});
